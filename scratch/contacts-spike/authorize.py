#!/usr/bin/env python3
"""authorize.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

EINZIGER vorgesehener Weg, den ersten TCC-Kontakte-Dialog auszulösen.

Hintergrund (Live-Befund 2026-07-27, macOS 12.7.6 Intel):
Eine normale Store-Operation wie `containers` löst bei `notDetermined` KEINEN
TCC-Dialog aus — der Sidecar scheitert vorher am eigenen `requireAuth`-Gate mit
`tcc_denied`. Der Dialog entsteht ausschließlich durch einen ausdrücklichen
`CNContactStore.requestAccess(for:)`-Aufruf, den der Sidecar über die
SPIKE-ONLY-Operation `requestAuthorization` anbietet.

SICHERHEIT (fail-closed in jeder Stufe):
  * Läuft ausschließlich im Testbenutzer `jarvisspike`.
  * Verwendet ausschließlich den signierten Sidecar unter dem festen Pfad
    <HANDOFF>/tools/jarvis-contacts — kein Symlink, keine Kopie in ein
    beschreibbares Verzeichnis.
  * Prüft vor dem Start die vollständige Binär-Identität: Manifest-Hash,
    Codesigning, exakte Designated Requirement, Authority, Hardened Runtime,
    Abwesenheit von Entitlements, eingebettete Identität, Architektur und
    Mindestversion.
  * Prüft nach dem Start erneut Pfad, Dateityp und SHA-256 (TOCTOU).
  * Setzt JARVIS_CONTACTS_SPIKE_TCC=1 NUR für den Child-Prozess.
  * Verlangt vor der Anforderung eine wörtliche manuelle Bestätigung.
  * Sendet ausschließlich `caps`, `requestAuthorization` und `shutdown` —
    keine Kontaktoperation.
  * Exitcode 0 nur bei granted:true UND authorizationStatus:authorized.

Nur Python-Standardbibliothek und macOS-Systemwerkzeuge.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat as statmod
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Sidecar  # noqa: E402

EXPECTED_USER = "jarvisspike"
HANDOFF_ROOT = Path("/Users/Shared/JarvisContactsSpike")
SIDECAR_PATH = HANDOFF_ROOT / "tools" / "jarvis-contacts"
MANIFEST_PATH = HANDOFF_ROOT / "SHA256SUMS.txt"
MANIFEST_KEY = "./tools/jarvis-contacts"
CONFIRM_PHRASE = "AUTHORIZE CONTACTS SPIKE"

# Erwartete Binär-Identität — exakt, nicht als Teilstring-Heuristik.
EXPECTED_DR = ('identifier "de.jarvis.contacts-spike.sidecar" '
               'and certificate leaf = '
               'H"f378c267e1c065e3dbfc07acb7b922c10651255c"')
EXPECTED_BUNDLE_ID = "de.jarvis.contacts-spike.sidecar"
EXPECTED_USAGE = "Spike-Test: Zugriff auf Kontakte (SIDECAR)"
EXPECTED_AUTHORITY = "Personal Jarvis Contacts Spike"
EXPECTED_ARCH = "x86_64"
EXPECTED_MINOS = "12.3"

# Operationen, die dieser Helper unter keinen Umständen sendet.
FORBIDDEN_OPS = ("containers", "enumerate", "changes", "token", "get",
                 "getUnified", "create", "update", "updateViaUnified", "delete")


class CheckError(Exception):
    """Fail-closed-Abbruchgrund einer Identitätsprüfung."""


def abort(msg: str, code: int = 2) -> None:
    print(f"\nABBRUCH: {msg}", file=sys.stderr)
    print("Der Sidecar wurde nicht gestartet bzw. beendet; es wurde keine "
          "Autorisierung angefordert.", file=sys.stderr)
    print("Es wurde kein Kontakt gelesen oder veraendert.", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_dr(text: str) -> str:
    """DR-Zeile aus `codesign -d -r-` auf eine vergleichbare Form bringen."""
    for raw in text.splitlines():
        line = raw.strip().lstrip("#").strip()
        if line.startswith("designated"):
            _, _, rhs = line.partition("=>")
            return re.sub(r"\s+", " ", rhs.strip())
    raise CheckError("Keine 'designated'-Zeile in der codesign-Ausgabe gefunden.")


# ── A. Datei und Manifest ────────────────────────────────────────────────────
def check_path_and_manifest() -> str:
    if not SIDECAR_PATH.exists():
        raise CheckError(f"Sidecar fehlt: {SIDECAR_PATH}")
    # Kein Symlink — weder die Datei selbst noch ein Bestandteil des Pfades.
    if SIDECAR_PATH.is_symlink():
        raise CheckError(f"Sidecar ist ein Symlink: {SIDECAR_PATH}")
    if SIDECAR_PATH.resolve() != SIDECAR_PATH:
        raise CheckError(f"Pfad enthaelt einen Symlink: {SIDECAR_PATH} -> "
                         f"{SIDECAR_PATH.resolve()}")
    st = SIDECAR_PATH.lstat()
    if not statmod.S_ISREG(st.st_mode):
        raise CheckError("Sidecar ist keine regulaere Datei.")

    if not MANIFEST_PATH.is_file():
        raise CheckError(f"Manifest fehlt: {MANIFEST_PATH}")
    entries = []
    for raw in MANIFEST_PATH.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0], parts[1].strip()
        if name == MANIFEST_KEY:
            entries.append(digest.lower())
    if not entries:
        raise CheckError(f"Kein Manifest-Eintrag fuer '{MANIFEST_KEY}' in "
                         f"{MANIFEST_PATH}.")
    if len(entries) > 1:
        raise CheckError(f"Mehrdeutiger Manifest-Eintrag fuer '{MANIFEST_KEY}': "
                         f"{len(entries)} Zeilen gefunden.")
    expected = entries[0]
    if len(expected) != 64 or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise CheckError(f"Manifest-Eintrag ist kein gueltiger SHA-256: {expected}")

    actual = sha256_of(SIDECAR_PATH)
    if actual != expected:
        raise CheckError("SHA-256 weicht vom Manifest ab.\n"
                         f"  Manifest: {expected}\n  Datei   : {actual}")
    print(f"  [A] Pfad/Manifest  : OK (sha256 {actual[:16]}...)")
    return actual


# ── B. Codesigning ───────────────────────────────────────────────────────────
def check_codesign() -> None:
    v = run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=4",
             str(SIDECAR_PATH)])
    if v.returncode != 0:
        raise CheckError(f"codesign --verify fehlgeschlagen:\n{v.stderr.strip()}")

    d = run(["/usr/bin/codesign", "-d", "-r-", str(SIDECAR_PATH)])
    dr = normalize_dr(d.stdout + d.stderr)
    if dr != EXPECTED_DR:
        raise CheckError("Designated Requirement weicht ab.\n"
                         f"  erwartet: {EXPECTED_DR}\n  gefunden: {dr}")

    info = run(["/usr/bin/codesign", "-d", "--verbose=4", str(SIDECAR_PATH)])
    blob = info.stdout + info.stderr
    flags = ""
    authority = ""
    for raw in blob.splitlines():
        line = raw.strip()
        if line.startswith("CodeDirectory") and "flags=" in line:
            flags = line.split("flags=", 1)[1].split(" ", 1)[0]
        elif line.startswith("Authority=") and not authority:
            authority = line.split("=", 1)[1].strip()
        elif line.startswith("Signature=") and "adhoc" in line:
            raise CheckError("Ad-hoc-Signatur ist unzulaessig.")
    if "adhoc" in flags:
        raise CheckError(f"Ad-hoc-Signatur ist unzulaessig (flags={flags}).")
    if "runtime" not in flags:
        raise CheckError(f"Hardened Runtime fehlt (flags={flags or 'unbekannt'}).")
    if authority != EXPECTED_AUTHORITY:
        raise CheckError("Signierende Instanz weicht ab.\n"
                         f"  erwartet: {EXPECTED_AUTHORITY}\n"
                         f"  gefunden: {authority or '(keine)'}")

    ent = run(["/usr/bin/codesign", "-d", "--entitlements", "-",
               str(SIDECAR_PATH)])
    ent_blob = ent.stdout + ent.stderr
    if "<key>" in ent_blob or "[Key]" in ent_blob:
        raise CheckError("Sidecar besitzt Entitlements — unzulaessig.")
    print(f"  [B] Codesigning    : OK ({flags}, Authority {authority})")
    print(f"      DR             : {dr}")


# ── C. Eingebettete Identität ────────────────────────────────────────────────
def _plist_string_after(blob: str, key: str) -> str | None:
    m = re.search(rf"<key>{re.escape(key)}</key>\s*<string>(.*?)</string>",
                  blob, re.S)
    return m.group(1) if m else None


def check_embedded_identity() -> None:
    p = run(["/usr/bin/otool", "-P", str(SIDECAR_PATH)])
    blob = p.stdout + p.stderr
    bundle_id = _plist_string_after(blob, "CFBundleIdentifier")
    usage = _plist_string_after(blob, "NSContactsUsageDescription")
    if bundle_id != EXPECTED_BUNDLE_ID:
        raise CheckError("CFBundleIdentifier weicht ab.\n"
                         f"  erwartet: {EXPECTED_BUNDLE_ID}\n"
                         f"  gefunden: {bundle_id!r}")
    if usage != EXPECTED_USAGE:
        raise CheckError("NSContactsUsageDescription weicht ab.\n"
                         f"  erwartet: {EXPECTED_USAGE}\n"
                         f"  gefunden: {usage!r}")
    print(f"  [C] Identitaet     : OK ({bundle_id})")
    print(f"      Usage-String   : {usage}")


# ── D. Native Plattform ──────────────────────────────────────────────────────
def check_platform() -> None:
    l = run(["/usr/bin/lipo", "-info", str(SIDECAR_PATH)])
    out = (l.stdout + l.stderr).strip()
    if "are:" in out:                     # Fat/Universal-Binary
        raise CheckError(f"Universal-Binary ist bei diesem Intel-Abnahmelauf "
                         f"unzulaessig: {out}")
    m = re.search(r"architecture:\s*(\S+)", out)
    arch = m.group(1) if m else "?"
    if arch != EXPECTED_ARCH:
        raise CheckError(f"Architektur weicht ab: erwartet {EXPECTED_ARCH}, "
                         f"gefunden {arch}")

    o = run(["/usr/bin/otool", "-l", str(SIDECAR_PATH)])
    minos = None
    lines = (o.stdout + o.stderr).splitlines()
    for i, raw in enumerate(lines):
        if "LC_BUILD_VERSION" in raw:
            for follow in lines[i:i + 6]:
                mm = re.search(r"\bminos\s+(\S+)", follow)
                if mm:
                    minos = mm.group(1)
                    break
        if minos:
            break
    if minos != EXPECTED_MINOS:
        raise CheckError(f"Mindestversion weicht ab: erwartet minos "
                         f"{EXPECTED_MINOS}, gefunden {minos!r}")
    print(f"  [D] Plattform      : OK ({arch}, minos {minos})")


def verify_identity() -> str:
    """Alle Identitaetspruefungen. Gibt den verifizierten SHA-256 zurueck."""
    digest = check_path_and_manifest()
    check_codesign()
    check_embedded_identity()
    check_platform()
    return digest


def current_user() -> str:
    r = run(["/usr/bin/whoami"])
    if r.returncode != 0:
        abort(f"whoami nicht ausfuehrbar: {r.stderr.strip()}")
    return r.stdout.strip()


def main() -> int:
    print("=== Kontakte-Spike: ausdrueckliche Autorisierungsanforderung ===\n")

    # ── 1) Benutzer — vor jeder Datei- oder Prozessaktion ────────────────────
    user = current_user()
    print(f"  Benutzer           : {user}")
    if user != EXPECTED_USER:
        abort(f"Dieser Helper laeuft ausschliesslich als '{EXPECTED_USER}', "
              f"nicht als '{user}'.")
    if not HANDOFF_ROOT.is_dir():
        abort(f"Uebergabeverzeichnis fehlt: {HANDOFF_ROOT}")
    print(f"  Sidecar            : {SIDECAR_PATH}\n")

    # ── 2) Vollstaendige Binaer-Identitaet (fail-closed) ─────────────────────
    print("  --- Identitaetspruefung vor dem Start ---")
    try:
        digest_before = verify_identity()
    except CheckError as e:
        abort(f"Identitaetspruefung fehlgeschlagen.\n{e}")
        raise

    # ── 3) TOCTOU: unmittelbar nach der Pruefung starten ─────────────────────
    child_env = {**os.environ, "JARVIS_CONTACTS_SPIKE_TCC": "1"}
    sc = Sidecar(binary=SIDECAR_PATH, env=child_env)
    ready = sc.start()

    granted = None
    status_after = None
    try:
        # Erneute Pruefung nach dem Start, noch vor jeder Anforderung.
        try:
            if SIDECAR_PATH.is_symlink() or SIDECAR_PATH.resolve() != SIDECAR_PATH:
                raise CheckError("Pfad wurde nach dem Start zu einem Symlink.")
            if not SIDECAR_PATH.is_file():
                raise CheckError("Pfad ist nach dem Start keine regulaere Datei.")
            digest_after = sha256_of(SIDECAR_PATH)
            if digest_after != digest_before:
                raise CheckError("SHA-256 hat sich nach dem Start geaendert.\n"
                                 f"  vorher : {digest_before}\n"
                                 f"  nachher: {digest_after}")
        except CheckError as e:
            sc.shutdown()
            abort(f"TOCTOU-Pruefung fehlgeschlagen.\n{e}")
        print("  [T] TOCTOU-Recheck : OK (Pfad, Dateityp und sha256 unveraendert)")

        if ready.get("protocol") != 1:
            sc.shutdown()
            abort(f"Unerwartete Protokollversion: {ready.get('protocol')}")
        status_before = ready.get("authorizationStatus")
        print(f"\n  Protokoll          : {ready.get('protocol')}")
        print(f"  Status vorher      : {status_before}")

        # ── 4) caps (kein Store-Zugriff) ─────────────────────────────────────
        r = sc.request("caps")
        if not r.get("ok"):
            sc.shutdown()
            abort(f"caps fehlgeschlagen: {json.dumps(r.get('error', {}))}")
        caps = r["result"]
        if caps.get("requestAuthorizationSupported") is not True:
            sc.shutdown()
            abort("Dieser Sidecar unterstuetzt requestAuthorization nicht "
                  "(veralteter Build).")
        if caps.get("requestAuthorizationEnabled") is not True:
            sc.shutdown()
            abort("requestAuthorization ist nicht freigeschaltet — das Env-Gate "
                  "JARVIS_CONTACTS_SPIKE_TCC=1 hat den Child-Prozess nicht erreicht.")
        print("  requestAuthorization: unterstuetzt und freigeschaltet")

        if status_before == "authorized":
            print("\nKontakte-Zugriff ist bereits erteilt. Keine Anforderung noetig.")
            sc.shutdown()
            return 0
        if status_before in ("denied", "restricted"):
            sc.shutdown()
            abort(f"Status ist '{status_before}'. Ein erneuter Dialog ist nicht "
                  "moeglich; die Entscheidung muss in den Systemeinstellungen "
                  "geaendert werden.", code=3)
        if status_before != "notDetermined":
            sc.shutdown()
            abort(f"Unerwarteter Status '{status_before}'.")

        # ── 5) Manueller Haltepunkt ──────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  MANUELLER HALTEPUNKT — bewusste Benutzeraktion erforderlich")
        print("=" * 70)
        print("""
Im naechsten Schritt wird EINMALIG die Kontakte-Autorisierung angefordert.
macOS zeigt daraufhin einen Berechtigungsdialog.

  * 'Erlauben' NUR waehlen, wenn der Dialogtext exakt lautet:

        Spike-Test: Zugriff auf Kontakte (SIDECAR)

  * Zeigt der Dialog stattdessen '... (APP)', einen anderen Text
    oder erscheint gar kein Dialog: NICHTS bestaetigen, Vorgang
    abbrechen und den Befund melden.

  * Voraussetzung: Kontakte.app in DIESEM Testbenutzer ist leer.

Zum Fortfahren die folgende Zeile exakt eingeben (oder Enter zum Abbrechen):
""")
        print(f"    {CONFIRM_PHRASE}\n")
        try:
            entered = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            sc.shutdown()
            abort("Abgebrochen (keine Eingabe).", code=1)
            raise
        if entered != CONFIRM_PHRASE:
            sc.shutdown()
            abort("Bestaetigung stimmt nicht exakt ueberein. "
                  "Es wurde keine Autorisierung angefordert.", code=1)

        # ── 6) Genau eine Anforderung ────────────────────────────────────────
        print("\nAnforderung laeuft — bitte den Dialog beantworten ...")
        r = sc.request("requestAuthorization", timeout=180)
        if not r.get("ok"):
            err = r.get("error", {})
            abort(f"requestAuthorization fehlgeschlagen: "
                  f"{err.get('code')} — {err.get('message')}")
        res = r["result"]
        granted = res.get("granted")
        status_after = res.get("authorizationStatus")
        print("\n=== Ergebnis ===")
        print(f"  granted            : {granted}")
        print(f"  authorizationStatus: {status_after}")
        print(f"  promptAttempted    : {res.get('promptAttempted')}")
    finally:
        sc.shutdown()

    # ── 7) Fail-closed-Bewertung ─────────────────────────────────────────────
    if granted is True and status_after == "authorized":
        print("\nERFOLG: Kontakte-Autorisierung erteilt.")
        print("Naechster Schritt: python3 phase_b.py")
        return 0
    print("\nFEHLGESCHLAGEN: Autorisierung wurde nicht erteilt.", file=sys.stderr)
    print("Es wurde kein Kontakt gelesen oder veraendert. "
          "phase_b.py NICHT starten.", file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
