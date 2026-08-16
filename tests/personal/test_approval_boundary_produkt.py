"""Die Freigabegrenze im **echten** Produktbaum — geschlossen, nicht ähnlich.

Die Wirkungsproben des Wächters stehen in `test_approval_boundary.py` und
laufen auf Fixtures. Hier steht, was für dieses Produkt gilt.

Zwei Aussagen, beide als Mengengleichheit — eine Teilmengenprüfung wäre von
einem leeren Scan nicht zu unterscheiden (Dauerregeln §9):

1. **Wer darf freigeben.** Genau die aufgeführten Dateien enthalten
   Aufrufstellen, die die Freigabegrenze erreichen. Eine neue Stelle
   irgendwo sonst fällt auf, gleichgültig wie die Funktion heisst.

2. **Execute erzeugt keine Freigabe.** Kein Blattsymbol erreicht beide
   Grenzen — Freigabe und Ausführung. Erlaubt sind allein die Verteiler, die
   getrennte Phasen nebeneinander beherbergen; sie tun in einem Lauf immer
   nur das eine oder das andere.

Gegen den Stand vor dem 2026-08-16 fallen beide Aussagen: dort riefen
`writeAdapter.fuehreAus`, `TerminFormular.anlegen` und
`TerminLoeschen.loeschen` die Freigabe im Ausführungsschritt selbst.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.guards.approval_boundary import (  # noqa: E402
    APPROVAL_MARKER,
    EXECUTE_MARKER,
    analysiere,
    coverage_limits,
)

_WURZEL = Path(__file__).resolve().parents[2] / "frontend" / "src"

#: Wer die Freigabegrenze erreichen darf — und warum.
ERLAUBTE_FREIGABEDATEIEN = {
    # ── Kontakte ────────────────────────────────────────────────────────────
    # Reine Durchreiche des Ports zur API, ohne eigene Entscheidung.
    "personal/contacts/data/source.ts",
    # Der Freigabeknopf der Vorschau.
    "personal/contacts/editor/dialogs.tsx",
    # Der Freigabeknopf des Boards.
    "personal/contacts/status/ContactsStatusSurface.tsx",
    # ── Kalender ────────────────────────────────────────────────────────────
    # `freigeben()` — gibt frei und tut sonst nichts.
    "personal/calendar/TerminFormular.tsx",
    "personal/calendar/TerminLoeschen.tsx",
    # ── Command Bar ─────────────────────────────────────────────────────────
    # `genehmige()` — der eine Freigabeweg des Adapters, beide Kanäle.
    "core/writeAdapter.ts",
    # Die Phase `approve` des Routers ruft ausschliesslich `genehmige`.
    "core/writeResolver.ts",
    # Die Eingabe des Menschen; sie reicht den Auftrag an den Router.
    "core/JarvisCommandBar.tsx",
    # ── Agentenfreigaben ────────────────────────────────────────────────────
    # Eine **andere** Fläche (`/v1/approvals/*`), nicht der Mutationskanal von
    # Kontakten und Kalender. Sie wird hier bewusst mitgeführt statt
    # weggeschnitten: Auch sie ist eine Eigentümerfreigabe, und ein zweiter
    # Aufrufer dort soll ebenso auffallen.
    "components/ApprovalBell.tsx",
}

#: Symbole, die beide Grenzen erreichen dürfen: Verteiler, keine Blätter.
#:
#: Sie beherbergen Freigeben und Ausführen als getrennte Zweige und wählen je
#: Lauf genau einen. Die Analyse kann das nicht unterscheiden — sie sieht nur
#: Erreichbarkeit —, deshalb stehen sie hier namentlich und einzeln begründet.
ERLAUBTE_VERTEILER = {
    # Der Phasenrouter: `approve` und `execute` sind zwei Zweige einer
    # Funktion, und `approve` verlässt sie, bevor `execute` beginnt.
    ("core/writeResolver.ts", "resolveWrite"),
    # Die Kommandozeile der Oberfläche: sie leitet JEDES Kommando weiter.
    ("core/JarvisCommandBar.tsx", "ausfuehren"),
    ("core/JarvisCommandBar.tsx", "aufFeldTaste"),
    # Die Dialoge: sie zeigen den Freigabe- und den Ausführungsknopf
    # nacheinander an; die zugehörigen Handler sind getrennt und disjunkt.
    ("personal/calendar/TerminFormular.tsx", "TerminFormular"),
    ("personal/calendar/TerminLoeschen.tsx", "TerminLoeschen"),
}

#: Die Blätter des Ausführungspfads. Keines darf die Freigabe erreichen —
#: das ist die G-Invariante, hier für beide Module.
AUSFUEHRUNGSBLAETTER = (
    ("core/writeAdapter.ts", "fuehreAus"),
    ("personal/calendar/TerminFormular.tsx", "ausfuehren"),
    ("personal/calendar/TerminLoeschen.tsx", "loeschen"),
)


@lru_cache(maxsize=2)
def _analyse(marker):
    return analysiere(_WURZEL, marker)


def _freigabe():
    return _analyse(APPROVAL_MARKER)


def test_die_grenze_wird_ueberhaupt_gefunden():
    """Ein leerer Scan ist kein Nachweis — die Saat muss da sein.

    Drei Endpunkte: der Mutationskanal von Kontakten und Kalender und die
    Agentenfreigabe. Verschwindet einer, ist der Wächter blind geworden und
    nicht das Produkt sauber.
    """
    saat = {(s.datei, s.name) for s in _freigabe().saat}
    assert saat == {
        ("personal/contacts/api.ts", "approveMutation"),
        ("personal/calendar/mutationsApi.ts", "gibFrei"),
        ("lib/api.ts", "approveAction"),
    }, sorted(saat)


def test_nur_die_erlaubten_dateien_erreichen_die_freigabe():
    ergebnis = _freigabe()
    gefunden = ergebnis.dateien_mit_aufrufstellen
    unerlaubt = gefunden - ERLAUBTE_FREIGABEDATEIEN
    assert not unerlaubt, "\n".join(
        str(a) for a in ergebnis.aufrufstellen if a.datei in unerlaubt)
    # Mengengleichheit: Verschwindet ein Einstieg, stimmt die Liste nicht mehr.
    assert gefunden == ERLAUBTE_FREIGABEDATEIEN, sorted(
        ERLAUBTE_FREIGABEDATEIEN - gefunden)


def test_der_ausfuehrungspfad_erreicht_die_freigabe_nicht():
    """Die G-Invariante — für Kalender **und** Kontakte.

    Vor dem 2026-08-16 waren alle drei `True`: `gibFrei` stand im
    Ausführungsschritt.
    """
    ergebnis = _freigabe()
    schuldig = [f"{d}::{n}" for d, n in AUSFUEHRUNGSBLAETTER
                if ergebnis.erreicht(d, n)]
    assert not schuldig, schuldig


def test_kein_blatt_erreicht_freigabe_und_ausfuehrung_zugleich():
    """Dieselbe Aussage, ohne eine einzige Funktion beim Namen zu nennen.

    Erreicht ein Symbol beide Endpunktfamilien, kann es in einem Lauf
    freigeben und senden. Erlaubt ist das nur den Verteilern.
    """
    freigabe = _freigabe()
    ausfuehrung = _analyse(EXECUTE_MARKER)
    beides = freigabe.erreichend & ausfuehrung.erreichend
    assert beides == ERLAUBTE_VERTEILER, sorted(beides ^ ERLAUBTE_VERTEILER)


def test_kontakte_bleiben_von_der_kalenderreparatur_unberuehrt():
    """Regression: Die drei Kontakt-Einstiege stehen unverändert."""
    ergebnis = _freigabe()
    for datei in ("personal/contacts/data/source.ts",
                  "personal/contacts/editor/dialogs.tsx",
                  "personal/contacts/status/ContactsStatusSurface.tsx"):
        assert ergebnis.stellen_in(datei), datei


def test_die_grenzen_der_aussage_stehen_dabei():
    """Diese Datei behauptet Geschlossenheit — also nennt sie ihre Reichweite."""
    assert coverage_limits()
