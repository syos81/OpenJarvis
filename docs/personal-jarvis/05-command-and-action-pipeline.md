---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-8, AV-14 (Pipeline-Anteil), AV-17 (Kontext-Anteil), AV-35
Zugehörige ADRs: ADR-0005
Verwandte DEC-Einträge: DEC-013
---

# 05 — ApplicationCommandBus und ActionPipeline

## §1 Ein logischer Schreibpfad

Jeder mutierende Use-Case ist ein **typisierter Command** mit genau einem Handler (Application Service), ausgeführt über den **ApplicationCommandBus**. **API-Router, CLI, Chat-Tools (via ToolRegistrationPort) und Automationen erzeugen dieselben Commands** und durchlaufen dieselben Validatoren, dieselbe ActionPipeline, dieselben Rechte, dieselbe Auditierung, dieselben Repositories und dieselben Zustandsmaschinen (AV-35). Lesezugriffe laufen über definierte Query-APIs der Module.

## §2 Transportregeln (CLI-Modi)

- **Serve läuft** (erkennbar an `personal/serve.lock`): Die CLI ist ein dünner Client der lokalen authentifizierten API (Auth: Installationsgeheimnis, 09 §1; Port-Discovery über die Lock-Datei).
- **Serve läuft nicht:** Die CLI startet **denselben PersonalBootstrap im In-Process-Modus**: exklusive Prozesssperre zwingend; Migrationen wie im Serve-Modus (fail-closed); **keine dauerhaften Hintergrund-Worker** — nur der DomainEvent-Dispatcher (begrenzt, bis die eigenen Ereignisse verarbeitet sind) und optional eine **auf die selbst erzeugten Einträge begrenzte** R1-Outbox-Ausführung (damit ein bewusst per CLI ausgelöster Versand tatsächlich stattfindet); danach geordneter Shutdown.
- **R2-Ausführung findet nie im CLI-In-Process-Modus statt** — die CLI kann R2-Intents nur erzeugen; Freigabe und Ausführung laufen über den Serve-Prozess und das Approval-Center (10).

## §3 Verbote

- keine direkten CLI-/UI-/LLM-Zugriffe auf Provideradapter,
- keine Zugriffe auf konkrete Repository-Implementierungen fremder Module,
- keine abweichende Validierungs- oder Freigabelogik je Transport,
- kein zweiter produktiver Ausführungsweg.

## §4 ActionPipeline — verbindliche Stufenkette

Jede zustandsändernde Capability-Operation durchläuft:

1. strukturierter Vorschlag (Command),
2. Schema-Validierung — bei LLM-erzeugten Vorschlägen: präziser Validierungsfehler an das Modell, **genau ein** Retry, danach Übergabe an die UI (kein „Raten"),
3. Ziel- und Workspace-Auflösung,
4. Berechtigungsprüfung (Capability im Workspace erlaubt),
5. Risikoklassen-Bestimmung (R0/R1/R2, 10 §1),
6. IdempotencyKey-Erzeugung (bei externen Schreiboperationen zusätzlich Client-UID, wo das Protokoll es erlaubt),
7. Vorschau-Erstellung (vollständig und verständlich: was, wohin, welches Konto),
8. Bestätigung/Freigabe gemäß Initiation-Kontext (§5) und Risikoklasse,
9. Ausführung — externe Wirkung nie direkt, sondern über die transaktionale Outbox (11 §1),
10. Provider-Verifikation (Read-back) mit Verifikationszustand (§6),
11. Abschluss der lokalen Transaktion bzw. Nachtrag des Endzustands,
12. Aktualisierung des abgeleiteten Index (über DomainEvent, 11 §2),
13. Audit-Eintrag je Stufe (10 §5).

## §5 Initiation-Kontexte und Bestätigung (R1)

Jeder Durchlauf trägt `initiation_context ∈ {user_direct, llm_assisted, automation, system}`:

- **`user_direct` + vollständige Vorschau im Formular/Dialog:** Der bewusste Klick („Speichern", „Senden", „Änderung bestätigen") **ist selbst die explizite Bestätigung** — kein zweiter Dialog. Voraussetzung: Die UI-Aktion zeigt den vollständigen Effekt.
- **`llm_assisted` / `automation` / `system`:** separate ausdrückliche Freigabe erforderlich (inline im Chat bzw. Freigabefläche). LLM-initiierte Intents parken in `pending_approval`; das Tool-Ergebnis an das Modell lautet „wartet auf Freigabe" — Ausführung erst nach menschlicher Aktion.
- **R2:** immer Approval-Center mit dauerhaftem Intent — unabhängig vom Kontext (10 §2).

## §6 Verifikationszustände

`verified` · `provider_acknowledged` · `pending_verification` · `unverified` · `verification_failed`

Regeln:

1. Jeder Adapter **deklariert je Operation seine Verifikationstiefe** (08 §3 Nr. 7); `unverified` ist nur bei deklarierter Providergrenze zulässig — nie stillschweigend.
2. Der lokale Erfolgs-Commit ist mit `provider_acknowledged` oder `pending_verification` erlaubt; der Endzustand wird durch den Verifikations-Reconciler nachgetragen (11 §5).
3. `verification_failed` erzeugt Aufmerksamkeit (`attention_required`) und niemals einen stillen Erfolg.
4. Eine Aktion darf nie fälschlich als `verified` gelten; die UI zeigt den Zustand an.

Instanzen dieser Zustände (z. B. die Mail-Zustandsmaschine) sind in 11 §4 normiert.
