"""Der Wächter über die Freigabegrenze — und die Proben, die ihn beweisen.

Ein Wächter, der nur bei sauberem Code grün meldet, ist von einem Wächter,
der immer grün meldet, nicht zu unterscheiden. Geprüft wird deshalb je
einzeln, dass er **erkennt**: den direkten Aufruf, den umbenannten Import,
den deutsch benannten Wrapper, den englisch benannten Wrapper und eine
zusätzliche Aufrufstelle in einer sonst unauffälligen Datei.

**Alles auf einer Fixture.** Der Produktbaum wird hier nie verändert; jede
Probe baut ihren eigenen kleinen Modulbaum in `tmp_path`. Die Aussagen über
den echten Baum stehen in `test_approval_boundary_produkt.py`.

Der Kern der Reparatur: Die Saat wird am **Endpunkt** erkannt, nicht am
Bezeichner. Deshalb hilft Umbenennen nicht — was `A3` ausdrücklich prüft.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.guards.approval_boundary import (  # noqa: E402
    APPROVAL_MARKER,
    analysiere,
    coverage_limits,
)

#: Die Grenze selbst — ein Modul, das den Freigabe-Endpunkt anspricht. Der
#: Funktionsname ist bewusst nichtssagend: er darf für die Erkennung keine
#: Rolle spielen.
_GRENZE = """\
const ENTSCHEIDER = 'lukas';

export function xy7(mutationId: string): Promise<{ state: string }> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decision_actor: ENTSCHEIDER }),
  });
}

export function beanspruche(mutationId: string): Promise<Auftrag> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/claim-app-execution`,
              { method: 'POST' });
}
"""

#: Der einzige erlaubte Eigentümereinstieg der Fixture.
_ERLAUBT = """\
import { xy7 } from './grenze';

export function Freigabeknopf(vorgang: string) {
  return <button onClick={() => void xy7(vorgang)}>Freigeben</button>;
}
"""


def _baum(tmp_path: Path, **dateien: str) -> Path:
    wurzel = tmp_path / "src"
    wurzel.mkdir(exist_ok=True)
    (wurzel / "grenze.ts").write_text(_GRENZE, encoding="utf-8")
    (wurzel / "erlaubt.tsx").write_text(_ERLAUBT, encoding="utf-8")
    for name, inhalt in dateien.items():
        pfad = wurzel / name.replace("__", ".")
        pfad.write_text(inhalt, encoding="utf-8")
    return wurzel


def _dateien_mit_stellen(wurzel: Path) -> set[str]:
    return analysiere(wurzel).dateien_mit_aufrufstellen


# ═══ Grundlage ══════════════════════════════════════════════════════════════
def test_die_saat_wird_am_endpunkt_erkannt(tmp_path):
    """Nicht am Namen: `xy7` heisst nichts und ist trotzdem die Grenze."""
    ergebnis = analysiere(_baum(tmp_path))
    assert {(s.datei, s.name) for s in ergebnis.saat} == {("grenze.ts", "xy7")}


def test_a3_umbenennen_macht_den_waechter_nicht_blind(tmp_path):
    """A3: Aus `xy7` wird `ownerApprove` — die Erkennung darf sich nicht ändern.

    Das ist die Probe gegen die alte Fassung: Sie suchte `approveMutation(`
    und `.approve(` und wurde durch jedes Umbenennen blind.
    """
    wurzel = _baum(tmp_path)
    (wurzel / "grenze.ts").write_text(
        _GRENZE.replace("xy7", "ownerApprove"), encoding="utf-8")
    (wurzel / "erlaubt.tsx").write_text(
        _ERLAUBT.replace("xy7", "ownerApprove"), encoding="utf-8")
    ergebnis = analysiere(wurzel)
    assert {(s.datei, s.name) for s in ergebnis.saat} == {
        ("grenze.ts", "ownerApprove")}
    assert ergebnis.dateien_mit_aufrufstellen == {"erlaubt.tsx"}


def test_a9_die_erlaubte_stelle_bleibt_gruen(tmp_path):
    """A9: Der Wächter darf die legitime Eigentümerfreigabe nicht blockieren."""
    assert _dateien_mit_stellen(_baum(tmp_path)) == {"erlaubt.tsx"}


# ═══ Negativproben ══════════════════════════════════════════════════════════
def test_a4_direkter_aufruf_ausserhalb_wird_erkannt(tmp_path):
    """A4: Produktcode ruft die Grenze direkt, ausserhalb eines Einstiegs."""
    wurzel = _baum(tmp_path, ausfuehrung__ts="""\
import { xy7, beanspruche } from './grenze';

export async function fuehreAus(id: string) {
  await xy7(id);
  return beanspruche(id);
}
""")
    ergebnis = analysiere(wurzel)
    assert "ausfuehrung.ts" in ergebnis.dateien_mit_aufrufstellen
    stellen = ergebnis.stellen_in("ausfuehrung.ts")
    assert stellen, "die konkrete Callsite muss benannt sein"
    assert stellen[0].innerhalb == "fuehreAus"
    assert ergebnis.erreicht("ausfuehrung.ts", "fuehreAus")


def test_a5_ein_alias_umgeht_die_erkennung_nicht(tmp_path):
    """A5: `import { xy7 as andererName }` — die Importkante trägt die Grenze."""
    wurzel = _baum(tmp_path, schmuggel__ts="""\
import { xy7 as andererName } from './grenze';

export function heimlich(id: string) {
  return andererName(id);
}
""")
    ergebnis = analysiere(wurzel)
    assert ergebnis.erreicht("schmuggel.ts", "heimlich")
    assert "schmuggel.ts" in ergebnis.dateien_mit_aufrufstellen
    assert any(s.name == "andererName"
               for s in ergebnis.stellen_in("schmuggel.ts"))


def test_a6_ein_deutsch_benannter_wrapper_wird_verfolgt(tmp_path):
    """A6: `erteileFreigabe` → `gibFrei` → Grenze. Der Name ist gleichgültig."""
    wurzel = _baum(tmp_path, wrapper__ts="""\
import { xy7 } from './grenze';

export function gibFrei(id: string) {
  return xy7(id);
}

export function erteileFreigabe(id: string) {
  return gibFrei(id);
}
""", nutzer__ts="""\
import { erteileFreigabe } from './wrapper';

export async function ausfuehrenUndFreigeben(id: string) {
  await erteileFreigabe(id);
}
""")
    ergebnis = analysiere(wurzel)
    assert ergebnis.erreicht("wrapper.ts", "gibFrei")
    assert ergebnis.erreicht("wrapper.ts", "erteileFreigabe")
    assert ergebnis.erreicht("nutzer.ts", "ausfuehrenUndFreigeben")
    assert "nutzer.ts" in ergebnis.dateien_mit_aufrufstellen


def test_a7_ein_englisch_benannter_wrapper_wird_verfolgt(tmp_path):
    """A7: dieselbe Wirkung, andere Sprache — dasselbe Ergebnis."""
    wurzel = _baum(tmp_path, wrapper__ts="""\
import { xy7 } from './grenze';

export function grantApproval(id: string) {
  return xy7(id);
}

export function approveOwnerMutation(id: string) {
  return grantApproval(id);
}
""", nutzer__ts="""\
import { approveOwnerMutation } from './wrapper';

export async function run(id: string) {
  await approveOwnerMutation(id);
}
""")
    ergebnis = analysiere(wurzel)
    assert ergebnis.erreicht("wrapper.ts", "approveOwnerMutation")
    assert ergebnis.erreicht("nutzer.ts", "run")
    assert "nutzer.ts" in ergebnis.dateien_mit_aufrufstellen


def test_a8_eine_zusaetzliche_callsite_bricht_die_geschlossene_menge(tmp_path):
    """A8: die zentrale Wirkungsprobe.

    Eine sonst unauffällige Produktdatei bekommt eine Freigabe-Aufrufstelle.
    Die geschlossene erlaubte Menge stimmt danach nicht mehr, und die neue
    Stelle wird konkret benannt.
    """
    erlaubte_menge = {"erlaubt.tsx"}
    sauber = _baum(tmp_path)
    assert _dateien_mit_stellen(sauber) == erlaubte_menge

    (sauber / "unauffaellig.ts").write_text("""\
import { xy7 } from './grenze';

export function formatiereDatum(d: Date) {
  void xy7('nebenbei');
  return d.toISOString();
}
""", encoding="utf-8")

    ergebnis = analysiere(sauber)
    assert ergebnis.dateien_mit_aufrufstellen != erlaubte_menge
    neu = ergebnis.dateien_mit_aufrufstellen - erlaubte_menge
    assert neu == {"unauffaellig.ts"}
    assert ergebnis.stellen_in("unauffaellig.ts")[0].innerhalb == "formatiereDatum"


def test_ein_behaelter_ist_kein_freigeber(tmp_path):
    """Wer die Grenze nur weiterreicht, erreicht sie nicht selbst.

    Ohne diese Trennung würde jeder Aufrufer einer Portfabrik als Freigeber
    gelten — und die Aussage über den Ausführungspfad wäre wertlos.
    """
    wurzel = _baum(tmp_path, port__ts="""\
import { xy7 } from './grenze';

export function baueQuelle() {
  return {
    freigeben: (id: string) => xy7(id),
    lesen: (id: string) => id,
  };
}
""", leser__ts="""\
import { baueQuelle } from './port';

export function nurLesen(id: string) {
  return baueQuelle().lesen(id);
}
""")
    ergebnis = analysiere(wurzel)
    assert ergebnis.erreicht("port.ts", "freigeben")
    assert not ergebnis.erreicht("port.ts", "baueQuelle"), \
        "die Fabrik enthaelt die Grenze, sie ueberquert sie nicht"
    assert not ergebnis.erreicht("leser.ts", "nurLesen")


def test_a10_die_grenzen_der_analyse_sind_benannt():
    """A10: Keine Vollständigkeitsbehauptung ohne die Einschränkungen."""
    grenzen = coverage_limits()
    assert grenzen, "eine Analyse ohne benannte Grenzen behauptet zu viel"
    zusammen = " ".join(grenzen)
    for stichwort in ("import()", "berechnete Namen", "Typ des Objekts"):
        assert stichwort in zusammen


@pytest.mark.parametrize("marke", APPROVAL_MARKER)
def test_die_marken_sind_endpunktmarken_keine_namen(marke):
    """Die Saat hängt am Endpunkt — `gibFrei` selbst darf nirgends stehen."""
    assert "gibFrei" not in marke.pattern
    assert "approveMutation" not in marke.pattern


def test_eine_mehrzeilige_signatur_verliert_die_saat_nicht(tmp_path):
    """Der blinde Fleck vom 2026-08-16, gefunden beim Reparieren.

    `gibFrei` bekam einen zweiten Parameter und damit eine umbrochene
    Signatur mit generischem Rückgabetyp. Die Rumpferkennung hielt den
    Zeilenumbruch für das Ende einer Deklaration, lieferte einen leeren
    Rumpf — und die Grenze verschwand lautlos aus der Saat. Ein leerer
    Lesepfad, der Erfolg meldet (Dauerregeln §9).
    """
    wurzel = _baum(tmp_path)
    (wurzel / "grenze.ts").write_text("""\
export function xy7(mutationId: string, entscheider: string):
    Promise<{ mutation_id: string; state: string }> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decision_actor: entscheider }),
  });
}
""", encoding="utf-8")
    ergebnis = analysiere(wurzel)
    assert {(s.datei, s.name) for s in ergebnis.saat} == {("grenze.ts", "xy7")}
    assert ergebnis.dateien_mit_aufrufstellen == {"erlaubt.tsx"}


def test_ein_kommentar_ueber_die_grenze_ist_kein_aufruf(tmp_path):
    """Sonst macht die Erklärung der Reparatur den reparierten Pfad schuldig.

    Gemessen am 2026-08-16: Der Kommentar „bis heute stand hier
    `await gibFrei(...)`" im bereinigten Ausführungspfad liess ihn weiter
    als Freigeber gelten.
    """
    wurzel = _baum(tmp_path, ausfuehrung__ts="""\
export async function fuehreAus(id: string) {
  // Hier wird NICHT freigegeben. Bis 2026-08-16 stand hier `await xy7(id)`.
  /* Auch ein Blockkommentar, der xy7(id) nennt, ist kein Aufruf. */
  return id;
}
""")
    ergebnis = analysiere(wurzel)
    assert not ergebnis.erreicht("ausfuehrung.ts", "fuehreAus")
    assert "ausfuehrung.ts" not in ergebnis.dateien_mit_aufrufstellen


def test_eine_zeichenkette_mit_doppelslash_bleibt_lesbar(tmp_path):
    """Kommentare ausblenden darf keine URL zerschneiden — dort steht die Saat."""
    from tools.guards.approval_boundary import ohne_kommentare
    quelle = "const u = 'https://example.test/mutations/x/approve'; // Kommentar\n"
    sauber = ohne_kommentare(quelle)
    assert "/approve" in sauber
    assert "Kommentar" not in sauber
    assert len(sauber) == len(quelle)


# ═══ Die Verengung der Ausführungsmarke ═════════════════════════════════════
#
# `invoke(` hiess bis zum 2026-08-17 „an den App-Prozess uebergeben" und damit
# „ausfuehren" — es gab nur einen Grund, ihn zu rufen. Der Belegaufruf der
# Einzelfreigabe ist der zweite und sendet nichts. Die Ausnahme dafuer muss
# eng sein, sonst schluepft das naechste aehnlich benannte Kommando mit durch.
_BELEG = "personal_contacts_attest_owner_approval"


def _fuehrt_aus(tmp_path, quelle: str) -> bool:
    from tools.guards.approval_boundary import EXECUTE_MARKER

    wurzel = _baum(tmp_path, kandidat__ts=quelle)
    ergebnis = analysiere(wurzel, marker=EXECUTE_MARKER)
    return ergebnis.erreicht("kandidat.ts", "handle")


def test_der_belegaufruf_ist_keine_ausfuehrungsmarke(tmp_path):
    assert not _fuehrt_aus(tmp_path, f"""\
export async function handle(id: string) {{
  return invoke('{_BELEG}', {{ mutationId: id }});
}}
""")


def test_ein_zweiter_invoke_in_derselben_datei_zaehlt_weiterhin(tmp_path):
    """Die Auflage: Die Ausnahme gilt dem einen Aufruf, nicht der Datei.

    Ohne diese Probe waere die Verengung nur behauptet — eine Datei, die
    einmal belegt und daneben etwas ausfuehrt, muss die Ausfuehrungsgrenze
    weiterhin erreichen.
    """
    assert _fuehrt_aus(tmp_path, f"""\
export async function handle(id: string) {{
  await invoke('{_BELEG}', {{ mutationId: id }});
  return invoke('personal_contacts_execute_mutation', {{ id }});
}}
""")


@pytest.mark.parametrize("name", [
    _BELEG + "_extra",          # Praefix
    _BELEG + "2",
    "x" + _BELEG,               # Suffixlage
    _BELEG.upper(),
    _BELEG.replace("_", "-"),
])
def test_ein_aehnlicher_kommandoname_schluepft_nicht_mit_durch(tmp_path, name):
    """Exakt, nicht Praefix und nicht Teilstring."""
    assert _fuehrt_aus(tmp_path, f"""\
export async function handle(id: string) {{
  return invoke('{name}', {{ id }});
}}
""")


def test_die_ausnahme_gilt_auch_in_der_generischen_form(tmp_path):
    """`invoke<T>(...)` ist derselbe Aufruf mit Typangabe."""
    assert not _fuehrt_aus(tmp_path, f"""\
export async function handle(id: string) {{
  return invoke<Ergebnis>('{_BELEG}', {{ mutationId: id }});
}}
""")


def test_ein_fremdes_kommando_in_generischer_form_zaehlt(tmp_path):
    assert _fuehrt_aus(tmp_path, """\
export async function handle(id: string) {
  return invoke<Ergebnis>('personal_calendar_execute_mutation', { id });
}
""")
