"""HTTP-Verträge des Kontakte-Moduls unter `/v1/personal/contacts` (Plan §9.2).

**Was diese Routen strukturell nicht können:**

* Keine Route ruft den Provider auf, startet den Sidecar, fragt TCC an oder
  ruft `execute()`. Die Mutationsrouten **bereiten ausschließlich vor**; die
  Ausführung ist ein getrennter, in Gate D bewusst nicht exponierter Schritt.
* Keine Route startet einen Hintergrundexecutor.
* `reconcile` gleicht ausschließlich **lesend** ab.

**Sicherheitsgrenzen:** Alle Routen liegen unter `/v1/` und erben damit die
Upstream-`AuthMiddleware` (Bearer, 09 §1). Jeder Zugriff nennt einen
Workspace; die Isolation ist Teil jeder Abfrage, nicht Sache des Aufrufers.
Eingaben sind `extra="forbid"`-validiert (keine Mass-Assignment-Lücke), und
kein Fehlertext trägt einen Kontaktwert.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from personaljarvis.base.approvals import (
    ApprovalError,
    ApprovalExpired,
    ApprovalNotPending,
    ApprovalPayloadMismatch,
    SelfApprovalRejected,
)
from personaljarvis.contacts.api import schemas as S
from personaljarvis.contacts.api.redaction import (
    account_ref,
    container_ref,
    provider_type,
)
from personaljarvis.contacts.application.commands import (
    ContactDraft,
    ContactPatch,
    CreateContact,
    DeleteContact,
    UpdateContact,
)
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    CapabilityNotDeclared,
    ContainerNotAvailable,
    ForeignProviderAccount,
    InvalidCommand,
    MeCardNotWritable,
    MutationError,
    MutationNotExecutable,
    MutationNotFound,
    RevisionConflict,
    TargetBindingError,
    UnifiedIdentifierNotWritable,
)
from personaljarvis.contacts.application.live import (
    ContactsLiveService,
    LiveError,
)
from personaljarvis.contacts.application.queries import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ContactsQueryService,
)
from personaljarvis.contacts.application.roles import ContactsRoleService
from personaljarvis.contacts.domain.enums import InitiationContext, SyncMode
from personaljarvis.contacts.domain.models import Contact
from personaljarvis.contacts.sync.recovery import (
    RecoveryBusy,
    RecoveryNotApplicable,
)

__all__ = ["PREFIX", "create_contacts_router", "DEFAULT_WORKSPACE_HEADER"]

PREFIX = "/v1/personal/contacts"

#: Der Workspace kommt aus einem Kopf-Feld. Fehlt es, gilt der Standard-
#: Workspace — nie „alle Workspaces": eine fehlende Angabe darf niemals mehr
#: Daten liefern als eine vorhandene.
DEFAULT_WORKSPACE_HEADER = "X-Personal-Workspace"
DEFAULT_WORKSPACE = "default"

#: Abbildung der Domänenfehler auf HTTP und die geschlossene Fehlertaxonomie
#: (08 §3 Nr. 5). Kein roher Fehler verlässt die Schicht.
_ERROR_MAP: tuple[tuple[type, int, str], ...] = (
    (UnifiedIdentifierNotWritable, 422, "forbidden"),
    (MeCardNotWritable, 422, "forbidden"),
    (ForeignProviderAccount, 403, "forbidden"),
    (TargetBindingError, 422, "validation_failed"),
    (ContainerNotAvailable, 409, "conflict"),
    (RevisionConflict, 409, "conflict"),
    (AlreadySettled, 409, "conflict"),
    (MutationNotExecutable, 409, "conflict"),
    (MutationNotFound, 404, "not_found"),
    (CapabilityNotDeclared, 422, "unsupported"),
    (InvalidCommand, 422, "validation_failed"),
    (ApprovalExpired, 409, "conflict"),
    (ApprovalPayloadMismatch, 409, "conflict"),
    (SelfApprovalRejected, 403, "forbidden"),
    (ApprovalNotPending, 409, "conflict"),
)


#: Live-Fehler tragen Kategorie und Wiederholbarkeit selbst; sie werden nie
#: zu einem nackten 500.
_LIVE_STATUS: dict[str, int] = {
    "conflict": 409,
    "forbidden": 403,
    "unavailable": 503,
    "internal": 500,
}


def _live_error(exc: "LiveError") -> HTTPException:
    """Bildet einen Live-Fehler auf den Vertrag ab.

    Der Körper trägt **drei** getrennte Angaben, damit die Oberfläche nie auf
    einen Klassennamen zurückfallen muss:

    * ``message`` — ein Satz für den Menschen,
    * ``code`` — die grobe Kategorie aus geschlossener Menge,
    * ``technical_code`` — die stabile, PII-freie Kennung des Fehlerbildes.

    Kein Feld enthält einen Pfad, einen Kontaktwert oder einen Cursor.
    """
    kategorie = getattr(exc, "code", "internal")
    return HTTPException(
        status_code=_LIVE_STATUS.get(kategorie, 500),
        detail={
            "code": kategorie,
            "message": str(exc),
            "technical_code": getattr(exc, "technical_code", type(exc).__name__),
            "retryable": bool(getattr(exc, "retryable", False)),
        })


def _http_error(exc: Exception) -> HTTPException:
    for typ, status, code in _ERROR_MAP:
        if isinstance(exc, typ):
            return HTTPException(
                status_code=status,
                detail={"code": code, "message": str(exc), "retryable": False})
    return HTTPException(
        status_code=500,
        detail={"code": "internal", "message": type(exc).__name__,
                "retryable": False})


def create_contacts_router(module) -> APIRouter:
    """Baut den Router über einem gestarteten `ContactsModule`."""
    router = APIRouter(prefix=PREFIX, tags=["personal-contacts"])
    queries = ContactsQueryService(module)
    roles = ContactsRoleService(module)

    def workspace(request: Request) -> str:
        return request.headers.get(DEFAULT_WORKSPACE_HEADER) or DEFAULT_WORKSPACE

    def actor(request: Request) -> str:
        """Der handelnde Mensch. In Gate D aus dem Kopf-Feld; mit dem
        Session-Token-Fluss (DEV-4) wird daraus die Sitzungsidentität."""
        return request.headers.get("X-Personal-Actor") or "desktop-user"

    def _mutation_service():
        # Fake-Provider bleibt Sache der Komposition. Die Route führt nie aus.
        return module.mutation_service()

    def _live() -> ContactsLiveService:
        """Der Live-Dienst wird **einmal** gebaut und gehalten.

        Der Riegel gegen parallele Läufe lebt in der Instanz — ein neuer
        Dienst je Anfrage hätte einen neuen Riegel und damit gar keinen.
        Tests dürfen ihn über `module.live_service` ersetzen.
        """
        vorhanden = getattr(module, "live_service", None)
        if vorhanden is not None:
            return vorhanden
        module.live_service = ContactsLiveService(module)
        return module.live_service

    # ── Kontakte lesen ──────────────────────────────────────────────────────
    @router.get("", response_model=S.ContactPageOut)
    def list_contacts(request: Request,
                      search: str | None = Query(default=None, max_length=200),
                      role: str | None = Query(default=None, max_length=64),
                      provider_account_id: str | None = Query(default=None,
                                                              max_length=128),
                      cursor: str | None = Query(default=None, max_length=512),
                      limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1,
                                         le=MAX_PAGE_SIZE)) -> Any:
        try:
            seite = queries.list_contacts(
                workspace_id=workspace(request), search=search, role=role,
                provider_account_id=provider_account_id, cursor=cursor,
                limit=limit)
        except MutationError as exc:
            raise _http_error(exc) from exc
        return S.ContactPageOut(
            items=[S.ContactSummaryOut(**vars(z)) for z in seite.items],
            next_cursor=seite.next_cursor, has_more=seite.has_more)

    @router.get("/categories", response_model=list[S.RoleCountOut])
    def list_categories(request: Request) -> Any:
        return [S.RoleCountOut(role=r, count=n)
                for r, n in queries.list_roles(workspace_id=workspace(request))]

    @router.get("/capabilities", response_model=S.CapabilitiesOut)
    def capabilities() -> Any:
        caps = module.capabilities
        return S.CapabilitiesOut(
            read_supported=caps.read_supported,
            create_supported=caps.create_supported,
            update_supported=caps.update_supported,
            delete_supported=caps.delete_supported,
            change_history_supported=caps.change_history_supported,
            full_diff_supported=caps.full_diff_supported,
            notes_supported=caps.notes_supported,
            unified_read_supported=caps.unified_read_supported,
            unified_link_supported=caps.unified_link_supported,
            me_card_writable=caps.me_card_writable,
            unavailable_fields=list(caps.unavailable_fields),
            mutations_available=(caps.create_supported or caps.update_supported
                                 or caps.delete_supported))

    @router.get("/sync/status", response_model=list[S.SyncStatusOut])
    def sync_status(provider_account_id: str | None = Query(
            default=None, max_length=128)) -> Any:
        # Der Filter nimmt weiterhin die **rohe** Kennung entgegen: er ist
        # Eingabe eines Aufrufers, der sie ohnehin kennt, und keine Ausgabe.
        return [_sync_status_out(s)
                for s in queries.sync_status(
                    provider_account_id=provider_account_id)]

    # ── Autorisierung und manueller Lese-Sync ───────────────────────────────
    #
    # Diese drei Routen sind die **einzigen**, die überhaupt einen Sidecar
    # starten können. Alle drei sind ausschließlich lesend, und keine wird
    # automatisch ausgelöst: `GET /authorization` liest nur den Status,
    # `POST /authorization/request` verlangt eine ausdrückliche Nutzeraktion
    # im Körper, und `POST /sync` läuft nur auf Knopfdruck.
    @router.get("/authorization", response_model=S.AuthorizationOut)
    def authorization() -> Any:
        """Liest den Status. Löst **keinen** Systemdialog aus."""
        sicht = _live().authorization()
        return S.AuthorizationOut(**vars(sicht))

    @router.post("/authorization/request", response_model=S.AuthorizationOut)
    def request_authorization(body: S.AuthorizationRequestIn) -> Any:
        """Fordert die Berechtigung an — nur auf ausdrückliche Nutzeraktion.

        Es gibt bewusst keinen automatischen Wiederholungsversuch: nach einer
        Ablehnung ändert das nur der Nutzer selbst in den Systemeinstellungen.
        """
        try:
            sicht = _live().request_authorization(
                user_initiated=body.user_initiated)
        except LiveError as exc:
            raise _live_error(exc) from exc
        return S.AuthorizationOut(**vars(sicht))

    @router.post("/sync", response_model=S.SyncRunOut)
    def run_sync(request: Request) -> Any:
        """Ein ausdrücklich ausgelöster, ausschließlich lesender Lauf.

        Zwei gleichzeitige Läufe desselben Workspace sind ausgeschlossen; der
        zweite bekommt 409 statt eines halben Bestands.
        """
        try:
            lauf = _live().sync(workspace_id=workspace(request))
        except LiveError as exc:
            raise _live_error(exc) from exc
        return S.SyncRunOut(**vars(lauf))

    # ── Wiederherstellung nach dem Vorfall vom 2026-07-30 ───────────────────
    #
    # Eng begrenzt und ausdrücklich **keine** gewöhnliche Nutzeraktion: die
    # Route beantwortet einen konkret erkannten Fehlerzustand — lokal
    # getombstonete Kontakte, die der Provider unverändert kennt. Sie ist kein
    # Reparatur-, SQL- oder Adminendpunkt und löst nichts anderes aus als den
    # bereits geprüften `ContactsRecoveryService`.
    #
    # Kein Start, kein Seitenaufruf, kein Folgesync, kein Agent kann sie
    # auslösen: zwei Pflichtbestätigungen im Körper und keine Schaltfläche in
    # der Oberfläche.
    @router.post("/recovery/suspicious-empty", response_model=S.RecoveryRunOut)
    def recover_suspicious_empty(body: S.RecoveryRunIn, request: Request) -> Any:
        """Reaktiviert fälschlich getombstonete Kontakte. Ein Lauf, ein Klick."""
        del body          # validiert; die Werte selbst werden nicht gebraucht
        dienst = getattr(module, "recovery_service", None)
        if dienst is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "unsupported",
                        "message": "Kein Wiederherstellungsdienst konfiguriert",
                        "retryable": False})
        live = getattr(module, "live_service", None)
        laeuft = bool(live and live.is_running(workspace(request)))
        try:
            ergebnis = dienst.recover(sync_running=laeuft)
        except RecoveryBusy as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "conflict", "message": str(exc),
                        "retryable": True}) from exc
        except RecoveryNotApplicable as exc:
            # Fail-closed **vor** jedem Store-Zugriff: kein Sidecar, keine
            # Enumeration, keine Datenbankaenderung.
            raise HTTPException(
                status_code=409,
                detail={"code": "conflict", "message": str(exc),
                        "technical_code": exc.technical_code,
                        "retryable": False}) from exc
        return S.RecoveryRunOut(
            status="recovered" if ergebnis.succeeded else "failed",
            containers_checked=ergebnis.containers,
            contacts_received=ergebnis.examined,
            reactivated=ergebnis.reactivated,
            tombstones_reconciled=ergebnis.tombstones_reconciled,
            still_absent=ergebnis.still_absent,
            local_ids_preserved=True, full_diff_required=True,
            cursor_present=False, mutations_performed=False,
            completed_at=ergebnis.completed_at,
            technical_code=ergebnis.error_class or "",
            retryable=not ergebnis.succeeded)

    # ── Mutationen und Freigaben (vor {contact_id}, sonst schluckt der
    #    Pfadparameter diese Routen) ───────────────────────────────────────
    @router.get("/mutations", response_model=list[S.MutationOut])
    def list_mutations(request: Request,
                       state: str | None = Query(default=None, max_length=64),
                       limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1,
                                          le=MAX_PAGE_SIZE)) -> Any:
        return [_mutation_out(m) for m in queries.list_mutations(
            workspace_id=workspace(request), state=state, limit=limit)]

    @router.get("/mutations/{mutation_id}", response_model=S.MutationDetailOut)
    def get_mutation(mutation_id: str, request: Request) -> Any:
        ws = workspace(request)
        eintrag = queries.get_mutation(mutation_id, workspace_id=ws)
        if eintrag is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        aenderungen = queries.mutation_changes(mutation_id, workspace_id=ws)
        basis = _mutation_out(eintrag).model_dump()
        return S.MutationDetailOut(
            **basis,
            changes=[S.FieldChangeOut(field_name=c["field"],
                                      previous=c["previous"],
                                      planned=c["planned"])
                     for c in aenderungen],
            payload_digest=eintrag.payload_digest,
            preview_digest=eintrag.preview_digest)

    @router.post("/mutations/{mutation_id}/reconcile",
                 response_model=S.ReconcileOut)
    def reconcile(mutation_id: str, request: Request) -> Any:
        """Gleicht **ausschließlich lesend** ab (Plan §7.2).

        In Gate D existiert noch kein Leser gegen den echten Store; ohne
        injizierten Leser antwortet die Route fail-closed statt zu raten.
        """
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        leser = getattr(module, "reconcile_reader", None)
        if leser is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "unsupported",
                        "message": "Kein Abgleichleser konfiguriert; der "
                                   "Abgleich braucht eine lesende Bridge",
                        "retryable": True})
        try:
            ergebnis = module.reconcile_service(leser).reconcile(mutation_id)
        except MutationError as exc:
            raise _http_error(exc) from exc
        return S.ReconcileOut(mutation_id=ergebnis.mutation_id,
                              verdict=ergebnis.verdict, state=ergebnis.state,
                              provider_identifier=ergebnis.provider_identifier,
                              detail=ergebnis.detail)

    @router.get("/approvals", response_model=list[S.ApprovalOut])
    def list_approvals(request: Request,
                       state: str | None = Query(default=None, max_length=64),
                       include_expired: bool = Query(default=True)) -> Any:
        return [S.ApprovalOut(**vars(a)) for a in queries.list_approvals(
            workspace_id=workspace(request), state=state,
            include_expired=include_expired)]

    @router.get("/approvals/{approval_id}", response_model=S.ApprovalOut)
    def get_approval(approval_id: str, request: Request) -> Any:
        eintrag = queries.get_approval(approval_id,
                                       workspace_id=workspace(request))
        if eintrag is None:
            raise _http_error(MutationNotFound("Freigabe existiert nicht"))
        return S.ApprovalOut(**vars(eintrag))

    def _entscheiden(mutation_id: str, request: Request, aktion: str,
                     decision_actor: str | None) -> Any:
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        service = _mutation_service()
        try:
            if aktion == "expire":
                service.expire(mutation_id)
            else:
                getattr(service, aktion)(mutation_id,
                                         decision_actor=decision_actor)
        except (ApprovalError, MutationError) as exc:
            raise _http_error(exc) from exc
        eintrag = queries.get_approval(
            queries.get_mutation(mutation_id, workspace_id=ws).approval_id,
            workspace_id=ws)
        return S.ApprovalOut(**vars(eintrag))

    @router.post("/mutations/{mutation_id}/approve", response_model=S.ApprovalOut)
    def approve(mutation_id: str, body: S.ApprovalDecisionIn,
                request: Request) -> Any:
        return _entscheiden(mutation_id, request, "grant", body.decision_actor)

    @router.post("/mutations/{mutation_id}/reject", response_model=S.ApprovalOut)
    def reject(mutation_id: str, body: S.ApprovalDecisionIn,
               request: Request) -> Any:
        return _entscheiden(mutation_id, request, "reject", body.decision_actor)

    @router.post("/mutations/{mutation_id}/cancel", response_model=S.ApprovalOut)
    def cancel(mutation_id: str, body: S.ApprovalDecisionIn,
               request: Request) -> Any:
        return _entscheiden(mutation_id, request, "cancel", body.decision_actor)

    @router.post("/mutations/{mutation_id}/expire", response_model=S.ApprovalOut)
    def expire(mutation_id: str, request: Request) -> Any:
        """Markiert eine abgelaufene Freigabe ausdrücklich als `expired`.

        Gate-C-Auflage: Ablauf geschieht nicht durch einen Timer, sondern durch
        eine sichtbare Handlung.
        """
        return _entscheiden(mutation_id, request, "expire", None)

    # ── Mutationen vorbereiten ──────────────────────────────────────────────
    def _prepare(command) -> S.PreparedMutationOut:
        try:
            vorgang = _mutation_service().prepare(command)
        except (MutationError, ApprovalError) as exc:
            raise _http_error(exc) from exc
        vorschau = vorgang.preview
        return S.PreparedMutationOut(
            mutation_id=vorgang.mutation_id, approval_id=vorgang.approval_id,
            state=vorgang.state, payload_digest=vorgang.payload_digest,
            preview_digest=vorschau.digest, reused=vorgang.reused,
            command=vorschau.command,
            target_provider_identifier=vorschau.target_provider_identifier,
            container_identifier=vorschau.container_identifier,
            target_label=vorschau.target_label,
            changes=[S.FieldChangeOut(field_name=c.field_name,
                                      previous=c.previous, planned=c.planned)
                     for c in vorschau.changes],
            warnings=list(vorschau.warnings))

    @router.post("", response_model=S.PreparedMutationOut, status_code=201)
    def prepare_create(body: S.CreateContactIn, request: Request) -> Any:
        try:
            command = CreateContact(
                mutation_id=str(uuid.uuid4()),
                idempotency_key=body.idempotency_key,
                provider_account_id=body.provider_account_id,
                workspace_id=workspace(request), actor=actor(request),
                initiation_context=InitiationContext(body.initiation_context),
                correlation_id=body.correlation_id,
                container_identifier=body.container_identifier,
                draft=ContactDraft(body.fields))
        except MutationError as exc:
            raise _http_error(exc) from exc
        return _prepare(command)

    @router.patch("/{contact_id}", response_model=S.PreparedMutationOut)
    def prepare_update(contact_id: str, body: S.UpdateContactIn,
                       request: Request) -> Any:
        ws = workspace(request)
        if queries.get_contact(contact_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Kontakt existiert nicht"))
        try:
            command = UpdateContact(
                mutation_id=str(uuid.uuid4()),
                idempotency_key=body.idempotency_key,
                provider_account_id=body.provider_account_id,
                workspace_id=ws, actor=actor(request),
                initiation_context=InitiationContext(body.initiation_context),
                correlation_id=body.correlation_id,
                target_provider_identifier=body.target_provider_identifier,
                expected_revision=body.expected_revision,
                patch=ContactPatch(body.fields))
        except MutationError as exc:
            raise _http_error(exc) from exc
        return _prepare(command)

    @router.post("/{contact_id}/delete", response_model=S.PreparedMutationOut)
    def prepare_delete(contact_id: str, body: S.DeleteContactIn,
                       request: Request) -> Any:
        """Bereitet eine Löschung vor.

        Bewusst `POST …/delete` statt `DELETE`: Der Aufruf **löscht nichts**,
        er erzeugt einen freigabepflichtigen Vorgang mit Nutzlast im Rumpf.
        Ein `DELETE` mit Body wäre irreführend und in Zwischenschichten
        unzuverlässig.
        """
        ws = workspace(request)
        if queries.get_contact(contact_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Kontakt existiert nicht"))
        try:
            command = DeleteContact(
                mutation_id=str(uuid.uuid4()),
                idempotency_key=body.idempotency_key,
                provider_account_id=body.provider_account_id,
                workspace_id=ws, actor=actor(request),
                initiation_context=InitiationContext(body.initiation_context),
                correlation_id=body.correlation_id,
                target_provider_identifier=body.target_provider_identifier,
                expected_revision=body.expected_revision)
        except MutationError as exc:
            raise _http_error(exc) from exc
        return _prepare(command)

    # ── Kontaktdetail und lokale Kategorien ─────────────────────────────────
    @router.get("/{contact_id}", response_model=S.ContactDetailOut)
    def get_contact(contact_id: str, request: Request) -> Any:
        kontakt = queries.get_contact(contact_id,
                                      workspace_id=workspace(request))
        if kontakt is None:
            raise _http_error(MutationNotFound("Kontakt existiert nicht"))
        return _detail_out(kontakt)

    @router.post("/{contact_id}/roles", response_model=S.RolesOut)
    def assign_role(contact_id: str, body: S.RoleAssignIn,
                    request: Request) -> Any:
        try:
            neue = roles.assign(contact_id, body.role,
                                workspace_id=workspace(request),
                                actor=actor(request))
        except MutationError as exc:
            raise _http_error(exc) from exc
        return S.RolesOut(contact_id=contact_id, roles=list(neue))

    @router.delete("/{contact_id}/roles/{role}", response_model=S.RolesOut)
    def remove_role(contact_id: str, role: str, request: Request) -> Any:
        try:
            neue = roles.remove(contact_id, role,
                                workspace_id=workspace(request),
                                actor=actor(request))
        except MutationError as exc:
            raise _http_error(exc) from exc
        return S.RolesOut(contact_id=contact_id, roles=list(neue))

    return router


# ── Umwandlung Domäne → Transport ───────────────────────────────────────────
def _sync_status_out(s) -> S.SyncStatusOut:
    """Interne Sicht → öffentlicher Vertrag, unter Maskierung der Kennungen.

    Die einzige Stelle, an der `SyncStatusOut` entsteht. Die rohen Kennungen
    bleiben in `SyncStatusView` — Persistenz und Sidecar brauchen sie, der
    Transport nicht.
    """
    erfolge = [t for t in (s.cursor_taken_at, s.last_full_diff_at) if t]
    return S.SyncStatusOut(
        provider_type=provider_type(s.provider_account_id),
        account_ref=account_ref(s.provider_account_id),
        container_ref=container_ref(s.container_identifier),
        mode=s.mode, circuit_state=s.circuit_state,
        key_set_version=s.key_set_version,
        cursor_present=s.has_cursor,
        cursor_taken_at=s.cursor_taken_at,
        last_full_diff_at=s.last_full_diff_at,
        last_successful_run_at=max(erfolge) if erfolge else None,
        # Identisch zu `pending_full_diff`: alles außer einem gültigen Cursor
        # im Modus `delta` führt auf den Voll-Diff-Pfad.
        requires_full_diff=(s.mode == SyncMode.FULL_DIFF_REQUIRED.value
                            or not s.has_cursor),
        updated_at=s.updated_at)


def _mutation_out(m) -> S.MutationOut:
    return S.MutationOut(
        mutation_id=m.mutation_id, command=m.command, state=m.state,
        outcome=m.outcome, initiation_context=m.initiation_context,
        actor=m.actor, correlation_id=m.correlation_id,
        provider_account_id=m.provider_account_id,
        target_contact_id=m.target_contact_id,
        target_display_name=m.target_display_name,
        container_identifier=m.container_identifier,
        expected_revision=m.expected_revision, attempt_count=m.attempt_count,
        last_error_code=m.last_error_code, created_at=m.created_at,
        approved_at=m.approved_at, completed_at=m.completed_at,
        approval_id=m.approval_id, approval_state=m.approval_state,
        approval_expires_at=m.approval_expires_at,
        requires_reconcile=m.requires_reconcile,
        needs_manual_decision=m.needs_manual_decision)


def _labeled(werte, wert_feld: str | None = None,
             extra_felder: tuple[str, ...] = ()) -> list[S.LabeledValueOut]:
    ergebnis = []
    for w in werte:
        ergebnis.append(S.LabeledValueOut(
            id=w.id, position=w.position, label_raw=w.label_raw,
            label_normalized=w.label_normalized,
            value=getattr(w, wert_feld) if wert_feld else None,
            extra={f: getattr(w, f, None) for f in extra_felder}))
    return ergebnis


def _detail_out(c: Contact) -> S.ContactDetailOut:
    schreibziel = c.external_ids[0].write_target if c.external_ids else None
    return S.ContactDetailOut(
        id=c.id, workspace_id=c.workspace_id, display_name=c.display_name,
        contact_type=c.contact_type.value, given_name=c.given_name,
        middle_name=c.middle_name, family_name=c.family_name,
        nickname=c.nickname, organization_name=c.organization_name,
        department_name=c.department_name, job_title=c.job_title,
        is_me_card=c.is_me_card, birthday_year=c.birthday_year,
        birthday_month=c.birthday_month, birthday_day=c.birthday_day,
        local_revision=c.local_revision, sync_state=c.sync_state.value,
        conflict_state=c.conflict_state,
        field_completeness=c.field_completeness.value, updated_at=c.updated_at,
        thumbnail_blob_ref=c.thumbnail_blob_ref,
        emails=_labeled(c.emails, "value_raw"),
        phones=_labeled(c.phones, "value_raw"),
        postal_addresses=_labeled(
            c.postal_addresses, None,
            ("street", "city", "postal_code", "country", "iso_country_code")),
        urls=_labeled(c.urls, "value_raw"),
        dates=_labeled(c.dates, None, ("kind", "year", "month", "day")),
        social_profiles=_labeled(c.social_profiles, "username", ("service",)),
        instant_messages=_labeled(c.instant_messages, "username", ("service",)),
        relations=_labeled(c.relations, None,
                           ("relation_type", "target_name_raw",
                            "to_contact_id")),
        roles=[r.role for r in c.roles],
        field_availability=[
            S.FieldAvailabilityOut(field_name=f.field_name,
                                   state=f.state.value)
            for f in c.field_availability],
        provider_accounts=sorted({e.provider_account_id
                                  for e in c.external_ids}),
        containers=sorted({e.container_identifier for e in c.external_ids}),
        write_target=schreibziel, unified_read_only=True)
