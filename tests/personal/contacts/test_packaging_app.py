"""Nachweise am **echten** gepackten App-Bundle — kontaktfrei.

Anders als `test_packaging_bundle.py` prüft diese Datei kein nachgebildetes
Layout, sondern das Ergebnis eines tatsächlichen `tauri build`. Ohne
vorhandenes Bundle werden die Tests übersprungen; der Übersprung ist im
Bericht auszuweisen und gilt **nicht** als Nachweis.

Ausgeführt wird nichts: es werden ausschliesslich Dateien inspiziert
(`lipo`, `codesign`, `otool`, `plutil`). Weder die App noch der Sidecar
startet, und der Kontakte-Store wird nicht berührt.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from personaljarvis.contacts.bridge.resolver import (
    BINARY_NAME,
    binary_architectures,
    host_architecture,
    resolve_sidecar,
    tauri_triple,
)

_REPO = Path(__file__).resolve().parents[3]
#: Der Zielordner heisst nach dem **Rust-Triple des Hosts** — beide macOS-
#: Architekturen sind gleichwertige Produktionsziele (DEC-042, ADR-0018).
#: Ein fest verdrahtetes Triple hiesse: auf der jeweils anderen Architektur
#: findet diese Datei kein Bundle und überspringt lautlos alle Nachweise.
_BUNDLE = (_REPO / "frontend/src-tauri/target" / tauri_triple()
           / "release/bundle/macos/Jarvis.app")

#: Produktive Kennungen. Eine Spike-Identität im Bundle wäre ein Fehler.
#: Endgültige Produktidentität. `com.openjarvis.desktop` war die
#: Upstream-Kennung; unter ihr soll diese Anwendung dauerhaft nicht laufen.
APP_IDENTIFIER = "de.kluender.jarvis"
#: Die alte Kennung darf im Paket nirgends mehr auftauchen.
ALTE_APP_IDENTIFIER = "com.openjarvis.desktop"
SIDECAR_IDENTIFIER = "de.kluender.jarvis.contacts-bridge"


def _erforderlich() -> Path:
    if not _BUNDLE.exists():
        pytest.skip("Kein gepacktes App-Bundle vorhanden "
                    "(npx tauri build --bundles app)")
    return _BUNDLE


def _sidecar() -> Path:
    pfad = _erforderlich() / "Contents" / "MacOS" / BINARY_NAME
    if not pfad.exists():
        pytest.fail(f"Sidecar fehlt im Bundle: {pfad}")
    return pfad


def _codesign(*args: str) -> str:
    proc = subprocess.run(["/usr/bin/codesign", *args],
                          capture_output=True, text=True, timeout=60)
    return proc.stdout + proc.stderr


def _info_plist(app: Path) -> dict:
    return plistlib.loads((app / "Contents" / "Info.plist").read_bytes())


# ── Der Sidecar liegt im Paket ──────────────────────────────────────────────
def test_sidecar_liegt_neben_der_ausfuehrbaren_datei():
    """Genau dort sucht der Resolver — und nur dort."""
    sidecar = _sidecar()
    assert sidecar.parent.name == "MacOS"
    assert (sidecar.parent / "openjarvis-desktop").exists()


def test_sidecar_traegt_kein_ziel_triple_im_namen():
    """Tauri entfernt den Suffix beim Bündeln; der Resolver erwartet das."""
    dateien = {p.name for p in _sidecar().parent.iterdir()}
    assert BINARY_NAME in dateien
    assert not any(n.startswith(f"{BINARY_NAME}-") for n in dateien)


def test_sidecar_ist_nativ_fuer_diesen_host():
    """Nativ heisst: genau **eine** Architektur, und zwar die des Hosts.

    Die Abnahme erfolgt je Architektur auf echter Hardware (ADR-0018 §5).
    Ein Cross-Build oder ein Universal-Binary wäre hier kein Nachweis — und
    ein arm64-Binary auf Intel liesse sich nicht einmal starten.
    """
    assert binary_architectures(_sidecar()) == (host_architecture(),)


def test_sidecar_ist_ausfuehrbar():
    import os

    assert os.access(_sidecar(), os.X_OK)


def test_resolver_findet_genau_dieses_binary():
    """Der produktive Auflösungsweg endet im Paket, nicht im Arbeitsbaum."""
    ort = resolve_sidecar(bundle_dir=_sidecar().parent)
    assert ort.path == _sidecar()
    assert host_architecture() in ort.architectures


# ── Kennungen ───────────────────────────────────────────────────────────────
def test_app_traegt_den_produktiven_identifier():
    assert _info_plist(_erforderlich())["CFBundleIdentifier"] == APP_IDENTIFIER


def test_sidecar_traegt_den_produktiven_identifier():
    ausgabe = _codesign("-dvvv", str(_sidecar()))
    assert f"Identifier={SIDECAR_IDENTIFIER}" in ausgabe


def test_keine_spike_identitaet_im_paket():
    """Weder App noch Sidecar dürfen die Spike-Identität tragen."""
    app = _erforderlich()
    ausgaben = _codesign("-dvvv", str(app)) + _codesign("-dvvv", str(_sidecar()))
    plist = str(_info_plist(app))
    for verboten in ("Spike", "spike", "contacts-bridge-g3a", "JarvisContactsSpike"):
        assert verboten not in plist, verboten
    assert "Spike" not in ausgaben


def test_keine_upstream_identitaet_mehr_im_paket():
    """Ein zweiter Produkt-Identifier im Bundle wäre eine zweite TCC-Identität.

    Geprüft werden Info.plist **und** die Code-Signatur: beide müssen
    ausschliesslich die endgültige Kennung tragen.
    """
    app = _erforderlich()
    plist = str(_info_plist(app))
    assert ALTE_APP_IDENTIFIER not in plist
    ausgabe = _codesign("-dvvv", str(app))
    assert ALTE_APP_IDENTIFIER not in ausgabe
    assert f"Identifier={APP_IDENTIFIER}" in ausgabe


def test_der_produktname_ist_jarvis():
    app = _erforderlich()
    assert app.name == "Jarvis.app"
    plist = _info_plist(app)
    assert plist.get("CFBundleName") == "Jarvis"


def test_die_beiden_identitaeten_gehoeren_zusammen():
    """Sidecar-Kennung ist eine Unterkennung der App — kein Fremdkörper."""
    assert SIDECAR_IDENTIFIER.startswith(APP_IDENTIFIER + ".")


# ── Usage Description ───────────────────────────────────────────────────────
def test_app_erklaert_den_kontaktezugriff():
    """Ohne diesen Schlüssel zeigt macOS keinen Dialog, sondern scheitert."""
    text = _info_plist(_erforderlich()).get("NSContactsUsageDescription", "")
    assert text, "NSContactsUsageDescription fehlt im App-Bundle"
    assert len(text) > 40, "Der Text muss dem Nutzer wirklich etwas sagen"


def test_der_usage_text_verspricht_kein_schreiben():
    """Der Text erscheint dem Nutzer wörtlich. Diese Version liest nur.

    Geprüft wird die Zusage, nicht das Vorkommen einzelner Wörter: die
    Verneinung „es werden keine Kontakte verändert" enthält „verändert" und
    ist gerade deshalb richtig. Eine reine Teilstringsuche hätte sie
    fälschlich als Schreibversprechen gewertet.
    """
    text = _info_plist(_erforderlich())["NSContactsUsageDescription"]
    klein = text.lower()
    assert "liest" in klein, "Der Text muss sagen, dass gelesen wird"
    assert "keine kontakte verändert" in klein, (
        "Der Text muss ausdrücklich verneinen, dass geschrieben wird")
    # Ein Schreibversprechen stünde ohne vorangehende Verneinung da.
    for satz in text.split("."):
        if any(v in satz.lower() for v in ("verwaltet", "bearbeitet", "schreibt")):
            assert "keine" in satz.lower(), satz


def test_sidecar_traegt_denselben_usage_text():
    """Beide Codeobjekte müssen dasselbe versprechen — sonst hängt der
    gezeigte Text davon ab, wen TCC gerade attribuiert."""
    proc = subprocess.run(["/usr/bin/otool", "-P", str(_sidecar())],
                          capture_output=True, text=True, timeout=60)
    assert "NSContactsUsageDescription" in proc.stdout
    app_text = _info_plist(_erforderlich())["NSContactsUsageDescription"]
    # Der eingebettete Plist-Text ist ASCII-transliteriert; verglichen wird
    # die Aussage, nicht die Kodierung.
    assert "liest deine Kontakte" in proc.stdout
    assert "liest deine Kontakte" in app_text


# ── Signierung ──────────────────────────────────────────────────────────────
def test_app_ist_signiert_und_gueltig():
    ausgabe = _codesign("--verify", "--strict", "--verbose=2",
                        str(_erforderlich()))
    assert "satisfies its Designated Requirement" in ausgabe


def test_sidecar_ist_signiert_und_gueltig():
    ausgabe = _codesign("--verify", "--strict", "--verbose=2", str(_sidecar()))
    assert "satisfies its Designated Requirement" in ausgabe


def test_sidecar_signatur_ist_nicht_ad_hoc():
    """Ad-hoc-Signaturen sind an den Hash gebunden und überleben keinen
    Neubau — die TCC-Berechtigung ginge bei jedem Build verloren."""
    ausgabe = _codesign("-dvvv", str(_sidecar()))
    assert "Signature=adhoc" not in ausgabe
    assert "Authority=" in ausgabe


def test_sidecar_designated_requirement_ist_zertifikatsgebunden():
    """Zertifikatsgebunden statt cdhash-gebunden: nur so bleibt die einmal
    erteilte Berechtigung über Neubauten hinweg bestehen."""
    ausgabe = _codesign("-d", "-r-", str(_sidecar()))
    assert "certificate leaf" in ausgabe
    assert f'identifier "{SIDECAR_IDENTIFIER}"' in ausgabe
    assert "cdhash" not in ausgabe


def test_sidecar_hat_hardened_runtime():
    ausgabe = _codesign("-dvvv", str(_sidecar()))
    assert "runtime" in ausgabe, "Hardened Runtime fehlt"


def test_sidecar_traegt_keine_entitlements():
    """Ohne Sandbox braucht der Kontakte-Zugriff kein Entitlement. Was nicht
    nötig ist, wird nicht gewährt."""
    ausgabe = _codesign("-d", "--entitlements", "-", str(_sidecar()))
    for verboten in ("com.apple.security.personal-information",
                     "com.apple.security.app-sandbox",
                     "addressbook"):
        assert verboten not in ausgabe.lower(), verboten


def test_app_entitlements_bleiben_unveraendert():
    """Diese Aufgabe erweitert die Rechte der App nicht."""
    ausgabe = _codesign("-d", "--entitlements", "-", str(_erforderlich()))
    assert "com.apple.security.personal-information" not in ausgabe.lower()
    assert "addressbook" not in ausgabe.lower()


# ── Nichts Verbotenes im Paket ──────────────────────────────────────────────
def test_kein_binary_ist_im_git_diff():
    """Weder Bundle noch Sidecar dürfen jemals eingecheckt werden."""
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(_REPO),
                          capture_output=True, text=True, timeout=60)
    for zeile in proc.stdout.splitlines():
        pfad = zeile[3:]
        assert BINARY_NAME not in pfad, pfad
        assert "OpenJarvis.app" not in pfad, pfad
        assert not pfad.endswith(".db"), pfad


# ═══ Sandbox- und Entitlement-Modell ════════════════════════════════════════
#
# Festgelegtes Modell, hier fixiert damit es nicht unbemerkt driftet:
#
#   Die App ist **nicht** sandboxed (`com.apple.security.app-sandbox = false`).
#   Der Kontaktezugriff wird deshalb allein von TCC geregelt, nicht von einem
#   Sandbox-Profil. `com.apple.security.personal-information.addressbook` ist
#   ein **Sandbox**-Entitlement: es gewährt eine Ausnahme innerhalb eines
#   Sandbox-Profils. Ohne Sandbox gibt es kein Profil, in dem es wirken
#   könnte — es wäre wirkungslos.
#
#   Der Sidecar erbt entsprechend **keine** Sandbox und trägt selbst keine
#   Entitlements. `com.apple.security.inherit` setzt eine sandboxed Elternapp
#   voraus; im Kind einer nicht-sandboxed App würde es ein leeres,
#   konkurrierendes Profil erzeugen und den Sidecar aussperren.
def _entitlements(pfad: Path) -> dict:
    import plistlib
    import re

    roh = _codesign("-d", "--entitlements", ":-", str(pfad))
    treffer = re.search(r"(<\?xml.*?</plist>)", roh, re.S)
    return plistlib.loads(treffer.group(1).encode()) if treffer else {}


ADDRESSBOOK = "com.apple.security.personal-information.addressbook"
SANDBOX = "com.apple.security.app-sandbox"
INHERIT = "com.apple.security.inherit"


def test_die_app_ist_bewusst_nicht_sandboxed():
    """Die Grundlage des gesamten Berechtigungsmodells."""
    assert _entitlements(_erforderlich()).get(SANDBOX) is False


def test_ohne_sandbox_kein_addressbook_entitlement():
    """Ein Sandbox-Entitlement ohne Sandbox wäre wirkungsloser Ballast.

    Die Zusicherung läuft in beide Richtungen: wer die Sandbox einschaltet,
    **muss** das Address-Book-Entitlement mitliefern — sonst verliert die App
    den Kontaktezugriff. Wer sie aus lässt, darf es nicht mitschleppen.
    """
    ent = _entitlements(_erforderlich())
    if ent.get(SANDBOX) is True:
        assert ent.get(ADDRESSBOOK) is True, (
            "sandboxed App ohne Address-Book-Entitlement kann keine Kontakte lesen")
    else:
        assert ADDRESSBOOK not in ent, (
            "Sandbox-Entitlement ohne Sandbox — wirkungslos, also weglassen")


def test_der_sidecar_traegt_kein_konkurrierendes_sandbox_profil():
    """`inherit` ohne sandboxed Elternprozess sperrt den Sidecar aus."""
    ent = _entitlements(_sidecar())
    assert SANDBOX not in ent
    assert INHERIT not in ent


def test_der_sidecar_hat_keine_hardened_runtime_ausnahmen():
    """JIT, unsignierter Speicher und abgeschaltete Library-Validation
    braucht ein kleiner Lese-Prozess nicht. Genau die erbte er vor dem
    Reseal von der App."""
    ent = _entitlements(_sidecar())
    for verboten in ("com.apple.security.cs.allow-jit",
                     "com.apple.security.cs.allow-unsigned-executable-memory",
                     "com.apple.security.cs.disable-library-validation"):
        assert verboten not in ent, verboten


def test_der_reseal_entfernt_keine_kontaktefaehigkeit():
    """Was der Reseal wegnimmt, sind ausschliesslich die geerbten
    App-Entitlements — und darunter war nie eine Kontaktefähigkeit.

    Belegt gegen die Quelle: `Entitlements.plist` der App enthält kein
    Address-Book-Entitlement, also kann der Reseal auch keines entfernt
    haben.
    """
    import plistlib

    quelle = plistlib.loads(
        (_REPO / "frontend/src-tauri/Entitlements.plist").read_bytes())
    assert ADDRESSBOOK not in quelle
    assert quelle.get(SANDBOX) is False


def test_usage_description_ueberlebt_den_reseal():
    """Der Reseal fasst die eingebettete Info.plist nicht an."""
    proc = subprocess.run(["/usr/bin/otool", "-P", str(_sidecar())],
                          capture_output=True, text=True, timeout=60)
    assert "NSContactsUsageDescription" in proc.stdout
    assert _info_plist(_erforderlich()).get("NSContactsUsageDescription")


def test_signatur_bleibt_zertifikatsgebunden_nach_dem_reseal():
    for ziel in (_erforderlich(), _sidecar()):
        dr = _codesign("-d", "-r-", str(ziel))
        assert "certificate leaf" in dr, ziel
        assert "cdhash" not in dr, ziel
