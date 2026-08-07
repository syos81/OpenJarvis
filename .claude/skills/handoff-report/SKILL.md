---
name: handoff-report
description: Erzeugt einen Abschluss- oder Handoff-Bericht ausschließlich aus überprüfbaren Quellen (Gate-Ergebnisse, sanitierte Evidenz, Git-Daten, Manifeste) und prüft vorher die Merkmalsvollständigkeit gegen den unmittelbaren Vorgänger.
---

# Skill: handoff-report

Dieser Skill schreibt Berichte. Er ermittelt selbst **keinen** Status und
erzeugt **keine** Gate-Ergebnisse. Fehlt eine Quelle, wird das als Lücke
benannt — nicht überbrückt.

## Zulässige Quellen

1. maschinenlesbare Gate-Ergebnisse (`.gate-runtime/results/<block>.<phase>.json`),
2. sanitierte Evidenz (`.gate-runtime/evidence/<block>.<phase>.json`),
3. `git status --short`, `git diff --stat`, `git diff --check`,
4. Commit- und Branchdaten (`git rev-parse HEAD`, `git branch --show-current`),
5. deklarative Block- und Merkmalsmanifeste unter `config/gates/`.

Andere Quellen sind unzulässig. Insbesondere: keine Rohlogs, keine
Erinnerungen aus dem Gesprächsverlauf, keine Vermutungen über nicht gelaufene
Prüfungen.

## Verbote

- Keinen Status aus Prosa erfinden oder aus einem „sah gut aus“ ableiten.
- `fail` oder `blocked` nicht abschwächen, nicht umbenennen, nicht als
  „bekannt“ wegerklären.
- Fehlende Evidenz nicht als bestanden darstellen.
- Rohlogs nicht zitieren, auch nicht auszugsweise, auch nicht „gekürzt“.
- Ungeprüfte Behauptungen nicht als Tatsache ausgeben.
- Bei mindestens einem fehlenden Pflichtmerkmal, einem `fail` oder einem
  `blocked` darf der Block nicht als abgeschlossen oder vollständig
  bezeichnet werden.

## Pflichtschritt: Merkmalsvollständigkeit

Vor dem Bericht läuft die maschinelle Prüfung gegen die Merkmalsliste des
**unmittelbaren Vorgängers**:

```bash
scripts/gate.sh --block <block-id> --phase offline-final
```

Der Check `of-feature-lineage` (bzw. `mf-feature-lineage` im Abschluss) nutzt
`tools/gates/features.py` und liest:

* `config/gates/features/<block>.predecessor.json` — die Merkmalsliste des
  Vorgängers, per SHA-256 gebunden,
* `config/gates/features/<block>.lineage.json` — Zuordnung, Fundort,
  Nachweis und Status je Merkmal.

Regeln:

- Die Merkmalsliste stammt aus dem tatsächlichen Vorgänger, nie aus der neuen
  konsolidierten Fassung.
- Jedes Pflichtmerkmal ist einzeln zugeordnet und nachgewiesen.
- Umbenannte, verschobene oder aufgeteilte Merkmale brauchen eine explizite
  Zuordnung (`predecessor_feature_id`).
- Ein nicht zugeordnetes oder fehlendes Pflichtmerkmal ist immer `fail`.
- Ein Pflichtmerkmal darf nie `not_applicable` sein.
- Fehlt der Vorgänger oder seine Liste, ist die Prüfung `blocked`;
  Vollständigkeit darf dann nicht behauptet werden.
- Eine bewusst geänderte oder aufgehobene Anforderung braucht eine konkrete
  Eigentümerentscheidung (`owner_decision`). Ohne sie gilt sie als fehlend.
- Ein bloßer Gesamttext- oder Längenvergleich genügt nicht.

Der Bericht nennt die Zahlen: erwartet / zugeordnet / geändert / fehlend.

## Berichtsaufbau

```text
Worktree (kanonisch), Branch
Ausgangs- und Abschluss-Commit
geänderte Dateien (aus git diff --stat)
Status der fünf Phasen, je genau ein Enum-Wert
maschineller Gesamtstatus
Baseline-Commit, Baseline-Worktree- und Cacheprüfung
Ergebnis der strukturellen Signaturtests
Ergebnis der Evidenz- und Canary-Tests
Ergebnis der Hook-Testmatrix
Merkmalsprüfung: erwartet/zugeordnet/geändert/fehlend
ausdrückliche Bestätigungen (kein Produktcode, kein Live-Lauf, kein Merge,
  kein Tag, kein Release, kein Folgeblock begonnen)
Pushstatus
verbleibende echte Blocker — ohne Spekulation
```

Der Bericht ist kurz, konkret und deltaorientiert. Jede Aussage lässt sich auf
eine der zulässigen Quellen zurückführen.

## Normative Quelle

Normativ: DEC-067 — Der Bericht ist Folge der Definition, nie ihre Schwester
(`docs/governance/decisions/DEC-067-bericht-als-folge.md`). Dieser Skill ist
das Durchsetzungsartefakt der Quellendisziplin; die Entscheidung selbst steht
ausschließlich im DEC-Dokument.
