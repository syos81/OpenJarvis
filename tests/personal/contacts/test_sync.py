"""Lese-Sync-Pipeline: Initialimport, Delta, Voll-Diff. **Kontaktfrei.**

Kein Test dieser Datei startet einen Sidecar, fragt TCC ab, berührt
`CNContactStore` oder liest einen echten Kontakt. Die Gegenstelle ist eine
Attrappe; alle Kontaktdaten sind erfunden (`*.invalid`).

**Herkunft der Fixtureform:** Die *Struktur* der Antworten — genau ein
Container `local`, eine vollständige Enumeration mit `count=1`, ein
Basislauf der Änderungshistorie mit einem `add` und einem `dropEverything`,
ein zweiter Lauf mit null Ereignissen — stammt aus der Intel-x86_64-
Live-Abnahme. Übernommen wurde ausschliesslich die Form, **keine** Inhalte:
Namen, Adressen, Identifier und Token sind hier frei erfunden.
"""

from __future__ import annotations

import pytest

from personaljarvis.contacts.bridge.errors import BridgeOperationError
from personaljarvis.contacts.bridge.models import (
    AuthorizationStatus,
    BridgeCapabilities,
    BridgeContact,
    ChangeEvent,
    ChangeEventType,
    ChangesResult,
    ContainerInfo,
    EnumerationResult,
    Handshake,
)
from personaljarvis.contacts.bridge.protocol import ErrorCode
from personaljarvis.contacts.domain.enums import (
    FieldAvailabilityState,
    InitiationContext,
    MutationState,
    SyncMode,
)
from personaljarvis.contacts.domain.models import ContactMutation
from personaljarvis.contacts.sync import (
    ContactsSyncService,
    CursorState,
    EchoSuppressionLedger,
    SyncRunKind,
    build_display_name,
)

from .conftest import WORKSPACE, new_id

ACCOUNT = "acct-test"
CONTAINER = "local"

#: Die Feldzustände, die der produktive Sidecar für einen vollständig
#: lesbaren Datensatz liefert. `note` ist dauerhaft nicht lesbar, solange
#: `notesSupported=false` gilt.
VOLL_LESBAR = {
    "note": "unavailable_by_capability",
    "givenName": "present", "familyName": "present",
    "organizationName": "absent", "birthday": "absent",
    "emails": "present", "phones": "absent", "postalAddresses": "absent",
    "urlAddresses": "absent", "socialProfiles": "absent",
    "instantMessages": "absent", "relations": "absent", "thumbnail": "absent",
}


def roh_kontakt(pid: str, *, given="Erfunden", family="Eins",
                emails=("eins@example.invalid",), verfuegbarkeit=None,
                me_card=False, key_set_version=1) -> BridgeContact:
    return BridgeContact.parse({
        "providerIdentifier": pid,
        "keySetVersion": key_set_version,
        "contactType": "person",
        "isMeCard": me_card,
        "fieldAvailability": dict(verfuegbarkeit or VOLL_LESBAR),
        "fieldCompleteness": "full",
        "givenName": given, "familyName": family,
        "emails": [{"label": "_$!<Work>!$_", "value": e} for e in emails],
    })


class AttrappenBridge:
    """Gegenstelle ohne Prozess, ohne Store, ohne Apple.

    Zählt jeden Aufruf mit — damit lässt sich beweisen, *dass* eine Operation
    unterblieben ist, nicht nur, dass sie kein Ergebnis hatte.
    """

    def __init__(self, *, kontakte=(), status=AuthorizationStatus.AUTHORIZED,
                 container=(CONTAINER,), key_set_version=1,
                 change_history=True):
        self.kontakte = {k.provider_identifier: k for k in kontakte}
        self.status = status
        self.container_ids = tuple(container)
        self.key_set_version = key_set_version
        self._change_history = change_history
        self.enumeration_vollstaendig = True
        self.enumeration_count_override: int | None = None
        self.ereignisse: list[ChangeEvent] = []
        self.token = "tok-1"
        self.changes_fehler: BridgeOperationError | None = None
        self.changes_key_set_version: int | None = None
        self.aufrufe: list[str] = []

    # ── Lebenszeichen ───────────────────────────────────────────────────────
    @property
    def handshake(self) -> Handshake:
        return Handshake(
            protocol_version=1, bundle_identifier="de.kluender.jarvis.contacts-bridge",
            transaction_author="personal-jarvis", key_set_version=self.key_set_version,
            authorization_status=self.status, operations=(),
            capabilities=self.capabilities)

    @property
    def capabilities(self) -> BridgeCapabilities:
        return BridgeCapabilities(change_history_supported=self._change_history)

    def authorization_status(self) -> AuthorizationStatus:
        self.aufrufe.append("authorizationStatus")
        return self.status

    def request_authorization(self, **_):          # pragma: no cover
        raise AssertionError("Der Sync-Dienst darf nie autorisieren")

    # ── Lesende Operationen ─────────────────────────────────────────────────
    def containers(self) -> tuple[ContainerInfo, ...]:
        self.aufrufe.append("containers")
        return tuple(ContainerInfo(identifier=i, name=i, type="local")
                     for i in self.container_ids)

    def enumerate(self, *, container_identifier=None, timeout=300.0):
        self.aufrufe.append("enumerate")
        werte = tuple(self.kontakte.values())
        return EnumerationResult(
            contacts=werte,
            count=(self.enumeration_count_override
                   if self.enumeration_count_override is not None else len(werte)),
            complete=self.enumeration_vollstaendig,
            key_set_version=self.key_set_version)

    def changes(self, *, starting_token=None):
        self.aufrufe.append("changes")
        if self.changes_fehler is not None:
            raise self.changes_fehler
        return ChangesResult(
            events=tuple(self.ereignisse), current_token=self.token,
            key_set_version=(self.changes_key_set_version
                             if self.changes_key_set_version is not None
                             else self.key_set_version))

    def get(self, provider_identifier: str) -> BridgeContact:
        self.aufrufe.append("get")
        if provider_identifier not in self.kontakte:
            raise BridgeOperationError(ErrorCode.NOT_FOUND, "nicht gefunden")
        return self.kontakte[provider_identifier]


@pytest.fixture
def bridge():
    return AttrappenBridge(kontakte=(roh_kontakt("pid-1"),))


@pytest.fixture
def service(module, bridge):
    return ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                               provider_account_id=ACCOUNT)


def kontakte(module):
    with module.unit_of_work() as uow:
        return tuple(module.repositories(uow).contacts.list_by_workspace(WORKSPACE))


def zustand(module):
    with module.unit_of_work() as uow:
        return module.repositories(uow).sync_state.get(ACCOUNT, CONTAINER)


def tombstones(module):
    with module.unit_of_work() as uow:
        return tuple(module.repositories(uow).tombstones.list_all())


# ── Anzeigename (Kernaufgabe, nie Sidecaraufgabe) ────────────────────────────
def test_anzeigename_entsteht_im_kern():
    assert build_display_name(roh_kontakt("p", given="Ada", family="Erfunden")) \
        == "Ada Erfunden"


def test_anzeigename_faellt_auf_organisation_zurueck():
    roh = BridgeContact.parse({
        "providerIdentifier": "p", "keySetVersion": 1, "contactType": "organization",
        "isMeCard": False, "fieldCompleteness": "full",
        "fieldAvailability": {**VOLL_LESBAR, "givenName": "absent",
                              "familyName": "absent", "organizationName": "present"},
        "givenName": "", "familyName": "", "organizationName": "Erfundenes Werk",
    })
    assert build_display_name(roh) == "Erfundenes Werk"


def test_anzeigename_traegt_nie_den_provider_identifier():
    roh = BridgeContact.parse({
        "providerIdentifier": "GEHEIM-ID-42", "keySetVersion": 1,
        "contactType": "person", "isMeCard": False, "fieldCompleteness": "partial",
        "fieldAvailability": {k: "unavailable_by_capability" for k in VOLL_LESBAR},
    })
    name = build_display_name(roh)
    assert "GEHEIM-ID-42" not in name and name == "(ohne Namen)"


# ── Initialimport ────────────────────────────────────────────────────────────
def test_initialimport_uebernimmt_den_bestand(service, module, bridge):
    ergebnis = service.initial_import(CONTAINER)

    assert ergebnis.succeeded and ergebnis.kind is SyncRunKind.INITIAL_IMPORT
    assert (ergebnis.imported, ergebnis.updated, ergebnis.tombstoned) == (1, 0, 0)
    assert ergebnis.cursor_advanced and ergebnis.cursor_state is CursorState.ACTIVE

    (kontakt,) = kontakte(module)
    assert kontakt.display_name == "Erfunden Eins"
    assert kontakt.emails[0].value_normalized == "eins@example.invalid"
    (extern,) = kontakt.external_ids
    assert extern.provider_identifier == "pid-1"
    assert extern.container_identifier == CONTAINER


def test_initialimport_nimmt_den_cursor_vor_der_enumeration(service, bridge):
    service.initial_import(CONTAINER)
    # Verlorene Änderungen sind nicht reparierbar, doppelt angewandte schon.
    assert bridge.aufrufe.index("changes") < bridge.aufrufe.index("enumerate")


def test_initialimport_persistiert_cursor_und_modus(service, module, bridge):
    service.initial_import(CONTAINER)
    z = zustand(module)
    assert z.cursor_token == bridge.token
    assert z.mode == SyncMode.DELTA.value
    assert z.last_full_diff_at is not None


def test_nicht_lesbares_feld_wird_nie_zu_leer(service, module):
    service.initial_import(CONTAINER)
    (kontakt,) = kontakte(module)
    assert kontakt.availability_of("note") is \
        FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY
    assert not kontakt.is_field_known_empty("note")


def test_unvollstaendige_enumeration_verwirft_den_lauf(service, module, bridge):
    bridge.enumeration_vollstaendig = False
    ergebnis = service.initial_import(CONTAINER)

    assert not ergebnis.succeeded
    assert ergebnis.error_class == "IncompleteEnumeration"
    # Kein Teilbestand, kein Tombstone, kein Cursor.
    assert kontakte(module) == () and tombstones(module) == ()
    assert zustand(module) is None


def test_abweichende_zaehlung_verwirft_den_lauf(service, module, bridge):
    bridge.enumeration_count_override = 99
    ergebnis = service.initial_import(CONTAINER)
    assert not ergebnis.succeeded and kontakte(module) == ()


def test_ohne_autorisierung_wird_nichts_gelesen(module, bridge):
    bridge.status = AuthorizationStatus.NOT_DETERMINED
    dienst = ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    ergebnis = dienst.initial_import(CONTAINER)

    assert not ergebnis.succeeded and ergebnis.error_class == "AuthorizationRequired"
    # Belegt, dass keine Store-Operation stattfand — nicht nur, dass sie leer war.
    assert bridge.aufrufe == ["authorizationStatus"]


# ── Delta ────────────────────────────────────────────────────────────────────
def test_delta_uebernimmt_hinzugefuegten_datensatz(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.kontakte["pid-2"] = roh_kontakt("pid-2", given="Zwei",
                                           emails=("zwei@example.invalid",))
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.ADD,
                                     provider_identifier="pid-2",
                                     container_identifier=CONTAINER)]
    bridge.token = "tok-2"

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.succeeded and ergebnis.imported == 1
    assert ergebnis.events_processed == 1 and ergebnis.cursor_advanced
    assert {k.display_name for k in kontakte(module)} == {"Erfunden Eins", "Zwei Eins"}
    assert zustand(module).cursor_token == "tok-2"


def test_delta_aktualisiert_geaenderten_datensatz(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.kontakte["pid-1"] = roh_kontakt("pid-1", given="Erfunden",
                                           family="Geaendert")
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-1")]

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.updated == 1 and ergebnis.imported == 0
    (kontakt,) = kontakte(module)
    assert kontakt.family_name == "Geaendert"
    assert kontakt.local_revision == 2


def test_delta_ohne_inhaltsaenderung_zaehlt_unveraendert(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-1")]

    ergebnis = service.delta_sync(CONTAINER)

    assert (ergebnis.updated, ergebnis.unchanged) == (0, 1)
    assert kontakte(module)[0].local_revision == 1


def test_delta_setzt_tombstone_bei_loeschereignis(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.kontakte.pop("pid-1")
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.DELETE,
                                     provider_identifier="pid-1")]

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.tombstoned == 1
    assert kontakte(module) == ()
    (grab,) = tombstones(module)
    assert grab.reason == "provider_delete_event"


def test_verschwundener_datensatz_wird_nicht_geraten(service, module, bridge):
    """Ein `update` auf einen zwischenzeitlich gelöschten Datensatz."""
    service.initial_import(CONTAINER)
    bridge.kontakte.pop("pid-1")
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-1")]

    ergebnis = service.delta_sync(CONTAINER)

    # Kein Tombstone aus einer Vermutung — das Löschereignis folgt noch.
    assert ergebnis.succeeded and ergebnis.tombstoned == 0
    assert tombstones(module) == ()


# ── Untragfähiger Delta-Pfad ─────────────────────────────────────────────────
def test_drop_everything_verlangt_voll_diff_ohne_ihn_zu_tun(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.DROP_EVERYTHING)]
    vorher = list(bridge.aufrufe)

    ergebnis = service.delta_sync(CONTAINER)

    assert not ergebnis.succeeded and ergebnis.requires_full_diff
    assert ergebnis.error_class == "FullDiffRequired"
    assert zustand(module).mode == SyncMode.FULL_DIFF_REQUIRED.value
    assert zustand(module).cursor_token is None
    # Ausdrücklich **keine** verdeckte Eskalation im selben Aufruf.
    assert "enumerate" not in bridge.aufrufe[len(vorher):]


def test_abgelehnter_cursor_fuehrt_in_den_voll_diff(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.changes_fehler = BridgeOperationError(ErrorCode.INVALID_TOKEN, "abgelehnt")

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.error_class == "CursorRejected"
    assert zustand(module).mode == SyncMode.FULL_DIFF_REQUIRED.value


def test_schluesselsatzwechsel_entwertet_den_cursor(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.changes_key_set_version = 2

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.error_class == "KeySetVersionChanged"
    assert zustand(module).mode == SyncMode.FULL_DIFF_REQUIRED.value


def test_unbekanntes_ereignis_bricht_fail_closed_ab(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.OTHER)]

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.error_class == "UnknownChangeEvent"
    assert not ergebnis.cursor_advanced


def test_nicht_zuordenbares_ereignis_bei_mehreren_containern(module, bridge):
    bridge.container_ids = (CONTAINER, "icloud")
    dienst = ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    dienst.initial_import(CONTAINER)
    bridge.kontakte["pid-9"] = roh_kontakt("pid-9", given="Fremd")
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.ADD,
                                     provider_identifier="pid-9",
                                     container_identifier="icloud")]

    ergebnis = dienst.delta_sync(CONTAINER)

    # Fremder Container: übersprungen, nicht importiert.
    assert ergebnis.succeeded and ergebnis.imported == 0
    assert len(kontakte(module)) == 1


def test_sync_waehlt_nach_dem_persistierten_zustand(service, module, bridge):
    erst = service.sync(CONTAINER)
    assert erst.kind is SyncRunKind.INITIAL_IMPORT

    zweit = service.sync(CONTAINER)
    assert zweit.kind is SyncRunKind.DELTA

    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.DROP_EVERYTHING)]
    service.sync(CONTAINER)
    bridge.ereignisse = []
    dritt = service.sync(CONTAINER)
    assert dritt.kind is SyncRunKind.FULL_DIFF and dritt.succeeded


# ── Voll-Diff ────────────────────────────────────────────────────────────────
def test_voll_diff_setzt_tombstone_fuer_fehlenden_datensatz(service, module, bridge):
    bridge.kontakte["pid-2"] = roh_kontakt("pid-2", given="Zwei")
    service.initial_import(CONTAINER)
    assert len(kontakte(module)) == 2

    bridge.kontakte.pop("pid-2")
    ergebnis = service.full_diff(CONTAINER)

    assert ergebnis.tombstoned == 1 and ergebnis.unchanged == 1
    (grab,) = tombstones(module)
    assert grab.reason == "absent_in_complete_enumeration"
    assert grab.provider_identifier == "pid-2"
    assert {k.display_name for k in kontakte(module)} == {"Erfunden Eins"}


def test_voll_diff_ohne_vollstaendigkeit_erzeugt_keine_loeschung(service, module,
                                                                 bridge):
    service.initial_import(CONTAINER)
    bridge.kontakte.clear()
    bridge.enumeration_vollstaendig = False

    ergebnis = service.full_diff(CONTAINER)

    assert not ergebnis.succeeded
    assert tombstones(module) == () and len(kontakte(module)) == 1


def test_wiederauftauchen_nach_tombstone_wird_neu_importiert(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.kontakte.clear()
    service.full_diff(CONTAINER)
    assert kontakte(module) == ()

    bridge.kontakte["pid-1"] = roh_kontakt("pid-1")
    ergebnis = service.full_diff(CONTAINER)

    assert ergebnis.imported == 1
    (kontakt,) = kontakte(module)
    assert kontakt.external_ids[0].provider_identifier == "pid-1"
    # Der Grabstein bleibt als Beleg der früheren Löschung bestehen.
    assert len(tombstones(module)) == 1


# ── Datenerhalt bei Fähigkeitslücken ─────────────────────────────────────────
def test_fehlende_lesbarkeit_loescht_keine_vorhandenen_daten(service, module, bridge):
    service.initial_import(CONTAINER)
    assert kontakte(module)[0].emails

    # Der Provider kann E-Mails plötzlich nicht mehr liefern.
    eingeschraenkt = dict(VOLL_LESBAR, emails="unavailable_by_capability")
    bridge.kontakte["pid-1"] = roh_kontakt("pid-1", emails=(),
                                           verfuegbarkeit=eingeschraenkt)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-1")]

    service.delta_sync(CONTAINER)

    (kontakt,) = kontakte(module)
    assert kontakt.emails and kontakt.emails[0].value_raw == "eins@example.invalid"
    assert kontakt.availability_of("emails") is \
        FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY


def test_nachweislich_leeres_feld_wird_geleert(service, module, bridge):
    """Der Gegentest: `absent` heisst leer und darf leeren."""
    service.initial_import(CONTAINER)
    leer = dict(VOLL_LESBAR, emails="absent")
    bridge.kontakte["pid-1"] = roh_kontakt("pid-1", emails=(), verfuegbarkeit=leer)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-1")]

    service.delta_sync(CONTAINER)

    assert kontakte(module)[0].emails == ()


def test_me_karte_wird_nie_ueberschrieben(module, bridge):
    bridge.kontakte = {"pid-me": roh_kontakt("pid-me", given="Ich", me_card=True)}
    dienst = ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    dienst.initial_import(CONTAINER)

    bridge.kontakte["pid-me"] = roh_kontakt("pid-me", given="Fremdgeaendert",
                                            me_card=True)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-me")]
    ergebnis = dienst.delta_sync(CONTAINER)

    assert ergebnis.updated == 0 and ergebnis.unchanged == 1
    assert kontakte(module)[0].given_name == "Ich"


# ── Echo-Unterdrückung ───────────────────────────────────────────────────────
def test_echo_ledger_kennt_nur_laufende_vorgaenge():
    laufend = ContactMutation(
        mutation_id=new_id(), command="update", idempotency_key="k1",
        state=MutationState.OUTCOME_UNKNOWN,
        initiation_context=InitiationContext.USER_DIRECT,
        target_provider_identifier="pid-1")
    abgeschlossen = ContactMutation(
        mutation_id=new_id(), command="update", idempotency_key="k2",
        state=MutationState.SUCCEEDED,
        initiation_context=InitiationContext.USER_DIRECT,
        target_provider_identifier="pid-2")

    ledger = EchoSuppressionLedger.from_mutations((laufend, abgeschlossen))
    assert ledger.suppresses("pid-1") and not ledger.suppresses("pid-2")
    assert not ledger.suppresses(None)


def test_eigenes_schreiben_kommt_nicht_als_fremdaenderung_zurueck(service, module,
                                                                  bridge):
    service.initial_import(CONTAINER)
    with module.unit_of_work() as uow:
        module.repositories(uow).mutations.add(ContactMutation(
            mutation_id=new_id(), command="update", idempotency_key="k-echo",
            state=MutationState.OUTCOME_UNKNOWN,
            initiation_context=InitiationContext.USER_DIRECT,
            provider_account_id=ACCOUNT, target_provider_identifier="pid-1"))

    bridge.kontakte["pid-1"] = roh_kontakt("pid-1", family="Echo")
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.UPDATE,
                                     provider_identifier="pid-1")]
    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.updated == 0
    assert kontakte(module)[0].family_name == "Eins"
    assert "sync.echo.suppressed" in ergebnis.audit_events


# ── Vertraulichkeit des Laufergebnisses ──────────────────────────────────────
def test_laufergebnis_traegt_keine_personenbezogenen_daten(service, bridge):
    ergebnis = service.initial_import(CONTAINER)
    text = repr(ergebnis.as_dict()) + " ".join(ergebnis.audit_events)

    for verboten in ("pid-1", "Erfunden", "Eins", "eins@example.invalid",
                     bridge.token):
        assert verboten not in text, verboten


def test_fehlerdetail_bleibt_technisch(service, module, bridge):
    """Die Fehlermeldung des Providers wird **nicht** durchgereicht."""
    service.initial_import(CONTAINER)
    bridge.changes_fehler = BridgeOperationError(
        ErrorCode.PROVIDER_ERROR, "Datensatz pid-1 (Erfunden Eins) fehlerhaft")
    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.detail == "bridge:provider_error"
    assert "pid-1" not in ergebnis.detail and "Erfunden" not in ergebnis.detail


def test_abgelehnter_cursor_wird_typisiert_statt_durchgereicht(service, bridge):
    service.initial_import(CONTAINER)
    bridge.changes_fehler = BridgeOperationError(ErrorCode.INVALID_TOKEN,
                                                 "Token pid-1 ungueltig")
    ergebnis = service.delta_sync(CONTAINER)

    # Der Vertragscode wird in einen Sync-Zustand übersetzt, nicht weitergereicht.
    assert ergebnis.error_class == "CursorRejected"
    assert ergebnis.detail == "CursorRejected"


# ── Keine Nebenwirkung ohne ausdrücklichen Aufruf ────────────────────────────
def test_konstruktion_loest_nichts_aus(module, bridge):
    ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                        provider_account_id=ACCOUNT)
    assert bridge.aufrufe == []


def test_inventar_legt_keinen_sync_zustand_an(service, module, bridge):
    inventar = service.inventory_containers()
    assert [c.identifier for c in inventar] == [CONTAINER]
    assert zustand(module) is None


def test_ohne_gestartete_bridge_wird_nicht_gelesen(module):
    class Ungestartet(AttrappenBridge):
        @property
        def handshake(self):
            return None

    stumpf = Ungestartet()
    dienst = ContactsSyncService(stumpf, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    ergebnis = dienst.initial_import(CONTAINER)

    assert ergebnis.error_class == "SyncError" and stumpf.aufrufe == []


# ── Form der Live-Abnahme ────────────────────────────────────────────────────
def test_form_der_live_abnahme_laeuft_durch(module):
    """Reproduziert die *Struktur* des Intel-Live-Laufs mit erfundenen Daten.

    Ein Container, eine vollständige Enumeration mit genau einem Datensatz,
    ein Basislauf mit `add` + `dropEverything`, danach ein leerer zweiter Lauf.
    """
    bridge = AttrappenBridge(kontakte=(roh_kontakt("pid-live"),))
    bridge.ereignisse = [
        ChangeEvent(type=ChangeEventType.ADD, provider_identifier="pid-live",
                    container_identifier=CONTAINER),
        ChangeEvent(type=ChangeEventType.DROP_EVERYTHING),
    ]
    dienst = ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)

    # Der Initialimport verwirft die Basisereignisse und nimmt nur den Cursor.
    erst = dienst.initial_import(CONTAINER)
    assert erst.succeeded and erst.imported == 1 and erst.events_processed == 0

    # Der zweite Lauf zieht null Ereignisse.
    bridge.ereignisse = []
    zweit = dienst.delta_sync(CONTAINER)
    assert zweit.succeeded and zweit.events_processed == 0
    assert (zweit.imported, zweit.updated, zweit.tombstoned) == (0, 0, 0)


def test_lebenszyklus_stellt_den_dienst_bereit_ohne_lauf(module, bridge):
    dienst = module.sync_service(bridge, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    assert isinstance(dienst, ContactsSyncService)
    # Bereitstellen ist kein Laufen: kein Store-Zugriff, kein Zustand.
    assert bridge.aufrufe == [] and zustand(module) is None


def test_dienst_ohne_gestartetes_modul_wird_abgelehnt(db_path, bridge):
    from personaljarvis.contacts.lifecycle import ContactsModule
    from personaljarvis.errors import PersonalJarvisError

    with pytest.raises(PersonalJarvisError):
        ContactsModule(db_path).sync_service(bridge, workspace_id=WORKSPACE,
                                             provider_account_id=ACCOUNT)
