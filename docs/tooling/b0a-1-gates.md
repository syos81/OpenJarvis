# B0a-1 — Deterministische Gates, Baseline und Evidenz

Dieser Block enthält ausschließlich Werkzeuge. Kein Produktcode, kein K1-Lauf,
keine Integration in Kontakte, Kalender, Trading, Ambient oder Hausverwaltung.

## Öffentliche Schnittstelle

```bash
scripts/gate.sh --block <block-id> --phase <phase>
```

Block und Phase sind Pflichtparameter. Es gibt keine stillen Standardwerte,
keine interaktive Auswahl und keine Statusableitung aus Freitext. stdout trägt
genau ein maschinenlesbares JSON-Dokument, stderr nur PII-sichere
Fortschrittsmeldungen.

## Phasen

| Phase | Zweck |
|---|---|
| `preflight` | nur Voraussetzungen: Manifest, Werkzeuge, Worktree/Branch, Arbeitsbaumzustand, Commitobjekte, Plattform, nicht geheime Konfiguration |
| `targeted` | begrenzte, aus Manifest und Änderungsregeln abgeleitete Prüfungen |
| `offline-final` | alle reproduzierbaren Offline-Prüfungen des Blocks |
| `platform-live` | echte Plattform-/Live-Prüfungen; für B0a-1 im Manifest begründet `not_applicable` |
| `module-final` | Abschlussaggregation inkl. Commitbezug, Evidenz- und Merkmalsvollständigkeit |

## Ergebnisse und Exitcodes

| Ergebnis | Exitcode | Bedeutung |
|---|---|---|
| `pass` | 0 | erfolgreich ohne Baseline-Ausnahme |
| `pass_with_baseline` | 0 | strukturell identische Ursache bereits auf `7986bee` |
| `not_applicable` | 0 | laut Manifest sachlich nicht anwendbar |
| `fail` | 20 | Fehler, Inkonsistenz, fehlendes Pflichtmerkmal, Evidenzleck |
| `blocked` | 30 | nachweisbare äußere Voraussetzung fehlt |
| Nutzungsfehler | 64 | fehlender, doppelter oder unbekannter Parameter |
| interner Fehler | 70 | unerwarteter Engine-Fehler |

`pass`, `pass_with_baseline` und `not_applicable` sind für Shell-Automation
nicht fehlgeschlagene Läufe (Exitcode 0) und bleiben über das `status`-Feld des
strukturierten Berichts unterscheidbar. Autoritativ ist immer dieses Enum,
nie der Freitext.

Aggregationspriorität: `fail` → `blocked` → `pass_with_baseline` → `pass` →
`not_applicable`. Eine leere Checkliste ist kein Erfolg. `module-final` darf
nie `not_applicable` ergeben.

## Baseline

Einzige Code-Baseline ist der Commit `7986bee`. Baseline-Läufe passieren in
einem dedizierten, detachten Worktree außerhalb des Arbeits-Worktrees, mit
Besitzmarker, Sperre und Prüfung von HEAD, Sauberkeit und Repositoryursprung.
Nur ein selbst erzeugter und markierter Baseline-Worktree wird erneuert oder
entfernt. Ein Kandidatenfehler wird nur bei identischer versionierter
struktureller Ursachensignatur entschuldigt — nie über Rohlog-Hash, Exitcode
oder Textähnlichkeit.

## Evidenz

Rohlogs liegen ausschließlich im gitignorierten Laufzeitbereich
`.gate-runtime/` (Rechte 0600) und werden weder committed noch zitiert noch
ungefiltert ausgegeben. Handoff- und Repositoryevidenz ist ausschließlich die
allowlistbasierte, sanitierte Evidenz; jedes unbekannte Feld ist ein Fehler.
Der SHA-256-Digest belegt die lokale Rohlogidentität.

## Blockregeln B0a-1

* Arbeitsbranch: `tooling/gates-v1`.
* Genau ein lokaler B0a-1-Commit:
  `chore(tooling): bootstrap deterministic gates and evidence`.
  Kein Amend, keine zusätzlichen B0a-1-Commits, kein Merge, kein Rebase,
  kein Tag, kein Release.
* Ein normaler Push nach `origin/tooling/gates-v1` erfolgt erst nach allen
  grünen Abschlussgates. Die harte Deny-Regel für `git push` bleibt bestehen;
  sie wird nicht dauerhaft gelockert. Ist kein enger, protokollierter
  Eigentümerfreigabeweg verfügbar, endet der Block nach dem lokalen Commit und
  der exakte manuelle Push-Befehl wird ausgegeben. Kein Force-Push.
