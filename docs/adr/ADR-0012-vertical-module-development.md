---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-2, AV-3, AV-33, AV-36
Zugehörige ADRs: ADR-0002, ADR-0005
Verwandte DEC-Einträge: DEC-018, DEC-021, DEC-024; offen: DEC-D10
---

# ADR-0012: Vertikale Modulentwicklung

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Eigentümer verlangt ausdrücklich, dass nicht mehrere parallele, nur teilweise oder nur lesend umgesetzte Module entstehen: ein Modul nach dem anderen vollständig — inklusive Datenmodell, Backend, Adapter, Rechte, UI, Fehlerfälle, Tests und Live-Abnahme — ohne Platzhalter und ohne vorsorgliches Framework für zehn zukünftige Module.

## Entscheidung

1. **Vertikale Vollständigkeit:** Ein Modul gilt erst mit erfüllter Definition of Done (19) als abgeschlossen; erst danach beginnt das nächste (AV-2). Keine parallelen halbfertigen Module.
2. **Materialisierungsregel (AV-33):** Gemeinsame Grundlagen entstehen nur, wenn das unmittelbar folgende Modul sie zwingend braucht. Einzige beschlossene Ausnahme: der Backup-Kern funktioniert ab dem ersten kanonischen Datenbestand (DEC-024).
3. **Keine Scheinimplementierungen:** keine Platzhalter, Fake-Daten oder leeren Menüpunkte in produktiven Pfaden (AV-3); UI-Sichtbarkeit ist an den Modul-Lifecycle gekoppelt (AV-36; 14 §4).
4. **Reihenfolge offen:** Erstes Fachmodul und Gesamtreihenfolge sind bewusst nicht entschieden (DEC-D10); es gelten nur die Startkriterien der Modulkarte (16 §4). Trading wird nach Kriterien eingeplant, nicht pauschal zuletzt; die Restore-Fähigkeit besteht ab dem ersten Datenbestand.
   > **Ersetzt am 2026-07-31 durch [ADR-0019](ADR-0019-module-sequence-and-total-completion.md) (DEC-045):** Die Reihenfolge ist bis Modul 3 festgelegt (Kontakte → Kalender → Trading Intelligence T1); DEC-D10 ist damit vollständig aufgelöst. Nach Modul 3 wird bewusst neu entschieden. **Die Punkte 1–3 dieses ADR (vertikale Vollständigkeit, Materialisierungsregel, keine Scheinimplementierungen) gelten unverändert fort** und werden durch ADR-0019 nur verschärft.

## Geprüfte Alternativen

- **Breites Vorab-Framework (alle Verträge/Basisdienste zuerst)** — verworfen: horizontale Großbaustelle, ungenutzte Abstraktionen, genau das verbotene Muster.
- **CLI-/API-first mit späterer UI** — verworfen: widerspricht der Definition „vollständig inkl. UI"; klassischer Weg zu nie gebauten Oberflächen.
- **Feste Modulreihenfolge jetzt** — verworfen (Eigentümer-Entscheid): Reihenfolge folgt erst nach Freigabe der Architektur anhand der Startkriterien.

## Konsequenzen

Jedes Modul liefert sofort nutzbaren, abgenommenen Wert; Basisdienste wachsen nachweislich bedarfsgetrieben; die Modulkarte (16) bleibt ungeordnet, bis DEC-D10 entschieden ist.

## Verweise

Primärdokumente: 19, 16, 14. Regeln: AV-2, AV-3, AV-33, AV-36.
