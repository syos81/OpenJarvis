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
* Sie nennt die **Fähigkeit**, für die sie gilt. Eine Kontaktfreigabe öffnet
  keinen anderen Fachbereich; der Aufrufer fragt für genau einen und bekommt
  nichts, wenn die Urkunde einen anderen nennt.

**Zwei Verträge, zwei Lebensdauern.** `contacts-write-v1` ist befristet und
läuft nach höchstens vier Stunden ab — eine Freigabe als Ereignis.
`contacts-write-v2` kennt zusätzlich den Modus `standing`: eine Freigabe, die
gilt, bis der Eigentümer sie zurücknimmt, und die einen Neustart überlebt. Der
Alltag braucht sie; ohne sie wäre jede Benutzung eine Zeremonie.

Dass dafür ein **eigener** Vertrag steht und kein Zusatzfeld an v1, ist der
Kern der Sache: eine früher erteilte befristete Freigabe kann dadurch niemals
nachträglich als Dauerfreigabe gelesen werden. Dauerhaftigkeit wird neu
erteilt, nicht umgedeutet. Und dauerhaft heisst nicht universell — die
Dauerfreigabe nennt Fähigkeit und Operationen so einzeln wie die befristete.

Fehlt sie, ist sie unlesbar, falsch berechtigt, abgelaufen, nennt einen fremden
Vertrag oder eine fremde Fähigkeit, so ist das Ergebnis **immer** dasselbe:
keine Freigabe. Es gibt keinen Zweig, der im Zweifel öffnet.

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
    "WRITE_RELEASE_CONTRACT_V2",
    "WRITE_RELEASE_CONTRACTS",
    "WRITE_RELEASE_CAPABILITY",
    "MODE_TEMPORARY",
    "MODE_STANDING",
    "RELEASE_MODES",
    "MAX_RELEASE_HOURS",
    "WriteRelease",
    "default_release_path",
    "read_write_release",
]

#: Dateiname im Personal-Datenverzeichnis, direkt neben der Datenbank.
WRITE_RELEASE_FILENAME = "contacts-write-release.json"

#: Vertragskennung. Ändert sich der Freigabevertrag, wird jede alte Datei
#: dadurch automatisch wirkungslos.
WRITE_RELEASE_CONTRACT = "contacts-write-v1"

#: Der Dauerhaftigkeitsvertrag. **Ein eigener Vertrag, kein Zusatzfeld an v1.**
#: Nur so kann eine bestehende v1-Datei nicht nachträglich als Dauerfreigabe
#: gelesen werden: Persistenz deutet keinen früher erteilten befristeten Grant
#: um, sie verlangt eine eigene, neu erteilte Urkunde.
WRITE_RELEASE_CONTRACT_V2 = "contacts-write-v2"

WRITE_RELEASE_CONTRACTS = (WRITE_RELEASE_CONTRACT, WRITE_RELEASE_CONTRACT_V2)

#: Die Fähigkeit, für die eine Freigabe überhaupt gelten kann. Sie steht
#: ausdrücklich **im** Dokument und wird nicht aus dem Dateinamen erschlossen:
#: eine Freigabe, die ihre Fähigkeit nicht nennt, gilt für keine.
WRITE_RELEASE_CAPABILITY = "contacts"

#: Befristet — die bisherige Form. Eine Freigabe als Ereignis.
MODE_TEMPORARY = "temporary"

#: Dauerhaft — gilt bis der Eigentümer sie zurücknimmt, und überlebt einen
#: Neustart. Sie hat **kein** Ablaufdatum; ein Ablauf wäre ein Widerspruch.
#: Was sie nicht ist: universell. Sie nennt Fähigkeit und Operationen so
#: einzeln wie die befristete.
MODE_STANDING = "standing"

RELEASE_MODES = (MODE_TEMPORARY, MODE_STANDING)

#: Längste zulässige Geltungsdauer ab Ausstellung — gilt ausschliesslich für
#: befristete Freigaben.
MAX_RELEASE_HOURS = 4

#: Jede Operation wird **einzeln** freigegeben. Eine Datei, die
#: `delete` nennt, gibt kein `update` frei und umgekehrt.
_OPERATIONS = ("create", "update", "delete")


@dataclass(frozen=True, slots=True)
class WriteRelease:
    """Eine geprüfte, gültige Freigabe."""

    contract: str
    operations: tuple[str, ...]
    expires_at: str | None
    reason: str
    capability: str = WRITE_RELEASE_CAPABILITY
    mode: str = MODE_TEMPORARY

    def erlaubt(self, operation: str) -> bool:
        return operation in self.operations

    def gilt_fuer(self, capability: str) -> bool:
        """Ob diese Freigabe **diese** Fähigkeit meint.

        Bewusst ein Vergleich und keine Vorbelegung: Eine Freigabe für
        Kontakte darf unter keinen Umständen als Freigabe für einen anderen
        Fachbereich durchgehen.
        """
        return self.capability == capability


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


def _zeitpunkt(wert: object) -> datetime | None:
    """Ein ISO-8601-Zeitpunkt oder `None`. Nie eine Ausnahme."""
    if not isinstance(wert, str):
        return None
    try:
        moment = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def read_write_release(pfad: Path | str | None = None, *,
                       jetzt: datetime | None = None,
                       capability: str = WRITE_RELEASE_CAPABILITY,
                       ) -> WriteRelease | None:
    """Liest die Freigabe — oder gibt `None` zurück. Nie eine Ausnahme.

    Fail-closed heisst hier auch: **still**. Eine fehlende Freigabe ist der
    Normalfall und kein Fehler; sie soll keinen Aufrufer zu einer
    Sonderbehandlung verleiten.

    `capability` ist ein Pflichtvergleich, keine Verzierung: Der Aufrufer sagt,
    für welchen Fachbereich er fragt, und bekommt nichts, wenn die Urkunde
    einen anderen nennt. Eine Kontaktfreigabe kann damit keinen anderen
    Schreibpfad öffnen — auch nicht versehentlich, auch nicht später.

    Zwei Verträge werden gelesen:

    * `contacts-write-v1` — befristet, wie bisher, höchstens vier Stunden.
      Er kennt keinen Modus und wird **nie** als Dauerfreigabe gelesen.
    * `contacts-write-v2` — nennt Fähigkeit und Modus ausdrücklich. Nur er
      kann `standing` sein, und nur dann entfällt der Ablauf.
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
    vertrag = roh.get("contract")
    if vertrag not in WRITE_RELEASE_CONTRACTS:
        return None

    operationen = roh.get("operations")
    if not isinstance(operationen, list) or not operationen:
        return None
    if any(o not in _OPERATIONS for o in operationen):
        return None

    grund = roh.get("reason")
    if not isinstance(grund, str) or not grund.strip():
        return None

    now = jetzt or datetime.now(timezone.utc)

    if vertrag == WRITE_RELEASE_CONTRACT:
        # v1 kennt weder Fähigkeit noch Modus. Die Fähigkeit ergibt sich aus
        # dem Vertrag selbst — er ist der Kontaktvertrag —, der Modus ist
        # immer befristet. Ein v1-Dokument mit `mode` bleibt trotzdem
        # befristet; das Feld gehört nicht zu diesem Vertrag.
        gemeint = WRITE_RELEASE_CAPABILITY
        modus = MODE_TEMPORARY
    else:
        gemeint = roh.get("capability")
        if not isinstance(gemeint, str) or not gemeint:
            return None
        modus = roh.get("mode")
        if modus not in RELEASE_MODES:
            return None

    if gemeint != capability:
        return None

    if modus == MODE_STANDING:
        # Eine Dauerfreigabe hat kein Ablaufdatum. Trüge sie eines, wäre
        # unklar, welche der beiden Aussagen gilt — also gilt keine.
        if roh.get("expires_at") is not None:
            return None
        # Sie nennt aber ihren Beginn: eine Freigabe ohne Ausstellungszeit
        # liesse sich später nicht mehr einordnen.
        if _zeitpunkt(roh.get("granted_at")) is None:
            return None
        if _zeitpunkt(roh.get("revoked_at")) is not None:
            return None
        return WriteRelease(contract=vertrag, operations=tuple(operationen),
                            expires_at=None, reason=grund.strip(),
                            capability=gemeint, mode=MODE_STANDING)

    ablauf = roh.get("expires_at")
    endet = _zeitpunkt(ablauf)
    if endet is None:
        return None
    if endet <= now:
        return None
    # Eine befristete Freigabe weit in der Zukunft ist keine Freigabe, sondern
    # ein Dauerzustand mit anderem Namen — und dafür gibt es jetzt den
    # ausdrücklichen Modus, der sich auch so nennt.
    if endet > now + timedelta(hours=MAX_RELEASE_HOURS):
        return None

    return WriteRelease(contract=vertrag, operations=tuple(operationen),
                        expires_at=ablauf, reason=grund.strip(),
                        capability=gemeint, mode=MODE_TEMPORARY)
