---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-8, AV-17 (Kontext-Anteil), AV-35
Zugehörige ADRs: ADR-0001, ADR-0006, ADR-0007
Verwandte DEC-Einträge: DEC-013
---

# ADR-0005: ApplicationCommandBus und ActionPipeline

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Die Regel „CLI schreibt über die API, wenn der Server läuft, sonst direkt in die Datenbank" hätte zwei produktive Schreibpfade mit potenziell abweichender Validierung, Rechten und Auditierung erzeugt. Zusätzlich müssen LLM-, Automations- und UI-initiierte Aktionen identisch geprüft werden, ohne die UI mit doppelten Bestätigungsdialogen zu belasten und ohne unehrliche Verifikationsversprechen gegenüber Providern.

## Entscheidung

1. **Ein logischer Schreibpfad:** API, CLI, Chat-Tools und Automationen erzeugen dieselben typisierten Commands, die über den ApplicationCommandBus durch dieselben Validatoren, dieselbe ActionPipeline, dieselben Rechte, Auditierung, Repositories und Zustandsmaschinen laufen.
2. **Transportmodi:** Läuft `serve`, ist die CLI dünner API-Client; sonst startet sie denselben PersonalBootstrap im begrenzten **In-Process-Modus** (exklusive Sperre; keine dauerhaften Worker; DomainEvent-Drain; optional auf eigene Einträge begrenzte R1-Ausführung). **R2-Ausführung nie in-process.**
3. **ActionPipeline** als verbindliche Stufenkette inkl. Schema-Validierung (bei LLM-Vorschlägen genau ein präziser Retry, dann UI), Vorschau, Freigabe, transaktionaler Outbox, Provider-Verifikation, Index-Aktualisierung, Audit (05 §4).
4. **Initiation-Kontexte:** `user_direct` mit vollständiger Vorschau gilt als explizite Bestätigung (kein Doppeldialog); `llm_assisted`/`automation`/`system` benötigen separate Freigabe; R2 immer Approval-Center.
5. **Verifikationszustände** (`verified` / `provider_acknowledged` / `pending_verification` / `unverified` / `verification_failed`) mit deklarierter Adapter-Verifikationstiefe; nie stiller oder fälschlich behaupteter Erfolg.

## Geprüfte Alternativen

- **Zwei Schreibpfade (API + Direkt-DB)** — verworfen: divergierende Validierungs-/Freigabelogik, doppelte Pflege, Audit-Lücken.
- **Bestätigungsdialog für jede R1-UI-Aktion** — verworfen: Doppeldialoge bei bewussten Nutzeraktionen; stattdessen Kontextmodell.
- **Read-back als absolute Pflicht ohne Zustände** — verworfen: Provider ohne Rücklesbarkeit würden das Modell blockieren oder zu stillen Falschangaben zwingen.

## Konsequenzen

Identisches Verhalten aller Transporte ist testbar (AV-35-Integrationstests); die CLI bleibt ohne Server nutzbar, aber begrenzt; jede neue Operation definiert Command, Risikoklasse, Kontextverhalten und Verifikationstiefe.

## Verweise

Primärdokument: 05. Betroffen: 10, 11. Regeln: AV-8, AV-35.
