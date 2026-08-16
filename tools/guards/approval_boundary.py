"""Wer im Frontend die Eigentümerfreigabe erreicht — und wer nicht.

**Warum es diese Datei gibt.** Der bisherige Wächter
(`test_keine_selbstfreigabe_irgendwo_in_der_oberflaeche`) suchte die
Zeichenketten `.approve(` und `approveMutation(` und behauptete daraus eine
geschlossene Menge zulässiger Freigabestellen. Er war blind für `gibFrei(` —
denselben Grenzübergang im Kalenderzweig. Ein Wächter, der über eine
Namensliste urteilt, ist selbst ein Fall der Fehlerklasse, gegen die er
gebaut wurde: Umbenennen genügt, um grün zu werden.

Dieses Modul urteilt deshalb nicht über Namen, sondern über **Erreichbarkeit**.

Der Weg in drei Schritten:

1. **Saat.** Gesucht wird die Stelle, an der tatsächlich eine Freigabe an das
   Backend geht — erkennbar am Endpunkt, nicht am Bezeichner. Drei Formen
   kommen im Produkt vor: der Pfad `/approve` in einem Template
   (`mutationsApi.gibFrei`, `lib/api.approveAction`) und die Aktionskonstante
   `'approve'`, die einem pfadbauenden Helfer übergeben wird
   (`contacts/api.approveMutation` → `decide(id, 'approve', actor)`).

2. **Hülle.** Von der Saat aus wird über den Modulgraphen geschlossen: Wer
   ein erreichendes Symbol importiert — auch unter anderem Namen —, wer es
   aufruft, wer es als Objekteigenschaft bindet, und wer diese Eigenschaft
   aufruft. Ein lokaler Wrapper erbt die Erreichbarkeit seines Rumpfes; ein
   umbenannter Import erbt sie über die Importkante. Der Name ist dabei nie
   das Kriterium.

3. **Urteil.** Zwei geschlossene Aussagen:
   * die Menge der Dateien mit Freigabe-Aufrufstellen ist **genau** die
     Allowlist — eine neue Stelle irgendwo sonst fällt auf;
   * die Symbole des **Ausführungspfads** erreichen die Grenze nicht. Das ist
     die eigentliche G-Invariante: Execute erzeugt keine Freigabe.

**Ein Aufruf ist nicht dasselbe wie ein Behälter.** `apiDataSource()` liefert
ein Objekt, dessen Eigenschaft `approve` die Grenze erreicht — die Funktion
selbst erreicht sie nicht. Deshalb zählt für jedes Symbol nur sein **eigener**
Rumpf; die Rümpfe darin geschachtelter Definitionen werden abgezogen. Ohne
diese Trennung würde jeder Aufrufer der Portfabrik als Freigeber gelten, und
die Aussage über den Ausführungspfad wäre wertlos.

**Was diese Analyse nicht kann** (Dauerregeln §6 — `unproven` ist nicht
`pass`): siehe `coverage_limits()`. Sie parst TypeScript nicht vollständig.
Eigenschaftszugriffe werden über den **Namen** aufgelöst, nicht über den Typ
des Objekts — bewusst überschätzend: lieber eine Fundstelle zu viel als eine
zu wenig.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Symbol",
    "Aufrufstelle",
    "Analyse",
    "APPROVAL_MARKER",
    "EXECUTE_MARKER",
    "analysiere",
    "ohne_kommentare",
    "coverage_limits",
]

#: Die Endpunktmarken der Freigabe. Sie stehen am Netzrand und überleben jedes
#: Umbenennen einer Funktion.
APPROVAL_MARKER = (
    re.compile(r"/approve\b"),                    # `/mutations/${id}/approve`
    # `decide(id, 'approve', actor)` — die Aktionskonstante zählt nur in
    # **Argumentposition**. Ein Feldwert wie `phase: 'approve'` benennt eine
    # Absicht und überquert keine Grenze; ohne diese Verengung galte der reine
    # Kommandorouter als Freigeber.
    re.compile(r"""[(,]\s*(['"])approve\1"""),
)

#: Die Marken des **Ausführungs**pfads — Claim, Provider-Execute und die
#: Übergabe an den App-Prozess. Damit lässt sich die eigentliche G-Invariante
#: formulieren, ohne eine Funktion beim Namen zu nennen: kein Blattsymbol darf
#: beide Grenzen erreichen.
EXECUTE_MARKER = (
    re.compile(r"/claim-app-execution\b"),
    re.compile(r"/execute\b"),
    re.compile(r"\binvoke\s*<"),
    re.compile(r"\binvoke\s*\("),
)

_QUELLDATEI = re.compile(r".*\.tsx?$")
_IST_TEST = re.compile(r"\.test\.|__tests__|\.spec\.")
_WORT = r"[A-Za-z_$][\w$]*"

_IMPORT_BLOCK = re.compile(
    r"import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", re.S)
_REEXPORT_BLOCK = re.compile(
    r"export\s+(?:type\s+)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", re.S)

_SCHLUESSELWORT = frozenset({
    "if", "for", "while", "switch", "catch", "return", "function", "const",
    "let", "var", "import", "export", "typeof", "await", "new", "do", "else",
    "type", "interface", "class", "case", "throw", "yield",
})

#: Definitionsformen. `art` unterscheidet freie Symbole von Objekteigenschaften
#: und Methoden — nur letztere machen ihren NAMEN zu einer Mitgliedsgrenze.
_DEFS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                r"function\s+(\w+)", re.M), "frei"),
    (re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::[^=\n]+)?=",
                re.M), "frei"),
    (re.compile(r"^[ \t]+(\w+)\s*:\s*(?:async\s+)?(?=\()", re.M), "mitglied"),
    (re.compile(r"^[ \t]+(?:async\s+)?(\w+)\s*(?=\()", re.M), "mitglied"),
)


@dataclass(frozen=True)
class Symbol:
    datei: str
    name: str
    zeile: int
    art: str
    #: Beginn des Definitionskopfes — vor Name, Parametern und Rückgabetyp.
    kopf: int
    #: Beginn des Rumpfes.
    anfang: int
    ende: int
    rumpf: str


@dataclass(frozen=True)
class Aufrufstelle:
    datei: str
    zeile: int
    name: str
    innerhalb: str

    def __str__(self) -> str:
        return (f"{self.datei}:{self.zeile} — "
                f"{self.innerhalb or '<modul>'} ruft {self.name}()")


@dataclass
class Analyse:
    saat: tuple[Symbol, ...] = ()
    erreichend: set[tuple[str, str]] = field(default_factory=set)
    mitgliedsgrenzen: set[str] = field(default_factory=set)
    aufrufstellen: tuple[Aufrufstelle, ...] = ()

    @property
    def dateien_mit_aufrufstellen(self) -> set[str]:
        return {a.datei for a in self.aufrufstellen}

    def erreicht(self, datei: str, name: str) -> bool:
        return (datei, name) in self.erreichend

    def stellen_in(self, datei: str) -> tuple[Aufrufstelle, ...]:
        return tuple(a for a in self.aufrufstellen if a.datei == datei)


def coverage_limits() -> tuple[str, ...]:
    """Was diese Analyse ausdrücklich **nicht** beweist."""
    return (
        "dynamisches import() wird nicht aufgeloest",
        "Aufrufe ueber berechnete Namen (obj[ausdruck]()) werden nicht aufgeloest",
        "ueber globalThis oder Closures weitergereichte Referenzen, die den "
        "Bezeichner unterwegs verlieren, werden nicht verfolgt",
        "Eigenschaftszugriffe werden ueber den Namen aufgeloest, nicht ueber "
        "den Typ des Objekts — bewusst ueberschaetzend",
        "nur relative Modulpfade werden aufgeloest; Paketimporte gelten als "
        "grenzenfrei",
    )


# ═══ Zerlegung ══════════════════════════════════════════════════════════════
def ohne_kommentare(text: str) -> str:
    """Kommentare durch Leerzeichen ersetzt — Länge und Zeilen bleiben gleich.

    **Warum das sein muss.** Der Wächter urteilt über Aufrufe. Ein Kommentar,
    der einen Aufruf *beschreibt* („bis 2026-08-16 stand hier
    `await gibFrei(...)`"), ist keiner. Ohne diesen Schritt machte
    ausgerechnet die Erklärung der Reparatur den reparierten
    Ausführungspfad wieder verdächtig — gemessen am 2026-08-16.

    **Zeichenketten bleiben stehen**, und zwar bewusst: In ihnen steht die
    Saat (`/mutations/${id}/approve`). Wer sie mitlöschte, verlöre die
    Grenze selbst. Der Scanner erkennt sie deshalb nur, um ein `//` darin
    (etwa in einer URL) nicht für einen Kommentar zu halten.

    Offsets bleiben erhalten, damit Zeilennummern und Symbolspannen weiter
    stimmen.
    """
    aus: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            grenze = c
            aus.append(c)
            i += 1
            while i < n:
                aus.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    aus.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == grenze:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                aus.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            while i < n and not (text[i] == "*" and i + 1 < n
                                 and text[i + 1] == "/"):
                aus.append("\n" if text[i] == "\n" else " ")
                i += 1
            for _ in range(min(2, n - i)):
                aus.append(" ")
            i += 2
            continue
        aus.append(c)
        i += 1
    return "".join(aus)


def _paare(text: str, i: int, auf: str, zu: str) -> int:
    """Index **hinter** der zu `text[i]` passenden schliessenden Klammer."""
    tiefe = 0
    n = len(text)
    while i < n:
        if text[i] == auf:
            tiefe += 1
        elif text[i] == zu:
            tiefe -= 1
            if tiefe == 0:
                return i + 1
        i += 1
    return n


def _block(text: str, i: int) -> tuple[int, int]:
    return i, _paare(text, i, "{", "}")


def _ausdruck(text: str, i: int) -> tuple[int, int]:
    """Ein Ausdrucksrumpf endet am Komma oder Semikolon auf Tiefe null."""
    tiefe = 0
    j = i
    n = len(text)
    while j < n:
        c = text[j]
        if c in "([{":
            tiefe += 1
        elif c in ")]}":
            if tiefe == 0:
                break
            tiefe -= 1
        elif c in ",;" and tiefe == 0:
            break
        j += 1
    return i, j


def _finde_koerper(text: str, i: int) -> tuple[int, int]:
    """Der Rumpf einer Definition, ab dem Punkt hinter ihrem Namen.

    Überspringt Generics und Parameterliste und erkennt, dass eine geschweifte
    Klammer **innerhalb** eines Rückgabetyps kein Rumpf ist — genau daran
    scheiterte die erste Fassung an
    `function gibFrei(id: string): Promise<{ … }> { … }` und hielt den
    Rückgabetyp für den Körper.
    """
    n = len(text)
    winkel = 0
    #: Gesetzt, sobald die Rückgabetyp-Annotation begonnen hat. Sie darf über
    #: Zeilen laufen — `function gibFrei(a: string, b: string):\n  Promise<…> {`
    #: hielt die erste Fassung sonst für eine Deklaration ohne Rumpf und
    #: verlor damit die Saat, die in diesem Rumpf steht.
    im_rueckgabetyp = False
    while i < n:
        c = text[i]
        if c == "(":
            i = _paare(text, i, "(", ")")
            continue
        if c == ":":
            im_rueckgabetyp = True
        if text.startswith("=>", i):
            i += 2
            while i < n and text[i] in " \t\r\n":
                i += 1
            if i < n and text[i] == "{":
                return _block(text, i)
            return _ausdruck(text, i)
        if c == "<":
            winkel += 1
        elif c == ">":
            winkel = max(0, winkel - 1)
        elif c == "{":
            if winkel > 0:
                i = _paare(text, i, "{", "}")
                continue
            return _block(text, i)
        elif c == ";" and winkel == 0:
            return i, i          # Signatur ohne Rumpf (Interface, Deklaration)
        elif (c == "\n" and winkel == 0 and not im_rueckgabetyp
                and text[i - 1:i] not in {"=", ",", "("}):
            nach = text[i:i + 200].lstrip()
            if not nach.startswith(("{", "=>", ":", ")", "|", "&")):
                return i, i
        i += 1
    return n, n


def _quelldateien(wurzel: Path) -> list[Path]:
    return sorted(p for p in wurzel.rglob("*")
                  if p.is_file() and _QUELLDATEI.match(p.name)
                  and not _IST_TEST.search(p.name))


def _symbole(text: str, rel: str) -> list[Symbol]:
    gefunden: dict[tuple[str, int], Symbol] = {}
    for muster, art in _DEFS:
        for treffer in muster.finditer(text):
            name = treffer.group(1)
            if name in _SCHLUESSELWORT:
                continue
            anfang, ende = _finde_koerper(text, treffer.end())
            if ende <= anfang:
                continue
            zeile = text.count("\n", 0, treffer.start()) + 1
            schluessel = (name, zeile)
            if schluessel not in gefunden:
                gefunden[schluessel] = Symbol(rel, name, zeile, art,
                                              treffer.start(), anfang, ende,
                                              text[anfang:ende])
    return sorted(gefunden.values(), key=lambda s: s.anfang)


def _eigener_rumpf(sym: Symbol, alle: list[Symbol]) -> str:
    """Der Rumpf ohne die geschachtelten Definitionen — **samt ihrer Köpfe**.

    Geschnitten wird ab `kopf`, nicht ab `anfang`: Der Kopf einer
    Objektmethode (`async genehmige(v, e): Promise<void> {`) sähe sonst im
    Rumpf der umschliessenden Fabrik wie ein Aufruf `genehmige(...)` aus —
    und machte jede Portfabrik zur Freigeberin. Gemessen am 2026-08-16 an
    `produktiverWritePort`.
    """
    stuecke: list[str] = []
    zeiger = sym.anfang
    for anderes in alle:
        if anderes is sym or anderes.kopf <= sym.anfang or anderes.ende > sym.ende:
            continue
        if anderes.kopf < zeiger:
            continue
        stuecke.append(sym.rumpf[zeiger - sym.anfang:anderes.kopf - sym.anfang])
        zeiger = anderes.ende
    stuecke.append(sym.rumpf[zeiger - sym.anfang:])
    return "".join(stuecke)


def _aufloesen(spezifizierer: str, von: Path, wurzel: Path) -> str | None:
    if not spezifizierer.startswith("."):
        return None
    ziel = (von.parent / spezifizierer).resolve()
    for kandidat in (Path(str(ziel) + ".ts"), Path(str(ziel) + ".tsx"),
                     ziel / "index.ts", ziel / "index.tsx"):
        if kandidat.is_file():
            try:
                return str(kandidat.relative_to(wurzel))
            except ValueError:
                return None
    return None


def _einfuhren(text: str, datei: Path, wurzel: Path) -> list[tuple[str, str, str]]:
    kanten: list[tuple[str, str, str]] = []
    for muster in (_IMPORT_BLOCK, _REEXPORT_BLOCK):
        for treffer in muster.finditer(text):
            quelle = _aufloesen(treffer.group(2), datei, wurzel)
            if quelle is None:
                continue
            for stueck in treffer.group(1).split(","):
                stueck = stueck.strip()
                if not stueck:
                    continue
                teile = re.split(r"\s+as\s+", stueck)
                original, lokal = teile[0].strip(), teile[-1].strip()
                if original and lokal:
                    kanten.append((lokal, quelle, original))
    return kanten


def _gerufene(rumpf: str) -> tuple[set[str], set[str]]:
    """(freie Aufrufe, Mitgliedsaufrufe).

    Getrennt, weil sie verschieden aufgelöst werden: Ein freier Aufruf
    verlangt eine sichtbare Bindung in dieser Datei — Import oder lokale
    Definition. Ein Mitgliedsaufruf (`api.approveMutation(…)`,
    `quelle.approve(…)`) wird über den **Namen** aufgelöst, weil der Typ des
    Objekts hier nicht bekannt ist. Das deckt Namensraum-Importe und das
    Portmuster gleichermassen und überschätzt bewusst.
    """
    frei = set(re.findall(rf"(?<![.\w$])({_WORT})\s*\(", rumpf))
    mitglied = set(re.findall(rf"\.({_WORT})\s*\(", rumpf))
    return frei, mitglied


def _weitergereicht(rumpf: str) -> set[str]:
    """Referenzen ohne Aufruf — `onClick={gibFrei}` oder `x = gibFrei`."""
    return set(re.findall(rf"[:=]\s*({_WORT})\s*[,;)}}\]\n]", rumpf))


# ═══ Analyse ════════════════════════════════════════════════════════════════
def analysiere(wurzel: Path,
               marker: tuple[re.Pattern[str], ...] = APPROVAL_MARKER) -> Analyse:
    """Erreichbarkeit einer Grenze. `marker` benennt sie am Endpunkt."""
    wurzel = wurzel.resolve()
    dateien = _quelldateien(wurzel)
    texte: dict[str, str] = {}
    symbole: dict[str, list[Symbol]] = {}
    eigen: dict[tuple[str, str, int], str] = {}
    einfuhren: dict[str, list[tuple[str, str, str]]] = {}

    for pfad in dateien:
        rel = str(pfad.relative_to(wurzel))
        text = ohne_kommentare(pfad.read_text(encoding="utf-8"))
        texte[rel] = text
        liste = _symbole(text, rel)
        symbole[rel] = liste
        einfuhren[rel] = _einfuhren(text, pfad, wurzel)
        for sym in liste:
            eigen[(rel, sym.name, sym.zeile)] = _eigener_rumpf(sym, liste)

    saat = tuple(sym for rel, liste in symbole.items() for sym in liste
                 if any(m.search(eigen[(rel, sym.name, sym.zeile)])
                        for m in marker))

    erreichend: set[tuple[str, str]] = {(s.datei, s.name) for s in saat}
    mitglieder: set[str] = {s.name for s in saat if s.art == "mitglied"}

    geaendert = True
    while geaendert:
        geaendert = False
        #: Alle erreichenden Namen — die Auflösung von Mitgliedsaufrufen.
        namen = {n for (_d, n) in erreichend} | mitglieder
        for rel, liste in symbole.items():
            sichtbar = {n for (d, n) in erreichend if d == rel}
            for (lok, quelle, orig) in einfuhren.get(rel, ()):
                if (quelle, orig) in erreichend:
                    sichtbar.add(lok)
            for sym in liste:
                if (rel, sym.name) in erreichend:
                    continue
                rumpf = eigen[(rel, sym.name, sym.zeile)]
                frei, mitglied = _gerufene(rumpf)
                if (frei & sichtbar) or (mitglied & namen) \
                        or (_weitergereicht(rumpf) & sichtbar):
                    erreichend.add((rel, sym.name))
                    if sym.art == "mitglied":
                        mitglieder.add(sym.name)
                    geaendert = True

    namen = {n for (_d, n) in erreichend} | mitglieder
    stellen: list[Aufrufstelle] = []
    for rel, text in texte.items():
        sichtbar = {n for (d, n) in erreichend if d == rel}
        for (lok, quelle, orig) in einfuhren.get(rel, ()):
            if (quelle, orig) in erreichend:
                sichtbar.add(lok)
        muster = [
            # Freier Aufruf: verlangt eine sichtbare Bindung in dieser Datei.
            (re.compile(rf"(?<![.\w$])({'|'.join(map(re.escape, sorted(sichtbar)))})"
                        rf"\s*\(") if sichtbar else None),
            # Mitgliedsaufruf: über den Namen aufgelöst, dateiübergreifend.
            (re.compile(rf"\.({'|'.join(map(re.escape, sorted(namen)))})\s*\(")
             if namen else None),
        ]
        for m in muster:
            if m is None:
                continue
            for treffer in m.finditer(text):
                if _ist_kommentar(text, treffer.start()):
                    continue
                if _ist_definition(text, treffer.start(), symbole[rel]):
                    continue
                if _ist_signatur(text, treffer.end() - 1):
                    continue
                zeile = text.count("\n", 0, treffer.start()) + 1
                stellen.append(Aufrufstelle(
                    rel, zeile, treffer.group(1),
                    _umgebendes_symbol(symbole[rel], treffer.start())))
    return Analyse(saat, erreichend, mitglieder,
                   tuple(sorted(stellen, key=lambda a: (a.datei, a.zeile))))


def _ist_kommentar(text: str, position: int) -> bool:
    anfang = text.rfind("\n", 0, position) + 1
    return text[anfang:position].lstrip().startswith(("//", "*", "/*"))


_NUR_MODIFIKATOREN = re.compile(
    r"[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+|const\s+|let\s+|var\s+)?")


def _ist_definition(text: str, position: int, liste: list[Symbol]) -> bool:
    """Der Kopf einer Definition ist kein Aufruf ihrer selbst.

    Positionsgenau, nicht zeilenweise: In
    `approve: (id, actor) => api.approveMutation(id, actor),` ist der Kopf
    ein Definitionsbeginn, der Aufruf dahinter aber eine echte Fundstelle.
    Eine zeilenweise Prüfung verschluckte beides.
    """
    anfang = text.rfind("\n", 0, position) + 1
    return bool(_NUR_MODIFIKATOREN.fullmatch(text[anfang:position]))


def _ist_signatur(text: str, klammer: int) -> bool:
    """`approve(id: string): Promise<unknown>;` in einem Interface ist kein Aufruf.

    Erkennungsmerkmal ist die **Rückgabetyp-Annotation**, nicht das
    Semikolon: `gibFrei(id);` ist ein Aufruf und sah der ersten Fassung wie
    eine Deklaration aus — sie verschwieg damit genau die drei Stellen, um
    die es hier geht.
    """
    hinter = _paare(text, klammer, "(", ")")
    return text[hinter:hinter + 4].lstrip().startswith(":")


def _umgebendes_symbol(liste: list[Symbol], position: int) -> str:
    treffer, engste = "", None
    for sym in liste:
        if sym.anfang <= position < sym.ende:
            weite = sym.ende - sym.anfang
            if engste is None or weite < engste:
                engste, treffer = weite, sym.name
    return treffer
