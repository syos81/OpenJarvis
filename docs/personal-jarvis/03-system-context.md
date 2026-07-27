---
Status: erläuternd
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: — (nicht normativ; maßgeblich sind 04, 05, 07, 09–14)
Zugehörige ADRs: ADR-0001, ADR-0005
Verwandte DEC-Einträge: DEC-003, DEC-013
---

# 03 — Systemkontext

Dieses Dokument ist **nicht normativ** — es visualisiert die in 04–14 normierten Bausteine. Im Widerspruchsfall gelten die dortigen Regelabschnitte.

## §1 Kontextdiagramm

```
Tauri-Shell ─ invoke() ─ React-SPA (Upstream-Seiten + build-time registrierte Personal-Module)
                              │ HTTP: Desktop-Session-Token · WS: Einmal-Ticket, 127.0.0.1
                              ▼
        FastAPI `jarvis serve` (unverändert) + additive Personal-Router (/v1/personal/…)
                              ▼
        Application Services (je Modul) ── Application Orchestrator (modulübergreifende Use-Cases)
                              ▼
        Capability Services + ActionPipeline (R0/R1/R2, Initiation-Kontexte, Verifikationszustände)
             │                    │                     │
             ▼                    ▼                     ▼
        Provideradapter      RiskEngine (R2)       AuditTrail (hash-verkettet) / Approvals
        (CardDAV, CalDAV, IMAP/SMTP/JMAP,
         AppleEventKit-/AppleContacts-Bridge, Broker-API)
                              │
   Sync-Worker + R1-Outbox-Executor   ║   separater R2-Executor (eigener Kill-Switch)
                              ▼
   Persistenz: jarvis.db (kanonisch, ConnectionFactory/UnitOfWork) · Blob-Store · abgeleitete Indizes
   CredentialStore → macOS-Keychain          Backup-Kern (DEK + Keychain + Recovery-Key)
                              ▲
        PersonalJarvisRuntime = Port-Bündel ◄── OpenJarvisRuntimeAdapter ──► OpenJarvis-Bestand
        (ModelPort · MemoryIndexPort · ToolRegistrationPort · EventPort ·
         SchedulerPort · ConfigurationPort · RuntimeHealthPort)
```

## §2 Schichten und Verantwortlichkeiten (Überblick)

- **Tauri-Shell / React-SPA** — produktive Oberfläche; Modul-Frontends strikt gekapselt; Navigation readiness-gesteuert (normativ: 14).
- **FastAPI `jarvis serve`** — unveränderter produktiver lokaler Serverpfad; Personal wird über genau einen bewachten Aufruf angebunden (normativ: 04 §4, 18 DEV-3).
- **Application Services / Orchestrator** — Use-Cases und modulübergreifende Transaktionen (normativ: 05, 07).
- **Capability Services + ActionPipeline** — jede Zustandsänderung durchläuft die Pipeline; Sprachmodelle erreichen nie Adapter oder Tabellen direkt (normativ: 05, AV-8).
- **Provideradapter** — providerneutrale Fachverträge, native Frameworks nur hier (normativ: 08).
- **Persistenz** — eine kanonische `jarvis.db`, Blob-Store, ausschließlich abgeleitete Indizes (normativ: 06, 07).
- **PJR/OJRA** — kleine stabile Port-Fassade; einzige Upstream-Brücke (normativ: 04).
- **Sicherheit querliegend** — CredentialStore/Keychain, Session-Token-Auth, RiskEngine/Approvals, Audit, Egress-Guard, Backup-Kern (normativ: 09–13).

## §3 Prozessmodell

- **Serve-Prozess** — hostet API, alle Worker (Sync, R1-Executor, DomainEvent-Dispatcher, Reconciler, R2-Executor) und hält die exklusive Sperre `personal/serve.lock` (normativ: 07 §5).
- **CLI** — bei laufendem Serve dünner Client der lokalen authentifizierten API; ohne Serve begrenzter In-Process-Modus mit derselben Sperre (normativ: 05 §2).
- **Tauri-Hauptprozess** — Supervisor (startet Backend/Sidecar), liest das Installationsgeheimnis aus dem Keychain und stellt der SPA Session-Tokens bereit (normativ: 09 §1).
