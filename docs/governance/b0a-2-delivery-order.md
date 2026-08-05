---
Status: normativ (B0a-2 Governance); einzige kanonische Liefer- und Fachmodulreihenfolge
Maschinelle Quelle: config/governance/delivery-order.json
Zitatregistry: config/governance/decision-citations.json
---

# B0a-2 — Kanonische Liefer- und Fachmodulreihenfolge

## §1 Grundsatz

**Lieferposition und Fachmodulnummer sind zwei getrennte Größen.** Ein technischer
Produktblock kann eine Lieferposition belegen, ohne Fachmodul zu sein und ohne eine
Fachmodulnummer zu erhalten. Die Verwechslung beider Größen ist ein Fehler und führt
im Gate zu `fail`.

Diese Datei und `config/governance/delivery-order.json` sind **eine** Quelle: das
Dokument stellt dar, die JSON-Datei ist maschinell verbindlich. Beide werden
mechanisch gegeneinander geprüft; eine Abweichung ist `fail`.

## §2 Verbindlicher Stand

| Lieferposition | Element | Typ | Fachmodulnummer | Eigene fachliche Datenhoheit |
|---:|---|---|---:|---|
| 1 | Kontakte | Fachmodul | 1 | ja — gemäß qualifizierter Kontakte-Entscheidung |
| 2 | Kalender | Fachmodul | 2 | ja — gemäß qualifizierter Kalender-Entscheidung |
| 3 | Ambient Interaction V1 | technischer Produktblock | keine | nein |
| 4 | Trading Intelligence T1 | Fachmodul | 3 | ja — gemäß späterer T1-Ausgestaltung |
| danach | nur nach neuer Eigentümerentscheidung | nicht vorab festlegen | keine Vorabvergabe | nicht vorab festlegen |

Nach Lieferposition 4 wird **nichts** vorab festgelegt. Ein weiteres Element braucht
eine neue Eigentümerentscheidung als qualifizierte Quelle; ohne sie ist der Eintrag
`fail`.

## §3 Normative Herkunft der Fachmodulreihenfolge

Die Fachmodulreihenfolge Kontakte → Kalender → Trading Intelligence T1 stammt
ausschließlich aus:

* DEC-045 (jarvis/rebuild-v1@c222601, „Verbindliche Modulreihenfolge bis Modul 3")
* ADR-0019 (jarvis/rebuild-v1@c222601, „Verbindliche Modulreihenfolge und 100-Prozent-Modulvollendung")

Die Modulwahl für Lieferposition 1 ist qualifiziert durch
DEC-030 (jarvis/rebuild-v1@c222601, „Erstes Fachmodul: Kontakte").

**Nicht** als Ursprung der Fachmodulreihenfolge auszugeben sind:

* DEC-049 (jarvis/rebuild-v1@c222601, „Gestufte Trading-Architektur T1–T4")
* ADR-0024 (jarvis/rebuild-v1@c222601, „Gestufte Trading-Architektur (T1–T4) und Modul 3 „Trading Intelligence"")

Sie regeln die Trading-Stufung, nicht die Reihenfolge der Fachmodule.

## §4 Einfügung von Ambient Interaction V1

Ambient Interaction V1 wird durch

```text
{{DEC_ID_AMBIENT_INTERACTION_V1}}
```

als **technischer Produktblock** auf Lieferposition 3 eingefügt. Ambient erhält

* keine Fachmodulnummer,
* keine eigene fachliche Datenhoheit.

Trading Intelligence T1 bleibt dadurch unverändert **Fachmodul 3** auf
**Lieferposition 4**. Die inhaltliche Einordnung von Ambient steht in
`docs/governance/b0a-2-ambient-interaction-v1.md`.

Der Platzhalter wird nicht ersetzt, nicht berechnet und nicht reserviert, solange die
Doppelvergaben nicht integriert aufgelöst sind
(`docs/governance/b0a-2-decision-collisions.md`).

## §5 Fehlerbedingungen des Reihenfolgen-Gates

Das Gate schlägt mindestens fehl bei:

1. fehlender Lieferposition,
2. doppelter Lieferposition,
3. Lücke in den festen Positionen 1 bis 4,
4. Kontakte nicht auf Lieferposition 1,
5. Kontakte nicht Fachmodul 1,
6. Kalender nicht auf Lieferposition 2,
7. Kalender nicht Fachmodul 2,
8. Ambient nicht auf Lieferposition 3,
9. Ambient mit Fachmodulnummer,
10. Ambient mit eigener fachlicher Datenhoheit,
11. Trading Intelligence T1 nicht auf Lieferposition 4,
12. Trading Intelligence T1 nicht Fachmodul 3,
13. Verwechslung von Lieferposition und Fachmodulnummer,
14. weiterem Element nach Position 4 ohne neue Eigentümerentscheidung,
15. Abweichung zwischen Register, Modullandkarte und maschinenlesbarer Quelle,
16. unqualifiziertem DEC- oder ADR-Verweis,
17. falscher Zuordnung der Reihenfolgenquelle,
18. vorzeitiger Ersetzung des Ambient-Platzhalters.
