---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-14, AV-19 (Queue-Anteil)
Zugehörige ADRs: ADR-0003, ADR-0005, ADR-0006
Verwandte DEC-Einträge: DEC-014
---

# ADR-0007: Transaktionale Outboxes und Domain Events

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Zwei Risiken waren zu lösen: (a) Externe Provider-Aktionen dürfen nie innerhalb einer SQLite-Transaktion laufen, müssen aber zuverlässig und genau nachvollziehbar ausgeführt werden. (b) Nach einem DB-Commit dürfen Suchindex, Benachrichtigungen, Statistiken und UI-Status nicht auseinanderlaufen, wenn ein EventBus-Publish oder eine Index-Aktualisierung scheitert. Der Upstream-EventBus (synchroner In-Prozess-Dispatch) taugt nicht als kanonische Ereigniswahrheit.

## Entscheidung

1. **Drei getrennte Warteschlangen:** ExternalActionOutbox (R1-Pushes, R1-Executor) · DomainEventOutbox (abgeleitete Wirkungen, Dispatcher) · R2ExecutionQueue (freigegebene R2-Intents, R2-Executor).
2. **In derselben Transaktion** werden gespeichert: kanonische Fachänderung + ggf. ExternalActionOutbox-Eintrag + DomainEvent (eindeutige ID, monotone Sequenz) + Audit-Stufe.
3. Der **DomainEvent-Dispatcher** beliefert nach dem Commit idempotente Consumer (EventPort-Brücke, Suchindex, Benachrichtigungen, abgeleitete Statistiken, Scheduler-Reconciliation): at-least-once, Event-ID + Consumer-Cursor, Retry mit Backoff, Dead-Letter `attention_required`, sichtbarer Index-Lag, vollständiger Index-Rebuild bleibt möglich.
4. **Kein fachlicher Erfolg hängt an einem synchronen Bus-Publish**; der Upstream-EventBus ist reiner Transport abgeleiteter Ereignisse.

## Geprüfte Alternativen

- **Synchrones Publish/Index-Update nach Commit ohne Outbox** — verworfen: Absturz zwischen Commit und Publish erzeugt stille Divergenz.
- **Eine gemeinsame Warteschlange für alles** — verworfen: verhindert getrennte Kill-Switch-Bereiche (AV-19) und vermischt Zustellgarantien.
- **Upstream-EventBus als Ereignisquelle** — verworfen: prozesslokal, synchron, nicht persistent — nie kanonische Wahrheit.

## Konsequenzen

Wiederanlauf nach Absturz ist an jeder Stelle definiert (Integrationstest-Pflicht); Consumer müssen idempotent implementiert werden; Index-Verzögerung ist ein sichtbarer, ehrlicher Systemzustand.

## Verweise

Primärdokument: 11. Regeln: AV-14.
