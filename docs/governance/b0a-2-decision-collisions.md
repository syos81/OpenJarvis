---
Status: historisch – nicht normativ
Aufgeloest in: B0a-3 (Integration in die Kalenderlinie)
Normative Nachfolgestelle: docs/personal-jarvis/calendar-implementation-baseline-2026-08-04.md §6
Maschinenlesbare Projektion: config/governance/decision-collisions.json
Ausschluss: config/governance/normative-sources.json
---

# HISTORISCH — B0a-2-Nachtrag zu den Entscheidungskollisionen

> **Diese Datei ist nicht mehr normativ.**
> Ihr vollständiger Inhalt ist mit B0a-3 in § 6 der Kalender-Implementierungs-
> baseline aufgegangen. Für Linien, Merge-Base, Kollisionsbefund und
> Umnummerierungs-Mapping gilt ausschließlich:
>
> `docs/personal-jarvis/calendar-implementation-baseline-2026-08-04.md` § 6

## Warum die Datei erhalten bleibt

Das unveränderte B0a-2-Blockmanifest
`config/gates/blocks/b0a-2-governance.json` verlangt diese Datei im Check
`pf-claude-config` als Konfigurationsnachweis. B0a-2-Manifeste dürfen nach
ihrer Bindung nicht nachträglich umgeschrieben werden, deshalb bleibt der
Pfad bestehen — als historischer Nachweis, nicht als zweite Wahrheit.

## Mechanischer Ausschluss

`config/governance/normative-sources.json` führt diese Datei unter
`historical_non_normative`. Das Gate `of-single-normative-source` beweist bei
jedem Lauf, dass

* die Datei die Kennzeichnung `Status: historisch – nicht normativ` trägt,
* sie in der Ausschlussliste steht,
* die Prüfungen `citations`, `id-freeze` und die Kollisionserkennung sie
  überspringen,
* und genau eine normative Stelle für den Sachverhalt verbleibt.

## Stand zum Zeitpunkt von B0a-2 (historisch)

Zum Abschluss von B0a-2 waren sieben Doppelvergaben offen: die DEC-Nummern
044 bis 048 sowie die ADR-Nummern 0019 und 0020, jeweils unabhängig vergeben
auf `jarvis/rebuild-v1@c222601` und auf der Kontakte-/Kalenderlinie. B0a-2
hat sie dokumentiert und ausdrücklich **nicht** aufgelöst; das
Integrations-Gate blieb deshalb mit
`integration_blocked_by_open_collision` blockiert.

B0a-3 hat die Auflösung nach fester Eigentümerfestlegung vollzogen. Der
aktuelle Stand — null offene Kollisionen, die sieben Alt-/Neu-Zuordnungen und
die unveränderten kanonischen IDs — steht ausschließlich in der normativen
Nachfolgestelle.
