"""Das Löschgate: keine Löschung ohne belegt wiederherstellbaren Inhalt.

**Wogegen es steht.** `scripts/contacts-backup.py` gibt es seit langem, und es
ist für diese Aufgabe untauglich: Es kopiert Jarvis' lokale SQLite als Ganzes,
wird von Hand aufgerufen, hängt an keiner Mutation und sichert das Falsche —
Jarvis' Abbild statt des Kontakts beim Provider. Zurückspielen brächte den
Eintrag in Jarvis zurück; beim nächsten Abgleich wäre er wieder weg. Es bleibt
unverändert bestehen, es ist nur nicht dieses Gate.

**Was hier gesichert wird.** Die kanonischen v1-Feldwerte des Zielkontakts,
je Mutation eine Datei, zusammen mit Container, Provider-Identifier und dem
Digest, an dem der Löschpfad den Vorzustand bindet. Das sind echte
Kontaktwerte, und das ist Absicht: Ohne die Werte sichert das Gate nichts.

**Der eine Re-Read.** Es gibt genau einen, und er liegt im App-Prozess:
`JCWriteRun` liest den Zielkontakt unmittelbar vor dem Save über den
Identifier — nie über einen Namen — und vergleicht den gelesenen Stand Feld
für Feld gegen `expectedPrevious`. Weicht er ab, endet der Vorgang mit
`revision_conflict`, und es wird nichts gesendet. Dieses Gate hängt sich an
genau diesen Vergleichsmaßstab, statt einen zweiten Lesevorgang zu erzeugen:
Bei zwei Lesevorgängen könnte sich der Kontakt dazwischen ändern, und dann
wäre Stand A gesichert und Stand B gelöscht.

Daraus folgt die **ehrliche Grenze** dieser Sicherung: Der gesicherte Stand
ist Jarvis' kanonischer Spiegel, kein frisch vom Provider gelesener Datensatz.
Seine Gleichheit mit dem Providerstand ist nicht vorher *gemessen*, sondern
vom Löschpfad *erzwungen* — weicht der Provider ab, wird nicht gelöscht.

**Was wiederherstellbar heißt.** Der **Inhalt** ist wiederherstellbar, die
Identität nicht. Eine Wiederherstellung erzeugt voraussichtlich einen neuen
Kontakt mit neuer Providerkennung; externe Verknüpfungen zur alten Identität
können verloren bleiben. Kurzform: `content-recoverable, identity-irreversible`.

**Aufbewahrung.** Die Datei bleibt liegen. Es gibt hier bewusst keine Frist,
keinen Aufräumweg und keine Funktion, die löscht — Löschen ist Eigentümersache.

**Schutz.** Die Werte gehen nie in git, nie in einen Bericht, nie in
Auditfakten und nie über die API. Der Digest darf nach außen, die Werte nie.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from personaljarvis.base.digest import digest_of
from personaljarvis.contacts.application.errors import (
    DeleteBackupMissing,
    DeleteBackupUnverified,
)

__all__ = [
    "FIELD_STATE_CONTRACT",
    "FieldStateBackup",
    "field_state_dir",
    "field_state_path",
    "Loeschbindung",
    "loeschbindung",
    "pruefe_loeschsicherung",
    "pruefe_sicherung",
    "schreibe_loeschsicherung",
    "schreibe_sicherung",
]

#: Vertragskennung der Sicherungsdatei. Eine unbekannte Kennung wird nicht
#: geraten, sondern abgewiesen — eine fremd geschriebene Datei ist kein Beleg.
FIELD_STATE_CONTRACT = "contacts-field-state-backup-v1"

_ORDNER_MODUS = 0o700
_DATEI_MODUS = 0o600


def field_state_dir(basis: Path | str | None = None) -> Path:
    """`<Datenverzeichnis>/personal/backups/contacts/field-state`.

    Ausserhalb des Repositorys und ausserhalb des gitignorierten
    Laufzeitbereichs: Das hier sind Kontaktwerte, keine Evidenz.
    """
    if basis is not None:
        return Path(basis)
    from personaljarvis.base.db.factory import default_database_path

    return (default_database_path().parent / "backups" / "contacts"
            / "field-state")


def field_state_path(mutation_id: str, *, basis: Path | str | None = None) -> Path:
    """Eine Datei je Mutation.

    Der Dateiname ist die Mutationskennung und nichts sonst. Damit
    ueberschreibt ein erneuter Anlauf derselben Mutation dieselbe Datei,
    statt eine zweite anzulegen — eine zweite waere eine zweite Klartextkopie
    desselben Kontakts.
    """
    if not mutation_id or "/" in mutation_id or mutation_id in (".", ".."):
        # Der Name wandert in einen Pfad. Was kein sauberer Name ist, wird
        # nicht bereinigt, sondern abgewiesen.
        raise DeleteBackupUnverified("Unbrauchbare Mutationskennung")
    return field_state_dir(basis) / f"{mutation_id}.json"


@dataclass(frozen=True, slots=True)
class FieldStateBackup:
    """Der gesicherte Feldstand eines Loeschziels."""

    mutation_id: str
    container_identifier: str
    provider_identifier: str
    field_contract_version: int
    fields: Mapping[str, Any]
    #: Der Digest, an dem der Loeschpfad den Vorzustand bindet. Er ist die
    #: Klammer zwischen dieser Sicherung und dem einen Re-Read.
    expected_fields_digest: str
    captured_at: str

    def als_dokument(self) -> dict:
        return {
            "contract": FIELD_STATE_CONTRACT,
            "mutationId": self.mutation_id,
            "containerIdentifier": self.container_identifier,
            "providerIdentifier": self.provider_identifier,
            "fieldContractVersion": self.field_contract_version,
            "fields": dict(self.fields),
            "expectedFieldsDigest": self.expected_fields_digest,
            "capturedAt": self.captured_at,
        }

    @property
    def inhaltsdigest(self) -> str:
        """Fingerabdruck der Sicherung selbst — er darf nach aussen."""
        return digest_of(self.als_dokument())


def _ordner_bereit(ordner: Path) -> None:
    """Legt den Ablageort an und stellt 0700 sicher — oder scheitert."""
    ordner.mkdir(parents=True, exist_ok=True)
    os.chmod(ordner, _ORDNER_MODUS)
    st = ordner.lstat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != _ORDNER_MODUS:
        raise DeleteBackupUnverified(
            "Der Ablageort der Sicherung hat nicht die erwarteten Rechte")


def schreibe_sicherung(sicherung: FieldStateBackup, *,
                       basis: Path | str | None = None) -> str:
    """Schreibt die Sicherung, liest sie zurueck und verifiziert sie.

    Geschrieben wird ueber eine temporaere Datei im Zielverzeichnis mit
    anschliessendem `os.replace`: Ein abgebrochener Schreibvorgang hinterlaesst
    damit nie eine halbe Sicherung, die spaeter als ganze gelesen wuerde.

    Zurueckgegeben wird der Inhaltsdigest — er darf nach aussen, die Werte nie.

    Scheitert irgendein Schritt, wird typisiert abgewiesen. Ein „vermutlich
    geschrieben" gibt es hier nicht: Der ganze Zweck dieses Gates ist, dass
    hinterher jemand die Werte tatsaechlich vorfindet.
    """
    ziel = field_state_path(sicherung.mutation_id, basis=basis)
    _ordner_bereit(ziel.parent)
    dokument = sicherung.als_dokument()
    roh = json.dumps(dokument, ensure_ascii=False, sort_keys=True)

    temp = ziel.with_name(f".{ziel.name}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as datei:
            datei.write(roh)
            datei.flush()
            os.fsync(datei.fileno())
        os.chmod(temp, _DATEI_MODUS)
        os.replace(temp, ziel)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise DeleteBackupUnverified(
            "Die Sicherung konnte nicht geschrieben werden") from exc

    # Zurueckgelesen und verifiziert — nicht angenommen.
    try:
        zurueck = json.loads(ziel.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeleteBackupUnverified(
            "Die geschriebene Sicherung war nicht wieder lesbar") from exc
    if zurueck != dokument:
        raise DeleteBackupUnverified(
            "Die zurueckgelesene Sicherung weicht vom Geschriebenen ab")

    st = ziel.lstat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != _DATEI_MODUS:
        raise DeleteBackupUnverified(
            "Die Sicherung hat nicht die erwarteten Rechte")
    return sicherung.inhaltsdigest


def pruefe_sicherung(mutation_id: str, *, container_identifier: str,
                     provider_identifier: str, expected_fields_digest: str,
                     basis: Path | str | None = None) -> str:
    """Fail-closed: Liegt eine gueltige, an **diese** Loeschung gebundene Sicherung?

    Geprueft wird nicht, dass irgendeine Datei existiert, sondern dass die
    Sicherung genau dieses Ziel meint: dieselbe Mutation, derselbe Container,
    dieselbe Providerkennung und derselbe Vorzustandsdigest, an dem der
    Loeschpfad seinen einen Re-Read misst. Weicht eines davon ab, ist die
    Sicherung nicht die Sicherung dieses Loeschvorgangs.

    Zurueckgegeben wird der Inhaltsdigest zur Protokollierung. Die Feldwerte
    verlassen diese Funktion nicht.
    """
    ziel = field_state_path(mutation_id, basis=basis)
    try:
        roh = json.loads(ziel.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DeleteBackupMissing(
            "Fuer diese Loeschung liegt keine Sicherung vor") from exc
    except (OSError, ValueError) as exc:
        raise DeleteBackupUnverified(
            "Die Sicherung war nicht lesbar") from exc

    if not isinstance(roh, dict) or roh.get("contract") != FIELD_STATE_CONTRACT:
        raise DeleteBackupUnverified("Unbekannter Sicherungsvertrag")

    erwartet = {
        "mutationId": mutation_id,
        "containerIdentifier": container_identifier,
        "providerIdentifier": provider_identifier,
        "expectedFieldsDigest": expected_fields_digest,
    }
    for schluessel, wert in erwartet.items():
        if roh.get(schluessel) != wert:
            raise DeleteBackupUnverified(
                f"Die Sicherung ist nicht an dieses Ziel gebunden ({schluessel})")

    if not isinstance(roh.get("fields"), dict) or not roh["fields"]:
        # Eine Sicherung ohne Werte ist keine Sicherung. Sie saehe nur so aus.
        raise DeleteBackupUnverified("Die Sicherung enthaelt keine Feldwerte")

    st = ziel.lstat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != _DATEI_MODUS:
        raise DeleteBackupUnverified(
            "Die Sicherung hat nicht die erwarteten Rechte")
    return digest_of(roh)


# ── Der Weg von einer Vorgangszeile zur Sicherung ────────────────────────────
#
# Beide Ausfuehrungswege — der App-Prozess-Kanal und der aeltere Dienstweg —
# benutzen genau diese Funktionen. Zwei Fassungen desselben Gates waeren zwei
# Gates, und eines davon waere irgendwann das schwaechere.
@dataclass(frozen=True, slots=True)
class Loeschbindung:
    """Woran diese eine Loeschung haengt — aufgeloest, nicht erraten."""

    mutation_id: str
    container_identifier: str
    provider_identifier: str
    fields: Mapping[str, Any]
    expected_fields_digest: str


def loeschbindung(uow, zeile) -> Loeschbindung:
    """Ziel, Ablageort, Vorzustand und dessen Digest — aus der Vorgangszeile.

    Vorzustand und Digest kommen aus derselben Nutzlast, die der
    `payload_digest` deckt — also aus dem, was der Eigentuemer freigegeben hat.
    Ein Seitenkanal waere hier ein zweiter Vergleichsmassstab neben dem einen
    Re-Read.

    Der Ablageort steht bei einer Loeschung **nicht** auf der Vorgangszeile:
    Ein `delete` nennt keinen Container, es verschiebt nichts. Der richtige
    Wert steht in der bestehenden Identitaet und wird dort nachgesehen — wie
    schon in der Vorschau, damit die Sicherung denselben Ort nennt, den der
    Mensch gesehen hat.

    Fehlt der gebundene Vorzustand, gibt es nichts zu sichern — und ohne
    Sicherung keine Loeschung. Fail-closed, nicht „dann eben ohne".
    """
    try:
        roh = json.loads(zeile["payload_json"])
    except (TypeError, ValueError) as exc:
        raise DeleteBackupUnverified(
            "Die Nutzlast des Vorgangs war nicht lesbar") from exc
    if not isinstance(roh, dict):
        raise DeleteBackupUnverified("Die Nutzlast des Vorgangs ist unbrauchbar")
    vorher = roh.get("expectedPrevious")
    digest = roh.get("expectedFieldsDigest")
    if not isinstance(vorher, dict) or not vorher or not digest:
        raise DeleteBackupUnverified(
            "Der Vorgang traegt keinen gebundenen Vorzustand")

    ziel = zeile["target_provider_identifier"] or ""
    if not ziel:
        raise DeleteBackupUnverified("Der Vorgang nennt kein stabiles Ziel")

    container = zeile["container_identifier"] or ""
    if not container:
        bestehend = uow.execute(
            "SELECT container_identifier FROM contact_external_ids "
            "WHERE provider_account_id = ? AND provider_identifier = ?",
            (zeile["provider_account_id"], ziel)).fetchone()
        container = (bestehend["container_identifier"] if bestehend else "")
    if not container:
        # Ein Kontakt ohne bekannten Ablageort laesst sich nicht eindeutig
        # zuordnen — und was nicht zuzuordnen ist, wird nicht geloescht.
        raise DeleteBackupUnverified(
            "Der Ablageort des Loeschziels ist nicht bekannt")

    return Loeschbindung(
        mutation_id=zeile["mutation_id"], container_identifier=container,
        provider_identifier=ziel, fields=vorher,
        expected_fields_digest=digest)


def schreibe_loeschsicherung(bindung: Loeschbindung, *, at: str,
                             basis: Path | str | None = None) -> str:
    """Sichert den Feldstand des Loeschziels — schreiben, zuruecklesen, pruefen."""
    from personaljarvis.contacts.application.field_contract import (
        FIELD_CONTRACT_VERSION,
    )

    return schreibe_sicherung(FieldStateBackup(
        mutation_id=bindung.mutation_id,
        container_identifier=bindung.container_identifier,
        provider_identifier=bindung.provider_identifier,
        field_contract_version=FIELD_CONTRACT_VERSION,
        fields=bindung.fields,
        expected_fields_digest=bindung.expected_fields_digest,
        captured_at=at,
    ), basis=basis)


def pruefe_loeschsicherung(bindung: Loeschbindung, *,
                           basis: Path | str | None = None) -> str:
    """Fail-closed: ohne gueltige Sicherung geht diese Loeschung nicht weiter."""
    return pruefe_sicherung(
        bindung.mutation_id,
        container_identifier=bindung.container_identifier,
        provider_identifier=bindung.provider_identifier,
        expected_fields_digest=bindung.expected_fields_digest, basis=basis)
