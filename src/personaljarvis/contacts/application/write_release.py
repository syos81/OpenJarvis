"""Die Schreibfreigabe — der einzige Weg, den Providerwrite einzuschalten.

**Warum keine Umgebungsvariable.** Eine Variable ist der schwächste
denkbare Schalter: Sie erbt sich in Kindprozesse, steht in jedem
Prozessabbild, überlebt kein Audit und lässt sich versehentlich in einem
Startskript setzen. Für einen Schalter, der einen echten Schreibvorgang in
fremde Kontaktdaten freigibt, ist das zu wenig.

Stattdessen: eine **Datei**, die genau dort liegt, wo ohnehin nur der
Eigentümer hinkommt, und die vier Dinge zugleich belegt — Absicht,
Eigentum, Umfang und Ablauf:

* Sie liegt in einem Verzeichnis mit Rechten 0700, das dem laufenden
  Benutzer gehört.
* Sie selbst hat Rechte 0600, gehört demselben Benutzer und ist kein Symlink.
* Sie nennt ausdrücklich den Vertrag und die freigegebenen Operationen —
  wer `create` freigibt, gibt kein `delete` frei.
* Sie läuft ab. Eine vergessene Freigabe ist damit keine dauerhafte.

Fehlt sie, ist sie unlesbar, falsch berechtigt, abgelaufen oder nennt einen
fremden Vertrag, so ist das Ergebnis **immer** dasselbe: keine Freigabe. Es
gibt keinen Zweig, der im Zweifel öffnet.

Dieselbe Datei liest der Rust-Layer vor dem nativen Save (`contacts_create.rs`)
— dieselben Regeln, dieselbe Antwort. Der Kern könnte sonst „darf" melden,
während der App-Prozess „darf nicht" meint, oder schlimmer: umgekehrt.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = [
    "WRITE_RELEASE_FILENAME",
    "WRITE_RELEASE_CONTRACT",
    "MAX_RELEASE_HOURS",
    "WriteRelease",
    "default_release_path",
    "read_write_release",
]

#: Dateiname im Personal-Datenverzeichnis, direkt neben der Datenbank.
WRITE_RELEASE_FILENAME = "contacts-write-release.json"

#: Vertragskennung. Ändert sich der Freigabevertrag, wird jede alte Datei
#: dadurch automatisch wirkungslos.
WRITE_RELEASE_CONTRACT = "contacts-create-v1"

#: Längste zulässige Geltungsdauer ab Ausstellung. Eine Freigabe ist ein
#: Ereignis, kein Zustand.
MAX_RELEASE_HOURS = 4

_OPERATIONS = ("create",)


@dataclass(frozen=True, slots=True)
class WriteRelease:
    """Eine geprüfte, gültige Freigabe."""

    contract: str
    operations: tuple[str, ...]
    expires_at: str
    reason: str

    def erlaubt(self, operation: str) -> bool:
        return operation in self.operations


def default_release_path(database_path: Path | str | None = None) -> Path:
    """Der kanonische Ort: neben der Personal-Datenbank.

    Bewusst dort und nicht in einem eigenen Ordner: Das Verzeichnis ist
    bereits 0700 und gehört dem Eigentümer der Daten.
    """
    if database_path is not None:
        return Path(database_path).parent / WRITE_RELEASE_FILENAME
    from personaljarvis.base.db.factory import default_database_path

    return default_database_path().parent / WRITE_RELEASE_FILENAME


def _verzeichnis_ist_privat(pfad: Path) -> bool:
    try:
        st = pfad.lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    return st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o700


def _datei_ist_privat(pfad: Path) -> bool:
    try:
        st = pfad.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return False
    return st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o600


def read_write_release(pfad: Path | str | None = None, *,
                       jetzt: datetime | None = None) -> WriteRelease | None:
    """Liest die Freigabe — oder gibt `None` zurück. Nie eine Ausnahme.

    Fail-closed heisst hier auch: **still**. Eine fehlende Freigabe ist der
    Normalfall und kein Fehler; sie soll keinen Aufrufer zu einer
    Sonderbehandlung verleiten.
    """
    ort = Path(pfad) if pfad is not None else default_release_path()
    if not _verzeichnis_ist_privat(ort.parent) or not _datei_ist_privat(ort):
        return None
    try:
        roh = json.loads(ort.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(roh, dict):
        return None
    if roh.get("contract") != WRITE_RELEASE_CONTRACT:
        return None

    operationen = roh.get("operations")
    if not isinstance(operationen, list) or not operationen:
        return None
    if any(o not in _OPERATIONS for o in operationen):
        return None

    ablauf = roh.get("expires_at")
    if not isinstance(ablauf, str):
        return None
    try:
        endet = datetime.fromisoformat(ablauf.replace("Z", "+00:00"))
    except ValueError:
        return None
    if endet.tzinfo is None:
        endet = endet.replace(tzinfo=timezone.utc)

    now = jetzt or datetime.now(timezone.utc)
    if endet <= now:
        return None
    # Eine Freigabe weit in der Zukunft ist keine Freigabe, sondern ein
    # Dauerzustand mit anderem Namen.
    if endet > now + timedelta(hours=MAX_RELEASE_HOURS):
        return None

    grund = roh.get("reason")
    if not isinstance(grund, str) or not grund.strip():
        return None

    return WriteRelease(contract=WRITE_RELEASE_CONTRACT,
                        operations=tuple(operationen),
                        expires_at=ablauf, reason=grund.strip())
