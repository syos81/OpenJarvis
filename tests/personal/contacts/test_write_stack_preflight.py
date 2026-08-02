"""Der Schreibstack-Preflight vor dem Create-Send. **Kontaktfrei.**

Kein `CNContactStore`, kein Store-Zugriff: die Swift-Seite wird statisch
geprüft (der native Fetch selbst ist ohne echten Store nicht ausführbar und
genau deshalb als EIN Fetch durch die bestehende @try/@catch-Grenze gebaut);
Kern und Pipeline laufen ausschliesslich über Fakes und temporäre Datenbanken.

Anlass: alle vier x86_64-Create-Livetests starben an
`NSInternalInconsistencyException` — Save auf einem Coordinator **ohne
angehängte Stores**. Der Kontakt-LESEpfad initialisiert den Stack, der
Save-Pfad setzt ihn nur voraus. Der Preflight ist deshalb dreierlei:
Initialisierungsversuch, sicherer Vor-Send-Abbruchpunkt (`not_sent` /
`write_stack_unavailable`) und Hypothesentest. Ein Erfolg garantiert den
Save ausdrücklich **nicht** — dann greift weiter die Uncaught-Diagnose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personaljarvis.contacts.api.routes import PREFIX, create_contacts_router
from personaljarvis.contacts.application.bridge_provider import (
    ContactsBridgeMutationProvider,
)
from personaljarvis.contacts.application.models import ProviderOutcome
from personaljarvis.contacts.application.mutation_service import (
    ContactsMutationService,
    ProviderResponse,
)
from personaljarvis.contacts.domain.enums import MutationState
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import (
    SqliteSyncStateRepository,
)

from .test_create_vertical import (
    CONTAINER,
    CREATE_CAPS,
    KONTO,
    _create_body,
    _kopf,
)

_REPO = Path(__file__).resolve().parents[3]
_SIDECAR = _REPO / "native" / "contacts-bridge" / "src" / "sidecar.swift"


def _quelle() -> str:
    return _SIDECAR.read_text()


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("//", 1)[0] for z in text.splitlines())


# ═══ H · Statik: Position und Form des Preflights ═══════════════════════════
def test_der_preflight_laeuft_vor_der_save_request_erzeugung():
    code = _ohne_kommentare(_quelle())
    op = code.split("func opCreate(")[1]
    aufruf = op.index("performCreateWriteStackPreflight()")
    save = op.index("CNSaveRequest()")
    shim = op.index("JCExecuteSaveRequestGuarded(")
    assert aufruf < save < shim


def test_der_preflight_laeuft_genau_einmal_je_ausfuehrung():
    code = _ohne_kommentare(_quelle())
    op = code.split("func opCreate(")[1]
    assert op.count("performCreateWriteStackPreflight()") == 1
    # Keine Schleife um Preflight oder Save.
    # Zwischen Preflight und Save liegt keine Schleife (die Pflichtfeld-
    # Pruefung davor iteriert legitim ueber Feldnamen).
    zwischen = op[op.index("performCreateWriteStackPreflight()"):
                  op.index("JCExecuteSaveRequestGuarded(")]
    for schleife in ("for ", "while ", "repeat "):
        assert schleife not in zwischen, schleife


def test_der_preflight_ist_ein_echter_kontakt_fetch():
    code = _ohne_kommentare(_quelle())
    fn = code.split("func performCreateWriteStackPreflight(")[1].split(
        "\nfunc opCreate(")[0]
    assert "enumerateContacts(with:" in fn.replace(" ", "").replace(
        "with:", "with:") or "enumerateContacts(with" in fn
    assert "unifyResults = false" in fn
    assert "mutableObjects = false" in fn
    assert "CNContactIdentifierKey" in fn
    # Kein Container-Ersatz, kein zweiter Fetch, keine Schleife.
    assert "containers(" not in fn
    assert fn.count("enumerateContacts") == 1
    for schleife in ("for ", "while ", "repeat "):
        assert schleife not in fn, schleife


def test_der_preflight_nutzt_dieselbe_store_instanz_und_die_shim_grenze():
    code = _ohne_kommentare(_quelle())
    assert code.count("CNContactStore()") == 1          # genau EINE Instanz
    fn = code.split("func performCreateWriteStackPreflight(")[1].split(
        "\nfunc opCreate(")[0]
    assert "store.enumerateContacts" in fn              # dieselbe globale
    assert "JCExecuteSaveGuardedWithAttempt" in fn      # dieselbe ObjC-Grenze
    assert "CNContactStore()" not in fn                 # keine zweite Instanz


def test_die_preflight_kennung_ist_kunstprodukt_und_wird_nie_protokolliert():
    code = _ohne_kommentare(_quelle())
    assert 'let kPreflightIdentifierPrefix = "JC-PREFLIGHT-"' in code
    fn = code.split("func performCreateWriteStackPreflight(")[1].split(
        "\nfunc opCreate(")[0]
    assert "UUID().uuidString" in fn
    # `probe` fliesst in das Prädikat — und sonst nirgendwohin.
    assert fn.count("probe") == 2                       # Definition + Prädikat
    assert "diag(" not in fn.split("let wache")[0]
    for zeile in fn.splitlines():
        if "probe" in zeile:
            assert "diag(" not in zeile and "ok(" not in zeile
            assert "emit(" not in zeile


def test_save_und_execute_bleiben_genau_einmal():
    code = _ohne_kommentare(_quelle())
    assert code.count("CNSaveRequest()") == 1
    assert code.count("JCExecuteSaveRequestGuarded(") == 1
    assert code.count("JCInstallUncaughtExceptionDiagnostics()") == 1


def test_der_exception_zweig_beendet_den_prozess_ohne_save():
    code = _ohne_kommentare(_quelle())
    op = code.split("func opCreate(")[1]
    zweig = op.split("case .exception(let name):")[1].split("}")[0]
    assert '"write_stack_unavailable"' in zweig
    assert '"not_sent"' in zweig
    assert "exit(0)" in zweig
    assert "fflush(stdout)" in zweig
    # Kein Save, kein Read-back, keine Weiterverwendung in diesem Zweig.
    for verboten in ("CNSaveRequest", "JCExecuteSaveRequestGuarded",
                     "fetchRaw"):
        assert verboten not in zweig, verboten
    # Und der Wurfzweig liegt VOR der SaveRequest-Erzeugung.
    assert op.index("case .exception(let name):") < op.index("CNSaveRequest()")


def test_die_fehlerdomain_wird_bereinigt():
    code = _ohne_kommentare(_quelle())
    fn = code.split("func performCreateWriteStackPreflight(")[1].split(
        "\nfunc opCreate(")[0]
    assert "sanitizedErrorDomain(" in fn
    hilfe = code.split("func sanitizedErrorDomain(")[1].split("\nfunc ")[0]
    assert "alphanumerics" in hilfe and "prefix(64)" in hilfe


# ═══ Kern: write_stack_unavailable fliesst als failed_before_send ═══════════
def test_not_sent_mit_neuem_code_wird_failed_before_send():
    antwort = ContactsBridgeMutationProvider._auswerten(
        {"outcome": "not_sent", "errorCode": "write_stack_unavailable"})
    assert antwort.outcome is ProviderOutcome.FAILED_BEFORE_SEND
    assert antwort.error_code == "write_stack_unavailable"


# ═══ Pipeline mit Fakes ═════════════════════════════════════════════════════
class PreflightAbbruchProvider:
    """Provider-Fake: der Sidecar meldete `not_sent`/`write_stack_unavailable`."""

    def __init__(self) -> None:
        self.calls = 0

    def apply(self, payload, *, mutation_id, idempotency_key, approval_id):
        self.calls += 1
        return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                error_code="write_stack_unavailable")


@pytest.fixture
def client_mit_preflight_abbruch(module):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))
    provider = PreflightAbbruchProvider()
    module._capabilities = CREATE_CAPS
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=CREATE_CAPS)
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    return TestClient(app), provider


def _bis_approved(client) -> str:
    r = client.post(PREFIX, headers=_kopf(), json=_create_body())
    mid = r.json()["mutation_id"]
    r = client.post(f"{PREFIX}/mutations/{mid}/approve", headers=_kopf(),
                    json={"decision_actor": "lukas"})
    assert r.status_code == 200, r.text
    return mid


def test_preflight_abbruch_wird_failed_before_send(
        client_mit_preflight_abbruch, module):
    client, provider = client_mit_preflight_abbruch
    mid = _bis_approved(client)
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json={"user_initiated": True})
    assert r.status_code == 200
    m = r.json()
    assert m["state"] == "failed_before_send"
    assert m["error_code"] == "write_stack_unavailable"
    assert m["attempt_count"] == 1
    assert provider.calls == 1

    detail = client.get(f"{PREFIX}/mutations/{mid}", headers=_kopf()).json()
    assert detail["approval_state"] == "consumed"
    assert detail["target_contact_id"] is None

    with module.unit_of_work() as uow:
        outbox = uow.execute(
            "SELECT state, attempt_count FROM personal_external_action_outbox "
            "ORDER BY created_at DESC LIMIT 1").fetchone()
        assert outbox["state"] == "abandoned"
        assert outbox["attempt_count"] == 1
        aktive = uow.execute(
            "SELECT COUNT(*) AS n FROM contacts WHERE deleted_at IS NULL"
        ).fetchone()["n"]
    assert aktive == 0                     # kein lokaler Spiegel entstanden


def test_zweiter_execute_bleibt_blockiert(client_mit_preflight_abbruch):
    client, provider = client_mit_preflight_abbruch
    mid = _bis_approved(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    zweiter = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    assert zweiter.status_code == 409
    assert provider.calls == 1             # at-most-once: kein zweiter Send


def test_kein_outcome_unknown_und_kein_retry(client_mit_preflight_abbruch,
                                             module):
    client, provider = client_mit_preflight_abbruch
    mid = _bis_approved(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    with module.unit_of_work() as uow:
        zustand = uow.execute(
            "SELECT state FROM contacts_mutations WHERE mutation_id = ?",
            (mid,)).fetchone()["state"]
    assert zustand == MutationState.FAILED_BEFORE_SEND.value
    # `recover_interrupted` darf den terminalen Eintrag nicht wiederbeleben.
    module._mutation_service.recover_interrupted()
    assert provider.calls == 1


def test_das_abschlussereignis_traegt_die_pre_send_fakten(
        client_mit_preflight_abbruch, module):
    client, _ = client_mit_preflight_abbruch
    mid = _bis_approved(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    from personaljarvis.base.digest import digest_of

    with module.unit_of_work() as uow:
        zeilen = uow.execute(
            "SELECT * FROM personal_audit_log WHERE subject_id = ? "
            "ORDER BY sequence", (mid,)).fetchall()
    stufen = [z["stage"] for z in zeilen]
    assert stufen[-1] == "failed_before_send"
    letzte = zeilen[-1]
    erwartet = digest_of({
        "sequence": letzte["sequence"], "stage": "failed_before_send",
        "module": "contacts", "subjectType": "contacts.mutation",
        "subjectId": mid,
        "facts": {"errorCode": "write_stack_unavailable", "sent": False,
                  "providerContacted": False, "resend": False},
        "prevHash": letzte["prev_hash"],
    })
    assert erwartet == letzte["payload_hash"]


# ═══ G · Datenschutz ════════════════════════════════════════════════════════
def test_die_preflight_kennung_erscheint_in_keiner_normalen_ausgabe(
        client_mit_preflight_abbruch, module):
    client, _ = client_mit_preflight_abbruch
    mid = _bis_approved(client)
    antwort = client.post(f"{PREFIX}/mutations/{mid}/execute",
                          headers=_kopf()).text
    detail = client.get(f"{PREFIX}/mutations/{mid}", headers=_kopf()).text
    assert "JC-PREFLIGHT-" not in antwort + detail
    with module.unit_of_work() as uow:
        for tabelle in ("contacts_mutations", "personal_audit_log",
                        "personal_external_action_outbox"):
            for zeile in uow.execute(f"SELECT * FROM {tabelle}").fetchall():
                for wert in tuple(zeile):
                    assert "JC-PREFLIGHT-" not in str(wert)


def test_swift_emittiert_die_kennung_nirgends():
    """Auch stdout/stderr des Sidecars sehen die Kennung nie: sie existiert
    nur als lokale Konstante im Prädikat."""
    code = _ohne_kommentare(_quelle())
    for zeile in code.splitlines():
        if "kPreflightIdentifierPrefix" not in zeile:
            continue
        assert not re.search(r"\b(diag|emit|ok|fail)\s*\(", zeile), zeile
