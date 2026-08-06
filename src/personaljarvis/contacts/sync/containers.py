"""Containerinventar: geschlossener Typvorrat und Prüfung des Inventars.

Das Inventar ist ein **eigener Schritt** mit einer eigenen Wahrheit. Es sagt,
welche Ablageorte der Provider führt und welcher Art sie sind — mehr nicht. Es
sagt ausdrücklich *nicht*, dass Kontakte gelesen, ein Cursor gesetzt oder ein
Bestand abgeglichen wurde.

Warum das ein eigenes Modul ist: bis zum 2026-08-01 wurde die Art eines
Ablageorts zwar beim Inventar erhoben, aber erst beim erfolgreichen Abschluss
eines Laufs gespeichert. Ein `dropEverything` des Providers verwarf damit eine
gültige, bereits vorliegende Metainformation — und ohne sie liess sich der
lokale Ablageort nicht mehr von einem kontogebundenen unterscheiden. Genau
diese Unterscheidung ist aber die Grundlage jeder bewussten Zielwahl
(ADR-0025 §2): nicht Reihenfolge, nicht Kontaktzahl, nicht rohe Kennung.

Der Typvorrat ist geschlossen. Was der Provider ausserhalb davon meldet, wird
zu `unknown` — nie durchgereicht, nie geraten.
"""

from __future__ import annotations

from collections.abc import Iterable

from personaljarvis.contacts.sync.errors import InventoryInvalid

__all__ = [
    "CONTAINER_TYPE_UNKNOWN",
    "CONTAINER_TYPES",
    "SPECIFIC_CONTAINER_TYPES",
    "is_specific_container_type",
    "normalize_container_type",
    "validate_inventory",
]

#: Der einzige Wert, der „keine Auskunft" bedeutet. Er ist **kein** Typ und
#: darf nie eine bereits erhobene Auskunft ersetzen.
CONTAINER_TYPE_UNKNOWN = "unknown"

#: Ablageortarten, die eine echte Auskunft sind. Wortgleich mit dem, was der
#: Sidecar aus `CNContainerType` bildet, und wortgleich mit der Anzeige im
#: Frontend (`CONTAINER_ART`). Eine abweichende Schreibweise an einer der
#: Stellen wäre ein stiller Ausfall der Zielwahl.
SPECIFIC_CONTAINER_TYPES = frozenset({"local", "cardDAV", "exchange",
                                      "unassigned"})

#: Der vollständige öffentliche Vorrat.
CONTAINER_TYPES = SPECIFIC_CONTAINER_TYPES | {CONTAINER_TYPE_UNKNOWN}


def normalize_container_type(raw: str | None) -> str:
    """Providerangabe → geschlossener Vorrat.

    Ein unbekannter oder fehlender Wert wird zu `unknown`. Das ist bewusst
    **kein** Fehler: ein künftiger Ablageorttyp darf einen Lauf nicht
    verhindern. Er darf nur nicht als etwas anderes ausgegeben werden.
    """
    if raw is None:
        return CONTAINER_TYPE_UNKNOWN
    wert = raw.strip()
    return wert if wert in SPECIFIC_CONTAINER_TYPES else CONTAINER_TYPE_UNKNOWN


def is_specific_container_type(wert: str | None) -> bool:
    """Ist das eine echte Auskunft — oder nur die Abwesenheit einer?"""
    return wert in SPECIFIC_CONTAINER_TYPES


def validate_inventory(container: Iterable) -> dict[str, str]:
    """Prüft das Inventar und bildet Kennung → Art ab.

    Fail-closed in genau zwei Fällen, beide gleichbedeutend mit „das Inventar
    trägt keine verlässliche Aussage":

    1. Eine leere Containerkennung. Sie liesse sich weder wiederfinden noch
       maskieren.
    2. Dieselbe Kennung mit **widersprüchlicher** Art. Welche gilt, ist nicht
       entscheidbar, und es wird nichts geraten.

    Eine wortgleich doppelte Nennung ist dagegen nur redundant und wird zu
    einem Eintrag zusammengefasst — sie ist nicht mehrdeutig.

    Ein leeres Inventar ist hier kein Fehler: ob ein Konto ohne Ablageort ein
    Problem ist, entscheidet der jeweilige Lauf, nicht die Metadatenprüfung.
    """
    arten: dict[str, str] = {}
    for eintrag in container:
        kennung = (getattr(eintrag, "identifier", "") or "").strip()
        if not kennung:
            raise InventoryInvalid(
                "Das Containerinventar enthält einen Eintrag ohne Kennung",
                code="inventory_missing_identifier")
        art = normalize_container_type(getattr(eintrag, "type", None))
        vorhanden = arten.get(kennung)
        if vorhanden is not None and vorhanden != art:
            raise InventoryInvalid(
                "Dieselbe Containerkennung wurde mit zwei verschiedenen Arten "
                "gemeldet; es wird nichts geraten",
                code="inventory_ambiguous_type")
        arten[kennung] = art
    return arten
