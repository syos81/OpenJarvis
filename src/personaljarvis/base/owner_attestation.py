"""Der Beleg, dass der Eigentümer **diese** Mutation freigegeben hat.

**Warum es das gibt.** Bis hierher entstand eine Eigentümerentscheidung aus
einem HTTP-Aufruf mit frei gesetztem `decision_actor`. Gemessen am 2026-08-17:
25 von 25 Mutationen liefen so nacheinander durch, ohne dass ein Mensch etwas
bestätigte. Der Name im Aufruf war ein Metadatum und wurde als
Authentizitätsbeweis gelesen — das ist der Fehler, den diese Datei behebt.

**Was ein Beleg ist.** Eine Datei, die der **App-Prozess** nach einer
Eigentümerhandlung schreibt und die der Kern nur liest. Sie bindet sich an
genau eine Mutation und an genau deren Nutzlast:

* `mutation_id` — der Beleg gilt für diesen Vorgang und keinen anderen.
* `payload_digest` — ändert sich die Nutzlast nach der Handlung, passt der
  Beleg nicht mehr.
* `preview_digest` — und ändert sich die **Darstellung**, passt er ebenso
  wenig. Die Nutzlast allein genügt nicht: Derselbe Datensatz lässt sich
  verschieden zeigen, und freigegeben wurde, was auf der Fläche stand. Die
  Vorschau deckt seit 2026-08-13 auch Name und Art des Zielablageorts, also
  bindet der Beleg genau die sechs Angaben, die der Eigentümer gesehen hat.
* `attested_at` — er ist frisch oder er ist keiner. Ein alter Beleg darf keine
  spätere Mutation tragen.
* Einmalig — `consume()` entfernt ihn. Kein zweiter Lauf aus derselben
  Handlung.

**Was das ist und was nicht.** Dieselbe Semantik wie überall in diesem
Projekt: `requires_interactive_owner_authentication`, nicht
`technically_impossible`. Der Beleg liegt im Benutzerordner, und jeder Prozess
unter derselben Benutzerkennung kann ihn schreiben. Gesichert ist, dass es im
Kern, im Backend und in der HTTP-Schicht **keinen Codepfad gibt**, der einen
Beleg erzeugt — ein Statiktest hält das fest. Der Agent spricht über HTTP mit
dem Kern; er erreicht damit keinen Erzeugungsweg mehr.

**Gemeinsam, nicht je Fachbereich.** Die Fähigkeit steht im Beleg und wird
verglichen. Kalender wird dasselbe Primitiv verwenden; bis dahin verhindert
sein Produktschloss ohnehin jede Mutation.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = [
    "ATTESTATION_CONTRACT",
    "ATTESTATION_DIRNAME",
    "MAX_ATTESTATION_AGE_SECONDS",
    "OwnerAttestation",
    "default_attestation_dir",
    "read_attestation",
    "consume_attestation",
]

#: Vertragskennung. Ändert sich der Beleg, wird jeder alte dadurch wirkungslos.
ATTESTATION_CONTRACT = "owner-approval-v1"

#: Verzeichnis neben der Personal-Datenbank — dort, wo schon die
#: Schreibfreigabe liegt und wo ohnehin nur der Eigentümer hinkommt.
ATTESTATION_DIRNAME = "owner-approvals"

#: Wie alt ein Beleg höchstens sein darf. Bewusst kurz und bewusst dieselbe
#: Grössenordnung wie die Freigabefrist: Der Beleg gehört zur Handlung, nicht
#: zum Tag.
MAX_ATTESTATION_AGE_SECONDS = 15 * 60

#: Wie weit ein Beleg in der Zukunft liegen darf. Uhren gehen auseinander;
#: eine halbe Minute ist Nachsicht, fünf Minuten wären ein Schlupfloch.
_MAX_SKEW_SECONDS = 30


@dataclass(frozen=True, slots=True)
class OwnerAttestation:
    """Ein geprüfter, noch nicht verbrauchter Beleg."""

    capability: str
    mutation_id: str
    payload_digest: str
    preview_digest: str
    attested_at: str
    #: Wie der Eigentümer gehandelt hat. Protokoll, nicht Nachweis — der
    #: Nachweis ist, dass der Beleg überhaupt aus dem App-Prozess kommt.
    method: str


def default_attestation_dir(database_path: Path | str | None = None) -> Path:
    if database_path is not None:
        return Path(database_path).parent / ATTESTATION_DIRNAME
    from personaljarvis.base.db.factory import default_database_path

    return default_database_path().parent / ATTESTATION_DIRNAME


def _ist_privat(pfad: Path, *, verzeichnis: bool) -> bool:
    try:
        st = pfad.lstat()
    except OSError:
        return False
    if verzeichnis and not stat.S_ISDIR(st.st_mode):
        return False
    if not verzeichnis and (stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode)):
        return False
    erwartet = 0o700 if verzeichnis else 0o600
    return st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == erwartet


def _pfad(verzeichnis: Path, mutation_id: str) -> Path | None:
    """Der Ort des Belegs — oder `None`, wenn die Kennung keiner ist.

    Die Kennung landet in einem Dateinamen. Ein Punkt oder ein Schrägstrich
    darin wäre ein Ausbruch aus dem Verzeichnis, deshalb wird sie hier
    ausdrücklich eingeschränkt statt bereinigt.
    """
    if not mutation_id or not all(z.isalnum() or z == "-" for z in mutation_id):
        return None
    return verzeichnis / f"{mutation_id}.json"


def read_attestation(*, capability: str, mutation_id: str, payload_digest: str,
                     preview_digest: str,
                     verzeichnis: Path | str | None = None,
                     jetzt: datetime | None = None) -> OwnerAttestation | None:
    """Liest den Beleg — oder gibt `None` zurück. Nie eine Ausnahme.

    Fail-closed und still: Ein fehlender Beleg ist der Normalfall (die meisten
    Vorgänge sind noch nicht freigegeben) und kein Fehler.
    """
    ort = Path(verzeichnis) if verzeichnis is not None else default_attestation_dir()
    if not _ist_privat(ort, verzeichnis=True):
        return None
    datei = _pfad(ort, mutation_id)
    if datei is None or not _ist_privat(datei, verzeichnis=False):
        return None
    try:
        roh = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(roh, dict):
        return None
    if roh.get("contract") != ATTESTATION_CONTRACT:
        return None
    if roh.get("capability") != capability:
        return None
    # Die Bindung. Ein Beleg für einen anderen Vorgang oder für eine andere
    # Nutzlast ist kein Beleg für diesen.
    if roh.get("mutation_id") != mutation_id:
        return None
    if roh.get("payload_digest") != payload_digest:
        return None
    # Und die Darstellung. Ohne sie deckte der Beleg dieselbe Nutzlast unter
    # einer anderen Anzeige — etwa mit einem anderen Zielablageort im Text.
    if roh.get("preview_digest") != preview_digest:
        return None

    gestempelt = roh.get("attested_at")
    if not isinstance(gestempelt, str):
        return None
    try:
        moment = datetime.fromisoformat(gestempelt.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    now = jetzt or datetime.now(timezone.utc)
    if moment > now + timedelta(seconds=_MAX_SKEW_SECONDS):
        return None
    if moment < now - timedelta(seconds=MAX_ATTESTATION_AGE_SECONDS):
        return None

    verfahren = roh.get("method")
    if not isinstance(verfahren, str) or not verfahren.strip():
        return None

    return OwnerAttestation(
        capability=capability, mutation_id=mutation_id,
        payload_digest=payload_digest, preview_digest=preview_digest,
        attested_at=gestempelt, method=verfahren.strip())


def consume_attestation(*, mutation_id: str,
                        verzeichnis: Path | str | None = None) -> bool:
    """Entfernt den Beleg. Eine Handlung, eine Mutation.

    Bleibt er liegen, trüge dieselbe Eigentümerhandlung einen zweiten Lauf —
    und genau das ist die Schleife, gegen die dieses Modul steht.
    """
    ort = Path(verzeichnis) if verzeichnis is not None else default_attestation_dir()
    datei = _pfad(ort, mutation_id)
    if datei is None:
        return False
    try:
        datei.unlink()
        return True
    except OSError:
        return False
