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

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from personaljarvis.base.approvals import (
    ApprovalError,
    ApprovalExpired,
    ApprovalNotPending,
    ApprovalPayloadMismatch,
    SelfApprovalRejected,
    owner_decision_attested,
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
    MutationAlreadyPending,
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
from personaljarvis.contacts.application.app_channel import (
    app_channel_capabilities,
)
from personaljarvis.contacts.application.app_execution import (
    AppExecutionService,
    ChannelNotEnabled,
    DeleteConfirmationRequired,
    SettleConflict,
)
from personaljarvis.contacts.application.execution_contracts import (
    ExecutionContractError,
    parse_execution_report,
)
from personaljarvis.contacts.application.roles import ContactsRoleService
from personaljarvis.contacts.domain.enums import InitiationContext, SyncMode
from personaljarvis.contacts.domain.models import Contact
from personaljarvis.contacts.sync.containers import normalize_container_type
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

#: Die Faehigkeit, fuer die ein Eigentuemerbeleg hier gelten muss. Steht einmal
#: und wird nie zusammengesetzt: eine getippte Faehigkeit faende keinen Beleg.
ATTESTATION_CAPABILITY = "contacts"

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
    # Eigener Code statt eines allgemeinen Konflikts: Die Oberflaeche
    # soll auf den bestehenden Vorgang zeigen koennen, statt nur
    # „geht nicht" zu melden.
    (MutationAlreadyPending, 409, "already_pending"),
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
            detail = {"code": code, "message": str(exc), "retryable": False}
            # Traegt der Fehler die Kennung des blockierenden Vorgangs, geht
            # sie mit: Sie ist eine lokale Mutationskennung, keine
            # Providerangabe, und ohne sie muesste die Oberflaeche raten,
            # worauf sie zeigen soll.
            offen = getattr(exc, "mutation_id", None)
            if offen:
                detail["mutation_id"] = offen
                detail["state"] = getattr(exc, "state", None)
            return HTTPException(status_code=status, detail=detail)
    return HTTPException(
        status_code=500,
        detail={"code": "internal", "message": type(exc).__name__,
                "retryable": False})


class _SanitizedValidationRoute(APIRoute):
    """Validierungsfehler ohne die abgelehnte Eingabe.

    FastAPI antwortet auf einen Schemaverstoss standardmässig mit der vollen
    Pydantic-Fehlerliste — **einschliesslich des eingereichten Werts** unter
    `input`. Bei einem Kontaktfeld ist dieser Wert ein Kontaktwert, und der
    stand damit im Antwortkörper, in jedem Log und in jedem Fehlerbericht.

    Diese Route-Klasse ersetzt die Antwort durch die Vertragsform des Moduls:
    **welche** Felder verletzt sind, steht drin — **was** darin stand, nicht.
    Die ursprüngliche Ausnahme wird bewusst nicht verkettet (`from None`),
    sonst trüge der Traceback den Wert weiter.
    """

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                felder = sorted({
                    ".".join(str(teil) for teil in fehler.get("loc", ())[1:])
                    for fehler in exc.errors()})
                raise HTTPException(
                    status_code=422,
                    detail={"code": "validation_failed",
                            "message": "Die Anfrage entspricht nicht dem "
                                       "Vertrag dieses Endpunkts",
                            "fields": [f for f in felder if f],
                            "retryable": False}) from None

        return handler


def create_contacts_router(module) -> APIRouter:
    """Baut den Router über einem gestarteten `ContactsModule`."""
    router = APIRouter(prefix=PREFIX, tags=["personal-contacts"],
                       route_class=_SanitizedValidationRoute)
    queries = ContactsQueryService(module)
    roles = ContactsRoleService(module)

    def workspace(request: Request) -> str:
        return request.headers.get(DEFAULT_WORKSPACE_HEADER) or DEFAULT_WORKSPACE

    def actor(request: Request) -> str:
        """Der handelnde Mensch. In Gate D aus dem Kopf-Feld; mit dem
        Session-Token-Fluss (DEV-4) wird daraus die Sitzungsidentität."""
        return request.headers.get("X-Personal-Actor") or "desktop-user"

    def kanal():
        """Der Kanalzustand **jetzt** — nicht der beim Start.

        Die Schreibfreigabe ist eine ablaufende Datei; ein einmal
        eingefrorener Fähigkeitssatz meldete nach ihrem Entzug weiterhin
        „darf". Der Aufruf ist billig (ein `stat` und ein kleines JSON) und
        die einzige Form, in der die Antwort ehrlich bleibt.
        """
        return app_channel_capabilities(database_path=module_datenbankpfad)

    module_datenbankpfad = getattr(getattr(module, "_factory", None), "_path", None)
    app_execution = AppExecutionService(module, channel_capabilities=kanal)

    def _mutation_service():
        # Welcher Provider dahintersteht, bleibt Sache der Komposition.
        # Ausgeführt wird ausschliesslich über `POST …/execute`, und das
        # verlangt eine ausdrückliche Nutzeraktion im Rumpf.
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
            items=[_summary_out(z) for z in seite.items],
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
        nachher = queries.get_mutation(mutation_id, workspace_id=ws)
        return S.ReconcileOut(
            mutation_id=ergebnis.mutation_id, verdict=ergebnis.verdict,
            state=ergebnis.state,
            contact_id=nachher.target_contact_id if nachher else None,
            detail=ergebnis.detail)

    # ── Ausführung: eine eigene, ausdrückliche Nutzeraktion ─────────────────
    @router.get("/app-channel", response_model=S.AppChannelCapabilitiesOut)
    def app_channel() -> Any:
        """Was der App-Prozess-Kanal kann — serverseitig, nie aus dem Client.

        In Phase A meldet die Route `provider_write_enabled: false` **und**
        `create/update/delete_supported: false` bei
        `channel_mode: "disabled"`. Das ist keine Momentaufnahme, sondern
        eine Konstante des Stands: Es gibt keinen nativen Save, also auch
        keine unterstützte Operation. Der Fake-Modus ist hier unerreichbar —
        er wird aus keiner Anfrage konstruiert.
        """
        return S.AppChannelCapabilitiesOut(**kanal().as_dict())

    @router.post("/mutations/{mutation_id}/claim-app-execution",
                 response_model=S.ExecutionOrderOut)
    def claim_app_execution(mutation_id: str, body: S.ClaimAppExecutionIn,
                            request: Request) -> Any:
        """Beansprucht **einen** Ausfuehrungsversuch und gibt den Auftrag aus.

        Hoechstens einmal je Vorgang: Ein zweiter Aufruf bekommt nie erneut
        einen Rohtoken, sondern einen typisierten Konflikt — auch dann,
        wenn der erste Auftrag verfallen ist. Ob irgendwo gesendet wurde,
        ist nach der Ausgabe unbeweisbar; der Weg heisst dann Abgleich.
        """
        assert body.user_initiated is True   # von Pydantic erzwungen
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        try:
            auftrag = app_execution.claim(
                mutation_id, confirm_delete=body.confirm_delete)
        except DeleteConfirmationRequired as exc:
            # 409, nicht 400: Der Aufruf ist wohlgeformt, es fehlt die
            # zweite Handlung des Menschen.
            raise HTTPException(status_code=409, detail={
                "code": "confirmation_required", "message": str(exc),
                "retryable": False}) from exc
        except ChannelNotEnabled as exc:
            raise HTTPException(status_code=503, detail={
                "code": "channel_unavailable", "message": str(exc),
                "retryable": False}) from exc
        except (MutationError, ApprovalError) as exc:
            raise _http_error(exc) from exc
        return S.ExecutionOrderOut(**auftrag.as_dict())

    @router.post("/mutations/{mutation_id}/settle-app-execution",
                 response_model=S.SettleResultOut)
    def settle_app_execution(mutation_id: str, body: S.SettleAppExecutionIn,
                             request: Request) -> Any:
        """Nimmt genau einen Bericht entgegen — idempotent, ohne Providerkontakt.

        Diese Route sendet nichts, ruft kein Tauri und keinen Sidecar. Sie
        liest einen geschlossenen Bericht, rechnet seinen Digest selbst und
        entscheidet allein serverseitig ueber den Zustand.
        """
        assert body.user_initiated is True
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        try:
            bericht = parse_execution_report(body.report)
        except ExecutionContractError as exc:
            raise HTTPException(status_code=422, detail={
                "code": exc.error_class, "message": str(exc),
                "retryable": False}) from exc
        try:
            ergebnis = app_execution.settle(mutation_id, bericht,
                                            claim_token=body.claim_token)
        except SettleConflict as exc:
            raise HTTPException(status_code=409, detail={
                "code": "settle_conflict", "message": str(exc),
                "retryable": False}) from exc
        except (MutationError, ApprovalError) as exc:
            raise _http_error(exc) from exc
        return S.SettleResultOut(
            mutation_id=ergebnis.mutation_id, state=ergebnis.state,
            outcome=ergebnis.outcome, error_class=ergebnis.error_class,
            idempotent=ergebnis.idempotent)

    @router.post("/mutations/{mutation_id}/execute",
                 response_model=S.ExecutionResultOut)
    def execute_mutation(mutation_id: str, body: S.ExecuteMutationIn,
                         request: Request) -> Any:
        """Führt **eine** freigegebene Mutation aus (ADR-0025 §1).

        Diese Route ist der einzige Weg zu einem Provider-Schreibvorgang. Sie
        ist bewusst von `approve` getrennt: eine Freigabe sagt „ich habe das
        gesehen und will es", die Ausführung sagt „jetzt". Ein Klick darf
        nicht beides bedeuten.

        Es gibt keinen Hintergrundexecutor und keinen Scheduler, der sie
        aufriefe; `body.user_initiated` ist `Literal[True]` und lässt sich
        nicht durch einen Query-Parameter ersetzen.

        Doppelte und gleichzeitige Aufrufe: der zweite verliert den
        Outbox-Claim und wird typisiert abgewiesen — es gibt genau einen Send.
        """
        assert body.user_initiated is True   # von Pydantic erzwungen
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        try:
            ergebnis = _mutation_service().execute(mutation_id)
        except (MutationError, ApprovalError) as exc:
            raise _http_error(exc) from exc
        return S.ExecutionResultOut(
            mutation_id=ergebnis.mutation_id, state=ergebnis.state,
            outcome=ergebnis.outcome, error_code=ergebnis.error_code,
            # Kein Zustand dieser Pipeline ist automatisch wiederholbar. Ein
            # neuer Versuch ist immer eine neue freigabepflichtige Mutation.
            retryable=False, attempt_count=ergebnis.attempt_count,
            contact_id=ergebnis.contact_id,
            pending_local_catchup=ergebnis.pending_local_catchup)

    def _approval_out(a) -> S.ApprovalOut:
        """Freigabe nach aussen — mit Zielangabe, ohne rohe Kennung.

        `vars(a)` waere hier falsch: `ApprovalSummary.container_identifier`
        traegt die **rohe** Providerkennung, und die verlaesst die API-Grenze
        nie (ADR-0025 §2). Nach draussen geht das Kuerzel.
        """
        felder = vars(a).copy()
        roh = felder.pop("container_identifier", None)
        return S.ApprovalOut(**felder,
                             container_ref=container_ref(roh) if roh else None)

    @router.get("/approvals", response_model=list[S.ApprovalOut])
    def list_approvals(request: Request,
                       state: str | None = Query(default=None, max_length=64),
                       include_expired: bool = Query(default=True)) -> Any:
        return [_approval_out(a) for a in queries.list_approvals(
            workspace_id=workspace(request), state=state,
            include_expired=include_expired)]

    @router.get("/approvals/{approval_id}", response_model=S.ApprovalOut)
    def get_approval(approval_id: str, request: Request) -> Any:
        eintrag = queries.get_approval(approval_id,
                                       workspace_id=workspace(request))
        if eintrag is None:
            raise _http_error(MutationNotFound("Freigabe existiert nicht"))
        return _approval_out(eintrag)

    def _entscheiden(mutation_id: str, request: Request, aktion: str,
                     decision_actor: str | None) -> Any:
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        service = _mutation_service()
        try:
            if aktion == "expire":
                service.expire(mutation_id)
            elif aktion == "grant":
                # Diese Route erzeugt **keine** Eigentuemerentscheidung mehr.
                # Sie legt einen Beleg vor, der im App-Prozess entstanden ist;
                # fehlt er, oder ist er nicht an genau diesen Vorgang und diese
                # Nutzlast gebunden, scheitert die Freigabe. Der mitgelieferte
                # Name ist Metadatum, nie Nachweis — genau diese Verwechslung
                # war der Befund vom 2026-08-17.
                vorgang = queries.get_mutation(mutation_id, workspace_id=ws)
                service.grant(
                    mutation_id,
                    decision=owner_decision_attested(
                        capability=ATTESTATION_CAPABILITY,
                        mutation_id=mutation_id,
                        payload_digest=vorgang.payload_digest,
                        preview_digest=vorgang.preview_digest,
                        actor=decision_actor or ""))
            else:
                getattr(service, aktion)(mutation_id,
                                         decision_actor=decision_actor)
        except (ApprovalError, MutationError) as exc:
            raise _http_error(exc) from exc
        eintrag = queries.get_approval(
            queries.get_mutation(mutation_id, workspace_id=ws).approval_id,
            workspace_id=ws)
        return _approval_out(eintrag)

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

    @router.post("/mutations/{mutation_id}/resolve-outcome",
                 response_model=S.ExecutionResultOut)
    def resolve_outcome(mutation_id: str, body: S.ResolveOutcomeIn,
                        request: Request) -> Any:
        """Schliesst einen ungewissen Ausgang nach **externer** Prüfung ab.

        Der Fall: der Provider hat technisch nicht geantwortet, der Mensch hat
        ausserhalb von Jarvis nachgesehen und die Änderung dort nicht
        gefunden. Ohne diesen Weg bliebe der Vorgang für immer offen — und
        ohne ihn wäre die Versuchung gross, ihn stattdessen als „nichts
        gesendet" zu verbuchen, was die Historie verfälschte.

        **Diese Route berührt den Provider nicht.** Kein Sidecar, kein Lesen,
        kein Senden. Sie hält eine menschliche Beobachtung fest und schliesst
        den Vorgang terminal ab; ein zweiter Send wird dadurch nie möglich.
        """
        assert body.user_initiated is True      # von Pydantic erzwungen
        ws = workspace(request)
        if queries.get_mutation(mutation_id, workspace_id=ws) is None:
            raise _http_error(MutationNotFound("Mutation existiert nicht"))
        try:
            ergebnis = _mutation_service().resolve_outcome_manually(
                mutation_id, decision=body.decision, evidence=body.evidence,
                actor=actor(request))
        except (MutationError, ApprovalError) as exc:
            raise _http_error(exc) from exc
        return S.ExecutionResultOut(
            mutation_id=ergebnis.mutation_id, state=ergebnis.state,
            outcome=ergebnis.outcome, error_code=ergebnis.error_code,
            retryable=False, attempt_count=ergebnis.attempt_count,
            contact_id=None, pending_local_catchup=False)

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
            target_contact_id=vorschau.target_contact_id,
            container_ref=(container_ref(vorschau.container_identifier)
                           if vorschau.container_identifier else None),
            container_type=vorschau.container_type or "unknown",
            container_name=vorschau.container_name,
            container_contact_count=vorschau.container_contact_count,
            target_label=vorschau.target_label,
            changes=[S.FieldChangeOut(field_name=c.field_name,
                                      previous=c.previous, planned=c.planned)
                     for c in vorschau.changes],
            warnings=list(vorschau.warnings))

    @router.post("", response_model=S.PreparedMutationOut, status_code=201)
    def prepare_create(body: S.CreateContactIn, request: Request) -> Any:
        """Bereitet eine Neuanlage vor. Es wird **nichts** gesendet.

        Das Ziel ist eine maskierte `container_ref`; die rohe Apple-Kennung
        entsteht erst hier drinnen und verlässt den Prozess nicht.
        """
        try:
            konto, container = queries.resolve_container_ref(body.container_ref)
            command = CreateContact(
                mutation_id=str(uuid.uuid4()),
                idempotency_key=body.idempotency_key,
                provider_account_id=konto,
                workspace_id=workspace(request), actor=actor(request),
                initiation_context=InitiationContext(body.initiation_context),
                correlation_id=body.correlation_id,
                container_identifier=container,
                draft=ContactDraft(body.fields.as_field_mapping()))
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
            konto, ziel = queries.resolve_contact_target(contact_id,
                                                         workspace_id=ws)
            command = UpdateContact(
                mutation_id=str(uuid.uuid4()),
                idempotency_key=body.idempotency_key,
                provider_account_id=konto,
                workspace_id=ws, actor=actor(request),
                initiation_context=InitiationContext(body.initiation_context),
                correlation_id=body.correlation_id,
                target_provider_identifier=ziel,
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
            konto, ziel = queries.resolve_contact_target(contact_id,
                                                         workspace_id=ws)
            command = DeleteContact(
                mutation_id=str(uuid.uuid4()),
                idempotency_key=body.idempotency_key,
                provider_account_id=konto,
                workspace_id=ws, actor=actor(request),
                initiation_context=InitiationContext(body.initiation_context),
                correlation_id=body.correlation_id,
                target_provider_identifier=ziel,
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
def _summary_out(z) -> S.ContactSummaryOut:
    """Listeneintrag mit maskierter Providerherkunft."""
    felder = {k: v for k, v in vars(z).items() if k != "provider_account_ids"}
    return S.ContactSummaryOut(
        **felder,
        account_refs=sorted({account_ref(k) for k in z.provider_account_ids}))


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
        # Zweiter Riegel am Austritt: was nicht im geschlossenen Vorrat steht,
        # verlaesst die Anwendung als `unknown` — nie als Rohwert.
        container_type=normalize_container_type(s.container_type),
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
        provider_type=provider_type(m.provider_account_id),
        account_ref=account_ref(m.provider_account_id),
        target_contact_id=m.target_contact_id,
        target_display_name=m.target_display_name,
        container_ref=(container_ref(m.container_identifier)
                       if m.container_identifier else None),
        container_type=m.container_type or "unknown",
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
    # `writable` statt `write_target`: die Oberflaeche zielt ueber die lokale
    # `id`, das Backend loest sie auf. Eine rohe Providerkennung verlaesst die
    # API nicht mehr (ADR-0025 §2).
    beschreibbar = bool(c.external_ids) and not c.is_me_card
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
        account_refs=sorted({account_ref(e.provider_account_id)
                             for e in c.external_ids}),
        container_refs=sorted({container_ref(e.container_identifier)
                               for e in c.external_ids}),
        provider_type=(provider_type(c.external_ids[0].provider_account_id)
                       if c.external_ids else "unknown"),
        writable=beschreibbar, revision=str(c.local_revision),
        unified_read_only=True)
