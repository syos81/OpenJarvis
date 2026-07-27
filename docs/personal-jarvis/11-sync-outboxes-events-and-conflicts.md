---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-14 (Primärdokument), AV-19 (Queue-Anteil)
Zugehörige ADRs: ADR-0007
Verwandte DEC-Einträge: DEC-014
---

# 11 — Synchronisation, Outboxes, Domain Events und Konflikte

## §1 Drei getrennte Warteschlangen

| Warteschlange | Inhalt | Executor |
|---|---|---|
| **ExternalActionOutbox** | externe Schreiboperationen (R1-Pushes) | R1-Executor |
| **DomainEventOutbox** | abgeleitete interne Wirkungen | DomainEvent-Dispatcher |
| **R2ExecutionQueue** | freigegebene R2-Intents | ausschließlich R2-Executor |

Die Executor- und Kill-Switch-Trennung ist in 10 §4 normiert; ein R2-Not-Aus berührt die beiden anderen Bereiche nie.

## §2 Transactional Domain Events

- **In derselben SQLite-Transaktion** werden gespeichert: kanonische Fachänderung + (falls nötig) ExternalActionOutbox-Eintrag + **DomainEvent-Eintrag** (eindeutige Event-ID, monotone Sequenz) + Audit-Stufe (AV-14).
- **Nach dem Commit** verarbeitet der DomainEvent-Dispatcher die Einträge und beliefert idempotente Consumer: EventPort-Brücke (→ Upstream-Bus als reiner **Transport abgeleiteter Ereignisse, nie kanonische Ereigniswahrheit**), Suchindex-Aktualisierung, Benachrichtigungen, abgeleitete Statistiken, Scheduler-Reconciliation.
- **Garantien:** at-least-once; Idempotenz über Event-ID + Consumer-Cursor; Retry mit Backoff; nach Erschöpfung Dead-Letter-Zustand `attention_required` mit Benachrichtigung; **Index-Lag sichtbar** (Systemstatus: letzte Sequenz vs. Consumer-Cursor); vollständiger Index-Rebuild bleibt jederzeit möglich (AV-16); **kein fachlicher Erfolg hängt an einem synchronen Bus-Publish**.

## §3 Synchronisationslogik

- **Pull:** je (Konto × Collection) ein SyncState-Eintrag mit opakem Cursor; Delta-Sync wo möglich, sonst ETag-basierter Voll-Abgleich; geänderte Objekte werden gelesen, normalisiert, per Repository upserted; externe Identitäten (ID + ETag/Version) werden aktualisiert; Provider-Löschungen erzeugen lokale Soft-Deletes.
- **Push (Outbox-Muster, verbindlich):** Jede lokale R1-Änderung schreibt kanonische Daten **und** Outbox-Eintrag (mit IdempotencyKey und Ziel-Version) in einer Transaktion. Der R1-Executor führt aus: Adapter-Aufruf → Read-back gemäß deklarierter Verifikationstiefe (05 §6, 08 §3 Nr. 7) → ETag/ID zurückschreiben → Eintrag abschließen. Abstürze zwischen Schritten sind wiederanlaufbar; Doppelausführung wird durch IdempotencyKey + Client-UID verhindert bzw. erkannt.
- **Tombstones:** lokale Löschungen bleiben als Tombstone bis zur bestätigten Provider-Löschung; eingehende Syncs prüfen gegen Tombstones (kein Wiederauferstehen).
- **Dubletten:** Kandidaten über normalisierte Schlüssel (E-Mail, Telefon, UID); **niemals Auto-Merge** — Zusammenführen ist immer ein bestätigter Vorgang (Referenzablauf 3; Modell in 06 §5).
- **Konflikte:** Schreiben mit Versionsbedingung; `Conflict` erzeugt einen Konfliktdatensatz mit beiden Ständen (lokal/extern) und gemeinsamer Basis, sichtbar in UI/Benachrichtigungen. Politik: **kein stiller Datenverlust**; feldweise Zusammenführung nur bei disjunkten Änderungen, sonst manuelle Dreiwege-Auflösung; die Auflösung erzeugt einen neuen Push mit neuer Versionsbedingung.
- **Offline und Teilfehler:** Lesen immer aus der kanonischen DB; Schreibvorgänge queuen in der Outbox; Fehler werden **pro Objekt** behandelt (nie Batch-Abbruch); Retry mit exponentiellem Backoff + Jitter und Obergrenze, danach `attention_required` + Benachrichtigung; `RateLimited` respektiert `retry_after`.
- **Circuit-Breaker je Konto:** wiederholte Transportfehler öffnen ihn (Zustand `degraded`, Worker pausiert das Konto, Outbox sammelt weiter); Half-Open-Probe in Intervallen; Erfolg schließt ihn und die Outbox arbeitet nach. `AuthExpired` führt stattdessen in `reauth_required` mit geführtem Re-Auth-Fluss. Andere Konten/Module bleiben unberührt.

## §4 Mail-Ausführungszustand (ehrlich)

`queued → submitting → accepted_by_smtp → sent_unverified → verified_in_sent_folder`

Fehlerpfade: `failed` (vor SMTP-Annahme; retry-fähig) und **`uncertain_outcome`** (Verbindungsabbruch nach Übermittlung / mehrdeutige Antwort): **kein automatischer Neuversand.** Der Reconciler prüft per Message-ID-Suche (Gesendet-Ordner/IMAP) und löst nach `verified_in_sent_folder` bzw. `failed` auf; bleibt es unklar, entscheidet der Nutzer explizit. Die Message-ID dient der **Erkennung**, nicht der Verhinderung des Doppelversands — die Zustandsmaschine ist die eigentliche Sicherung. Kann ein Provider den Gesendet-Ordner nicht bereitstellen, endet der Erfolgspfad deklariert bei `sent_unverified` (08 §3 Nr. 7).

## §5 Reconciler

Ein Hintergrundprozess (nur im Serve-Prozess) trägt offene Zustände nach: `pending_verification` → Endzustand; `uncertain_outcome` → Auflösung gemäß §4; er arbeitet idempotent und objektweise.

## §6 Referenzabläufe

*Nicht eigenständig normativ — verbindliche Illustration der Regeln aus 05, 06, 10, 11 und 13; im Widerspruchsfall gelten die Regelabschnitte.*

1. **Termin erstellen.** Chat (`llm_assisted`): strukturierter Vorschlag → Schema-Validierung (ein präziser Retry) → Ziel-/Teilnehmer-Auflösung (unbekannte Teilnehmer bleiben Roh-E-Mail) → R1 → Vorschau im Chat → separate Bestätigung → Transaktion (Event + Outbox + DomainEvent + Audit) → Push (CalDAV-PUT mit Client-UID/If-None-Match) → Read-back `verified` (EventKit: lokal sofort `verified`) → Index/Audit. Kalender-Formular (`user_direct`): der Speichern-Klick mit Vollvorschau ist die Bestätigung. Fehlerpfade: verweigert/abgelaufen ⇒ nichts geschrieben; `Conflict` ⇒ Konfliktdatensatz; Read-back-Abweichung ⇒ `verification_failed` + Aufmerksamkeit.
2. **Mail senden.** Compose (`user_direct`, Senden-Klick = Bestätigung) bzw. Chat (`llm_assisted`, separate Freigabe) → Outbox `queued` → Zustandsmaschine §4 inkl. `uncertain_outcome`-Reconciliation; kein automatischer Neuversand nach SMTP-Annahme.
3. **Kontakt zusammenführen.** Dubletten-Vorschlag (nie automatisch) → Vorschau (feldweiser Plan + Push-Folgen) → Bestätigung → **eine UoW**: Zielkontakt aktualisiert, Quelle soft-deleted, **MergeRedirect angelegt (kein Massen-Umschreiben fremder Tabellen)**, modul-lokale Strukturen bereinigt, Outbox-Einträge je Provider, MergeRecord + DomainEvent + Audit → Pushes mit Verifikationszuständen (`synchronized`/`partially_synchronized` je Binding) → Undo nur als neue Entität + Reversal Event (06 §5).
4. **Dokument importieren.** Datei → Hash → Dedup (vorhandener Hash ⇒ nur neue Referenz) → Blob inhaltsadressiert → Transaktion: Metadaten + DomainEvent → asynchrone Chunking-/Index-Aktualisierung; Parserfehler ⇒ sichtbarer Zustand `imported_unindexed` mit Grund; Index jederzeit aus Blobs + Metadaten neu aufbaubar.
5. **Life-OS-Messwert übernehmen.** Quelle-Adapter liefert Rohsätze → Validierung (Einheit, Plausibilitätsfenster) → Provenienz (Quelle, Import-Charge, Rohreferenz) → idempotenter Upsert (natürlicher Schlüssel Quelle+Zeit+Metrik) → abgeleitete Statistiken via DomainEvent → Audit der Charge. Teilinvalide Chargen: valide Sätze übernommen, Fehlerliste sichtbar; Widersprüche ⇒ Konfliktliste statt Überschreiben.
6. **Trading-Order vorbereiten und freigeben (R2).** Vorschlag (LLM oder UI) → Schema-Validierung → **deterministische RiskEngine** (Allowlist, Limits, Deckung, Handelszeiten, Duplikatssperre) → dauerhafter ApprovalIntent (`pending_approval`) mit vollständiger Vorschau inkl. Regelergebnis → menschliche Freigabe im Approval-Center → **Zustands-Recheck unmittelbar vor Ausführung** (Abweichung ⇒ `pending_approval`/`aborted`) → BrokerAdapter mit IdempotencyKey → Read-back Orderstatus/Fills → kanonische Order-Zustandsmaschine `submitted → partially_filled → filled | rejected | cancelled` → unveränderliches Ausführungsprotokoll + signierter Checkpoint. Läuft ausschließlich im R2-Executor; der R2-Kill-Switch stoppt nur diesen (offene Intents ⇒ `aborted`); Sync/R1 laufen weiter.
7. **Provider verliert die Verbindung.** Transportfehler → objektweiser Retry (Backoff+Jitter, Obergrenze) → Circuit-Breaker öffnet (`degraded`, Konto pausiert, Outbox sammelt, UI-Statuschip + Benachrichtigung) → Half-Open-Probe → Erfolg schließt, Outbox arbeitet nach; `AuthExpired` ⇒ `reauth_required` mit geführtem Fluss. Betrifft nur das jeweilige Konto/Binding.
8. **Konflikt lokal ↔ extern.** Push trifft `Conflict` → externer Stand wird geladen → Konfliktdatensatz (lokal, extern, Basis) → Objekt `conflicted` (weiter lesbar; weitere lokale Änderungen stapeln lokal) → Auflösung (automatisch nur disjunkt, sonst Dreiwege-UI) → neuer Push mit neuer Versionsbedingung → Read-back → `resolved`; das Audit dokumentiert die Wahl. Nie stiller Verlust einer Seite.
9. **Wiederherstellung aus Backup.** Vollständig in 13 §4 normiert (Manifest-/Prüfsummen-Verifikation, Staging, Migrationen, Integritätsprüfung, atomare Aktivierung, Index-Rebuild, Konten-Re-Link, Abschluss-Audit).
