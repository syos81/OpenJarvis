# B0g Handoff — Regelkodifizierung: dreizehn Entscheidungen auf dem echten Register

Alle Aussagen stammen aus maschinellen Gate-Ergebnissen
(`.gate-runtime/results/b0g-rule-codification.*.json`, gebunden als
sanitierte Schnappschüsse unter
`config/gates/evidence/b0g-rule-codification/`), aus Git-Daten, aus der
Werkzeugausgabe des Reservierungsregisters und aus den committeten
deklarativen Artefakten.

## §1 Rahmen

- Worktree mechanisch über `git rev-parse --show-toplevel`; Branch
  `spike/calendar-foundation-intel-2026-08-04`.
- Ausgangs-Commit `537f9c2b0dbc0fefcda071deaa3de0df2f59655c`.
- Normative Commits: Position 1 `8a0f6d8` (Genesis-Importvertrag durch das
  Werkzeug schreibbar, RC-032), Position 2
  `c12617d1944310fdc47dbf4a0b11716c6d6d0bb3` (die dreizehn Entscheidungen).
  Abnahmelauf vollständig gegen `c12617d…`; kein Amend, kein Rebase.
- Delta Position 2 laut `git diff --stat 537f9c2..c12617d`: 37 Dateien,
  +9549/−3603.

## §2 Phasen (Enum-Werte aus den maschinellen Berichten)

| Phase | Ergebnis |
|---|---|
| preflight | `pass` (13 Checks) |
| targeted | `pass` (13 Checks) |
| offline-final | `pass` (22 Checks) |
| platform-live | `pass` (3 Checks, **anwendbar**: echter Remote-Zustand) |
| module-final | `pass` (4 Checks) |

Maschineller Gesamtstatus: alle fünf Phasen `pass` gegen das Paar aus
normativem Commit `c12617d…` und Governance-Ref-OID `3e58129…`.
Baseline-Commit `7986bee` unverändert; kein Ergebnis `pass_with_baseline`,
kein `fail`, kein `blocked`.

## §3 Register: Genesis, Reservierung, Vergabe (drei Eigentümer-Pushes)

Kanonischer Ref `refs/governance/dec-reservations`, bedient ausschließlich
über `scripts/dec-reservations.sh`; jede Remote-Fortschreibung war ein vom
Eigentümer ausgeführter, vom Werkzeug exakt ausgegebener Push:

1. **Genesis** `bb94b11edc1275dde4f7296896712fe12d2710f7` — 72 Ereignisse:
   die strukturell belegten historischen Allokationen beider unveränderlicher
   Linien (55 numerisch + 17 D-Serie), je Ereignis `origin_line`,
   `source_commit`, `import_note` und `original_file`; unbeweisbare Metadaten
   sind als solche markiert, nichts wurde erfunden.
2. **Reservierung** `912887065f89e8b1bbeb04274a1929b5f4a0074e` — 85
   Ereignisse: die dreizehn Nummern aus §4 `reserved`, mechanisch aus
   `next-free`/`scan` abgeleitet, keine aus dem Prompt übernommen.
3. **Vergabe** `3e58129bdd3491eb85ea2b764b400e45606cb9bb` — 98 Ereignisse:
   alle dreizehn `reserved → assigned`, jedes Vergabeereignis gebunden an
   `source_commit = c12617d…`. Kettendigest
   `a7284a5e599d32b3f8d66d75edff367d346620b4febe9a2f74b56670697de535`.

Jeder Remote-Stand wurde nach dem Push frisch gelesen (`git ls-remote`) und
gegen die lokale Ableitung verifiziert; `pl-b0g-register-remote` prüft das
dauerhaft in jeder platform-live-Phase. Reihenfolge eingehalten: keine
Entscheidung in einem normativen Commit vor ihrer Reservierung, keine
Vergabe vor dem fixierten normativen Commit.

## §4 Die dreizehn Entscheidungen

- R1 → DEC-056 (spike/calendar-foundation-intel-2026-08-04, „Genau eine normative Stelle je Sachverhalt")
- R2 → DEC-057 (spike/calendar-foundation-intel-2026-08-04, „DEC-/ADR-Vergabe ausschließlich über das kanonische Reservierungsregister")
- R3 → DEC-058 (spike/calendar-foundation-intel-2026-08-04, „Kein stilles not_applicable für garantiert vorhandene Artefakte")
- R4 → DEC-059 (spike/calendar-foundation-intel-2026-08-04, „Schema vor Daten: jede Konfiguration an genau einen akzeptierenden Leser gebunden")
- R5 → DEC-060 (spike/calendar-foundation-intel-2026-08-04, „Jede deklarierte Phase läuft gegen den neuen Prüfumfang")
- R6 → DEC-061 (spike/calendar-foundation-intel-2026-08-04, „Eigentümer-Erwartungswerte reproduzierbar aus genau dem benannten Commit")
- R7 → DEC-062 (spike/calendar-foundation-intel-2026-08-04, „Jedes normative Feld ist mechanisch an seinen Gegenstand gebunden")
- R8 → DEC-063 (spike/calendar-foundation-intel-2026-08-04, „Konfigurationsmigrationen laufen als weiten, migrieren, verengen")
- R9 → DEC-064 (spike/calendar-foundation-intel-2026-08-04, „Eine absichtliche Einwirkung wird vor der Erwartung mechanisch belegt")
- R10 → DEC-065 (spike/calendar-foundation-intel-2026-08-04, „Eine Aggregation über eine leere Menge meldet nie pass")
- Zwei-Test-Regel → DEC-066 (spike/calendar-foundation-intel-2026-08-04, „Zwei-Test-Regel für jede Änderung einer bestehenden Prüfregel")
- Bericht-als-Folge → DEC-067 (spike/calendar-foundation-intel-2026-08-04, „Der Bericht ist Folge der Definition, nie ihre Schwester")
- Eigentümergrenzen → DEC-068 (spike/calendar-foundation-intel-2026-08-04, „Eigentümergrenzen: abschließende Klassen der Eigentümerhandlungen")

Je Entscheidung ein Dokument unter
`docs/governance/decisions/` mit Frontmatter-Bindung (DEC-ID, Alias,
Status) und den Abschnitten Kontext, Entscheidung (normativ),
Geltungsbereich, Ausdrücklich nicht geregelt, Mechanische Durchsetzung,
Herkunft. Semantik wörtlich aus den bestehenden Repositoriumsquellen
gehoben, keine erfunden; Quellkonflikte sind je Dokument in der Herkunft
aufgelöst und dokumentiert. Dreizehn Registerzeilen in
`docs/personal-jarvis/decisions-register.md` §1 als strukturelle
Allokationen (Scanner: 78 Zeilen, lückenlos, Maximum DEC-068 (spike/calendar-foundation-intel-2026-08-04, „Eigentümergrenzen: abschließende Klassen der Eigentümerhandlungen")).

## §5 Autoritäts- und Bindungsmodell (eine normative Stelle, mechanisch)

`config/governance/decision-authority.json` (R4-gebunden an
`tools.gates.decauthority:load_model`): je Entscheidung genau eine
autoritative Stelle (das DEC-Dokument), jeder weitere Träger
`derived_enforcement` (mit deklarierter Validierung) oder `reference_only`,
jeder Träger mit DEC-Marker. Der Fragmentschirm beweist je Entscheidung an
mindestens einem operativen Satz, dass der Volltext nur im DEC-Dokument
steht — 13 Entscheidungen, 59 gescannte Trägerdateien, 0 Befunde
(`of-b0g-authority`); Ausnahmen sind pfadgenau und tragen Gründe. Leerer
Scan besteht nie (R10). Validator mit 12 Negativfixtures und 4
Loader-Abweisungen (`tests/tooling/governance/test_decision_authority.py`,
17 Tests). Referenzmigration: CLAUDE.md (sechs Abschnitte auf Verweisform),
`config-loaders`, `owner-expectations`, `effect-evidence`, `field-binding`,
`ast-dispositions` (R9/R10-Statements), `rule-changes`,
`guard-trust-model`, `normative-sources`, `decision-citations`,
`r3-not-applicable-review`, Handoff-Skill — operative Volltexte stehen nur
noch in den DEC-Dokumenten.

## §6 Merkmalsprüfung

`of-`/`mf-feature-lineage` gegen den unmittelbaren Vorgänger
(B0f-Merkmalsliste, SHA-256-gebunden): erwartet 247 / zugeordnet 247 /
geändert 0 / fehlend 0; eigene Merkmale B0G-001…016: 16/16 nachgewiesen.

## §7 Korrekturen und dokumentierte Grenzen (Korrektur neben, nie statt)

Maschinenlesbar in `documented_limitations` des Abnahmerecords
`config/gates/history/b0g-rule-codification.acceptance.json`:

1. Der Schalter `cross_line_dec_allocation_permitted=false` aus dem
   Auftragsprompt existiert nirgends im Repositorium oder seiner Historie
   (mechanisch gesucht); als unverifizierte Promptbehauptung behandelt,
   kein Schalter erfunden.
2. Die gepinnten `first_unused`-Behauptungen des Registerwerkzeugtests
   waren ref-stale (an bewegliches HEAD gebunden); jetzt an den
   unveränderlichen Blockstart-Commit gebunden, HEAD strukturell geprüft.
3. `tg-/of-b0f-blind` und `tg-/of-b0f-sample` sind konstruktionsbedingt an
   das B0f-Commitpaar gebunden und wurden nicht in das B0g-Manifest
   vererbt; die dauerhaften B0f-Checks (baseline, method) laufen weiter.
4. Die Reihenfolgehälfte von DEC-067 (spike/calendar-foundation-intel-2026-08-04, „Der Bericht ist Folge der Definition, nie ihre Schwester") (normativ/feststellend) wird von
   keinem Prüfer konsumiert; die Durchsetzungslücke ist im DEC-Dokument
   deklariert.
5. Die Alias-Bindung R1…R10 beruht auf der je Dokument dokumentierten
   Herleitung; der Titel von DEC-067 (spike/calendar-foundation-intel-2026-08-04, „Der Bericht ist Folge der Definition, nie ihre Schwester") ist die B0g-Lesebezeichnung einer
   Eigentümerentscheidung, deren beide Hälften wörtlich gehoben sind.

## §8 Ausdrückliche Bestätigungen

Kein Produktcode, kein Live-Lauf außer dem deklarierten
`git ls-remote`-Lesezugriff der platform-live-Phase, kein Merge, kein Tag,
kein Release, kein Folgeblock begonnen, keine Guard-Aktivierung, kein
Force-Push, keine direkte Remote-Ref-Mutation durch einen Agenten. Die drei
Register-Pushes waren Eigentümerhandlungen. Rohlogs verbleiben im
gitignorierten Laufzeitbereich.

## §9 Pushstatus und verbleibende echte Blocker

- Pushstatus des Branches: `not_performed_owner_action`.
- Verbleibende echte Blocker: keine im Block. Offen bleiben die vererbten
  Methodenpunkte: Unit-Lokalität der Siebung als `open_gap`
  (`config/governance/b0f-unit-locality.json`) und die unter §7.4 benannte
  Durchsetzungslücke der Reihenfolgehälfte der Entscheidung
  Bericht-als-Folge.
