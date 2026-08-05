---
name: gate
description: Führt die deterministischen Gates eines Blocks über scripts/gate.sh aus. Nutze diesen Skill, wenn ein Block geprüft, eine Phase gefahren oder ein Abschlussgate benötigt wird — nie einen eigenen Testlauf als Ersatz.
---

# Skill: gate

Dieser Skill fährt Gates. Er enthält **keine zweite Gateimplementierung** und
darf keine Statusermittlung nachbauen. Die einzige Quelle für Ergebnisse ist
die Engine hinter `scripts/gate.sh`.

## Vorgehen

1. **Arbeitsbereich feststellen** – vor allem anderen:

   ```bash
   git rev-parse --show-toplevel
   git branch --show-current
   git status --short
   git rev-parse HEAD
   ```

   Nie einen Repositorypfad fest codieren, nie einen gemerkten absoluten Pfad
   wiederverwenden, nie in einem fremden Worktree arbeiten.

2. **Blockmanifest lesen** – `config/gates/blocks/<block-id>.json`. Daraus
   ergeben sich Phasen, Checks, Pflichtstatus, Baselinepolitik,
   Plattformvoraussetzungen und Merkmalsbindung. Was dort nicht deklariert
   ist, wird nicht behauptet.

3. **Gates ausschließlich über die öffentliche Schnittstelle aufrufen:**

   ```bash
   scripts/gate.sh --block <block-id> --phase <phase>
   ```

   Block und Phase sind Pflichtparameter. Kein direkter Aufruf der internen
   Module, kein `pytest`/`unittest`-Aufruf als Ersatz, keine Statusableitung
   aus Prosa.

4. **Phasen in dieser Reihenfolge fahren:**

   ```text
   preflight → targeted → offline-final → platform-live → module-final
   ```

   Während der Arbeit genügt `targeted`. `module-final` erst ausführen, wenn
   die erforderlichen Vorphasen mit gültigen, aktuellen Ergebnissen vorliegen.

5. **Ergebnis wörtlich übernehmen.** Maßgeblich ist das `status`-Feld des
   JSON-Berichts, nicht der Exitcode-Eindruck und nicht der Freitext.

## Harte Regeln

- Ein fehlendes Gate-Ergebnis wird nicht durch einen manuellen Testlauf
  ersetzt und nicht geschätzt.
- Keine Phase wird zu `not_applicable` oder `blocked` umgedeutet.
  `not_applicable` entsteht nur aus einer deklarativen Manifestregel; eine
  fehlende Voraussetzung für einen verpflichtenden Test ist `blocked`.
- `pass_with_baseline` wird ausschließlich aus der Baseline-Engine übernommen.
  Niemals selbst behaupten, ein Fehler sei „derselbe wie vorher“.
- Bei `fail` oder `blocked` wird kein grüner Abschluss behauptet. Der Block
  bleibt offen, bis das Gate selbst grün ist.
- Rohlogs aus `.gate-runtime/` werden weder zitiert noch in Antworten oder
  Berichte kopiert. Für Aussagen zählt die sanitierte Evidenz.
- Der Commitbezug der verwendeten Ergebnisse wird geprüft: `commit`,
  `manifest_digest`, `engine_version` und `worktree_state_digest` im Bericht
  müssen zum aktuellen Stand passen. Veraltete Ergebnisse werden neu erzeugt,
  nicht weiterverwendet.

## Ergebnisse lesen

| Feld | Bedeutung |
|---|---|
| `status` | Gesamtergebnis der Phase, genau ein Enum-Wert |
| `checks[].status` / `checks[].reason_code` | Einzelergebnis und maschineller Grund |
| `baseline` | Baseline-Commit, Signaturversion, Cachezustand |
| `evidence` | sanitierte Evidenz dieser Phase |

Exitcodes: `0` für `pass`, `pass_with_baseline` und `not_applicable`, `20` für
`fail`, `30` für `blocked`, `64` für Nutzungsfehler, `70` für interne Fehler.

## Bei Problemen

- Unbekannter Block oder unbekannte Phase → Aufruf korrigieren, nicht raten.
- `blocked` → die genannte äußere Voraussetzung benennen und an Lukas
  eskalieren; nicht in `not_applicable` umdeuten.
- `fail` → Ursache beheben und die Phase erneut fahren; anschließend die
  betroffenen Folgephasen wiederholen.
