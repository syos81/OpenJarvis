---
Status: normativ (B0a-2 Governance); Tooling-Merge-Nachtrag
Maschinelle Quelle: config/gates/blocks/tooling-merge-readiness.json
---

# B0a-2 — Tooling-Merge-Nachtrag

## §1 Zuordnung

Der Tooling-Merge-Nachtrag ist **gemeinsam** diesen beiden Entscheidungen zugeordnet:

1. DEC-045 (jarvis/rebuild-v1@c222601, „Verbindliche Modulreihenfolge bis Modul 3")
2. DEC-048 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Kalender-Fundament-Spike (Intel) freigegeben und begrenzt"), fortgeführt auf `spike/calendar-foundation-intel-2026-08-04@8e6e206`

**Ausdrücklich nicht zugeordnet** ist
DEC-050 (jarvis/rebuild-v1@c222601, „Acht blockierende Kontakte-Gates").

Beide zugeordneten Nummern sind doppelt vergeben; die jeweils gemeinte Belegung ist
durch Linie und exakten Titel eindeutig bestimmt und in
`docs/governance/b0a-2-decision-collisions.md` vollständig dokumentiert.

## §2 Genau eine erlaubte spätere Integration

Der Nachtrag erlaubt genau **eine** eng begrenzte spätere eingehende Integration:

```text
Quelle: tooling/gates-v1
Ziel:   spike/calendar-foundation-intel-2026-08-04
```

Sie ist erst nach einer mechanischen Prüfung zulässig, die mindestens belegt:

1. Quelle und Ziel sind exakt die vorgesehenen Linien,
2. der vollständige Diff wurde geprüft,
3. die geänderten Pfade entsprechen einer expliziten Tooling-/Governance-Allowlist,
4. kein Kontakte-, Kalender-, Trading-, Ambient- oder sonstiger Produktcode ist
   enthalten,
5. keine Produktkonfiguration und keine Migration ist enthalten,
6. keine Binärdatei und keine reale Evidenz ist enthalten,
7. die Modulabschlussgates von B0a-1 und B0a-2 sind gültig,
8. Merkmalslisten und sanitierte Evidenz sind vollständig,
9. keine Rohlogs werden integriert.

Die Prüfung ist als deklaratives Readiness-Manifest `tooling-merge-readiness`
umgesetzt und wird über die öffentliche Gate-Schnittstelle gefahren:

```bash
scripts/gate.sh --block tooling-merge-readiness --phase preflight
scripts/gate.sh --block tooling-merge-readiness --phase offline-final
```

Das Manifest prüft ausschließlich die spätere Mergebereitschaft. **Es führt keinen
Merge aus.** B0a-2 führt den Merge ebenfalls nicht aus.

## §3 Was der Nachtrag ausdrücklich nicht bewirkt

Der Tooling-Merge-Nachtrag

* startet **nicht** das Kalender-Fachmodul,
* genehmigt **keinen** Kalender-Produktcode,
* schließt Kalender **nicht** ab,
* erlaubt **keinen** Rückwärtsmerge in `tooling/gates-v1`,
* erlaubt **keinen** weiteren Merge,
* erlaubt **keinen** Tag,
* erlaubt **kein** Release,
* erlaubt **keinen** Push auf einen Produktbranch.

Das Startgate des Kalendermoduls bleibt unberührt: es öffnet erst nach dem Abschluss
des Kontaktmoduls, wie in
DEC-048 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Kalender-Fundament-Spike (Intel) freigegeben und begrenzt")
festgehalten.

## §4 Inhalt der Integration

Integriert werden ausschließlich Tooling- und Governance-Artefakte:

```text
CLAUDE.md
.claude/settings.json
.claude/hooks/**
.claude/skills/**
scripts/gate.sh
tools/gates/**
config/gates/**
config/governance/**
docs/governance/**
docs/tooling/**
tests/tooling/**
.gitignore
```

Mit der Integration erreicht insbesondere der Kollisions-Nachtrag aus
`docs/governance/b0a-2-decision-collisions.md` die Kalenderlinie, auf der die
Kalender-Implementierungsbaseline mit ihrem § 6 liegt.
