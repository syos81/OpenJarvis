#!/usr/bin/env python3
"""authorize.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

EINZIGER vorgesehener Weg, den ersten TCC-Kontakte-Dialog auszulösen.

Hintergrund (Live-Befund 2026-07-27):
Eine normale Store-Operation wie `containers` löst bei `notDetermined` KEINEN
TCC-Dialog aus — der Sidecar scheitert vorher am eigenen `requireAuth`-Gate mit
`tcc_denied`. Der Dialog entsteht ausschließlich durch einen ausdrücklichen
`CNContactStore.requestAccess(for:)`-Aufruf, den der Sidecar über die
SPIKE-ONLY-Operation `requestAuthorization` anbietet.

PLATTFORMNEUTRALITÄT (2026-07-28):
Architektur und Zertifikats-Leaf sind NICHT mehr im Code verdrahtet. Sie stammen
aus einem lokalen, schreibgeschützten Plattformprofil:

    <HANDOFF>/tools/authorization-profile.json

Das Profil wird bei der administrativen Paketbereitstellung aus bereits
unabhängig geprüften Build- und Signaturwerten erzeugt. Es wird bewusst NICHT
aus dem zu prüfenden Sidecar abgeleitet — das wäre eine zirkuläre
Identitätsprüfung, die jede manipulierte Binärdatei bestätigen würde.

Der Python-Code ist auf arm64 und x86_64 identisch; nur das Profil unterscheidet
sich lokal.

SICHERHEIT (fail-closed in jeder Stufe):
  * Läuft ausschließlich im Testbenutzer `jarvisspike`.
  * Im Live-Betrieb ausschließlich feste Pfade — WEDER CLI-Argumente NOCH
    Umgebungsvariablen können Profilpfad oder Erwartungswerte einschleusen.
  * Prüft zuerst das Profil selbst (Pfad, Symlinks, Eigentümer, Schreibrechte,
    Manifest-Hash, Schema, Wertebereiche, rekonstruierte DR).
  * Prüft danach den Sidecar exakt gegen die Profilwerte.
  * Prüft nach dem Start erneut Pfad, Dateityp, Sidecar- und Profil-SHA-256
    (TOCTOU) und beendet den Child bei jeder Abweichung sofort.
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
import platform
import pwd
import re
import stat as statmod
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Sidecar  # noqa: E402

# ── Feste Live-Pfade (nicht überschreibbar) ──────────────────────────────────
EXPECTED_USER = "jarvisspike"
HANDOFF_ROOT = Path("/Users/Shared/JarvisContactsSpike")
PROFILE_RELPATH = "tools/authorization-profile.json"
MANIFEST_RELPATH = "SHA256SUMS.txt"
CONFIRM_PHRASE = "AUTHORIZE CONTACTS SPIKE"

# ── Invarianten des Spikes (bewusst NICHT plattformabhängig) ─────────────────
EXPECTED_SCHEMA_VERSION = 1
EXPECTED_PLATFORM = "macOS"
EXPECTED_MINIMUM_SYSTEM_VERSION = "12.3"
EXPECTED_SIDECAR_RELPATH = "tools/jarvis-contacts"
ALLOWED_ARCHITECTURES = ("arm64", "x86_64")

# Genau diese Felder — nicht mehr und nicht weniger. Unbekannte Felder gelten
# als sicherheitsrelevanter Override und führen zum Abbruch.
PROFILE_FIELDS = frozenset({
    "schemaVersion", "platform", "architecture", "minimumSystemVersion",
    "sidecarRelativePath", "bundleIdentifier", "usageDescription",
    "signingAuthority", "certificateLeafSha1", "designatedRequirement",
    "hardenedRuntimeRequired", "entitlementsRequiredEmpty",
})

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


def reconstruct_dr(bundle_id: str, leaf_sha1: str) -> str:
    """Erwartete DR ausschließlich aus Profilwerten aufbauen."""
    return f'identifier "{bundle_id}" and certificate leaf = H"{leaf_sha1}"'


def manifest_digest(manifest_path: Path, key: str) -> str:
    """Genau einen SHA-256-Eintrag zu `key` aus dem Manifest lesen."""
    if not manifest_path.is_file():
        raise CheckError(f"Manifest fehlt: {manifest_path}")
    entries = []
    for raw in manifest_path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0], parts[1].strip()
        if name == key:
            entries.append(digest.lower())
    if not entries:
        raise CheckError(f"Kein Manifest-Eintrag fuer '{key}' in {manifest_path}.")
    if len(entries) > 1:
        raise CheckError(f"Mehrdeutiger Manifest-Eintrag fuer '{key}': "
                         f"{len(entries)} Zeilen gefunden.")
    expected = entries[0]
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise CheckError(f"Manifest-Eintrag ist kein gueltiger SHA-256: {expected}")
    return expected


def assert_no_symlink(root: Path, relative: str) -> Path:
    """Datei und jedes Pfadelement unterhalb von `root` duerfen keine Symlinks sein."""
    target = root / relative
    if target.is_symlink():
        raise CheckError(f"Ist ein Symlink: {target}")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise CheckError(f"Pfadelement ist ein Symlink: {current}")
    if not target.exists():
        raise CheckError(f"Datei fehlt: {target}")
    if not statmod.S_ISREG(target.lstat().st_mode):
        raise CheckError(f"Keine regulaere Datei: {target}")
    return target


def _uid_of(user: str) -> int | None:
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError:
        return None


def assert_not_writable_by_testuser(path: Path, user: str = EXPECTED_USER) -> None:
    """Weder Eigentum des Testbenutzers noch Schreibrecht fuer ihn/Gruppe/andere."""
    st = path.lstat()
    uid = _uid_of(user)
    if uid is not None and st.st_uid == uid:
        raise CheckError(f"Datei gehoert dem Testbenutzer '{user}': {path}")
    if st.st_mode & (statmod.S_IWGRP | statmod.S_IWOTH):
        raise CheckError(f"Datei ist fuer Gruppe/andere beschreibbar "
                         f"(mode {oct(st.st_mode & 0o777)}): {path}")
    acl = run(["/bin/ls", "-le", str(path)])
    for line in (acl.stdout + acl.stderr).splitlines():
        low = line.lower()
        if f"user:{user}".lower() in low and "allow" in low:
            for verb in ("write", "append", "delete", "writeattr", "writeextattr"):
                if verb in low:
                    raise CheckError(f"ACL gewaehrt '{user}' Schreibrecht: "
                                     f"{line.strip()}")


# ── A. Plattformprofil laden und absichern ───────────────────────────────────
def load_profile(root: Path = HANDOFF_ROOT, *, user: str = EXPECTED_USER,
                 quiet: bool = False) -> tuple[dict, str]:
    """Profil validieren. Gibt (Profil, Profil-SHA-256) zurueck. Fail-closed."""
    profile_path = assert_no_symlink(root, PROFILE_RELPATH)
    assert_not_writable_by_testuser(profile_path, user)

    expected = manifest_digest(root / MANIFEST_RELPATH, f"./{PROFILE_RELPATH}")
    actual = sha256_of(profile_path)
    if actual != expected:
        raise CheckError("Profil-SHA-256 weicht vom Manifest ab.\n"
                         f"  Manifest: {expected}\n  Datei   : {actual}")

    try:
        profile = json.loads(profile_path.read_text())
    except json.JSONDecodeError as e:
        raise CheckError(f"Profil ist kein gueltiges JSON: {e}") from None
    if not isinstance(profile, dict):
        raise CheckError("Profil ist kein JSON-Objekt.")

    present = set(profile)
    missing = PROFILE_FIELDS - present
    unknown = present - PROFILE_FIELDS
    if missing:
        raise CheckError(f"Profil unvollstaendig, fehlende Felder: "
                         f"{sorted(missing)}")
    if unknown:
        raise CheckError(f"Profil enthaelt unbekannte (potenziell "
                         f"sicherheitsrelevante) Felder: {sorted(unknown)}")

    if profile["schemaVersion"] != EXPECTED_SCHEMA_VERSION:
        raise CheckError(f"schemaVersion muss exakt "
                         f"{EXPECTED_SCHEMA_VERSION} sein, ist "
                         f"{profile['schemaVersion']!r}.")
    if profile["platform"] != EXPECTED_PLATFORM:
        raise CheckError(f"platform muss exakt {EXPECTED_PLATFORM!r} sein, "
                         f"ist {profile['platform']!r}.")

    arch = profile["architecture"]
    if arch not in ALLOWED_ARCHITECTURES:
        raise CheckError(f"architecture {arch!r} ist unzulaessig "
                         f"(erlaubt: {list(ALLOWED_ARCHITECTURES)}).")
    host = platform.machine()
    if host != arch:
        raise CheckError(f"Host-Architektur {host!r} passt nicht zum Profil "
                         f"({arch!r}). Falsches Paket auf diesem Geraet.")

    if profile["minimumSystemVersion"] != EXPECTED_MINIMUM_SYSTEM_VERSION:
        raise CheckError(f"minimumSystemVersion muss exakt "
                         f"{EXPECTED_MINIMUM_SYSTEM_VERSION!r} sein, ist "
                         f"{profile['minimumSystemVersion']!r}.")

    rel = profile["sidecarRelativePath"]
    if not isinstance(rel, str) or not rel:
        raise CheckError("sidecarRelativePath fehlt oder ist leer.")
    if rel.startswith("/") or Path(rel).is_absolute():
        raise CheckError(f"sidecarRelativePath darf nicht absolut sein: {rel!r}")
    if ".." in Path(rel).parts:
        raise CheckError(f"sidecarRelativePath darf kein '..' enthalten: {rel!r}")
    if rel != EXPECTED_SIDECAR_RELPATH:
        raise CheckError(f"sidecarRelativePath muss exakt "
                         f"{EXPECTED_SIDECAR_RELPATH!r} sein, ist {rel!r}.")

    leaf = profile["certificateLeafSha1"]
    if not isinstance(leaf, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", leaf):
        raise CheckError("certificateLeafSha1 muss exakt 40 hexadezimale "
                         f"Zeichen haben, ist {leaf!r}.")

    for key in ("bundleIdentifier", "usageDescription", "signingAuthority"):
        if not isinstance(profile[key], str) or not profile[key]:
            raise CheckError(f"{key} fehlt oder ist leer.")
    for key in ("hardenedRuntimeRequired", "entitlementsRequiredEmpty"):
        if not isinstance(profile[key], bool):
            raise CheckError(f"{key} muss ein Boolescher Wert sein, ist "
                             f"{profile[key]!r}.")

    rebuilt = reconstruct_dr(profile["bundleIdentifier"], leaf.lower())
    if re.sub(r"\s+", " ", profile["designatedRequirement"].strip()) != rebuilt:
        raise CheckError("designatedRequirement ist nicht aus den Profilwerten "
                         "rekonstruierbar.\n"
                         f"  Profil     : {profile['designatedRequirement']}\n"
                         f"  rekonstruiert: {rebuilt}")

    if not quiet:
        print(f"  [P] Profil         : OK ({arch}, minos "
              f"{profile['minimumSystemVersion']}, sha256 {actual[:16]}...)")
        print(f"      Leaf           : {leaf.lower()}")
    return profile, actual


# ── B. Sidecar gegen das Profil pruefen ──────────────────────────────────────
def check_sidecar_manifest(root: Path, profile: dict, *,
                           quiet: bool = False) -> str:
    rel = profile["sidecarRelativePath"]
    path = assert_no_symlink(root, rel)
    expected = manifest_digest(root / MANIFEST_RELPATH, f"./{rel}")
    actual = sha256_of(path)
    if actual != expected:
        raise CheckError("Sidecar-SHA-256 weicht vom Manifest ab.\n"
                         f"  Manifest: {expected}\n  Datei   : {actual}")
    if not quiet:
        print(f"  [A] Pfad/Manifest  : OK (sha256 {actual[:16]}...)")
    return actual


def check_codesign(path: Path, profile: dict, *, runner=run,
                   quiet: bool = False) -> None:
    v = runner(["/usr/bin/codesign", "--verify", "--strict", "--verbose=4",
                str(path)])
    if v.returncode != 0:
        raise CheckError(f"codesign --verify fehlgeschlagen:\n{v.stderr.strip()}")

    d = runner(["/usr/bin/codesign", "-d", "-r-", str(path)])
    dr = normalize_dr(d.stdout + d.stderr)
    expected_dr = re.sub(r"\s+", " ", profile["designatedRequirement"].strip())
    if dr != expected_dr:
        raise CheckError("Designated Requirement weicht vom Profil ab.\n"
                         f"  Profil  : {expected_dr}\n  gefunden: {dr}")
    leaf = profile["certificateLeafSha1"].lower()
    if leaf not in dr.lower():
        raise CheckError(f"certificate leaf {leaf} kommt in der DR nicht vor.")

    info = runner(["/usr/bin/codesign", "-d", "--verbose=4", str(path)])
    blob = info.stdout + info.stderr
    flags, authority = "", ""
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
    if profile["hardenedRuntimeRequired"] and "runtime" not in flags:
        raise CheckError(f"Hardened Runtime fehlt (flags={flags or 'unbekannt'}).")
    if authority != profile["signingAuthority"]:
        raise CheckError("Signierende Instanz weicht vom Profil ab.\n"
                         f"  Profil  : {profile['signingAuthority']}\n"
                         f"  gefunden: {authority or '(keine)'}")

    if profile["entitlementsRequiredEmpty"]:
        ent = runner(["/usr/bin/codesign", "-d", "--entitlements", "-", str(path)])
        ent_blob = ent.stdout + ent.stderr
        if "<key>" in ent_blob or "[Key]" in ent_blob:
            raise CheckError("Sidecar besitzt Entitlements — unzulaessig.")
    if not quiet:
        print(f"  [B] Codesigning    : OK ({flags}, Authority {authority})")
        print(f"      DR             : {dr}")


def _plist_string_after(blob: str, key: str) -> str | None:
    m = re.search(rf"<key>{re.escape(key)}</key>\s*<string>(.*?)</string>",
                  blob, re.S)
    return m.group(1) if m else None


def check_embedded_identity(path: Path, profile: dict, *, runner=run,
                            quiet: bool = False) -> None:
    p = runner(["/usr/bin/otool", "-P", str(path)])
    blob = p.stdout + p.stderr
    bundle_id = _plist_string_after(blob, "CFBundleIdentifier")
    usage = _plist_string_after(blob, "NSContactsUsageDescription")
    if bundle_id != profile["bundleIdentifier"]:
        raise CheckError("CFBundleIdentifier weicht vom Profil ab.\n"
                         f"  Profil  : {profile['bundleIdentifier']}\n"
                         f"  gefunden: {bundle_id!r}")
    if usage != profile["usageDescription"]:
        raise CheckError("NSContactsUsageDescription weicht vom Profil ab.\n"
                         f"  Profil  : {profile['usageDescription']}\n"
                         f"  gefunden: {usage!r}")
    if not quiet:
        print(f"  [C] Identitaet     : OK ({bundle_id})")
        print(f"      Usage-String   : {usage}")


def check_platform(path: Path, profile: dict, *, runner=run,
                   quiet: bool = False) -> None:
    l = runner(["/usr/bin/lipo", "-info", str(path)])
    out = (l.stdout + l.stderr).strip()
    if "are:" in out:                       # Fat/Universal-Binary
        raise CheckError("Universal-Binary ist bei einem architekturspezifischen "
                         f"Abnahmelauf unzulaessig: {out}")
    m = re.search(r"architecture:\s*(\S+)", out)
    arch = m.group(1) if m else "?"
    if arch != profile["architecture"]:
        raise CheckError(f"Architektur weicht vom Profil ab: erwartet "
                         f"{profile['architecture']}, gefunden {arch}")

    o = runner(["/usr/bin/otool", "-l", str(path)])
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
    if minos != profile["minimumSystemVersion"]:
        raise CheckError(f"Mindestversion weicht vom Profil ab: erwartet minos "
                         f"{profile['minimumSystemVersion']}, gefunden {minos!r}")
    if not quiet:
        print(f"  [D] Plattform      : OK ({arch}, minos {minos})")


def verify_identity(root: Path, profile: dict, *, runner=run,
                    quiet: bool = False) -> str:
    """Alle Sidecar-Pruefungen gegen das Profil. Gibt den SHA-256 zurueck."""
    digest = check_sidecar_manifest(root, profile, quiet=quiet)
    path = root / profile["sidecarRelativePath"]
    check_codesign(path, profile, runner=runner, quiet=quiet)
    check_embedded_identity(path, profile, runner=runner, quiet=quiet)
    check_platform(path, profile, runner=runner, quiet=quiet)
    return digest


def preflight(root: Path = HANDOFF_ROOT, *, runner=run, user: str = EXPECTED_USER,
              quiet: bool = False) -> tuple[dict, str, str]:
    """Vollstaendige Vorpruefung OHNE jeden Sidecar-Start.

    Gibt (Profil, Profil-SHA-256, Sidecar-SHA-256) zurueck.
    """
    profile, profile_digest = load_profile(root, user=user, quiet=quiet)
    sidecar_digest = verify_identity(root, profile, runner=runner, quiet=quiet)
    return profile, profile_digest, sidecar_digest


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

    # ── 2) Profil und Binaer-Identitaet (fail-closed) ───────────────────────
    print("  --- Vorpruefung vor dem Start ---")
    try:
        profile, profile_digest_before, digest_before = preflight(HANDOFF_ROOT)
    except CheckError as e:
        abort(f"Vorpruefung fehlgeschlagen.\n{e}")
        raise
    sidecar_path = HANDOFF_ROOT / profile["sidecarRelativePath"]
    profile_path = HANDOFF_ROOT / PROFILE_RELPATH
    print(f"  Sidecar            : {sidecar_path}\n")

    # ── 3) TOCTOU: unmittelbar nach der Pruefung starten ─────────────────────
    child_env = {**os.environ, "JARVIS_CONTACTS_SPIKE_TCC": "1"}
    sc = Sidecar(binary=sidecar_path, env=child_env)
    ready = sc.start()

    granted = None
    status_after = None
    try:
        try:
            for p, label, before in ((sidecar_path, "Sidecar", digest_before),
                                     (profile_path, "Profil", profile_digest_before)):
                if p.is_symlink() or p.resolve() != p:
                    raise CheckError(f"{label}-Pfad wurde nach dem Start zu "
                                     "einem Symlink.")
                if not p.is_file():
                    raise CheckError(f"{label}-Pfad ist nach dem Start keine "
                                     "regulaere Datei.")
                after = sha256_of(p)
                if after != before:
                    raise CheckError(f"{label}-SHA-256 hat sich nach dem Start "
                                     f"geaendert.\n  vorher : {before}\n"
                                     f"  nachher: {after}")
        except CheckError as e:
            sc.shutdown()
            abort(f"TOCTOU-Pruefung fehlgeschlagen.\n{e}")
        print("  [T] TOCTOU-Recheck : OK (Pfad, Dateityp, Sidecar- und "
              "Profil-sha256 unveraendert)")

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
        print(f"""
Im naechsten Schritt wird EINMALIG die Kontakte-Autorisierung angefordert.
macOS zeigt daraufhin einen Berechtigungsdialog.

  * 'Erlauben' NUR waehlen, wenn der Dialogtext exakt lautet:

        {profile['usageDescription']}

  * Zeigt der Dialog stattdessen einen anderen Text (z. B. '... (APP)')
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
