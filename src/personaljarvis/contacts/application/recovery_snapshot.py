"""Der Wiederherstellungsschnappschuss: was ein Kontakt ausser v1 noch trägt.

**Warum es ihn gibt.** Die Löschsicherung des Gates deckt den Feldvertrag v1
(`delete_gate.py`). Ein Kontakt trägt mehr. Befund B-3 hat vermessen, was
Jarvis liest und lokal hält, was aber weder in `expectedPrevious` noch in der
Sicherung noch im Vergleich des Löschpfads steht:

* `social_profiles` — gelesen, lokal in `contact_social_profiles`
* `instant_messages` — gelesen, lokal in `contact_instant_messages`
* `relations` — gelesen, lokal in `contact_relations`

Bei diesen drei ist der Verlust real: Jarvis liest sie, hält sie lokal, und
eine Wiederherstellung aus der v1-Sicherung bringt sie nicht zurück; der
lokale Spiegel wird beim Löschen getombstonet. Dieser Schnappschuss legt sie
daneben, damit sie jemand **von Hand** wieder eintippen kann.

**Was er ausdrücklich nicht ist.**

*Kein Vergleichsmassstab.* Nichts vergleicht gegen diese Datei. Sie trägt
keinen Vorzustandsdigest, an dem ein Löschpfad etwas messen könnte, und der
Löschpfad kennt sie nicht. Der eine Vergleichsmassstab bleibt der eine
Re-Read gegen `expectedPrevious` — ein zweiter wäre genau der Zustand, gegen
den das Gate gebaut wurde.

*Kein Teil der Gate-Entscheidung, in keiner Richtung.* Gelingt er nicht, wird
trotzdem gelöscht, wenn die v1-Sicherung steht. Gelingt er, macht er keine
Löschung zulässig, die es sonst nicht wäre. Deshalb wirft dieses Modul nach
aussen nicht: Es meldet ein Ergebnis, und der Aufrufer schreibt es fort.

*Kein frischer Providerstand.* Gelesen wird Jarvis' lokaler Spiegel, in einem
**eigenen** Lesevorgang, getrennt von der Bindung des Löschvorgangs. Beide
können auseinanderlaufen; das ist kein Fehler, sondern der Grund, warum diese
Datei nichts entscheiden darf.

**Die Zusicherung, wörtlich:** `gesichert, manuell rekonstruierbar`. Nicht
„wiederhergestellt", nicht „automatisch". Wer die Datei öffnet, findet Werte,
die er selbst einträgt.

**Was draussen bleibt, und warum.**

*Foto* (`image_available`, `thumbnail_blob_ref`). Es ist kein Text und lässt
sich nicht abtippen — die Zusicherung dieser Datei gälte dafür nicht. Die
Bilddaten hier hineinzukopieren hiesse, eine zweite, unverwaltete Klartextkopie
eines Personenbildes ausserhalb des Blob-Stores anzulegen, für eine
Wiederherstellung, die ohnehin über die Originaldatei liefe. Der Verlust ist
damit benannt und nicht behoben.

*Notiz* (`note`). Jarvis liest sie nie — `unavailable_by_capability`, das
Entitlement fehlt seit macOS 11. Was nicht gelesen wird, kann nicht gesichert
werden; ein Feld dafür wäre immer leer und sähe aus wie eine leere Notiz.

**Schutz.** Dieselbe Ordnung wie bei der v1-Sicherung: 0700-Ordner,
0600-Datei, ausserhalb des Repositorys, ausserhalb von `.gate-runtime/`. Die
Werte gehen nie in git, nie in einen Bericht, nie in Auditfakten und nie über
die API. Der Inhaltsdigest darf nach aussen, die Werte nie.

**Aufbewahrung.** Die Datei bleibt liegen. Keine Frist, kein Aufräumweg, keine
Funktion, die löscht — Löschen ist Eigentümersache.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personaljarvis.base.digest import digest_of

__all__ = [
    "RECOVERY_SNAPSHOT_CONTRACT",
    "RECOVERY_ASSURANCE",
    "SNAPSHOT_FAMILIES",
    "EXCLUDED_FAMILIES",
    "RecoverySnapshot",
    "SnapshotErgebnis",
    "default_recovery_snapshot_dir",
    "recovery_snapshot_dir",
    "recovery_snapshot_path",
    "lese_schnappschuss",
    "schreibe_schnappschuss",
    "sichere_zusatzfamilien",
]

#: Vertragskennung der Schnappschussdatei. Bewusst **nicht** die des Gates:
#: Wer die beiden Dateien verwechselte, hielte den Schnappschuss für einen
#: Beleg, und er ist keiner.
RECOVERY_SNAPSHOT_CONTRACT = "contacts-recovery-snapshot-v1"

#: Die Zusicherung, wörtlich. Sie steht in der Datei, damit sie beim Öffnen
#: dabeisteht und nicht nur in einem Dokument, das niemand danebenlegt.
RECOVERY_ASSURANCE = "gesichert, manuell rekonstruierbar"

#: Die drei Familien dieses Vertrags, in fester Reihenfolge.
SNAPSHOT_FAMILIES = ("social_profiles", "instant_messages", "relations")

#: Was nicht drin ist — mit Grund, in der Datei selbst.
EXCLUDED_FAMILIES = (
    {
        "family": "photo",
        "reasonCode": "not_text_not_manually_reconstructible",
        "reason": "Ein Bild laesst sich nicht abtippen; die Zusicherung "
                  "dieser Datei gilt dafuer nicht. Eine Kopie der Bilddaten "
                  "waere eine zweite, unverwaltete Klartextkopie ausserhalb "
                  "des Blob-Stores.",
    },
    {
        "family": "note",
        "reasonCode": "unavailable_by_capability",
        "reason": "Jarvis liest die Notiz nie — das Entitlement fehlt seit "
                  "macOS 11. Was nicht gelesen wird, kann nicht gesichert "
                  "werden.",
    },
)

_ORDNER_MODUS = 0o700
_DATEI_MODUS = 0o600


def default_recovery_snapshot_dir() -> Path:
    """Der **produktive** Ablageort:
    `<Datenverzeichnis>/personal/backups/contacts/recovery-snapshot`.

    Ein eigener Ordner neben `field-state`, nicht derselbe: Zwei Dateien
    gleichen Namens in einem Ordner wären zwei Beleghalter, und nur einer
    davon ist einer.
    """
    from personaljarvis.base.db.factory import default_database_path

    return (default_database_path().parent / "backups" / "contacts"
            / "recovery-snapshot")


def recovery_snapshot_dir(basis: Path | str | None = None) -> Path:
    """Der Ablageort dieses Aufrufs — `basis`, sonst der produktive Ort."""
    return Path(basis) if basis is not None else default_recovery_snapshot_dir()


def recovery_snapshot_path(mutation_id: str, *,
                           basis: Path | str | None = None) -> Path | None:
    """Eine Datei je Mutation — oder `None` bei unbrauchbarem Namen.

    Kein Wurf: Der Name wandert in einen Pfad, und was kein sauberer Name
    ist, wird abgewiesen — aber die Abweisung darf den Löschpfad nicht
    anhalten, denn dieses Modul entscheidet dort nichts.
    """
    if not mutation_id or "/" in mutation_id or mutation_id in (".", ".."):
        return None
    return recovery_snapshot_dir(basis) / f"{mutation_id}.json"


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    """Die drei Familien eines Kontakts, wie der lokale Spiegel sie hält."""

    mutation_id: str
    container_identifier: str
    provider_identifier: str
    families: dict[str, list[dict[str, Any]]]
    captured_at: str

    def als_dokument(self) -> dict:
        return {
            "contract": RECOVERY_SNAPSHOT_CONTRACT,
            "assurance": RECOVERY_ASSURANCE,
            "source": "local_mirror",
            "mutationId": self.mutation_id,
            "containerIdentifier": self.container_identifier,
            "providerIdentifier": self.provider_identifier,
            "families": {name: list(self.families.get(name, ()))
                         for name in SNAPSHOT_FAMILIES},
            "excluded": [dict(eintrag) for eintrag in EXCLUDED_FAMILIES],
            "capturedAt": self.captured_at,
        }

    @property
    def inhaltsdigest(self) -> str:
        """Fingerabdruck der Datei — er darf nach aussen.

        Er benennt **diese Datei** und ist kein Vergleichsmassstab: Nichts im
        Löschpfad rechnet ihn nach, und keine Entscheidung hängt an ihm.
        """
        return digest_of(self.als_dokument())

    @property
    def ist_leer(self) -> bool:
        """Trägt der Kontakt in keiner der drei Familien etwas?"""
        return all(not self.families.get(name) for name in SNAPSHOT_FAMILIES)


@dataclass(frozen=True, slots=True)
class SnapshotErgebnis:
    """Was der Versuch ergeben hat — nie eine Ausnahme nach aussen.

    `reason_code` ist gesetzt, wenn nichts geschrieben wurde. Er ist eine
    Meldung, keine Sperre: Der Löschpfad liest ihn fort und hält deswegen
    nicht an.
    """

    written: bool
    reason_code: str | None = None
    content_digest: str | None = None
    #: Anzahl je Familie — Zahlen, keine Werte. Sie dürfen in ein Protokoll.
    counts: dict[str, int] | None = None


def lese_schnappschuss(uow, *, mutation_id: str, provider_account_id: str,
                       provider_identifier: str, container_identifier: str,
                       at: str) -> RecoverySnapshot | None:
    """Liest die drei Familien aus dem lokalen Spiegel — ein eigener Lesevorgang.

    `None`, wenn das Ziel lokal nicht auffindbar ist. Das ist kein Fehler des
    Löschpfads: Ein Kontakt, den Jarvis nicht gespiegelt hat, trägt hier auch
    nichts zu sichern.
    """
    zeile = uow.execute(
        "SELECT contact_id FROM contact_external_ids "
        "WHERE provider_account_id = ? AND provider_identifier = ?",
        (provider_account_id, provider_identifier)).fetchone()
    if zeile is None:
        return None
    contact_id = zeile["contact_id"]

    social = [
        {"position": r["position"], "label_raw": r["label_raw"],
         "service": r["service"], "username": r["username"], "url": r["url"]}
        for r in uow.execute(
            "SELECT position, label_raw, service, username, url "
            "FROM contact_social_profiles WHERE contact_id = ? "
            "ORDER BY position", (contact_id,)).fetchall()
    ]
    ims = [
        {"position": r["position"], "label_raw": r["label_raw"],
         "service": r["service"], "username": r["username"]}
        for r in uow.execute(
            "SELECT position, label_raw, service, username "
            "FROM contact_instant_messages WHERE contact_id = ? "
            "ORDER BY position", (contact_id,)).fetchall()
    ]
    # Der Bezug bleibt als Rohtext stehen, wo er nicht auflösbar war — und
    # wo er auflösbar war, wird der Name des Ziels danebengelegt. Eine blosse
    # lokale Kennung wäre nach dem Löschen nichts, was jemand abtippen kann.
    relations = [
        {"position": r["position"], "relation_type": r["relation_type"],
         "label_raw": r["label_raw"],
         "target_name_raw": r["target_name_raw"],
         "target_display_name": r["target_display_name"]}
        for r in uow.execute(
            "SELECT b.position, b.relation_type, b.label_raw, "
            "       b.target_name_raw, z.display_name AS target_display_name "
            "FROM contact_relations AS b "
            "LEFT JOIN contacts AS z ON z.id = b.to_contact_id "
            "WHERE b.from_contact_id = ? ORDER BY b.position",
            (contact_id,)).fetchall()
    ]

    return RecoverySnapshot(
        mutation_id=mutation_id, container_identifier=container_identifier,
        provider_identifier=provider_identifier,
        families={"social_profiles": social, "instant_messages": ims,
                  "relations": relations},
        captured_at=at)


def schreibe_schnappschuss(schnappschuss: RecoverySnapshot, *,
                           basis: Path | str | None = None) -> SnapshotErgebnis:
    """Schreibt, liest zurück, verifiziert — und wirft nach aussen nicht.

    Geschrieben wird wie bei der v1-Sicherung über eine temporäre Datei mit
    `os.replace`; ein Abbruch hinterlässt nie eine halbe Datei, die später
    als ganze gelesen würde.

    Trägt der Kontakt in keiner der drei Familien etwas, entsteht **keine**
    Datei: Eine Datei mit drei leeren Listen wäre eine Klartextablage ohne
    Klartext und sähe später aus wie ein Verlust, den es nicht gab.
    """
    if schnappschuss.ist_leer:
        return SnapshotErgebnis(
            written=False, reason_code="nothing_beyond_v1",
            counts={name: 0 for name in SNAPSHOT_FAMILIES})

    counts = {name: len(schnappschuss.families.get(name, ()))
              for name in SNAPSHOT_FAMILIES}
    ziel = recovery_snapshot_path(schnappschuss.mutation_id, basis=basis)
    if ziel is None:
        return SnapshotErgebnis(written=False, reason_code="invalid_mutation_id",
                                counts=counts)

    dokument = schnappschuss.als_dokument()
    roh = json.dumps(dokument, ensure_ascii=False, sort_keys=True)
    temp = ziel.with_name(f".{ziel.name}.tmp")
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(ziel.parent, _ORDNER_MODUS)
        st = ziel.parent.lstat()
        if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != _ORDNER_MODUS:
            return SnapshotErgebnis(written=False, reason_code="directory_unsafe",
                                    counts=counts)
        with open(temp, "w", encoding="utf-8") as datei:
            datei.write(roh)
            datei.flush()
            os.fsync(datei.fileno())
        os.chmod(temp, _DATEI_MODUS)
        os.replace(temp, ziel)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return SnapshotErgebnis(written=False, reason_code="write_failed",
                                counts=counts)

    # Zurückgelesen und verifiziert — nicht angenommen. Ein „vermutlich
    # geschrieben" wäre hier zwar folgenlos für die Löschung, aber es stünde
    # ein `written: true` in einem Protokoll, dem nichts entspricht.
    try:
        zurueck = json.loads(ziel.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SnapshotErgebnis(written=False, reason_code="readback_failed",
                                counts=counts)
    if zurueck != dokument:
        return SnapshotErgebnis(written=False, reason_code="readback_mismatch",
                                counts=counts)
    st = ziel.lstat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != _DATEI_MODUS:
        return SnapshotErgebnis(written=False, reason_code="permissions_unsafe",
                                counts=counts)

    return SnapshotErgebnis(written=True,
                            content_digest=schnappschuss.inhaltsdigest,
                            counts=counts)


def sichere_zusatzfamilien(persistence, *, bindung, provider_account_id: str,
                           at: str, basis: Path | str | None = None,
                           ) -> SnapshotErgebnis:
    """Der ganze Weg in einem Aufruf: eigener Lesevorgang, schreiben, melden.

    **Fängt alles.** Der weite `except` ist hier kein Schlamperei-Fang, sondern
    der Vertrag dieses Moduls: Die Gate-Entscheidung darf in keiner Richtung
    von diesem Schnappschuss abhängen. Eine Ausnahme, die bis in den Löschpfad
    durchschlüge, hielte eine Löschung an, deren v1-Sicherung längst steht —
    das wäre eine Wirkung, und dieses Modul soll keine haben.

    Was schiefging, steht im `reason_code` und geht ins Protokoll. Still ist
    hier nichts.
    """
    try:
        with persistence.unit_of_work() as uow:
            schnappschuss = lese_schnappschuss(
                uow, mutation_id=bindung.mutation_id,
                provider_account_id=provider_account_id,
                provider_identifier=bindung.provider_identifier,
                container_identifier=bindung.container_identifier, at=at)
    except Exception:
        return SnapshotErgebnis(written=False, reason_code="read_failed")

    if schnappschuss is None:
        # Kein lokaler Spiegel des Ziels: Dann trägt dieser Kontakt hier auch
        # nichts zu sichern. Kein Fehler des Löschpfads.
        return SnapshotErgebnis(written=False, reason_code="target_not_mirrored")

    try:
        return schreibe_schnappschuss(schnappschuss, basis=basis)
    except Exception:
        return SnapshotErgebnis(written=False, reason_code="write_failed")
