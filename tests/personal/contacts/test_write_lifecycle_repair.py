"""Reparaturblock 2026-08-13: B (Ablauf beim Lesen), E (Tombstone), F (Vorwert).

**Kontaktfrei.** Fake-Provider, temporäre SQLite-Datenbanken, erfundene Daten.
Kein Sidecar, kein TCC, kein `CNContactStore`.

Jeder Test reproduziert den Defekt, wie er vor der Reparatur war — nicht nur
das gewünschte Verhalten danach. Ein Test, der nur das Ziel prüft, hätte auch
vor der Reparatur grün sein können, wenn der Defekt woanders sass.
"""

from __future__ import annotations

import pytest

from personaljarvis.base.approvals import ApprovalState, effective_state
from personaljarvis.contacts.application import (
    ContactsMutationService,
    UpdateContact,
)
from personaljarvis.contacts.application.queries import ContactsQueryService
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import ExternalIdentifier
from personaljarvis.contacts.repositories.sqlite import (
    SqliteContactRepository,
    SqliteExternalIdentifierRepository,
)

from .conftest import WORKSPACE, make_contact, new_id
from .test_mutation_pipeline import (
    CONTAINER,
    KONTO,
    MENSCH,
    AttrappenProvider,
)

FRUEHER = "2026-08-13T09:00:00+00:00"
SPAETER = "2026-08-13T11:00:00+00:00"


# ═══ B · Ablauf wird beim Lesen ausgewertet ═════════════════════════════════
class TestAblaufBeimLesen:
    """Der Kern von §8 B: `granted` überlebte seine Frist in jeder Anzeige."""

    def test_erteilte_freigabe_nach_frist_liest_sich_als_abgelaufen(self):
        assert effective_state(ApprovalState.GRANTED, FRUEHER,
                               now=SPAETER) == ApprovalState.EXPIRED

    def test_wartende_freigabe_nach_frist_liest_sich_als_abgelaufen(self):
        assert effective_state(ApprovalState.AWAITING, FRUEHER,
                               now=SPAETER) == ApprovalState.EXPIRED

    def test_vor_der_frist_bleibt_erteilt_erteilt(self):
        assert effective_state(ApprovalState.GRANTED, SPAETER,
                               now=FRUEHER) == ApprovalState.GRANTED

    @pytest.mark.parametrize("zustand", [
        ApprovalState.REJECTED, ApprovalState.CANCELLED,
        ApprovalState.CONSUMED, ApprovalState.EXPIRED,
    ])
    def test_entschiedene_zustaende_werden_nicht_umgedeutet(self, zustand):
        """Ein verbrauchter Vorgang wird durch Zeitablauf nicht „abgelaufen".

        Sonst verlöre der Bericht die Aussage, *wie* er geendet hat.
        """
        assert effective_state(zustand, FRUEHER, now=SPAETER) == zustand

    def test_die_grenze_ist_einschliesslich(self):
        """Gleicher Zeitpunkt heisst abgelaufen — wie in `consume()`."""
        assert effective_state(ApprovalState.GRANTED, FRUEHER,
                               now=FRUEHER) == ApprovalState.EXPIRED

    def test_leseweg_der_freigabeliste_zeigt_den_wirksamen_zustand(self, module):
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module)
        befehl = _update_befehl(kontakt)
        dienst.prepare(befehl)
        dienst.grant(befehl.mutation_id, decision_actor=MENSCH)

        fragen = ContactsQueryService(module)
        vorher = fragen.list_approvals(workspace_id=WORKSPACE)
        assert [a.state for a in vorher] == [ApprovalState.GRANTED]
        assert not vorher[0].is_expired

        # Derselbe Datensatz, nur später gelesen. Es wird nichts geschrieben.
        nachher = fragen.list_approvals(workspace_id=WORKSPACE,
                                        now="2099-01-01T00:00:00+00:00")
        assert [a.state for a in nachher] == [ApprovalState.EXPIRED]
        assert nachher[0].is_expired

    def test_lesen_schreibt_den_zustand_nicht_fort(self, module):
        """Anzeige ist kein Zustandswechsel — `expire` bleibt ein Schritt."""
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module)
        befehl = _update_befehl(kontakt)
        dienst.prepare(befehl)
        dienst.grant(befehl.mutation_id, decision_actor=MENSCH)

        ContactsQueryService(module).list_approvals(
            workspace_id=WORKSPACE, now="2099-01-01T00:00:00+00:00")

        with module.unit_of_work() as uow:
            gespeichert = uow.execute(
                "SELECT state FROM personal_approvals").fetchone()["state"]
        assert gespeichert == ApprovalState.GRANTED


# ═══ E · Die Detailroute verspricht den aktiven Kontakt ═════════════════════
class TestTombstoneDetailroute:
    def test_aktiver_kontakt_wird_geliefert(self, module):
        kontakt = _lokal(module)
        gefunden = ContactsQueryService(module).get_contact(
            kontakt.id, workspace_id=WORKSPACE)
        assert gefunden is not None and gefunden.id == kontakt.id

    def test_tombstone_wird_nicht_mehr_geliefert(self, module):
        kontakt = _lokal(module)
        with module.unit_of_work() as uow:
            SqliteContactRepository(uow).soft_delete(
                kontakt.id, "2026-08-13T10:00:00+00:00")

        assert ContactsQueryService(module).get_contact(
            kontakt.id, workspace_id=WORKSPACE) is None

    def test_historie_bleibt_ausdruecklich_erreichbar(self, module):
        """Der Tombstone verschwindet aus der aktiven Sicht, nicht aus der DB.

        Eine positive Abwesenheitskontrolle nach DELETE benutzt die aktive
        Sicht; die Historie braucht den ausdrücklichen Schalter.
        """
        kontakt = _lokal(module)
        with module.unit_of_work() as uow:
            SqliteContactRepository(uow).soft_delete(
                kontakt.id, "2026-08-13T10:00:00+00:00")

        historisch = ContactsQueryService(module).get_contact(
            kontakt.id, workspace_id=WORKSPACE, include_tombstones=True)
        assert historisch is not None
        assert historisch.is_tombstone

    def test_fremder_workspace_bekommt_weiterhin_nichts(self, module):
        kontakt = _lokal(module)
        assert ContactsQueryService(module).get_contact(
            kontakt.id, workspace_id="ws-fremd") is None


# ═══ F · Der Vorwert im Änderungssatz ═══════════════════════════════════════
class TestVorwertImAenderungssatz:
    def test_update_nennt_den_vorwert_statt_null(self, module):
        """Der Defekt: kanonischer Schlüssel gegen Spaltennamen nachgeschlagen.

        `nickname` heisst kanonisch und als Spalte gleich — deshalb prüft
        dieser Test ein Feld, dessen Namen sich unterscheiden.
        """
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module, organization_name="Beispiel GmbH")
        befehl = _update_befehl(
            kontakt, patch_felder={"organization_name": "Beispiel AG"})
        dienst.prepare(befehl)

        aenderungen = ContactsQueryService(module).mutation_changes(
            befehl.mutation_id, workspace_id=WORKSPACE)

        nach_feld = {a["field"]: a for a in aenderungen}
        assert "organizationName" in nach_feld, nach_feld
        eintrag = nach_feld["organizationName"]
        assert eintrag["previous"] == "Beispiel GmbH"
        assert eintrag["planned"] == "Beispiel AG"

    def test_create_hat_keinen_vorwert(self, module):
        """Kein Vorzustand ist die richtige Aussage, kein Defekt."""
        from personaljarvis.contacts.application import ContactDraft, CreateContact

        dienst = ContactsMutationService(module, AttrappenProvider())
        befehl = CreateContact(
            mutation_id=new_id(), idempotency_key=new_id(),
            provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
            initiation_context=InitiationContext.USER_DIRECT,
            correlation_id=new_id(), container_identifier=CONTAINER,
            draft=ContactDraft({"given_name": "Fixi", "family_name": "Eins"}))
        dienst.prepare(befehl)

        aenderungen = ContactsQueryService(module).mutation_changes(
            befehl.mutation_id, workspace_id=WORKSPACE)
        assert aenderungen
        assert all(a["previous"] is None for a in aenderungen)


# ═══ A · Der Zielablageort in der Vorschau ══════════════════════════════════
class TestZielablageortInDerVorschau:
    """§8 A: Die Vorschau nannte den Zielcontainer nicht sichtbar.

    Für `update` und `delete` stand dort fest `None` — die Nutzlast nennt
    keinen Container, weil nichts verschoben wird (ADR-0026 §7). Für den
    Menschen ist „wohin" trotzdem die erste Frage vor einer Freigabe.
    """

    def test_create_nennt_ablageort_und_art(self, module):
        from personaljarvis.contacts.application import ContactDraft, CreateContact

        _inventar(module)
        dienst = ContactsMutationService(module, AttrappenProvider())
        befehl = CreateContact(
            mutation_id=new_id(), idempotency_key=new_id(),
            provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
            initiation_context=InitiationContext.USER_DIRECT,
            correlation_id=new_id(), container_identifier=CONTAINER,
            draft=ContactDraft({"given_name": "Fixi", "family_name": "Eins"}))
        vorgang = dienst.prepare(befehl)

        assert vorgang.preview.container_identifier == CONTAINER
        assert vorgang.preview.container_type == "local"

    @pytest.mark.parametrize("bauer", ["update", "delete"])
    def test_update_und_delete_nennen_den_ablageort_ebenfalls(self, module, bauer):
        from personaljarvis.contacts.application import DeleteContact

        _inventar(module)
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module)
        if bauer == "update":
            befehl = _update_befehl(kontakt)
        else:
            befehl = DeleteContact(
                mutation_id=new_id(), idempotency_key=new_id(),
                provider_account_id=KONTO, workspace_id=WORKSPACE,
                actor=MENSCH,
                initiation_context=InitiationContext.USER_DIRECT,
                correlation_id=new_id(), target_provider_identifier="raw-1")
        vorgang = dienst.prepare(befehl)

        assert vorgang.preview.container_identifier == CONTAINER
        assert vorgang.preview.container_type == "local"

    def test_unbekannte_art_ist_eine_aussage_keine_vermutung(self, module):
        """Ohne Inventareintrag lautet die Antwort `unknown` — nicht `local`."""
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module)
        vorgang = dienst.prepare(_update_befehl(kontakt))

        assert vorgang.preview.container_identifier == CONTAINER
        assert vorgang.preview.container_type == "unknown"

    def test_der_digest_deckt_die_art_des_ablageorts(self):
        """Was gezeigt wurde, muss die Freigabe binden."""
        from personaljarvis.contacts.application.models import MutationPreview

        eine = MutationPreview(command="create",
                               target_provider_identifier=None,
                               container_identifier="c-1",
                               container_type="local")
        andere = MutationPreview(command="create",
                                 target_provider_identifier=None,
                                 container_identifier="c-1",
                                 container_type="cardDAV")
        assert eine.digest != andere.digest

    def test_der_leseweg_nennt_den_ablageort_auch_spaeter(self, module):
        """Nicht nur beim Vorbereiten — auch beim Nachschauen und Freigeben."""
        _inventar(module)
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module)
        befehl = _update_befehl(kontakt)
        dienst.prepare(befehl)

        fragen = ContactsQueryService(module)
        vorgang = fragen.get_mutation(befehl.mutation_id,
                                      workspace_id=WORKSPACE)
        assert vorgang.container_identifier == CONTAINER
        assert vorgang.container_type == "local"

        freigabe = fragen.list_approvals(workspace_id=WORKSPACE)[0]
        assert freigabe.container_identifier == CONTAINER
        assert freigabe.container_type == "local"
        assert freigabe.target_display_name == kontakt.display_name

    def test_die_rohe_kennung_verlaesst_die_api_grenze_nicht(self, module):
        """Nach draussen geht das Kürzel, nie die Apple-Kennung."""
        from personaljarvis.contacts.api.redaction import container_ref

        _inventar(module)
        dienst = ContactsMutationService(module, AttrappenProvider())
        kontakt = _lokal(module)
        befehl = _update_befehl(kontakt)
        dienst.prepare(befehl)

        freigabe = ContactsQueryService(module).list_approvals(
            workspace_id=WORKSPACE)[0]
        kuerzel = container_ref(freigabe.container_identifier)
        assert kuerzel.startswith("C-")
        assert CONTAINER not in kuerzel


# ── Hilfen ──────────────────────────────────────────────────────────────────
def _inventar(module, *, art="local"):
    """Ein Inventareintrag, damit die Art des Ablageorts bekannt ist."""
    with module.unit_of_work() as uow:
        uow.execute(
            "INSERT INTO contacts_sync_state (provider_account_id, "
            "container_identifier, key_set_version, mode, circuit_state, "
            "updated_at, container_type) VALUES (?,?,?,?,?,?,?)",
            (KONTO, CONTAINER, "v1", "delta", "closed",
             "2026-08-13T10:00:00+00:00", art))


def _lokal(module, *, provider_identifier="raw-1", **felder):
    with module.unit_of_work() as uow:
        kontakt = make_contact(**felder)
        SqliteContactRepository(uow).add(kontakt)
        SqliteExternalIdentifierRepository(uow).upsert(
            kontakt.id, ExternalIdentifier(
                id=new_id(), provider_account_id=KONTO,
                container_identifier=CONTAINER,
                provider_identifier=provider_identifier, key_set_version="v1"))
    return kontakt


def _update_befehl(kontakt, *, patch_felder=None):
    from personaljarvis.contacts.application import ContactPatch

    return UpdateContact(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), target_provider_identifier="raw-1",
        patch=ContactPatch(patch_felder or {"nickname": "Neu"}))
