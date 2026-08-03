#!/usr/bin/env python3
"""Phase-A-Smoke-Vertrag: die gepackte App gegen ein Wegwerfprofil starten.

**Warum es diese Datei gibt.** Der erste Phase-A-Smoke lief versehentlich
gegen die produktive Datenbank und hat sie migriert. Die Ursache war keine
Nachlässigkeit beim Aufruf, sondern eine Eigenschaft von macOS: `open`
startet über LaunchServices, und die geerbte Umgebung ist die von `launchd`
— nicht die der Shell. Ein `export OPENJARVIS_HOME=…` vor `open` erreicht
die App also gar nicht. Die App wiederum reicht an ihr Backend nur die
Variablen weiter, die sie selbst setzt; alles andere kommt aus ihrer eigenen
Umgebung. Ohne Zutun landet man damit zwangsläufig bei
`~/.openjarvis/personal/jarvis.db`.

**Wie es gelöst ist.** `open --env VAR=WERT` (macOS 12+) legt die Variable
in die Umgebung des gestarteten Prozesses. Damit greift der bereits
vorhandene, unterstützte Konfigurationsmechanismus `OPENJARVIS_HOME`
(`openjarvis.core.paths.get_config_dir`) — es braucht keine Sonderlogik im
Produktpfad, und der Smoke sieht dieselbe Auflösungskette wie ein echter
Start.

**Fail-closed.** Vor dem Start wird bewiesen, dass der wirksame
Datenbankpfad unter dem Wegwerfverzeichnis liegt und *nicht* der produktive
ist. Trifft eine Vorbedingung nicht zu, startet nichts. Ein Smoke, der im
Zweifel trotzdem loslegt, ist genau der Fehler, den diese Datei verhindert.

Aufruf::

    uv run python scripts/personal/phase_a_smoke.py \
        --app <Pfad>/Jarvis.app [--keep] [--timeout 240]

Das Skript öffnet **keinen** Kontaktebereich, löst keinen Sync aus, führt
keine Mutation und keine Freigabe aus und ruft kein Tauri-Mutationskommando.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "SmokeProfile",
    "SmokeVerletzung",
    "erzeuge_profil",
    "pruefe_vorbedingungen",
    "wirksamer_datenbankpfad",
    "produktiver_datenbankpfad",
    "datei_digest",
    "TEMP_CONFIG",
    "OPEN_ENV_FLAG",
]

#: Der Start reicht die Variable über `open --env` weiter — nicht über die
#: Shell-Umgebung, die LaunchServices verwirft.
OPEN_ENV_FLAG = "--env"

#: Wegwerfkonfiguration. Analytics ist ausdrücklich aus: der Standardwert von
#: `AnalyticsConfig.enabled` ist wahr, und ein Abnahmelauf hat auf keinem
#: fremden Server etwas verloren.
TEMP_CONFIG = """# Wegwerfprofil des Phase-A-Smokes — niemals produktiv verwenden.
[analytics]
enabled = false
"""


class SmokeVerletzung(RuntimeError):
    """Eine Vorbedingung des Smoke-Vertrags ist nicht erfüllt."""


@dataclass(frozen=True, slots=True)
class SmokeProfile:
    """Ein vollständig eigenständiges Wegwerfprofil."""

    home: Path
    """Wert für `OPENJARVIS_HOME` — Wurzel *aller* Zustände dieses Laufs."""

    datenbank: Path
    """Der erwartete Ort der Personal-Datenbank innerhalb des Profils."""

    config: Path
    """Die Wegwerfkonfiguration."""

    @property
    def env_argument(self) -> str:
        return f"OPENJARVIS_HOME={self.home}"


def produktiver_datenbankpfad() -> Path:
    """Der Standardort — ohne jede Umgebungsvariable.

    Bewusst unabhängig von `os.environ` berechnet: wer prüfen will, ob ein
    Lauf die produktive Datei meidet, darf nicht dieselbe Variable benutzen,
    die den Lauf umlenkt.
    """
    return Path.home() / ".openjarvis" / "personal" / "jarvis.db"


def wirksamer_datenbankpfad(home: Path | str) -> Path:
    """Der Datenbankpfad, den der Kern bei diesem `OPENJARVIS_HOME` wählt.

    Gefragt wird der Produktivcode selbst (`default_database_path`), nicht
    eine nachgebaute Formel — eine Kopie der Regel könnte auseinanderlaufen,
    und dann prüfte der Smoke etwas anderes als der Start tut.
    """
    umgebung = dict(os.environ)
    umgebung["OPENJARVIS_HOME"] = str(home)
    ausgabe = subprocess.run(
        [sys.executable, "-c",
         "from personaljarvis.base.db.factory import default_database_path;"
         "print(default_database_path())"],
        env=umgebung, capture_output=True, text=True, timeout=120,
    )
    if ausgabe.returncode != 0:
        raise SmokeVerletzung(
            "Der wirksame Datenbankpfad liess sich nicht bestimmen: "
            + ausgabe.stderr.strip()[-400:])
    return Path(ausgabe.stdout.strip())


def datei_digest(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def erzeuge_profil(basis: Path | str | None = None) -> SmokeProfile:
    """Legt ein 0700-Wegwerfverzeichnis samt Konfiguration an."""
    # `.resolve()` ist kein Schoenheitsfehler: Auf macOS liegt das
    # Temp-Verzeichnis unter `/var/folders/...`, was ein Symlink nach
    # `/private/var/folders/...` ist. Der Kern loest den Pfad auf; ohne
    # dieselbe Aufloesung hier verglichen die Vorbedingungen zwei
    # Schreibweisen derselben Datei und schluegen immer fehl.
    wurzel = Path(tempfile.mkdtemp(
        prefix="pj-smoke-", dir=str(basis) if basis else None)).resolve()
    os.chmod(wurzel, 0o700)
    home = wurzel / "openjarvis-home"
    home.mkdir(mode=0o700)
    (home / "personal").mkdir(mode=0o700)
    config = home / "config.toml"
    config.write_text(TEMP_CONFIG, encoding="utf-8")
    os.chmod(config, 0o600)
    return SmokeProfile(home=home, datenbank=home / "personal" / "jarvis.db",
                        config=config)


def pruefe_vorbedingungen(profil: SmokeProfile, *,
                          produktiv: Path | None = None) -> dict:
    """Fail-closed vor dem Start. Gibt die Belege zurück, die sie geprüft hat.

    Geprüft wird in dieser Reihenfolge, weil jede Stufe die nächste erst
    sinnvoll macht: Existiert das Profil? Zeigt der Kern wirklich dorthin?
    Ist das *nicht* die produktive Datei? Und existiert die produktive Datei
    mit einem Hash, gegen den sich hinterher vergleichen lässt?
    """
    produktiv = produktiv or produktiver_datenbankpfad()
    belege: dict[str, object] = {}

    if not profil.home.is_dir():
        raise SmokeVerletzung(f"Profilverzeichnis fehlt: {profil.home}")
    rechte = stat.S_IMODE(profil.home.stat().st_mode)
    if rechte != 0o700:
        raise SmokeVerletzung(
            f"Profilverzeichnis hat {oct(rechte)} statt 0700")
    belege["profil_rechte"] = oct(rechte)

    if not profil.config.is_file():
        raise SmokeVerletzung("Wegwerfkonfiguration fehlt")
    if "enabled = false" not in profil.config.read_text(encoding="utf-8"):
        raise SmokeVerletzung("Wegwerfkonfiguration schaltet Analytics nicht ab")

    wirksam = wirksamer_datenbankpfad(profil.home)
    belege["wirksamer_pfad"] = str(wirksam)
    if wirksam != profil.datenbank:
        raise SmokeVerletzung(
            f"Wirksamer Datenbankpfad {wirksam} liegt nicht im Profil "
            f"({profil.datenbank})")
    try:
        wirksam.relative_to(profil.home)
    except ValueError as fehler:
        raise SmokeVerletzung(
            f"Wirksamer Datenbankpfad {wirksam} liegt ausserhalb von "
            f"{profil.home}") from fehler

    if wirksam == produktiv or produktiv in wirksam.parents:
        raise SmokeVerletzung("Der Lauf zeigt auf die produktive Datenbank")
    if str(wirksam).startswith(str(Path.home() / ".openjarvis")):
        raise SmokeVerletzung("Der Lauf zeigt in das produktive Datenverzeichnis")

    if not produktiv.is_file():
        raise SmokeVerletzung(
            f"Produktive Datenbank {produktiv} fehlt — ohne sie gibt es "
            "keinen Vergleichshash, und der Lauf bliebe unbeweisbar")
    belege["produktiv_digest_vorher"] = datei_digest(produktiv)
    belege["produktiv_pfad"] = str(produktiv)
    belege["profil_home"] = str(profil.home)
    return belege


# ── Ab hier: der eigentliche Lauf (nur CLI, nicht importiert benutzt) ───────
def _warte_auf(url: str, sekunden: int) -> bool:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except urllib.error.HTTPError:
            return True          # antwortet — mehr braucht der Smoke nicht
        except OSError:
            time.sleep(1)
    return False


def _hole(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as antwort:
            return json.loads(antwort.read())
    except (OSError, ValueError):
        return None


#: Was nach einem sauberen Cmd+Q niemand mehr sein darf: das App-Binary und
#: das Backend, das es startet.
RESTMUSTER = ("Jarvis.app/Contents/MacOS/openjarvis-desktop",
              "bin/jarvis serve", "jarvis-contacts")


def _laeuft(muster: str) -> list[str]:
    proc = subprocess.run(["pgrep", "-f", muster], capture_output=True, text=True)
    return [z for z in proc.stdout.split() if z]


def _restprozesse() -> list[str]:
    gefunden: list[str] = []
    for muster in RESTMUSTER:
        gefunden.extend(_laeuft(muster))
    return gefunden


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app", required=True, type=Path)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--timeout", type=int, default=240)
    p.add_argument("--keep", action="store_true",
                   help="Profilverzeichnis nach dem Lauf behalten")
    args = p.parse_args(argv)

    profil = erzeuge_profil()
    belege = pruefe_vorbedingungen(profil)
    print("Vorbedingungen erfuellt:")
    for schluessel, wert in belege.items():
        print(f"  {schluessel}: {wert}")

    basis = f"http://127.0.0.1:{args.port}"
    subprocess.run(["open", OPEN_ENV_FLAG, profil.env_argument,
                    "-n", str(args.app)], check=True)
    ergebnis: dict[str, object] = {"profil": str(profil.home)}
    try:
        bereit = _warte_auf(f"{basis}/v1/personal/contacts/app-channel", args.timeout)
        ergebnis["backend_erreichbar"] = bereit
        if bereit:
            ergebnis["app_channel"] = _hole(f"{basis}/v1/personal/contacts/app-channel")
        ergebnis["temp_db_existiert"] = profil.datenbank.is_file()
    finally:
        # Beendet wird ausschliesslich ueber das regulaere „quit" (Cmd+Q).
        # Es wird **kein** Signal geschickt — weder SIGTERM noch SIGKILL:
        # Was die App danach noch stehen laesst, waere ein echter Befund und
        # kein Grund, nachzuhelfen.
        beginn = time.monotonic()
        subprocess.run(["osascript", "-e", 'tell application "Jarvis" to quit'],
                       capture_output=True)
        while time.monotonic() - beginn < 30 and _restprozesse():
            time.sleep(0.1)
        ergebnis["shutdown_sekunden"] = round(time.monotonic() - beginn, 2)
        ergebnis["restprozesse"] = len(_restprozesse())
        ergebnis["kill_gesendet"] = False

    produktiv = Path(str(belege["produktiv_pfad"]))
    ergebnis["produktiv_digest_nachher"] = datei_digest(produktiv)
    ergebnis["produktiv_unveraendert"] = (
        ergebnis["produktiv_digest_nachher"] == belege["produktiv_digest_vorher"])
    print(json.dumps(ergebnis, indent=2, ensure_ascii=False))

    if not args.keep:
        shutil.rmtree(profil.home.parent, ignore_errors=True)
    return 0 if ergebnis["produktiv_unveraendert"] else 1


if __name__ == "__main__":          # pragma: no cover - CLI
    raise SystemExit(main())
