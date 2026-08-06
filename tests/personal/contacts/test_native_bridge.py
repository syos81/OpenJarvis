"""Der produktive Sidecar — kontaktfreie Prüfungen (Gate B).

Ausgeführt werden **ausschliesslich** `ready`, `ping`, `caps`, eine typisierte
ungültige Anfrage und `shutdown`. Es gibt keine Contacts-Operation, keinen
TCC-Dialog und kein `requestAuthorization`.

Der arm64-Cross-Build wird **nur statisch** geprüft und nie gestartet.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.models import AuthorizationStatus
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import (
    BINARY_NAME,
    binary_architectures,
    host_architecture,
    resolve_sidecar,
    tauri_triple,
)

_REPO = Path(__file__).resolve().parents[3]
_NATIVE = _REPO / "native" / "contacts-bridge"
_BINARIES = _REPO / "frontend" / "src-tauri" / "binaries"


def _min_os(path: Path) -> str | None:
    out = subprocess.run(["/usr/bin/otool", "-l", str(path)],
                         capture_output=True, text=True).stdout
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if "LC_BUILD_VERSION" in line:
            for follow in lines[i:i + 6]:
                if "minos" in follow:
                    return follow.split("minos", 1)[1].strip()
    return None


def _embedded_plist(path: Path) -> str:
    return subprocess.run(["/usr/bin/otool", "-P", str(path)],
                          capture_output=True, text=True).stdout


#: Alle Orte, an denen ein gebautes Sidecar-Artefakt liegen kann. Vorrang hat
#: das Tauri-Paketartefakt `binaries/jarvis-contacts-<triple>` — das ist der
#: Stand, der tatsaechlich gebuendelt wird. Danach die Build-Verzeichnisse der
#: beiden Aufrufwege (`build.sh` direkt bzw. `build-contacts-sidecar.sh`).
def _artifact_candidates(arch: str) -> tuple[Path, ...]:
    triple = tauri_triple(arch)
    return (
        _BINARIES / f"{BINARY_NAME}-{triple}",
        _NATIVE / f"build-{triple}" / BINARY_NAME,
        _NATIVE / f"build-{arch}" / BINARY_NAME,
        _NATIVE / "build" / BINARY_NAME,
    )


def _artifact(arch: str) -> Path | None:
    """Ein bereits gebautes Binary der Architektur — es wird nie gebaut."""
    for cand in _artifact_candidates(arch):
        if cand.exists() and arch in binary_architectures(cand):
            return cand
    return None


def _native() -> Path:
    path = _artifact(host_architecture())
    if path is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    return path


def _foreign() -> Path:
    other = "arm64" if host_architecture() == "x86_64" else "x86_64"
    path = _artifact(other)
    if path is None:
        pytest.skip("Cross-Build nicht vorhanden")
    return path


# ── Statische Prüfungen: beide Architekturen ────────────────────────────────
def test_nativer_build_hat_hostarchitektur():
    assert host_architecture() in binary_architectures(_native())


def test_cross_build_hat_fremde_architektur():
    """Nur statisch — das Binary wird niemals ausgeführt."""
    other = "arm64" if host_architecture() == "x86_64" else "x86_64"
    assert other in binary_architectures(_foreign())


@pytest.mark.parametrize("which", ["native", "foreign"])
def test_mindestversion_ist_12_3(which):
    path = _native() if which == "native" else _foreign()
    assert _min_os(path) == "12.3", "AV-29/ADR-0018 verlangen macOS 12.3"


@pytest.mark.parametrize("which", ["native", "foreign"])
def test_produktiver_identifier_und_usage_string(which):
    path = _native() if which == "native" else _foreign()
    plist = _embedded_plist(path)
    assert "de.kluender.jarvis.contacts-bridge" in plist
    assert "NSContactsUsageDescription" in plist
    # Kein Spike-Identifier, kein Spike-Usage-String.
    assert "contacts-spike" not in plist
    assert "(SIDECAR)" not in plist and "(APP)" not in plist


@pytest.mark.parametrize("which", ["native", "foreign"])
def test_keine_entitlements(which):
    path = _native() if which == "native" else _foreign()
    out = subprocess.run(["/usr/bin/codesign", "-d", "--entitlements", "-", str(path)],
                         capture_output=True, text=True)
    blob = out.stdout + out.stderr
    assert "<key>" not in blob and "[Key]" not in blob


# ── Kontaktfreier Protokolllauf gegen den NATIVEN Sidecar ───────────────────
def test_kontaktfreier_handshake_ping_caps_shutdown():
    location = resolve_sidecar(_native())
    proc = SidecarProcess(location)
    handshake = proc.start()
    try:
        assert handshake.protocol_version == protocol.PROTOCOL_VERSION
        assert handshake.bundle_identifier == "de.kluender.jarvis.contacts-bridge"
        # Ehrliche Capability-Grenzen (08 §4).
        assert handshake.capabilities.notes_supported is False
        assert handshake.capabilities.link_unlink_supported is False
        assert handshake.capabilities.unified_read_only is True
        # Seit ADR-0026 hat der Sidecar **keinen** produktiven Schreibpfad
        # mehr; produktive Writes laufen im Tauri-App-Prozess.
        assert handshake.capabilities.mutations_implemented is False
        assert handshake.capabilities.create_implemented is False
        assert handshake.capabilities.update_implemented is False
        assert handshake.capabilities.delete_implemented is False
        assert handshake.capabilities.mutation_contract_version == \
            protocol.MUTATION_CONTRACT_VERSION
        assert handshake.capabilities.field_contract_version == \
            protocol.FIELD_CONTRACT_VERSION

        assert proc.request(protocol.Operation.PING, timeout=10)["ok"] is True
        caps = proc.request(protocol.Operation.CAPS, timeout=10)
        assert caps["ok"] is True
        assert caps["result"]["capabilities"]["notesSupported"] is False
    finally:
        proc.stop()
    assert not proc.is_running


def test_unbekannte_operation_wird_typisiert_abgelehnt():
    proc = SidecarProcess(resolve_sidecar(_native()))
    proc.start()
    try:
        envelope = proc.request("gibtEsNicht", timeout=10)
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == protocol.ErrorCode.INVALID_REQUEST
    finally:
        proc.stop()


def test_create_bricht_ohne_pflichtfelder_vor_dem_store_ab():
    """`create` ist implementiert — aber ohne Vertrag geschieht nichts.

    Frueher endete diese Anfrage in `not_implemented`. Seit ADR-0025 endet sie
    in `not_sent`: die Aussage ist damit schaerfer, denn `not_sent` behauptet
    ausdruecklich, dass **nichts uebergeben wurde** — genau das, worauf der
    Kern seine Zustandsentscheidung stuetzt.
    """
    proc = SidecarProcess(resolve_sidecar(_native()))
    proc.start()
    try:
        envelope = proc.request(protocol.Operation.CREATE, {}, timeout=10)
        assert envelope["ok"] is True
        ergebnis = envelope["result"]
        assert ergebnis["outcome"] == protocol.MutationOutcome.NOT_SENT
        # Seit ADR-0026 endet jeder Create bereits an der Kanalgrenze —
        # noch vor der Pflichtfeldpruefung, aber ebenso beweisbar ohne
        # Uebergabe an den Store.
        assert ergebnis["errorCode"] in (protocol.ErrorCode.INVALID_REQUEST,
                                         "capability_denied")

        # Auch mit Pflichtfeldern, aber ohne Container: weiterhin not_sent.
        envelope = proc.request(
            protocol.Operation.CREATE,
            {"mutationId": "m", "idempotencyKey": "k", "approvalId": "a"},
            timeout=10)
        assert envelope["result"]["outcome"] == protocol.MutationOutcome.NOT_SENT
    finally:
        proc.stop()


def test_update_und_delete_verlangen_ziel_id():
    proc = SidecarProcess(resolve_sidecar(_native()))
    proc.start()
    try:
        for op in (protocol.Operation.UPDATE, protocol.Operation.DELETE):
            envelope = proc.request(
                op, {"mutationId": "m", "idempotencyKey": "k", "approvalId": "a"},
                timeout=10)
            assert envelope["ok"] is False
            assert "targetProviderIdentifier" in envelope["error"]["message"], (
                "keine Mutation ohne ausdrueckliche Ziel-ID (Plan §7.1)")
    finally:
        proc.stop()


def test_autorisierungsstatus_bleibt_unveraendert():
    """Der kontaktfreie Lauf loest keinen Dialog aus."""
    proc = SidecarProcess(resolve_sidecar(_native()))
    handshake = proc.start()
    try:
        before = handshake.authorization_status
        envelope = proc.request(protocol.Operation.AUTHORIZATION_STATUS, timeout=10)
        after = AuthorizationStatus.parse(envelope["result"]["authorizationStatus"])
        assert after is before
    finally:
        proc.stop()


def test_keine_spike_operationen_im_vertrag():
    proc = SidecarProcess(resolve_sidecar(_native()))
    handshake = proc.start()
    try:
        for entfallen in ("token", "updateViaUnified", "enumerateProbe",
                          "isolationSummary"):
            assert entfallen not in handshake.operations
    finally:
        proc.stop()


# ── Dünnheits-Review des Sidecar-Quelltexts (ADR-0016 Punkt 4) ──────────────
def _swift_code_ohne_kommentare(path: Path) -> str:
    """Swift-Quelltext ohne Zeilenkommentare.

    Die Duennheits-Verbote stehen als Kommentar IM Sidecar; eine reine
    Textsuche wuerde genau diese Notiz als Verstoss melden.
    """
    zeilen = []
    for zeile in path.read_text(encoding="utf-8").splitlines():
        code = zeile.split("//", 1)[0]
        if code.strip():
            zeilen.append(code)
    return "\n".join(zeilen)


def test_sidecar_enthaelt_keine_fachlogik():
    """ADR-0016 Punkt 4: keine Fach-, Merge-, Normalisierungs- oder Hashlogik."""
    code = _swift_code_ohne_kommentare(_NATIVE / "src" / "sidecar.swift")
    verboten = ["workspace", "displayname", "sha256", "normalize", "merge(",
                "zzz-jarvistest-", "audit", "risk"]
    treffer = [w for w in verboten if w in code.lower()]
    assert not treffer, f"Fachlogik im Sidecar: {treffer}"


def test_objc_shim_ist_reine_weiterleitung():
    """Der Shim leitet ausschliesslich zwei Selektoren weiter (ADR-0016 Pkt. 4)."""
    code = _swift_code_ohne_kommentare(_NATIVE / "src" / "JCChangeHistoryShim.m")
    assert code.count("return [store") == 2
    for verboten in ("if ", "for ", "while ", "switch "):
        assert verboten not in code, "Der Shim darf keine Ablauflogik enthalten"


# ── Mutationsvertrag: kontaktfrei am laufenden Sidecar ──────────────────────
#
# Ausgefuehrt werden ausschliesslich Anfragen, die **vor** jedem Store-Zugriff
# abbrechen. Seit ADR-0026 endet jeder Create schon an der Kanalgrenze
# (`capability_denied`) — der Sidecar hat keinen produktiven Schreibpfad mehr.
# Die frueheren Abbruchgruende (fehlende Pflichtfelder, fremde
# Vertragsversion) bleiben als zulaessige Antworten stehen, damit die Suite
# auch gegen einen aelteren gebauten Sidecar gruen bleibt. In beiden Faellen
# gilt dasselbe: kein Kontakt wird angelegt, gelesen oder veraendert, und es
# gibt keinen TCC-Dialog.
def _mutationsantwort(payload: dict) -> dict:
    proc = SidecarProcess(resolve_sidecar(_native()))
    proc.start()
    try:
        return proc.request(protocol.Operation.CREATE, payload, timeout=15)
    finally:
        proc.stop()


def test_create_ohne_pflichtfelder_meldet_not_sent():
    antwort = _mutationsantwort({"fields": {"givenName": "X"}})
    assert antwort["ok"] is True
    ergebnis = antwort["result"]
    assert ergebnis["outcome"] == protocol.MutationOutcome.NOT_SENT
    assert ergebnis["errorCode"] in ("invalid_request", "capability_denied")


def test_create_mit_fremder_vertragsversion_meldet_not_sent():
    """Ein Kern mit anderem Vertragsstand schreibt hier nichts."""
    antwort = _mutationsantwort({
        "mutationId": "m-1", "idempotencyKey": "i-1", "approvalId": "a-1",
        "containerIdentifier": "egal", "fields": {"givenName": "X"},
        "mutationContractVersion": 99, "fieldContractVersion": 99})
    ergebnis = antwort["result"]
    assert ergebnis["outcome"] == protocol.MutationOutcome.NOT_SENT
    assert ergebnis["errorCode"] in ("protocol_mismatch", "capability_denied")


def test_die_mutationsantwort_nennt_ihre_vertragsversionen():
    antwort = _mutationsantwort({"fields": {}})
    ergebnis = antwort["result"]
    assert ergebnis["mutationContractVersion"] == protocol.MUTATION_CONTRACT_VERSION
    assert ergebnis["fieldContractVersion"] == protocol.FIELD_CONTRACT_VERSION
    assert ergebnis["transactionAuthor"] == "de.kluender.jarvis.contacts-bridge"


def test_die_mutationsantwort_traegt_keinen_feldwert_und_keinen_pfad():
    antwort = _mutationsantwort({
        "mutationId": "m-2", "idempotencyKey": "i-2", "approvalId": "a-2",
        "containerIdentifier": "egal",
        "fields": {"givenName": "Geheimname-XYZ"},
        "mutationContractVersion": 99, "fieldContractVersion": 1})
    text = json.dumps(antwort)
    assert "Geheimname-XYZ" not in text
    assert "/Users/" not in text


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_update_und_delete_bleiben_nicht_implementiert(operation):
    proc = SidecarProcess(resolve_sidecar(_native()))
    proc.start()
    try:
        antwort = proc.request(operation, {
            "mutationId": "m-3", "idempotencyKey": "i-3", "approvalId": "a-3",
            "targetProviderIdentifier": "egal"}, timeout=15)
    finally:
        proc.stop()
    assert antwort["ok"] is False
    assert antwort["error"]["code"] == protocol.ErrorCode.NOT_IMPLEMENTED
