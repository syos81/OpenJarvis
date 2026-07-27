---
Status: normativ (Index)
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-30 (Entscheidungsweg)
Zugehörige ADRs: ADR-0001 bis ADR-0014
Verwandte DEC-Einträge: alle (dieses Dokument ist der Hub)
---

# Entscheidungsregister

Zentrale Übersicht aller Architekturentscheidungen. Neue Entscheidungen werden hier ergänzt (accepted mit Quelle; deferred mit Auslöser). Vertagte Entscheidungen dürfen nicht vorweggenommen werden (17 §1).

## §1 Akzeptierte Entscheidungen

| ID | Titel | Status | Quelle | Datum |
|---|---|---|---|---|
| DEC-001 | Zielbild: offener persönlicher Jarvis auf schlanker, allgemeiner OpenJarvis-Basis; kein Nachbau des alten Jarvis; kein alter Produktivcode | accepted | Eigentümer-Entscheid (Baseline) | 2026-07-27 |
| DEC-002 | Providerneutrale Capability-Verträge je Fachbereich; keine Mega-Schnittstelle; MCP nur möglicher Adapter | accepted | ADR-0002 | 2026-07-27 |
| DEC-003 | Runtime-Fassade: PJR-Port-Bündel + OJRA; keine direkte SystemBuilder-Kopplung; kein Umbau von serve/ask/chat | accepted | ADR-0001 | 2026-07-27 |
| DEC-004 | Eine kanonische `personal/jarvis.db` für alle Fachmodule; getrennte abgeleitete/technische Speicher | accepted | ADR-0003 | 2026-07-27 |
| DEC-005 | Risikomodell R0/R1/R2 mit präzisierten Anforderungen; Trading immer R2; kein LLM-Direkthandel | accepted | ADR-0006 | 2026-07-27 |
| DEC-006 | Externe Telemetrie standardmäßig aus (Code-Default + Presets); `install.sh` kein Installationsweg | accepted | ADR-0013; 18 DEV-1 | 2026-07-27 |
| DEC-007 | Selektive Upstream-Integration ab eingefrorener Baseline; keine automatischen Rebases | accepted | ADR-0011 | 2026-07-27 |
| DEC-008 | Bestehende React-/Tauri-App als produktive UI; strikt gekapselte Modul-Frontends | accepted | Baseline (14) | 2026-07-27 |
| DEC-009 | Toolchain: uv, Python 3.12, Rust ≥ 1.88, maturin, Node 22 (Frontend/Tauri); macOS primär, Linux sekundär; Zusatz-Bridges nicht unterstützt | accepted | Baseline (AV-29; 15 §6) | 2026-07-27 |
| DEC-010 | Keychain-only CredentialStore mit CredentialReference; kein dateibasierter Store; kein Upstream-`credentials.toml` | accepted | ADR-0004 | 2026-07-27 |
| DEC-011 | Workspaces/Rollen/Tags/Organisationen/Beziehungen als konfigurierbares Modell; nie hart codiert | accepted | Baseline (06 §6) | 2026-07-27 |
| DEC-012 | Apple-native Adapter (EventKit/Reminders/CNContactStore) gleichwertig hinter Fachverträgen; Apple-Mail-App keine Datenquelle | accepted | Baseline (08 §4) | 2026-07-27 |
| DEC-013 | ApplicationCommandBus als einziger Schreibpfad; CLI-Modi; R2 nur im Serve-Prozess | accepted | ADR-0005 | 2026-07-27 |
| DEC-014 | Transaktionale Warteschlangen: ExternalActionOutbox / DomainEventOutbox / R2ExecutionQueue | accepted | ADR-0007 | 2026-07-27 |
| DEC-015 | Lokale Auth: Installationsgeheimnis (Keychain) + kurzlebige Desktop-Session-Tokens; SPA nie mit Dauergeheimnis | accepted | ADR-0008 | 2026-07-27 |
| DEC-016 | Cloud-Egress default-deny, fail-closed, EgressGuard-Durchsetzung; Local-first inkl. lokaler Speech-Defaults | accepted | ADR-0009 | 2026-07-27 |
| DEC-017 | Backup/Recovery: DEK + Keychain- und Recovery-Hüllen; SnapshotCoordinator; atomare Aktivierung | accepted | ADR-0010 | 2026-07-27 |
| DEC-018 | Vertikale Modulentwicklung, Materialisierungsregel, Definition of Done | accepted | ADR-0012 | 2026-07-27 |
| DEC-019 | Chatverläufe: Richtungsentscheidung Überführung in die Personal-Datenhoheit (Zeitpunkt offen → DEC-D08) | accepted | Baseline (06 §3) | 2026-07-27 |
| DEC-020 | Konventionen: Namensraum `personaljarvis`, Router-Präfix `/v1/personal/`, UUIDv7, UTC + IANA-Zeitzone | accepted | Baseline (07 §4, 09 §1) | 2026-07-27 |
| DEC-021 | Modul-Lifecycle-Zustandsmaschine mit readiness-gesteuerter Navigation | accepted | Baseline (14 §4) | 2026-07-27 |
| DEC-022 | Globales Migrationsmodell (monotone IDs, Prüfsummen-Ledger, forward-only, Backup-Barriere, fail-closed) | accepted | Baseline (07 §6) | 2026-07-27 |
| DEC-023 | Audit: Hash-Kette + signierte Checkpoints; ehrliches Bedrohungsmodell ohne Unveränderlichkeits-Behauptung | accepted | Baseline (10 §5–6, 13 §5) | 2026-07-27 |
| DEC-024 | Backup-Kern funktioniert ab dem ersten kanonischen Datenbestand (Ausnahme zur Materialisierungsregel) | accepted | Baseline (AV-33, 13 §1) | 2026-07-27 |
| DEC-025 | Tauri-Härtung (Capability-Einengung; kein `run_jarvis_command` im Personal-Betrieb) vor produktivem Desktop-Betrieb | accepted | ADR-0014; 18 DEV-2 | 2026-07-27 |
| DEC-026 | Ein-Punkt-Integration in `jarvis serve` (bewachter `attach`-Aufruf, feature-geschaltet) | accepted | ADR-0001; 18 DEV-3 | 2026-07-27 |
| DEC-027 | Grundsatz: Jede bewusste Upstream-Abweichung besitzt einen eigenen akzeptierten ADR — Baseline-Autorisierung allein ersetzt keinen ADR; DEV-1 nachdokumentiert | accepted | ADR-0013; 18 §1 | 2026-07-27 |
| DEC-028 | DEV-2 (Tauri-Capability-Einengung) in eigenem ADR nachdokumentiert | accepted | ADR-0014; 18 DEV-2 | 2026-07-27 |
| DEC-029 | WebSocket-Authentifizierung per Einmal-Ticket (kryptografisch zufällig, ≤ 30 s, einmalig, sitzungs-/fenster-/origin-/endpunktgebunden; Prüfung vor `accept()`; Redaction aus Logs) — konkrete Ausgestaltung von ADR-0008 | accepted | ADR-0008 (ergänzt); 09 §1 | 2026-07-27 |

## §2 Vertagte Entscheidungen (deferred)

Details, Optionen und unverbindliche Empfehlungen: 17 §2.

| ID | Titel | Status | Auslöser |
|---|---|---|---|
| DEC-D01 | Native-Bridge-Technik (PyObjC vs. Swift-Helper) | deferred | Materialisierung des ersten Apple-nativen Adapters |
| DEC-D02 | Keychain-Anbindung (`keyring` vs. native Security-Framework-Integration) | deferred | Materialisierung des CredentialStore |
| DEC-D03 | Recovery-Key-Format und optionale Passphrase | deferred | Materialisierung des Backup-Kerns |
| DEC-D04 | UI-E2E-Werkzeug | deferred | erstes Modul mit UI-E2E-Pflicht |
| DEC-D05 | Session-Token-TTL und Rotation | deferred | Materialisierung der Auth |
| DEC-D06 | Optionale native R2-Zweitbestätigung | deferred | erstes R2-Modul |
| DEC-D07 | Audit-Checkpoint-Kadenz und externes Medium | deferred | Materialisierung des Audit-Kerns |
| DEC-D08 | Chat-Migration in die Personal-Datenhoheit (Zeitpunkt) | deferred | Planung des Chat-Moduls |
| DEC-D09 | Sensitivitätsmatrix einzelner Datentypen | deferred | erstes LLM-nutzendes Modul |
| DEC-D10 | Erstes Fachmodul und Modulreihenfolge | deferred | gesonderte Freigabe nach Architektur-Materialisierung |
| DEC-D11 | Live-Abnahme-Anbieter | deferred | je Modul vor der Abnahme |
| DEC-D12 | Broker-Ziel | deferred | weit vor dem Trading-Modul |
| DEC-D13 | Home-Server-Secret-Store | deferred | Planung eines Home-Server-Betriebs |
| DEC-D14 | Mail-Skalenpolitik | deferred | Planung des Mail-Moduls |
| DEC-D15 | Initiale Workspaces | deferred | Inbetriebnahme des ersten Moduls |
| DEC-D16 | Backup-Ziele und Aufbewahrung | deferred | Materialisierung des Backup-Kerns |

**Zählung:** 29 akzeptierte, 16 vertagte Entscheidungen.
