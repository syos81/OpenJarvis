"""Tauri-Bundle-Integration des Contacts-Sidecars — kontaktfrei (Gate B).

Geprüft werden Konfiguration, Namenskonvention, Capability-Fläche, Resolver und
ein **nachgebildetes** Bundle-Layout.

**Abgrenzung, die dieser Test ausdrücklich nicht überschreitet:** Ein
nachgebildetes Layout ist ein *Packaging-Integrationstest*. Es ist **kein**
Nachweis, dass die echte gepackte App den Sidecar startet — dafür müsste der
Tauri-Prozess selbst laufen. Die entsprechende Abnahmezeile in 15 §8 bleibt
`OPEN`.

Ausgeführt werden ausschließlich `ready`, `ping`, `caps` und `shutdown`.
`authorizationStatus` wird hier **nicht** gesendet: die Operation ist zwar
belegt store-frei (Klassenmethode), aber für die Bundle-Integration ohne
Aussagewert — und was nicht nötig ist, wird nicht ausgeführt.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.errors import BridgeConfigurationError
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import (
    BINARY_NAME,
    binary_architectures,
    host_architecture,
    resolve_sidecar,
    tauri_triple,
)

_REPO = Path(__file__).resolve().parents[3]
_TAURI = _REPO / "frontend" / "src-tauri"
_BINARIES = _TAURI / "binaries"
_NATIVE = _REPO / "native" / "contacts-bridge"
_CONF = _TAURI / "tauri.conf.json"
_CAPS = _TAURI / "capabilities" / "default.json"
_SCRIPT = _TAURI / "scripts" / "build-contacts-sidecar.sh"


def _shell_code(path: Path) -> str:
    """Shell-Quelltext ohne Kommentarzeilen.

    Die Verbote stehen als Kommentar IM Skript ("never reads spikes/"). Eine
    reine Textsuche wuerde genau diese Abgrenzungsnotiz als Verstoss melden —
    geprueft wird deshalb ausschliesslich echter Code.
    """
    zeilen = []
    for raw in path.read_text().splitlines():
        ohne = raw.split("#", 1)[0] if not raw.lstrip().startswith("#") else ""
        zeilen.append(ohne)
    return "\n".join(zeilen)


def _python_code(path: Path) -> str:
    """Python-Quelltext ohne Kommentare und Zeichenkettenliterale."""
    import tokenize

    stuecke = []
    with open(path, "rb") as fh:
        try:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                stuecke.append(tok.string)
        except tokenize.TokenError:            # pragma: no cover
            return path.read_text()
    return " ".join(stuecke)


def _conf() -> dict:
    return json.loads(_CONF.read_text())


def _caps() -> dict:
    return json.loads(_CAPS.read_text())


def _artifact(arch: str) -> Path | None:
    for cand in (
        _BINARIES / f"{BINARY_NAME}-{tauri_triple(arch)}",
        _NATIVE / f"build-{tauri_triple(arch)}" / BINARY_NAME,
        _NATIVE / f"build-{arch}" / BINARY_NAME,
        _NATIVE / "build" / BINARY_NAME,
    ):
        if cand.exists() and arch in binary_architectures(cand):
            return cand
    return None


# ── externalBin-Konfiguration ───────────────────────────────────────────────
def test_external_bin_ist_konfiguriert():
    assert "binaries/jarvis-contacts" in _conf()["bundle"]["externalBin"]


def test_external_bin_traegt_keine_architektur():
    """Tauri hängt das Ziel-Triple selbst an — der Basisname bleibt logisch."""
    for entry in _conf()["bundle"]["externalBin"]:
        for verboten in ("aarch64", "x86_64", "arm64", "universal", ".exe"):
            assert verboten not in entry, entry


def test_external_bin_ist_relativ():
    for entry in _conf()["bundle"]["externalBin"]:
        assert not entry.startswith("/"), entry
        assert "~" not in entry and ".." not in entry, entry


def test_minimum_system_version_bleibt_12_3():
    assert _conf()["bundle"]["macOS"]["minimumSystemVersion"] == "12.3"


def test_produktiver_identifier_unveraendert():
    assert _conf()["identifier"] == "de.kluender.jarvis"
    assert _conf()["productName"] == "Jarvis"
    # Die Upstream-Kennung darf in der Konfiguration nicht mehr vorkommen.
    assert "com.openjarvis.desktop" not in _CONF.read_text()


def test_keine_signaturidentitaet_der_bridge_in_der_konfiguration():
    """Die Sidecar-Signaturidentität wird nie in Produktkonfiguration verdrahtet."""
    text = _CONF.read_text() + _shell_code(_SCRIPT)
    for verboten in ("Personal Jarvis Contacts Spike", "0139fb6e", "0139FB6E"):
        assert verboten not in text, verboten


def test_keine_universal2_entscheidung_in_der_konfiguration():
    """DEC-D17 bleibt offen — kein Format wird vorgeschrieben."""
    assert "universal" not in _CONF.read_text().lower()


# ── Namenskonvention je Target-Triple ───────────────────────────────────────
@pytest.mark.parametrize("arch,triple", [
    ("arm64", "aarch64-apple-darwin"),
    ("x86_64", "x86_64-apple-darwin"),
])
def test_artefaktname_je_triple(arch, triple):
    assert tauri_triple(arch) == triple
    erwartet = f"{BINARY_NAME}-{triple}"
    art = _artifact(arch)
    if art is None:
        pytest.skip(f"{arch}-Artefakt nicht gebaut")
    if art.parent == _BINARIES:
        assert art.name == erwartet


def test_arm64_build_erwartet_nur_arm64_artefakt():
    art = _artifact("arm64")
    if art is None:
        pytest.skip("arm64-Artefakt nicht gebaut")
    assert binary_architectures(art) == ("arm64",)


def test_x86_64_build_erwartet_nur_x86_64_artefakt():
    art = _artifact("x86_64")
    if art is None:
        pytest.skip("x86_64-Artefakt nicht gebaut")
    assert binary_architectures(art) == ("x86_64",)


# ── Build-Skript ────────────────────────────────────────────────────────────
def test_build_skript_existiert_und_ist_ausfuehrbar():
    assert _SCRIPT.exists()
    assert os.access(_SCRIPT, os.X_OK)


def test_build_skript_ohne_download_ohne_spikes_ohne_privatpfad():
    code = _shell_code(_SCRIPT)
    for verboten in ("curl", "wget", "spikes/", "/Users/lukaskluender", "$HOME/"):
        assert verboten not in code, verboten


def test_build_skript_signiert_nur_mit_ausdruecklicher_variable():
    code = _shell_code(_SCRIPT)
    assert "CONTACTS_SIDECAR_IDENTITY" in code
    # Ohne die Variable darf kein codesign-Aufruf erreichbar sein.
    vor_gate = code.split("CONTACTS_SIDECAR_IDENTITY", 1)[0]
    assert "codesign" not in vor_gate


def test_build_skript_lehnt_unbekanntes_target_ab(tmp_path):
    proc = subprocess.run([str(_SCRIPT), "aarch64-unknown-linux-gnu"],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "Unknown target triple" in proc.stdout + proc.stderr


# ── Binaries bleiben ignoriert ──────────────────────────────────────────────
def test_sidecar_binaries_sind_ignoriert():
    for triple in ("aarch64-apple-darwin", "x86_64-apple-darwin"):
        pfad = f"frontend/src-tauri/binaries/{BINARY_NAME}-{triple}"
        proc = subprocess.run(["git", "check-ignore", pfad],
                              cwd=str(_REPO), capture_output=True, text=True)
        assert proc.returncode == 0, f"{pfad} ist NICHT ignoriert"


def test_kein_sidecar_binary_getrackt():
    proc = subprocess.run(["git", "ls-files"], cwd=str(_REPO),
                          capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        assert not line.endswith(BINARY_NAME), line
        assert BINARY_NAME + "-" not in line, line


# ── Capability-Fläche ───────────────────────────────────────────────────────
def _sidecar_scopes(caps: dict) -> list[dict]:
    scopes = []
    for perm in caps["permissions"]:
        if isinstance(perm, dict):
            scopes.extend(perm.get("allow", []))
    return scopes


def test_capability_gewaehrt_der_webview_keinen_contacts_sidecar():
    """Der Contacts-Sidecar wird vom Python-Backend gestartet, nicht von Tauri.

    Ein `shell:allow-execute`-Scope für `binaries/jarvis-contacts` würde der
    Webview einen **zweiten fachlichen Ausführungspfad** geben — genau das
    verbieten AV-35 und DEV-4. Er darf deshalb nicht existieren.
    """
    namen = [s.get("name") for s in _sidecar_scopes(_caps())]
    assert "binaries/jarvis-contacts" not in namen, (
        "Die Webview darf den Contacts-Sidecar nicht starten duerfen"
    )


def test_capability_scopes_erlauben_keine_freie_argumentinjektion_fuer_contacts():
    for scope in _sidecar_scopes(_caps()):
        if "jarvis-contacts" in str(scope.get("name", "")):
            assert scope.get("args") is not True, scope


def test_keine_neue_tauri_capability_fuer_contacts():
    """Gate B fügt der Kommandofläche nichts hinzu."""
    text = _CAPS.read_text()
    for verboten in ("contacts", "requestAuthorization", "enumerate"):
        assert verboten not in text, verboten


def _rust_ohne_kommentare(pfad: Path) -> str:
    """Rust-Quelltext ohne Kommentare.

    Notwendig, weil sonst der erklärende Kommentar neben einer Zeile die
    Prüfung auslöst — der Test würde dann die Dokumentation bestrafen.
    """
    text = pfad.read_text()
    ohne_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(z.split("//", 1)[0] for z in ohne_block.splitlines())


def test_lib_rs_spricht_das_bridge_protokoll_nicht():
    """Kein zweiter fachlicher Ausführungsweg im Tauri-Hauptprozess.

    Der Hauptprozess **darf** den gebündelten Sidecar finden und seinen Pfad
    an den Python-Prozess durchreichen — das ist Paketierung, nicht Fachlogik.
    Er darf ihn nicht starten, nicht mit ihm sprechen und keine
    Kontakte-Operation auslösen. Genau das wird hier geprüft, statt ein Wort
    zu verbieten: die frühere Fassung untersagte den blossen String
    `jarvis-contacts` und hätte damit auch die Pfadauflösung verboten, die
    für den Betrieb aus der gepackten App notwendig ist.
    """
    code = _rust_ohne_kommentare(_TAURI / "src" / "lib.rs")

    # Keine Kontakte-Operation und kein Protokollverkehr.
    for verboten in ("requestAuthorization", "authorizationStatus",
                     "enumerate", "containers", "changes",
                     "CNContact", "protocolVersion", '"op"'):
        assert verboten not in code, verboten

    # Der Sidecar wird nirgends gestartet: sein Pfad taucht ausschliesslich
    # in der Auflösung und in der Env-Übergabe auf, nie in einem Command.
    for zeile in code.splitlines():
        if "jarvis-contacts" in zeile:
            assert "Command::new" not in zeile, zeile
            assert ".spawn(" not in zeile, zeile

    # Und er wird nie über PATH gesucht.
    assert "resolve_bin(\"jarvis-contacts\")" not in code.replace(" ", "")


def test_lib_rs_uebergibt_den_sidecar_nur_als_umgebungsvariable():
    """Der Python-Resolver bleibt die einzige Stelle, die prüft.

    Rust reicht den Pfad durch; Architektur-, Symlink- und Signaturprüfung
    macht ausschliesslich `resolve_sidecar`.
    """
    code = _rust_ohne_kommentare(_TAURI / "src" / "lib.rs")
    assert 'cmd.env("PERSONAL_JARVIS_CONTACTS_SIDECAR"' in code
    assert 'cmd.env("OPENJARVIS_PERSONAL_ENABLED", "1")' in code


def test_personal_jarvis_wird_nur_mit_vorhandenem_sidecar_aktiviert():
    """DEV-3 bleibt gewahrt: ohne Sidecar keine Verhaltensänderung.

    Ein Upstream-Build trägt kein `jarvis-contacts`; dort bleibt der Schalter
    ungesetzt und die App verhält sich unverändert.
    """
    code = _rust_ohne_kommentare(_TAURI / "src" / "lib.rs")
    stelle = code.index('cmd.env("OPENJARVIS_PERSONAL_ENABLED"')
    umfeld = code[max(0, stelle - 400):stelle]
    assert "bundled_contacts_sidecar()" in umfeld, (
        "Der Schalter muss an das Vorhandensein des Sidecars gebunden sein")


def test_sidecar_wird_nur_neben_der_ausfuehrbaren_datei_gesucht():
    """Kein PATH-Lookup — sonst wäre das Binary austauschbar."""
    code = _rust_ohne_kommentare(_TAURI / "src" / "lib.rs")
    start = code.index("fn bundled_contacts_sidecar")
    rumpf = code[start:start + 400]
    assert "current_exe()" in rumpf
    for verboten in ("PATH", "resolve_bin", "which"):
        assert verboten not in rumpf, verboten


# ── Resolver im nachgebildeten Bundle-Layout ────────────────────────────────
def _bundle(tmp_path: Path) -> Path:
    """Layout einer gepackten Tauri-App: Sidecar neben der ausführbaren Datei."""
    macos = tmp_path / "OpenJarvis.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    return macos


def test_resolver_findet_sidecar_im_bundle(tmp_path):
    art = _artifact(host_architecture())
    if art is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    macos = _bundle(tmp_path)
    ziel = macos / BINARY_NAME
    shutil.copy2(art, ziel)
    loc = resolve_sidecar(bundle_dir=macos)
    assert loc.path == ziel
    assert host_architecture() in loc.architectures


def test_resolver_findet_sidecar_unter_triple_namen_im_bundle(tmp_path):
    art = _artifact(host_architecture())
    if art is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    macos = _bundle(tmp_path)
    ziel = macos / f"{BINARY_NAME}-{tauri_triple()}"
    shutil.copy2(art, ziel)
    loc = resolve_sidecar(bundle_dir=macos)
    assert loc.path == ziel


def test_resolver_meldet_fehlendes_bundle_artefakt(tmp_path):
    macos = _bundle(tmp_path)
    with pytest.raises(BridgeConfigurationError, match="nicht gefunden"):
        resolve_sidecar(bundle_dir=macos)


def test_resolver_lehnt_fremde_architektur_im_bundle_ab(tmp_path):
    other = "arm64" if host_architecture() == "x86_64" else "x86_64"
    art = _artifact(other)
    if art is None:
        pytest.skip("Cross-Build nicht vorhanden")
    macos = _bundle(tmp_path)
    ziel = macos / BINARY_NAME
    shutil.copy2(art, ziel)
    with pytest.raises(BridgeConfigurationError, match="Architektur"):
        resolve_sidecar(bundle_dir=macos)


def test_resolver_lehnt_symlink_im_bundle_ab(tmp_path):
    art = _artifact(host_architecture())
    if art is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    echt = tmp_path / "echt"
    shutil.copy2(art, echt)
    macos = _bundle(tmp_path)
    (macos / BINARY_NAME).symlink_to(echt)
    with pytest.raises(BridgeConfigurationError, match="Symlink"):
        resolve_sidecar(bundle_dir=macos)


def test_resolver_lehnt_nicht_ausfuehrbare_datei_ab(tmp_path):
    art = _artifact(host_architecture())
    if art is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    macos = _bundle(tmp_path)
    ziel = macos / BINARY_NAME
    shutil.copy2(art, ziel)
    ziel.chmod(stat.S_IRUSR)
    try:
        with pytest.raises(BridgeConfigurationError, match="ausfuehrbar"):
            resolve_sidecar(bundle_dir=macos)
    finally:
        ziel.chmod(0o755)


def test_resolver_hat_keine_zweite_wahrheit():
    """Nur ein Auflösungsweg: explizit, Umgebung, Bundle — sonst nichts."""
    code = _python_code(_REPO / "src/personaljarvis/contacts/bridge/resolver.py")
    for verboten in ("/usr/local", "/opt/", "PATH", "which", "spikes"):
        assert verboten not in code, verboten


# ── Nachgebildetes Bundle: kontaktfreier Handshake ──────────────────────────
def test_bundle_layout_handshake_kontaktfrei(tmp_path):
    """Packaging-Integrationstest — **kein** Live-App-Nachweis.

    Der Sidecar wird aus dem nachgebildeten Bundle-Pfad gestartet; ausgeführt
    werden nur `ready`, `ping`, `caps`, `shutdown`.
    """
    art = _artifact(host_architecture())
    if art is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    macos = _bundle(tmp_path)
    shutil.copy2(art, macos / BINARY_NAME)
    location = resolve_sidecar(bundle_dir=macos)

    proc = SidecarProcess(location)
    try:
        handshake = proc.start()                      # ready
        assert handshake.protocol_version == protocol.PROTOCOL_VERSION
        assert handshake.bundle_identifier == "de.kluender.jarvis.contacts-bridge"
        assert handshake.capabilities.notes_supported is False
        # Aus dem gepackten Bundle heraus gilt derselbe Vertrag wie direkt:
        # `create` implementiert, `update`/`delete` nicht.
        assert handshake.capabilities.create_implemented is True
        assert handshake.capabilities.update_implemented is False
        assert handshake.capabilities.delete_implemented is False

        assert proc.request("ping")["result"]["pong"] is True
        assert proc.request("caps")["result"]["type"] == "ready"
        assert proc.request("shutdown")["result"]["bye"] is True
    finally:
        proc.stop()
    assert not proc.is_running
