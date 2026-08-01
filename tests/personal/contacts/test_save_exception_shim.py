"""Die Objective-C-Exception-Grenze um den nativen Save-Aufruf. **Kontaktfrei.**

Kein `CNContactStore`, kein Schreibzugriff auf Apple Contacts: Die native
@try/@catch-Grenze selbst wird durch den bei jedem Build mitlaufenden
Harness (`jarvis-contacts-shim-tests`, reine Fake-Blöcke) belegt; hier wird
dieser Harness ausgeführt, die Quelltexte werden statisch geprüft, und der
Weg der Ausnahme durch Prozessprotokoll, Provider und Pipeline läuft
ausschliesslich über Fakes und temporäre Datenbanken.

Anlass: beide x86_64-Create-Livetests am 2026-08-01 starben an einer nicht
gefangenen Objective-C-Ausnahme in Apples Save-Pfad (`SIGABRT`); Klasse und
Begründung der Ausnahme gingen dabei verloren. Der Shim verwandelt diesen
stillen Tod in eine typisierte `outcome_unknown`-Antwort — er behebt den
Apple-Schreibpfad **nicht**, und genau das halten die Tests auch fest: nie
`not_sent`, nie ein zweiter Send, Prozessende nach der Antwort.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from personaljarvis.contacts.application.bridge_provider import (
    ContactsBridgeMutationProvider,
    _exception_diagnostics,
)
from personaljarvis.contacts.application.models import ProviderOutcome
from personaljarvis.contacts.bridge.errors import MutationOutcomeUnknown
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import (
    SidecarLocation,
    host_architecture,
)

_REPO = Path(__file__).resolve().parents[3]
_SRC = _REPO / "native" / "contacts-bridge" / "src"
_BUILD_DIRS = (
    _REPO / "native" / "contacts-bridge" / "build",
    _REPO / "native" / "contacts-bridge" / "build-x86_64",
    _REPO / "native" / "contacts-bridge" / "build-arm64",
)

#: Ein erfundener Reason mit allem, was nie durchsickern darf.
BOESER_REASON = ("Kontakt 'ZZZ-Geheimname' <zzz-geheim@example.invalid> "
                 "+49 30 999999 unter /Users/erfunden in "
                 "01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount")

#: SHA-256("abc") — bekannter Vektor.
ABC_DIGEST = ("ba7816bf8f01cfea414140de5dae2223"
              "b00361a396177a9cb410ff61f20015ad")


def _quelle(name: str) -> str:
    return (_SRC / name).read_text()


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z.split("//", 1)[0] for z in text.splitlines())


# ═══ Statik: der Shim selbst ════════════════════════════════════════════════
def test_der_shim_hat_genau_eine_try_catch_grenze():
    code = _ohne_kommentare(_quelle("JCContactsSaveShim.m"))
    assert code.count("@try") == 1
    assert code.count("@catch") == 1
    assert "NSException" in code


def test_der_shim_ruft_execute_genau_einmal():
    code = _ohne_kommentare(_quelle("JCContactsSaveShim.m"))
    assert code.count("executeSaveRequest:") == 1
    assert code.count("attempt(&error)") == 1
    # Keine Schleife um den Versuch: der @try-Block kennt keine Iteration.
    # (Die Hex-Schleife der Digestbildung liegt ausserhalb und zaehlt nicht.)
    versuch = code.split("@try")[1].split("@catch")[0]
    for schleife in ("for ", "for(", "while ", "while(", "goto "):
        assert schleife not in versuch, schleife


def test_der_shim_erzeugt_keinen_eigenen_save_request():
    """Er nimmt Store und Request entgegen — er baut nie einen zweiten."""
    code = _ohne_kommentare(_quelle("JCContactsSaveShim.m"))
    assert "alloc] init" not in code.replace("JCSaveOutcome alloc] init", "")
    assert "CNSaveRequest alloc" not in code
    assert "new]" not in code


def test_der_shim_liest_und_sucht_keine_kontakte():
    code = _ohne_kommentare(_quelle("JCContactsSaveShim.m"))
    for verboten in ("unifiedContact", "enumerateContacts", "CNContactFetch",
                     "predicateForContacts", "containersMatching",
                     "sqlite", "SELECT ", "INSERT "):
        assert verboten not in code, verboten


def test_der_shim_traegt_keine_fachlogik():
    """Wortgleiche Grenze wie beim ChangeHistory-Shim (ADR-0016 Punkt 4).

    Geprüft wird der Code ohne Kommentare: die Kommentare dürfen die Verbote
    ja gerade benennen.
    """
    code = (_ohne_kommentare(_quelle("JCContactsSaveShim.m"))
            + _ohne_kommentare(_quelle("JCContactsSaveShim.h")))
    for verboten in ("workspace", "Merge", "merge", "Risiko", "risk",
                     "approval", "Freigabe", "outbox", "Retry", "retry"):
        assert verboten not in code, verboten


def test_der_reason_verlaesst_den_shim_nur_als_digest_oder_artefakt():
    """`sanitizedDiagnostic` wird nie aus dem Reason-Text gebaut."""
    code = _ohne_kommentare(_quelle("JCContactsSaveShim.m"))
    diagnose = code.split("sanitizedDiagnostic = ")[1].split(";")[0]
    assert "reason" not in diagnose.replace("reasonPresent", "").replace(
        "reasonDigest", "")


# ═══ Statik: der Swift-Aufrufer ═════════════════════════════════════════════
def test_swift_kennt_keinen_direkten_execute_mehr():
    code = _ohne_kommentare(_quelle("sidecar.swift"))
    assert "store.execute(" not in code
    assert code.count("JCExecuteSaveRequestGuarded(") == 1


def test_die_exception_antwort_ist_outcome_unknown_mit_terminierung():
    code = _quelle("sidecar.swift")
    zweig = code.split("case .exception:")[1].split("@unknown default")[0]
    assert '"outcome_unknown"' in zweig
    assert '"objc_exception"' in zweig
    assert '"processMustTerminate": true' in zweig
    assert "exit(0)" in zweig
    # Nach der Ausnahme wird der Store nie wieder angefasst: kein Read-back.
    assert "fetchRaw" not in zweig
    # Reihenfolge: Antwort vor dem Ende, Flush vor dem Ende.
    assert zweig.index("ok(id") < zweig.index("exit(0)")
    assert zweig.index("fflush") < zweig.index("exit(0)")


def test_der_bridging_header_importiert_beide_shims():
    kopf = _quelle("JCBridgingHeader.h")
    assert '#import "JCChangeHistoryShim.h"' in kopf
    assert '#import "JCContactsSaveShim.h"' in kopf


def test_build_sh_baut_und_startet_den_harness():
    skript = (_REPO / "native" / "contacts-bridge" / "build.sh").read_text()
    assert "JCContactsSaveShim.m" in skript
    assert "JCContactsSaveShimTests.m" in skript
    assert "shim-tests" in skript


# ═══ Der native Harness (gebautes Artefakt; ohne Build: Skip) ═══════════════
def _harness() -> Path | None:
    for verzeichnis in _BUILD_DIRS:
        kandidat = verzeichnis / "jarvis-contacts-shim-tests"
        if kandidat.exists():
            return kandidat
    return None


def test_der_native_harness_besteht():
    """Führt die echten @try/@catch-Prüfungen aus — reine Fake-Blöcke."""
    binary = _harness()
    if binary is None:
        pytest.skip("Shim-Harness nicht gebaut (native/contacts-bridge/build.sh)")
    lauf = subprocess.run([str(binary)], capture_output=True, text=True,
                          timeout=60)
    assert lauf.returncode == 0, lauf.stderr
    assert "alle Pruefungen bestanden" in lauf.stdout


def test_das_gepackte_binary_traegt_die_grenze():
    """Symbole und Vertragsstrings im tatsächlich gebauten Sidecar."""
    from personaljarvis.contacts.bridge.resolver import (
        BINARY_NAME,
        binary_architectures,
        tauri_triple,
    )

    kandidaten = [
        _REPO / "frontend" / "src-tauri" / "binaries"
        / f"{BINARY_NAME}-{tauri_triple(host_architecture())}",
        *(v / BINARY_NAME for v in _BUILD_DIRS),
    ]
    binary = next((k for k in kandidaten if k.exists()
                   and host_architecture() in binary_architectures(k)), None)
    if binary is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    symbole = subprocess.run(["/usr/bin/nm", "-gU", str(binary)],
                             capture_output=True, text=True).stdout
    assert "JCExecuteSaveRequestGuarded" in symbole
    daten = binary.read_bytes()
    assert b"objc_exception" in daten
    assert b"processMustTerminate" in daten
    assert b"OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH" in daten


# ═══ Provider: Auswertung der Exception-Antwort ═════════════════════════════
def _antwort(**extra) -> dict:
    return {"outcome": "outcome_unknown", "errorCode": "objc_exception",
            "mutationContractVersion": 1, "fieldContractVersion": 1,
            "exceptionName": "NSInternalInconsistencyException",
            "reasonPresent": True, "reasonDigest": ABC_DIGEST,
            "processMustTerminate": True, **extra}


def test_die_exception_antwort_wird_outcome_unknown():
    auswerten = ContactsBridgeMutationProvider._auswerten
    ergebnis = auswerten(_antwort())
    assert ergebnis.outcome == ProviderOutcome.OUTCOME_UNKNOWN
    assert ergebnis.error_code == "objc_exception"
    assert ergebnis.exception_diagnostics == {
        "exception_name": "NSInternalInconsistencyException",
        "reason_present": True,
        "reason_digest": ABC_DIGEST,
    }


def test_niemals_not_sent_aus_einer_exception():
    ergebnis = ContactsBridgeMutationProvider._auswerten(_antwort())
    assert ergebnis.outcome not in (ProviderOutcome.FAILED_BEFORE_SEND,
                                    ProviderOutcome.REJECTED_BEFORE_SEND,
                                    ProviderOutcome.SUCCEEDED)


def test_ein_boeser_ausnahmename_wird_auf_bezeichner_reduziert():
    ergebnis = ContactsBridgeMutationProvider._auswerten(
        _antwort(exceptionName="Evil/Name @x <zzz@example.invalid> "
                               "/Users/erfunden"))
    name = ergebnis.exception_diagnostics["exception_name"]
    assert name == "EvilNamexzzzexampleinvalidUserserfunden"[:64]
    for verboten in ("/", "@", " ", "<", ">"):
        assert verboten not in name


@pytest.mark.parametrize("digest", ["", "zzzz", ABC_DIGEST[:-2],
                                    ABC_DIGEST + "aa", 42, None,
                                    ABC_DIGEST.upper()])
def test_ein_ungueltiger_digest_wird_verworfen(digest):
    ergebnis = ContactsBridgeMutationProvider._auswerten(
        _antwort(reasonDigest=digest))
    assert "reason_digest" not in ergebnis.exception_diagnostics


def test_ein_eingeschmuggelter_reason_wird_nicht_mitgelesen():
    """Selbst eine vertragswidrige Antwort mit Reason-Text bleibt draussen."""
    ergebnis = ContactsBridgeMutationProvider._auswerten(
        _antwort(reason=BOESER_REASON, exceptionReason=BOESER_REASON))
    text = json.dumps(ergebnis.exception_diagnostics)
    assert "ZZZ-Geheimname" not in text
    assert "@" not in text.replace('"@"', "")
    assert "/Users/" not in text


def test_ohne_objc_exception_gibt_es_keine_diagnose():
    assert _exception_diagnostics({"errorCode": "save_failed"}) is None
    assert _exception_diagnostics({}) is None


def test_save_failed_bleibt_outcome_unknown_ohne_diagnose():
    ergebnis = ContactsBridgeMutationProvider._auswerten(
        {"outcome": "outcome_unknown", "errorCode": "save_failed"})
    assert ergebnis.outcome == ProviderOutcome.OUTCOME_UNKNOWN
    assert ergebnis.exception_diagnostics is None


# ═══ Prozessprotokoll: Antwort vor Exit hat Vorrang ═════════════════════════
_HANDSHAKE = json.dumps({
    "type": "ready", "protocolVersion": 1,
    "bundleIdentifier": "de.kluender.jarvis.contacts-bridge",
    "transactionAuthor": "de.kluender.jarvis.contacts-bridge",
    "keySetVersion": 1, "authorizationStatus": "authorized",
    "operations": ["create"], "capabilities": {},
})


def _fake_sidecar(tmp_path: Path, koerper: str) -> SidecarProcess:
    """Ein Shell-Fake: Handshake, eine Anfrage lesen, `koerper` ausführen."""
    pfad = tmp_path / "fake-sidecar"
    pfad.write_text("#!/bin/sh\n"
                    f"echo '{_HANDSHAKE}'\n"
                    "read -r anfrage\n"
                    f"{koerper}\n")
    pfad.chmod(0o755)
    arch = host_architecture()
    return SidecarProcess(SidecarLocation(
        path=pfad, architectures=(arch,), host_architecture=arch))


def _exception_zeile(rid: int = 1) -> str:
    antwort = {"protocolVersion": 1, "requestId": rid, "ok": True,
               "result": _antwort()}
    return json.dumps(antwort)


def test_die_antwort_ueberlebt_den_kontrollierten_exit(tmp_path):
    """Antwort schreiben, sofort enden — die Antwort gewinnt, kein Fehler."""
    prozess = _fake_sidecar(
        tmp_path, f"echo '{_exception_zeile()}'\nexit 0")
    prozess.start(timeout=10.0)
    hülle = prozess.request("create", {}, timeout=10.0)
    prozess.stop()
    assert hülle["ok"] is True
    assert hülle["result"]["outcome"] == "outcome_unknown"
    assert hülle["result"]["errorCode"] == "objc_exception"


def test_ein_exit_ohne_antwort_bleibt_prozessfehler(tmp_path):
    """Die Grosszügigkeit gilt nur der Antwort — nie dem blossen Exit."""
    prozess = _fake_sidecar(tmp_path, "exit 0")
    prozess.start(timeout=10.0)
    with pytest.raises(MutationOutcomeUnknown) as exc:
        prozess.request("create", {}, timeout=10.0)
    prozess.stop()
    assert exc.value.underlying_class == "child_exited"


def test_ein_signaltod_ohne_antwort_bleibt_child_signalled(tmp_path):
    prozess = _fake_sidecar(tmp_path, "kill -ABRT $$")
    prozess.start(timeout=10.0)
    with pytest.raises(MutationOutcomeUnknown) as exc:
        prozess.request("create", {}, timeout=10.0)
    prozess.stop()
    assert exc.value.underlying_class == "child_signalled"


# ═══ Pipeline: Ausnahme bleibt terminal ungewiss, genau ein Send ════════════
def _pipeline_client(module):
    """Die Create-Pipeline mit einem Provider, der wie ein Sidecar antwortet,
    dessen Save in der @try/@catch-Grenze endete: `outcome_unknown`,
    `objc_exception`, PII-armer Befund — nie ein Reason-Text."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from personaljarvis.contacts.api.routes import create_contacts_router
    from personaljarvis.contacts.application.mutation_service import (
        ContactsMutationService,
        ProviderResponse,
    )
    from personaljarvis.contacts.domain.models import ContactSyncState
    from personaljarvis.contacts.repositories.sqlite import (
        SqliteSyncStateRepository,
    )

    from .test_create_vertical import CONTAINER, CREATE_CAPS, KONTO, ZaehlProvider

    class ExceptionProvider(ZaehlProvider):
        def apply(self, payload, *, mutation_id, idempotency_key, approval_id):
            self.calls += 1
            return ProviderResponse(
                ProviderOutcome.OUTCOME_UNKNOWN, error_code="objc_exception",
                exception_diagnostics={
                    "exception_name": "NSInternalInconsistencyException",
                    "reason_present": True, "reason_digest": ABC_DIGEST})

    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))
    provider = ExceptionProvider()
    module._capabilities = CREATE_CAPS
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=CREATE_CAPS)
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    return TestClient(app), provider


def _bis_ausgefuehrt(client) -> str:
    from .test_create_vertical import PREFIX, _create_body, _kopf

    r = client.post(PREFIX, headers=_kopf(), json=_create_body())
    assert r.status_code == 201, r.text
    mid = r.json()["mutation_id"]
    r = client.post(f"{PREFIX}/mutations/{mid}/approve", headers=_kopf(),
                    json={"decision_actor": "lukas"})
    assert r.status_code == 200, r.text
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json={"user_initiated": True})
    assert r.status_code == 200, r.text
    return mid


def test_die_pipeline_endet_in_outcome_unknown_mit_einem_send(module):
    from .test_create_vertical import PREFIX, _kopf

    client, provider = _pipeline_client(module)
    mid = _bis_ausgefuehrt(client)

    detail = client.get(f"{PREFIX}/mutations/{mid}", headers=_kopf()).json()
    assert detail["state"] == "outcome_unknown"
    assert detail["last_error_code"] == "objc_exception"
    assert detail["attempt_count"] == 1
    assert provider.calls == 1

    # Ein zweiter Ausfuehrungsversuch wird abgewiesen und sendet nicht.
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json={"user_initiated": True})
    assert r.status_code == 409
    assert provider.calls == 1

    with module.unit_of_work() as uow:
        outbox = uow.execute(
            "SELECT state, attempt_count FROM personal_external_action_outbox"
        ).fetchone()
        assert outbox["state"] == "outcome_unknown"
        assert outbox["attempt_count"] == 1
        stufen = [r["stage"] for r in uow.execute(
            "SELECT stage FROM personal_audit_log ORDER BY sequence").fetchall()]
    assert stufen[-1] == "outcome_unknown"
    assert "provider_send_started" in stufen


def test_die_auditkette_bleibt_frei_von_reason_texten(module):
    client, _ = _pipeline_client(module)
    mid = _bis_ausgefuehrt(client)
    with module.unit_of_work() as uow:
        text = " ".join(str(dict(r)) for r in uow.execute(
            "SELECT * FROM personal_audit_log").fetchall())
        kette_ok = True
        vorher = None
        for zeile in uow.execute(
                "SELECT payload_hash, prev_hash FROM personal_audit_log "
                "ORDER BY sequence").fetchall():
            kette_ok &= zeile["prev_hash"] == vorher
            vorher = zeile["payload_hash"]
    assert kette_ok
    for verboten in ("ZZZ-Geheimname", "example.invalid", "/Users/",
                     BOESER_REASON[:20]):
        assert verboten not in text, verboten
    assert mid in text
