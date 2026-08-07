# B0e Handoff — Testhärtung: hergeleiteter Prüfbestand, R9-/R10-Durchsicht, Dispositionsregister

Alle Aussagen stammen aus maschinellen Gate-Ergebnissen
(`.gate-runtime/results/b0e-test-hardening.*.json`, als sanitierte
Schnappschüsse unter `config/gates/evidence/b0e-test-hardening/` gebunden),
aus Git-Daten und aus den committeten deklarativen Artefakten.

## §1 Rahmen

- Worktree: mechanisch über `git rev-parse --show-toplevel`; Branch
  `spike/calendar-foundation-intel-2026-08-04`.
- Ausgangs-Commit `3e90d675a3dce38348cc0fcf1556f8a68dd14031` (lokal == remote
  bei Blockbeginn, Baum sauber).
- Normative Commits: Position 1 `5e95f5f`, Korrekturposition 2 `f812b24`
  (Begründung maschinenlesbar in `config/gates/history/b0e-commit-plan.json`).
- Abnahmelauf vollständig gegen `f812b24828e17eef34c4e729012c1a753f9246a9`.
- Delta laut `git diff --stat`: 74 Dateien, +9861/−155.
- Baseline-Commit der Blockdefinition: `7986bee` (Baseline-Engine unverändert,
  Cache deaktiviert; kein Check baseline-eligible).

## §2 Phasen (Enum-Werte aus den maschinellen Berichten)

| Phase | Ergebnis |
|---|---|
| preflight | `pass` (12 Checks) |
| targeted | `pass` (8 Checks) |
| offline-final | `pass` (18 Checks) |
| platform-live | `not_applicable` (per Manifest deklariert, siehe §5) |
| module-final | `pass` (4 Checks: `evidence_complete`, `phase_results_consistent`, Merkmals- und Preservationslauf) |

Maschineller Gesamtstatus des Blocks: alle erforderlichen Phasen `pass`,
platform-live als deklariertes `not_applicable` mit hergeleiteter Begründung.

## §3 Prüfbestand — abgeleitet statt behauptet

`tools/gates/astcorpus.py` leitet den ausführbaren Prüfbestand aus
pytest-`testpaths`, der Manifest-Verdrahtung (`unittest discover`,
Modullisten, Runner-argv), den Shell-Entry-Points und dem Importschluss
unter `tools/` ab; jede Datei trägt ihre Herleitung. Zählwerte des
Abnahmelaufs (gebunden in `config/gates/history/b0e-test-hardening.acceptance.json`):

- ausführbare Prüfdateien: **731**
- analysierte Einheiten: **10750** (davon 8417 Testeinheiten, 623 Validatoreinheiten)
- analysierte AST-Knoten: **697072**

Eine entzogene Discovery-Eingabe ist ein Fehler (`corpus_source_missing`),
nie ein leerer Bestand; ein leerer Bestand ist `corpus_empty`. Beides ist
fixture-getestet.

## §4 Durchsicht, Dispositionen, Reparaturen

Gemeinsames AST-Gerüst `tools/gates/astscan.py`; Register
`config/governance/ast-dispositions.json` (R4-gebunden an
`tools.gates.astscan:load_register`). `erkannte Kandidaten ==
disponierte Kandidaten` erzwingen `tg-/of-dispositions` und dauerhaft
`tests/tooling/gates/test_ast_dispositions.py`.

- R9-Kandidaten gesamt: **120** — `mark_and_fix` **57**,
  `exclude_with_reason` **63**
- R10-Kandidaten gesamt: **73** — `repair` **13**, `exclude_with_reason` **60**
- Dispositionen gesamt: **193**; keine fehlenden, keine verwaisten
  (`of-dispositions` `pass`; 58 Reparaturen führen den Anker belegt als
  `resolved_by_removal`).
- Deklarierte Einwirkungstests unter der R9-Konvention: **65** Funktionen in
  `config/governance/effect-evidence.json`, alle im `of-effect-evidence`-Lauf
  geprüft (`pass`); die B0d-Regression bleibt erhalten.
- Reparaturklassen: 55 Produkttests (Kanäle, Engine, CLI, Agents, Server,
  Tools, Telemetrie) beobachten ihre Injektion jetzt als erste Zusicherung;
  `tests/tooling/guard/test_bootstrap.py` belegt die Nadel vor der
  Substitution; elf Gate-Prüferpfade behandeln fehlende Deklarationsschlüssel
  als Fehler statt als leere Menge (RC-024); zwei Generality-Pfade und
  `tools/gates/paths.py::ensure_private_dir` beobachten ihre Wirkung.
- Echtbefund aus der Reparatur: der Granola-Test bestand bisher über eine
  Live-Netzwerkprobe, weil ein `importlib.reload` den Patch verwarf — exakt
  die R9-Fehlerklasse; der Test bindet die Injektion jetzt nachweisbar.

## §5 platform-live — Herleitung

`git diff --name-only 3e90d675..f812b24 -- tools/guard tools/guardpkg
tools/guardops src` ist leer (im Abnahmerecord als
`guard_paths_diff_since_block_start: []` gebunden). Es existiert kein neuer
Guard-Kandidat und kein Live-Artefakt, dessen Abnahme ausstehen könnte; die
aktive Installation wird weiter in jedem Lauf von `pf-guard-base` geprüft.
Die Phase ist deshalb per Manifest mit dieser Begründung `not_applicable` —
kein stiller und kein promptbestimmter Ausschluss.

## §6 Merkmalsvollständigkeit

`of-feature-lineage`/`mf-feature-lineage` gegen den unmittelbaren Vorgänger
B0d: erwartet **209** / zugeordnet **209** / geändert **0** / fehlend **0**;
eigene Merkmale `B0E-`: erwartet **20** / verifiziert **20** / fehlend **0**.

## §7 Verstoßmengenvergleich

- Tooling-Suite vor dem Block: 722 Tests `OK`; im Abnahmelauf
  (`of-tooling-tests`): 785 Tests `pass` — kein zuvor gefangener Verstoß
  entfiel, 63 Fälle kamen hinzu (Scanner-, Register- und RC-024-Paare).
- `of-violation-corpus` `pass` (Korpus unverändert, nun zusätzlich gegen
  leere Korpora abgesichert); `of-manifest-validation` mit allen
  Negativfixtures `pass`; `of-rule-changes` `pass` mit den neuen Paaren
  RC-024 (Schärfung `test_r10_repairs.py::TestSharpening`, Gegentest
  `::TestCounter`) und RC-025 (Schärfung
  `test_ast_dispositions.py::TestTheComparison`, Gegentest
  `test_effect_evidence.py::TestTheCheckHasTeeth`).

## §8 Bestätigungen

Kein Produktcode geändert (`src/` unberührt, siehe §5-Diff), kein Live-Lauf,
kein Merge, kein Rebase, kein Tag, kein Release, kein Push, kein Folgeblock
begonnen. Der Guard blieb unangetastet; die Guard-Kette ist ein
Disziplinmechanismus im Sinne des Vertrauensmodells, keine vollständige
Sicherheitsgrenze.

Pushstatus: `not_performed_owner_action`.

## §9 Protokollierte Zusatzbefunde (nicht Teil von B0e)

1. `tests/server/test_connectors_router.py::test_connect_slack_bot_token_returns_400`
   trägt mutmaßlich dieselbe Reload-gegen-Patch-Schwäche wie der reparierte
   Granola-Test; kein R9-Kandidat der deklarierten Klassen, daher hier nur
   protokolliert.
2. Die Durchsichten sind einheitenlokal; Beobachtungen über Helferfunktionen
   hinweg und aufruferseitige Konsumption leerer Defaults liegen außerhalb
   der strukturellen Reichweite und sind als Klassengrenzen im Register
   dokumentiert.

## §10 Verbleibende echte Blocker

Keine. Der Eigentümer-Push steht aus und ist ausdrücklich Eigentümerhandlung.
