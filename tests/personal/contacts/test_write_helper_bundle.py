"""Der opferbare Schreibhelfer im Bundle: Signatur-, Entitlement- und TCC-Kette.

**Kontaktfrei.** Geprüft wird ausschliesslich das gebaute Artefakt — kein
Store-Zugriff, kein TCC-Dialog, kein Start des Helfers mit einer echten
Order. Fehlt das Bundle, wird übersprungen (der Gate-Lauf baut vorher).

Warum diese Kette so pedantisch geprüft wird: Der Helfer erbt die
TCC-Verantwortung von der GUI, die ihn startet. Damit die einmal erteilte
Berechtigung Neubauten überlebt, muss seine Signatur **zertifikatsgebunden**
sein (cdhash-gebunden wäre nach jedem Build eine neue Identität), und damit
er gegenüber dem System als das auftritt, was er ist, trägt er einen eigenen
Identifier und genau ein Entitlement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_BUNDLE = (_REPO / "frontend/src-tauri/target/x86_64-apple-darwin/release"
           / "bundle/macos/Jarvis.app")
_HELPER = _BUNDLE / "Contents/MacOS/contacts-write-helper"

pytestmark = pytest.mark.skipif(
    not _HELPER.is_file(),
    reason="Bundle mit Schreibhelfer nicht gebaut (npm run tauri build)")


def _codesign(*args: str) -> str:
    proc = subprocess.run(["/usr/bin/codesign", *args],
                          capture_output=True, text=True, timeout=60)
    return proc.stdout + proc.stderr


# ═══ A · Artefakt ═══════════════════════════════════════════════════════════
def test_der_helfer_ist_ein_natives_x86_64_binary():
    ausgabe = subprocess.run(["/usr/bin/file", str(_HELPER)],
                             capture_output=True, text=True).stdout
    assert "Mach-O 64-bit executable x86_64" in ausgabe


def test_der_helfer_traegt_seinen_eigenen_identifier():
    ausgabe = _codesign("-dvvv", str(_HELPER))
    assert "Identifier=de.kluender.jarvis.contacts-write-helper" in ausgabe
    assert "Spike" not in ausgabe


def test_die_signatur_ist_zertifikatsgebunden_nicht_cdhash():
    ausgabe = _codesign("-d", "-r-", str(_HELPER))
    assert "certificate leaf" in ausgabe
    assert 'identifier "de.kluender.jarvis.contacts-write-helper"' in ausgabe
    assert "cdhash" not in ausgabe


def test_der_helfer_hat_hardened_runtime():
    assert "runtime" in _codesign("-dvvv", str(_HELPER))


def test_genau_ein_entitlement_das_adressbuch():
    ausgabe = _codesign("-d", "--entitlements", "-", str(_HELPER))
    assert "com.apple.security.personal-information.addressbook" in ausgabe
    # Keine der App-Lockerungen — ein kleiner Einmalprozess braucht sie nicht.
    for verboten in ("allow-jit", "allow-unsigned-executable-memory",
                     "disable-library-validation", "network.server"):
        assert verboten not in ausgabe, verboten


def test_helfer_und_app_teilen_das_zertifikatsblatt():
    """Gleiches Blatt = gleiche Signaturkette = die TCC-Vererbung trägt."""
    helfer = _codesign("-d", "-r-", str(_HELPER))
    app = _codesign("-d", "-r-", str(_BUNDLE))
    blatt = lambda s: s.split("certificate leaf = ")[1].split()[0]  # noqa: E731
    assert blatt(helfer) == blatt(app)


def test_die_aeussere_signatur_versiegelt_den_helfer():
    ausgabe = _codesign("--verify", "--deep", "--strict", str(_BUNDLE))
    assert "invalid" not in ausgabe.lower()


# ═══ B · Grenzen ════════════════════════════════════════════════════════════
def test_der_sidecar_bleibt_ohne_schreibfaehigkeit():
    quelle = (_REPO / "native/contacts-bridge/src/sidecar.swift").read_text(
        encoding="utf-8")
    for flag in ("createImplemented", "updateImplemented",
                 "deleteImplemented", "mutationsImplemented"):
        assert f'"{flag}": false' in quelle, flag


def test_die_gui_startet_den_helfer_und_forkt_nie():
    quelle = (_REPO / "frontend/src-tauri/src/contacts_create.rs").read_text(
        encoding="utf-8")
    code = "\n".join(z for z in quelle.splitlines()
                     if not z.lstrip().startswith("//"))
    assert "Command::new(helper)" in code
    assert "fork(" not in code


def test_kein_in_prozess_save_mehr_im_dispatch():
    """Der widerlegte Zustand darf nicht als Fallback zurückkehren."""
    quelle = (_REPO / "frontend/src-tauri/src/contacts_execution.rs").read_text(
        encoding="utf-8")
    code = "\n".join(z for z in quelle.splitlines()
                     if not z.lstrip().startswith("//"))
    assert "fuehre_im_helfer_aus" in code
    # Die direkten Ausfuehrungen gehoeren dem Helfer-Binary, nicht der GUI.
    for direkt in ("fuehre_create_aus", "fuehre_update_aus",
                   "fuehre_delete_aus"):
        assert direkt not in code, f"{direkt} wird noch in der GUI gerufen"


def test_der_helfer_liest_genau_eine_order():
    quelle = (_REPO / "frontend/src-tauri/src/bin/contacts_write_helper.rs"
              ).read_text(encoding="utf-8")
    code = "\n".join(z for z in quelle.splitlines()
                     if not z.lstrip().startswith("//"))
    assert "read_to_string" in code
    for verboten in ("loop", "while", "retry"):
        assert verboten not in code, verboten


def test_der_marker_steht_unmittelbar_vor_der_uebergabe():
    quelle = (_REPO / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
        encoding="utf-8")
    # In beiden Abläufen: PrepareDiag → Marker → Save, nichts dazwischen.
    assert quelle.count("JCCreateWriteSaveMarker(") == 3  # Definition + 2 Aufrufe
    fuer_create = quelle.index('JCCreateWriteSaveMarker("create")')
    save_create = quelle.index("ops.save(neu, containerIdentifier")
    assert fuer_create < save_create


def test_das_diagnoseverzeichnis_wird_mit_0700_angelegt():
    quelle = (_REPO / "frontend/src-tauri/src/contacts_create.rs").read_text(
        encoding="utf-8")
    assert 'join("diagnostics")' in quelle
    assert "from_mode(0o700)" in quelle


def test_der_marker_ist_pii_frei():
    """Der Markerinhalt nennt Phase und Operation — sonst nichts."""
    quelle = (_REPO / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
        encoding="utf-8")
    start = quelle.index("static void JCCreateWriteSaveMarker")
    # Nur der Funktionskoerper — bis zur ersten schliessenden Klammer am
    # Zeilenanfang, sonst prueft das Fenster die Nachbarfunktion mit.
    ende = quelle.index(chr(10) + '}', start)
    block = quelle[start:ende]
    assert '\\"phase\\"' in block and '\\"operation\\"' in block
    for verboten in ("givenName", "identifier", "payload", "email"):
        assert verboten not in block, verboten


# ═══ C · Warmlauf der Persistenz-Stores (Beleg: Helfer-Spike 2026-08-04) ════
def _shim() -> str:
    return (_REPO / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
        encoding="utf-8")


def test_es_gibt_genau_einen_warmlauf_und_er_liest_wirklich():
    """Zwei echte Lesevorgänge — kein Fetch auf eine erfundene Kennung.

    Der frühere Preflight suchte `JC-CREATE-PROBE-<uuid>`; ein solcher Fetch
    findet nichts und hängt die Stores offenbar nicht an. Der Save starb
    danach mit `no persistent stores`.
    """
    code = _shim()
    assert code.count("static BOOL JCCreateWarmUpStores") == 1
    start = code.index("static BOOL JCCreateWarmUpStores")
    block = code[start:code.index("\n}", start)]
    assert "containersMatchingPredicate:nil" in block
    assert "predicateForContactsInContainerWithIdentifier" in block
    assert "enumerateContactsWithFetchRequest" in block
    # Die Attrappen-Kennung ist verschwunden.
    assert "JC-CREATE-PROBE-" not in code


def test_der_warmlauf_steht_vor_jedem_save():
    code = _shim()
    # Create: probeFetch ruft den Warmlauf, und der Ablauf prüft ihn vor dem Save.
    assert "return JCCreateWarmUpStores(store, zielcontainer, error);" in code
    vorher = code.index("ops.probeFetch(&error)")
    speichern = code.index("ops.save(neu, containerIdentifier")
    assert vorher < speichern
    # Update/Delete: der Warmlauf sitzt im Zielabruf, der vor dem Save läuft.
    ziel = code.index("ops.fetchTarget = ^CNContact")
    assert "JCCreateWarmUpStores(store, nil, &warm)" in code[ziel:ziel + 600]


def test_ein_gescheiterter_warmlauf_verhindert_den_save():
    code = _shim()
    # Create: der Ablauf endet bei ReadPreflightFailed, bevor irgendetwas geht.
    assert "JCContactsCreateOutcomeReadPreflightFailed" in code
    # Update/Delete: nicht lesbar heisst nicht schreibbar.
    ziel = code.index("ops.fetchTarget = ^CNContact")
    fenster = code[ziel:ziel + 600]
    assert "*lesbar = NO;" in fenster
