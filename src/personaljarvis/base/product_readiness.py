"""Produktreife des Schreibpfads — die Ebene **über** jeder Freigabe.

Zwei Fragen, die nichts miteinander zu tun haben, wurden bisher als eine
behandelt:

1. **Darf dieses Modul grundsätzlich mutieren?** Das ist eine Aussage über den
   Bauzustand des Produkts: Ist der Schreibpfad fertig, geprüft und
   verantwortbar? Sie wird von der Entwicklung beantwortet.
2. **Hat der Eigentümer diese Mutation freigegeben?** Das ist eine Aussage
   über den Willen des Eigentümers. Sie wird von ihm beantwortet.

Solange beide in einer einzigen Prüfung steckten, konnte die zweite die erste
überstimmen: Eine formal einwandfreie Einzelfreigabe hätte einen Schreibpfad
geöffnet, dessen Bestand nachweislich Termine überschreibt. Genau das war der
Zustand, den der Befund vom 2026-08-17 offengelegt hat — `ENABLED_COMMANDS`
führte alle drei Kalenderoperationen, und „Calendar Write ist gesperrt"
beschrieb nur die Abwesenheit erteilter Freigaben, nicht ein Schloss.

Deshalb steht die Reife hier, vor der Freigabe und unabhängig von ihr. Eine
gültige Freigabe für ein nicht reifes Modul bleibt wirkungslos. Das ist kein
Misstrauen gegen den Eigentümer, sondern die ehrliche Reihenfolge: er kann
freigeben, was das Produkt kann — nicht, was es noch nicht kann.

**Diese Datei ist die einzige normative Stelle** für diese Aussage
(DEC-056 — Eine normative Stelle,
`docs/governance/decisions/DEC-056-eine-normative-stelle.md`). Kein zweiter
Schalter, keine Umgebungsvariable, keine Kopie im App-Prozess: Aufträge an den
Provider entstehen ausschliesslich im Kern, und der Kern liest hier.
"""

from __future__ import annotations

__all__ = [
    "PRODUCT_WRITE_READINESS",
    "ProductWriteReadiness",
    "product_write_ready",
    "readiness_reason",
]

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductWriteReadiness:
    """Reifezustand **einer** Fähigkeit, mit Begründung.

    Die Begründung ist Pflicht und kein Kommentar: Ein gesperrtes Modul ohne
    nachlesbaren Grund wird beim nächsten Aufräumen versehentlich geöffnet.
    """

    ready: bool
    reason: str


#: Der Bestand. Eine unbekannte Fähigkeit ist **nicht** reif — wer eine neue
#: einführt, trägt sie hier ein und entscheidet dabei bewusst.
PRODUCT_WRITE_READINESS: dict[str, ProductWriteReadiness] = {
    "contacts": ProductWriteReadiness(
        ready=True,
        reason="Nativer Schreibpfad mit Vorschau, Re-Read, Fingerprint und "
               "Zielcontainerbindung; x86_64 und arm64 abgeschlossen.",
    ),
    "calendar": ProductWriteReadiness(
        ready=False,
        reason="Der lokale Bestand bindet Termine ohne Vorkommensdiskriminator; "
               "zwei Vorkommen einer Serie ueberschreiben einander (Befund "
               "2026-08-17). Bis die Occurrence-Identity-Reparatur mechanisch "
               "gruen ist, entsteht kein Schreibauftrag — auch nicht mit "
               "gueltiger Einzelfreigabe. Geoeffnet wird ausschliesslich in B2.",
    ),
}


def product_write_ready(capability: str) -> bool:
    """Ob **diese** Fähigkeit überhaupt mutieren darf.

    Unbekannt heisst nicht reif. Ein Tippfehler im Aufrufer öffnet damit
    nichts, sondern schliesst.
    """
    eintrag = PRODUCT_WRITE_READINESS.get(capability)
    return bool(eintrag and eintrag.ready)


def readiness_reason(capability: str) -> str:
    """Der nachlesbare Grund — für Fehlermeldung und Bericht."""
    eintrag = PRODUCT_WRITE_READINESS.get(capability)
    if eintrag is None:
        return f"Fähigkeit '{capability}' ist im Reifebestand nicht geführt"
    return eintrag.reason
