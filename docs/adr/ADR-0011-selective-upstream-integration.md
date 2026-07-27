---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1, AV-27 (Pick-Anteil), AV-32
Zugehörige ADRs: ADR-0001
Verwandte DEC-Einträge: DEC-007
---

# ADR-0011: Selektive Upstream-Integration

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Audit belegte einen Kollaps der Upstream-Velocity (menschliche Commits: März 478 → Juli 18; Bus-Faktor: ~82 % ein Autor) bei weiterhin wertvollen Einzel-Fixes (WAL/SQLITE_BUSY, FTS5-Crash). Ein langlebiger Fork mit additiven Modulen braucht Stabilität ohne Verzicht auf Sicherheits- und Datenintegritäts-Fixes.

## Entscheidung

1. Die Baseline bleibt eingefroren (`openjarvis-baseline-2026-07-27`); **keine automatischen Rebases, keine Pauschal-Merges.**
2. **Übernahmekriterien** (abschließend): Sicherheitsfixes · Datenverlust-/Korruptionsfixes · Fehler in tatsächlich genutzten Komponenten · wichtige macOS-, Rust-, Tauri- oder Inferenzfixes.
3. **Prozess je Übernahme:** Prüfung des Patches → Tests → eigener Commit → Dokumentationseintrag → Re-Check der Abweichungsliste (18).
4. Eigene generische Fixes dürfen upstream angeboten werden.

## Geprüfte Alternativen

- **Harte Abkopplung (nie wieder übernehmen)** — verworfen: Verzicht auf Sicherheits-/Integritäts-Fixes; irreversible Drift.
- **Regelmäßige Rebases auf `main`** — verworfen: wühlt unter den eigenen Modulen, unreviewtes Upstream-Risiko (Bus-Faktor), täglicher Bot-Noise; Additivität der Module macht Cherry-Picks ohnehin konfliktarm.

## Konsequenzen

Geringer, planbarer Review-Aufwand; degradiert würdevoll zur Abkopplung, falls Upstream endet, und skaliert zu engerer Integration, falls er wiederauflebt. Voraussetzung ist die Additivität aller Personal-Änderungen (AV-1).

## Verweise

Primärdokument: 02 §3. Regeln: AV-27, AV-32.
