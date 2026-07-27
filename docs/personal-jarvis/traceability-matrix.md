---
Status: normativ (Index)
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1 bis AV-37 (Zuordnung)
Zugehörige ADRs: ADR-0001 bis ADR-0014
Verwandte DEC-Einträge: siehe Spalten
---

# Traceability-Matrix

Für jede Verfassungsregel: **Primärdokument** (Single Source der Mechanik; zugleich Dopplungsprüfung — **genau ein Primärdokument je Regel**), **zugehörige ADRs**, **späterer Testtyp** (Taxonomie 15 §1) und **vorgesehene Durchsetzungsstelle**. Zweitnennungen weiterer fachlich relevanter Dokumente stehen ausschließlich als „(Verweis: …)". Testtypen und technische Durchsetzung werden gemäß Materialisierungsregel mit dem jeweils ersten betroffenen Modul umgesetzt; bis dahin gilt manuelle Review gegen diese Matrix (15 §3).

| AV | Primärdokument | Zugehörige ADRs | Späterer Testtyp | Durchsetzungsstelle |
|---|---|---|---|---|
| AV-1 | 02 §2 (Verweis: 18) | ADR-0011, ADR-0013, ADR-0014 | Diff-Scope-Review; Abweichungs-Re-Check je Pick | Review-/Pick-Prozess, Abweichungsliste |
| AV-2 | 19 | ADR-0012 | Modul-Abnahme-Review (DoD-Checkliste) | DoD-Gate, Eigentümer-Abnahme |
| AV-3 | 19 (Verweis: 14 §2) | ADR-0012 | UI-E2E + Review (keine Platzhalter) | Readiness-Gating, Review |
| AV-4 | 08 | ADR-0002 | Contract-Suite + Import-Grenzen-Check | Adapterschicht, Lint-Regel |
| AV-5 | 12 | ADR-0009 | Security-Tests (Egress) | EgressGuard (jeder Cloud-Abfluss inkl. Speech) |
| AV-6 | 04 §2 | ADR-0001 | struktureller Import-Grenzen-Check (CI) | Lint-/Struktur-Check |
| AV-7 | 04 §2 | ADR-0001 | Port-Contract-Tests | OJRA (Typkonvertierung) |
| AV-8 | 05 (Verweis: 12 §6) | ADR-0005, ADR-0009 | Security- + Integrationstests | ActionPipeline, ToolRegistrationPort |
| AV-9 | 14 §2 | ADR-0012 | UI-E2E | Build-time-Registry + Readiness-Endpoint |
| AV-10 | 08 §3 | ADR-0002 | Adapter-Contract-Suite | Capability Service |
| AV-11 | 06 §1–2 | ADR-0003 | Migrationstests + Register-Review | ConnectionFactory, Speicher-Register |
| AV-12 | 07 §2–3 | ADR-0003 | Integrationstests (UoW, Verträge) | UnitOfWork, CompositionRoot-DI |
| AV-13 | 07 §6 | ADR-0003 | Migrationstests | Migrations-Runner |
| AV-14 | 11 | ADR-0007 | Integrationstests (Wiederanlauf, Idempotenz, Lag) | Outboxes + Dispatcher |
| AV-15 | 06 §5 | ADR-0003 | Unit-/Integrationstests (Alias/Merge azyklisch) | Alias-Resolver, Application Orchestrator |
| AV-16 | 06 §1 | ADR-0003 | Index-Rebuild-Test | MemoryIndexPort |
| AV-17 | 10 §1–3 | ADR-0006 | Security-/Integrationstests (Kontexte, Freigaben) | ActionPipeline, Approval-Center |
| AV-18 | 10 §1–2 | ADR-0006 | Security-Tests (kein LLM-Zugriff auf Orders/Regeln) | RiskEngine, R2-Executor |
| AV-19 | 10 §4 | ADR-0006, ADR-0007 | Kill-Switch-Scope-Tests | Executor-Trennung |
| AV-20 | 09 §4 | ADR-0004 | Security-Tests (Leak-Scan, Zweckbindung) | CredentialStore |
| AV-21 | 09 §1 | ADR-0008, ADR-0014 | Security-/Integrationstests (Token; WS-Ticket: Einmalverwendung, Ablauf, Origin-Bindung; Lock) | Auth-Middleware, Session-/WS-Ticket-Aussteller, serve.lock |
| AV-22 | 12 | ADR-0009 | Security-Tests (S2-Blockade, Redaction, Provider-Eigenschaften) | EgressGuard (ModelPort; ebenso Cloud-Speech) |
| AV-23 | 13 | ADR-0010 | Restore-Drill + Migrationstests | SnapshotCoordinator |
| AV-24 | 10 §5–6 (Verweis: 13 §5) | ADR-0010 | Security-Tests (Chain-/Checkpoint-Verifikation) | AuditTrail, Checkpoint-Signierer |
| AV-25 | 18 DEV-1 | ADR-0013 | Unit-Test (Default `False`) | Config-Default + Presets |
| AV-26 | 15 §1 | ADR-0002, ADR-0012 | Contract-Suiten + Live-Abnahme | CI-Gates, DoD |
| AV-27 | 02 §3 (Verweis: 15 §1 Nr. 2) | ADR-0001, ADR-0011 | Port-Contract-Tests + Pick-Prozess | CI + Review |
| AV-28 | 15 §1 | ADR-0012 | Pflichtsuiten (Migration/Security/Recovery/Kill-Switch/Restore) | CI-Gates |
| AV-29 | 15 §6 | — (Baseline; DEC-009) | CI-Umgebungsdefinition | CI-Konfiguration, Doku |
| AV-30 | 01 §4 | alle | Prozess-Review | ADR-Verfahren, Eigentümer-Freigabe |
| AV-31 | 01 §4 (Verweis: 04 §2) | ADR-0001, ADR-0002 | Prozess-Review | ADR-Verfahren |
| AV-32 | 18 §1 | ADR-0011, ADR-0013, ADR-0014 | Review je Pick | Abweichungsliste |
| AV-33 | 01 §5 (Verweis: 16 §3) | ADR-0012 | Planungs-Review | Review-Gate |
| AV-34 | 04 §1, §4 | ADR-0001 | Integrationstests (Bootstrap fail-closed; App-Identität ohne Personal) | PersonalCompositionRoot, Integrationspunkt-Tests |
| AV-35 | 05 | ADR-0005 | Integrationstests (Transport-Gleichheit API/CLI) | ApplicationCommandBus |
| AV-36 | 14 §4 | ADR-0012 | UI-E2E + Zustandsmaschinen-Unit-Tests | Modul-Lifecycle, Nav-Gating |
| AV-37 | 07 §6 | ADR-0003 | Migrationstests (Ledger, Prüfsummen, fail-closed) | Migrations-Runner |
