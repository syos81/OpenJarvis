# Kontakte — zwei latente Befunde, festgehalten statt repariert

**Stand:** 2026-08-17, Intel MacBook Air (x86_64, macOS 12.7.6)
**Zweig:** `feature/everyday-readiness-v1-2026-08-16`

Beide Befunde sind beim Bau des Kontingentzählers und des Löschgates
aufgefallen. Beide sind ausdrücklich **nicht** repariert worden — sie stehen
hier, damit sie nicht ein drittes Mal von jemandem neu entdeckt werden.

## B-1 · `PATCH /{contact_id}` schluckt jedes Pfadsegment

**Was.** Die Kontaktroute `PATCH /v1/personal/contacts/{contact_id}` bindet
jedes Segment an ihren Pfadparameter. `PATCH …/write-quota`,
`PATCH …/capabilities` und `PATCH …/categories` landen deshalb nicht bei einem
`405 Method Not Allowed`, sondern in der Vorbereitung einer Kontaktänderung
und scheitern dort mit `422` an der Nutzlast.

**Gemessen.** Alle drei Leserouten verhalten sich gleich: `POST`, `PUT` und
`DELETE` ergeben `405`, `PATCH` ergibt `422`.

**Warum es heute nichts aufreisst.** Der Aufruf erreicht einen Weg, der die
betroffene Ressource gar nicht kennt: Die Kontingentzeile wird dabei nicht
berührt, und ein Vorgang entsteht nicht, weil die Nutzlastprüfung vorher
greift. Der Befund ist eine Unsauberkeit der Routenform, keine offene Tür.

**Was daraus nicht folgen darf.** Kein Test darf für diese Pfade ein `405`
behaupten — das gäbe es nicht, und die Zusicherung wäre falsch.
`tests/personal/contacts/test_write_quota.py::test_die_route_ist_nur_lesend`
sagt den gemessenen Zustand und prüft stattdessen das, worauf es ankommt:
Keiner dieser Wege bewegt den Stand.

**Nicht heute.** Eine Reparatur hiesse, die Kontaktroute auf eine engere
Pfadform festzulegen (etwa eine Kennungsgestalt im Routenmuster). Das berührt
jede Leseroute des Moduls und gehört in einen eigenen Block.

## B-2 · Kein Gate-Block deckt das Kontaktmodul ab

**Was.** `config/gates/blocks/` kennt vierzehn Blöcke — Kalender, Governance,
Tooling. Keiner davon nimmt `src/personaljarvis/contacts/**` oder
`frontend/src/personal/contacts/**` in seinen Umfang. `scripts/gate.sh` hat
für dieses Modul also nichts zu prüfen.

**Folge.** Die Prüfung des Kontaktzweigs sind heute die Suiten
(`tests/personal/contacts`, `frontend … src/personal/contacts`, `tsc`,
`ruff`). Das ist der Stand, in dem auch die vorangegangenen Blöcke dieses
Zweigs abgeschlossen wurden.

**Was daraus nicht folgen darf.** Ein Gatelauf gegen einen Kalenderblock ist
kein Beleg für das Kontaktmodul. Ein Bericht, der ein `pass` eines fremden
Blocks als Kontaktbeleg führt, wäre eine stärkere Behauptung als die Messung.

**Nicht heute.** Ein eigener Block braucht Umfang, Phasenzuschnitt und eine
Merkmalslinie; das ist eine Governance-Handlung und keine Nebenarbeit.

## B-3 · Die Löschsicherung deckt den Feldvertrag v1 — und der ist enger als ein Kontakt

**Die Frage.** Deckt der Vergleich, an dem die Löschung hängt, genau die
Felder ab, die die Sicherung speichert? Geprüft wurde in beide Richtungen.

**Kein Überhang.** Was in der Sicherung steht, wird auch verglichen. Die
Sicherung trägt `expectedPrevious` unverändert; der Digest ist
`digest_of({"fieldContractVersion": 1, "fields": <ebendieses Wörterbuch>})`;
der native Pfad rechnet dieselbe Formel nach (`vorzustand_ist_gebunden`) und
vergleicht dann mit `[ist isEqualToDictionary:erwartetVorher]` — einer
**vollständigen** Wörterbuchgleichheit über beide Schlüsselmengen. Ein Feld,
das nur mitgeschrieben und nicht erzwungen wäre, gibt es nicht.

**Der Unterschuss — das ist die Lücke.** Ein Kontakt trägt mehr, als v1 kennt.
Weder in `expectedPrevious` noch in der Sicherung noch im Vergleich stehen:

| Familie | Zustand bei Jarvis |
|---|---|
| `social_profiles` | gelesen (`sidecar.swift`), lokal in `contact_social_profiles` |
| `instant_messages` | gelesen, lokal in `contact_instant_messages` |
| `relations` | gelesen, lokal in `contact_relations` |
| Foto (`image_available`, `thumbnail_blob_ref`) | gelesen, lokal in `contacts` |
| `note` | nie gelesen — `unavailable_by_capability` (Entitlement seit macOS 11) |

Bei den ersten vier ist der Verlust real und nicht theoretisch: Jarvis liest
sie und hält sie lokal, aber eine Wiederherstellung aus der Sicherung bringt
sie nicht zurück, und der lokale Spiegel wird beim Löschen getombstonet.

**Was daraus folgt.** „Kontaktinhalt wiederherstellbar" gilt für den
Feldvertrag v1 — nicht für alles, was an einem Kontakt hängt. Die
Oberflächentexte zählen deshalb auf, was gesichert wird, und nennen
ausdrücklich, was nicht: Ein pauschales „die Feldwerte" verspräche direkt vor
einer nicht rücknehmbaren Handlung mehr, als es hält.

**Nicht heute entschieden.** Ob die Sicherung über v1 hinaus greifen soll, ist
eine Eigentümerentscheidung. Sie berührt den Feldvertrag, und der ist
unverändert.

Mechanisch festgehalten in `tests/personal/contacts/test_delete_gate.py`,
Abschnitt G.

## B-4 · Dieselbe Tooling-Suite scheitert auf zwei Rechnern verschieden oft

**Was.** `tests/tooling` meldet auf dem Intel MacBook Air (x86_64,
macOS 12.7.6) **fünf** Fehlschläge, auf dem M2 **vierzehn** — jeweils am
Commitstand und jeweils mit `git stash` gegengeprüft, also in beiden Fällen
ohne die laufende Arbeit.

**Die fünf hier gemessenen:**

* `test_ast_dispositions.py::TestTheRealRegister::test_detected_candidates_equal_disposed_candidates`
* `test_governance.py::TestCollisionRegistry::test_no_collision_is_detected_any_more`
* `test_governance.py::TestCollisionRegistry::test_the_runner_accepts_the_resolved_state`
* `test_governance.py::TestQualifiedReferences::test_every_governance_document_is_qualified`
* `test_merge_readiness.py::TestReadinessChecks::test_the_resolved_collisions_no_longer_block_the_integration`

Alle fünf liegen in der Ecke der bekannten DEC-Doppelvergaben, die
ausdrücklich dokumentiert und nicht bereinigt wird.

**Warum der Unterschied selbst ein Befund ist.** Die Dauerregel verlangt
deterministische Testzustände. Eine Suite, deren Ergebnis vom Zustand des
Entwicklerrechners abhängt, liefert keinen vergleichbaren Ausgangswert: Ein
Bericht kann dann weder „unverändert rot" noch „neu rot" belegen, ohne den
Rechner mitzunennen.

**Was daraus folgt.** Jede Angabe zu vorbestehend roten Tooling-Tests nennt
den Rechner, auf dem sie gemessen wurde. Eine Zahl ohne Rechner ist keine
Angabe.

**Nicht heute.** Die Ursache ist nicht erhoben. Sie zu suchen heisst, beide
Rechner gegeneinander zu vermessen — ein eigener Arbeitsblock.

## B-5 · Das Paket trägt keinen Python-Kern — der Startort entscheidet, welcher Code läuft

**Was.** `Jarvis.app` enthält vier Mach-O-Dateien (`openjarvis-desktop`, den
Schreibhelfer, beide Sidecars) und **kein** Python. Der Kern wird zur Laufzeit
aus einem Projektordner gestartet (`uv run jarvis serve`). Welcher das ist,
entscheidet `find_project_root()` in `frontend/src-tauri/src/lib.rs` in dieser
Reihenfolge:

1. `OPENJARVIS_ROOT`, falls gesetzt und mit `pyproject.toml`
2. Aufstieg vom Programm aus, bis zu 14 Ebenen, bis ein `pyproject.toml` liegt
3. Rückfall auf feste Pfade — der erste davon ist `~/OpenJarvis`

**Die Gefahr.** Aus dem Bauordner heraus gestartet trägt Schritt 2: Von
`…/target/x86_64-apple-darwin/release/bundle/macos/Jarvis.app/Contents/MacOS`
sind es elf Ebenen bis zum Worktree — innerhalb der Grenze. Dann läuft der
Kern dieses Zweigs.

Aus `/Applications` heraus gestartet trägt Schritt 2 **nicht**: Über
`Contents`, `Jarvis.app`, `/Applications` liegt kein `pyproject.toml`. Dann
greift Schritt 3.

**Gemessen am 2026-08-17 auf dem Intel:** `~/OpenJarvis` existiert, steht auf
`main` bei `ed01ab8` und enthält weder `delete_gate.py` noch den
Kontingentzähler. Ein aus `/Applications` gestarteter Build spräche also mit
einem Kern **ohne Löschgate** — und zwar ohne sichtbaren Unterschied an der
Oberfläche.

**Was daraus folgt.** Der Livetest wird ausschliesslich aus dem Bauordner
gestartet, oder mit ausdrücklich gesetztem `OPENJARVIS_ROOT`. Vor einem echten
Delete wird geprüft, welchen Ordner der laufende Prozess benutzt — nicht
angenommen, dass es der richtige ist. Ein Delete gegen einen Kern ohne Gate
wäre genau der Fall, gegen den das Gate gebaut wurde.

**Nebenbefund.** In `/Applications` liegt bereits eine `Jarvis.app`, aber eine
andere: Version 0.1.0 vom 26.07. mit `jarvis-shell` und
`jarvis-credential-helper` statt `openjarvis-desktop`. Ein Installationslauf
des neuen DMG würde sie ersetzen. Das ist eine Eigentümerentscheidung und
heute nicht getroffen.

**Nicht heute.** Ein Paket, das seinen Kern selbst mitbringt, oder ein
Startpfad, der ohne passenden Ordner ehrlich abbricht statt einen fremden zu
nehmen, sind beides eigene Arbeitsblöcke.

## B-6 · Es gibt nichts zu ersetzen — die Schrift ist eine Größenfrage

**Nachtrag vom 2026-08-18**, gemessen an der laufenden Oberfläche per
`getComputedStyle`, nicht aus dem Stylesheet gelesen.

**Die Familie stimmt.** `body` rechnet auf
`system-ui, -apple-system, "system-ui", "Segoe UI", sans-serif`, und
`system-ui` zeichnet tatsächlich — eine Breitenprobe über `Handgloves` bei
100 px trennt es sauber von der Rückfallschrift (495,6 px gegen 476,1 px).
Es fehlt keine Schrift zur Laufzeit: `document.fonts` enthält ausschliesslich
die zwanzig KaTeX-Gesichter, alle im Zustand `unloaded`. Kein `@font-face`
des Produkts, keine Webfont, kein Ladefehler.

**Eine Korrektur am bisherigen Befund.** `@fontsource-variable/geist` steht
sehr wohl in `frontend/package.json` und liegt installiert in
`node_modules/`. Es wird nur **nirgends importiert** — nicht in `src/`, nicht
in `index.html`, nicht in der Vite-Konfiguration. Die Breitenprobe bestätigt
es: `Geist` und `Geist Variable` messen exakt wie die Rückfallschrift, sind
also nicht vorhanden. Der Befund „keine Webfont im Baum" trifft im Ergebnis
zu; die Ursache ist aber nicht Abwesenheit, sondern eine verdrahtete
Abhängigkeit ohne Verdrahtung. Ob Geist einmal gewollt war, ist damit eine
offene Frage — und eine Eigentümerentscheidung, weil ihre Beantwortung das
Aussehen der ganzen Anwendung ändert.

**Was tatsächlich klein ist.** Auf `/contacts` gemessen, 22 Textknoten:

| Fläche | Grösse | Gewicht |
|---|---|---|
| Seitentitel „Kontakte" | 15 px | 600 |
| Abschnittstitel „Alle Kontakte", „Quelle & Status" | 13 px | 600 |
| Fliesstext | 14 px | 400 |
| Tastenkürzel | 10 px | 400 |

Auf der Startfläche, 45 Textknoten: 26 davon liegen bei **12 px oder
darunter**, der grösste Wert ausser einem einzelnen Titel ist 14 px.

Die Hypothese `0.8125rem` trifft zu — sie ist `--pjc-font-title` und
`--pjc-font-body` in `frontend/src/personal/contacts/tokens.css` und ergibt
13 px. Sie trifft aber nicht den Seitentitel (15 px) und nicht den Fliesstext
der Anwendung (14 px).

**Der eigentliche Befund ist die fehlende Staffelung.** Titel 15 px,
Abschnitt 13 px, Fliesstext 14 px — alles liegt in einem Zwei-Pixel-Band, und
unterschieden wird fast nur über das Gewicht. Dazu läuft
`letter-spacing: -0.01em` von `body` (`index.css:278`) auf **jeden**
Textknoten durch, auch auf die mit 9 bis 12 px; gemessen wurden −0,16 px
überall. Negative Laufweite gehört auf grosse Schrift, nicht auf 10-px-Text.

**Was daraus folgt.** Es ist eine Feinjustierung an Grösse und Laufweite,
keine Schriftersetzung. Welche Staffelung richtig ist, ist eine
Gestaltungsentscheidung und berührt jede Fläche der Anwendung; sie wird
deshalb heute nicht einseitig gesetzt.

**Grenze dieser Messung.** Gemessen im Vorschaufenster (Chromium), nicht in
der ausgelieferten `WKWebView`. Rechenwerte aus `rem`-Arithmetik und
Kaskadenregeln übertragen sich; welche Glyphen `system-ui` dort zeichnet,
kann abweichen und ist hier nicht belegt.

## B-7 · Zweimal derselbe Vorsatz, zwei verschiedene Schriften

**Was.** Die technische Kennung („Code: …") wird an zwei Stellen gesetzt, mit
denselben zwei Eigenschaften in **umgekehrter** Reihenfolge:

* `frontend/src/personal/contacts/status/ContactsStatusSurface.tsx:140`
  — `fontFamily: 'monospace'`, **danach** `font: 'var(--pjc-font-label)'`
* `frontend/src/personal/contacts/editor/dialogs.tsx:36–37`
  — `font: 'var(--pjc-font-label)'`, **danach** `fontFamily: 'monospace'`

**Gemessen** am 2026-08-18, beide Schreibweisen zur Laufzeit gegeneinander
gestellt und per `getComputedStyle` gelesen:

| Stelle | gerechnete Familie | Grösse |
|---|---|---|
| Statusfläche | `system-ui` | 12 px |
| Dialog | `monospace` | 12 px |

Die Kurzform `font` setzt `font-family` mit zurück. Wer sie **nach** der
Familie schreibt, verliert die Familie; wer sie davor schreibt, behält sie.
Beide Male steht dasselbe im Quelltext, beide Male ist dasselbe gemeint, und
es kommt Verschiedenes heraus.

**Nicht angefasst.** Ob an diesen Stellen Monospace gewollt war, ist eine
Gestaltungsfrage und wird bei der Sichtprüfung der Statusfläche entschieden.
Die Reparatur ist danach ein Einzeiler — in die eine oder die andere
Richtung, aber in beiden Dateien gleich.
