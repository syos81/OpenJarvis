---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1, AV-11, AV-12, AV-16, AV-33, AV-35
Zugehörige ADRs: ADR-0020 (autorisiert dieses Register), ADR-0003, ADR-0004, ADR-0011, ADR-0017
Verwandte DEC-Einträge: DEC-044 (Übernahme des Audit-Kanons); berührt DEC-D09
---

# 20 — OpenJarvis-Reuse-Register (Audit-Übernahme)

Dieses Register überführt die Einzelentscheidungen des am **2026-07-31** formal abgenommenen **OpenJarvis Connector-, Capability- und Reuse-Audits** verbindlich in die Personal-Jarvis-Architektur (ADR-0020, DEC-044). Es ist die **einzige kanonische Stelle** dieser Entscheidungen; der Auditbericht wird nicht als Parallelkopie eingefroren. Bei Komponentenkonflikt gilt die feinere Einzelentscheidung hier gegenüber der Boundary-Map (02).

## §0 Lesehinweise

- **Entscheidungsklassen** (abschließend, ADR-0020 §2): KEEP · REUSE · ADAPT · PROJECT · REPLACE · REMOVE. **REMOVE = Stilllegung/Deaktivierung in der Personal-Zielarchitektur**; physisches Löschen von Upstream-Dateien nur nach gesonderter Freigabe (02 §2.4, 18 §3, ADR-0011).
- **Wartungszustand** (ruhend/Legacy/experimentell/verwaist/tot) ist **kein** Entscheidungsbestandteil.
- **Kanonische Datenquelle** einer projizierbaren Domäne ist stets `personal/jarvis.db`; Suchindex und Agentenmemory sind ausschließlich abgeleitet (AV-16, 06 §1).
- **Beweisstände** des Audits: BELEGT · STATISCH PLAUSIBEL · DOKUMENTIERT · WIDERSPRÜCHLICH · UNGEKLÄRT. Plattformtauglichkeit reiner Python-/portabler Komponenten ist, sofern nicht anders vermerkt, arm64/x86_64 **statisch plausibel**, produktiv nicht nachgewiesen.
- **Branchgültigkeit:** Alle Upstream-Befunde dieses Registers gelten identisch auf `origin/jarvis/rebuild-v1` (@ `d037cb67`) und dem Kontakte-Handoff; sie sind branchunabhängig. Kontakte-Sync-Audit, Recovery und die TCC-/Entitlement-Architektur liegen ausschließlich auf dem Handoff und werden erst mit dessen Integration Teil der Produktivarchitektur (modules/contacts.md §19, Gate 8).

## §1 Kategorientrennung (ADR-0020 §3)

Jeder Bestandteil gehört genau einer Primärkategorie an: (a) **Fachmodul** · (b) **Connector/externe Datenquelle** · (c) **kontrollierte Suchprojektion** · (d) **gemeinsame Infrastruktur** · (e) **Channel/Kommunikationsweg** · (f) **autonom ausführbare Fähigkeit**. Mischformen werden analytisch getrennt; die verletzte Grenze wird benannt (§6).

## §2 Connectoren C-01 … C-25 (Kategorie b)

Gemeinsame Fakten (BELEGT, Audit): Registry `src/openjarvis/core/registry.py:157`; Auto-Import mit stillem `except ImportError` in `src/openjarvis/connectors/__init__.py:14-134`; Persistenz in `~/.openjarvis/knowledge.db` (`src/openjarvis/connectors/store.py:28-111`); **keine Löschsemantik** (`knowledge_chunks.deleted_at` ohne Schreiber); Secrets als Klartext-JSON `~/.openjarvis/connectors/<id>.json` (`src/openjarvis/connectors/oauth.py:260-268`); Auto-Backfill bei Connect (`src/openjarvis/server/connectors_router.py:443-449`). Diese Grenzen begründen die Sperren aus ADR-0020 §5.

| ID | Komponente / Pfad | Entscheidung | Begründung (Kurz) | zulässige spätere Verwendung | unzulässig | kanon. Quelle |
|---|---|---|---|---|---|---|
| C-01 | apple_contacts · `src/openjarvis/connectors/apple_contacts.py` | **REMOVE** | zweite Kontakte-Wahrheit; undokumentiertes AddressBook-SQLite; FDA | — | jeder Personal-Betrieb bis Deaktivierung; Zugriff aus personaljarvis | `personal/jarvis.db` (Kontakte) |
| C-02 | imessage · `src/openjarvis/connectors/imessage.py` | **ADAPT** | einziger iMessage-Lesezugang; nur nach einem eigenen, bei Bedarf noch zu erstellenden Nachrichtenquellen-ADR (Grundsatz analog DEC-012) | kontrollierte Datenquelle je ADR, mit SQL-`since` und Inkrementalität | produktive Nutzung ohne ADR; interner Formatzugriff ungeklärt | keine — reine Datenquelle; Index bleibt abgeleitet |
| C-03 | apple_notes · `src/openjarvis/connectors/apple_notes.py` | **ADAPT** | mögliche Wissensquelle; fragiler gzip-Protobuf-Parser | Dokumente/Wissen je ADR | produktive Nutzung ohne ADR | Dokumente-Modul (später) |
| C-04 | apple_health · `src/openjarvis/connectors/apple_health.py` | **ADAPT** | XML-Export = vorgesehener Life-OS-Adapter; DB-Direktzugriff (ohne ro-Modus) entfernen | XML-Exportpfad im Life-OS-Modul | HealthKit-DB-Direktzugriff | Life-OS-Modul (später) |
| C-05 | apple_music · `src/openjarvis/connectors/apple_music.py` | **REMOVE** | kein Zielbild-Nutzen; osascript-Subprozess; kein Cursor | — | Personal-Betrieb | — |
| C-06 | obsidian · `src/openjarvis/connectors/obsidian.py` | **REUSE** | sauberste Dateisystemquelle; Vorlage Dokumente-Adapter | Dokumente-Modul (Dateisystem-Adapter) | als eigene fachliche Wahrheit | Dokumente-Modul (später) |
| C-07 | whatsapp (Export) · `src/openjarvis/connectors/whatsapp.py` | **REMOVE** | Einmal-Import, fehlerhafte Datumsparserei, defekter HTTP-Weg | — | Personal-Betrieb | — |
| C-08 | gmail (OAuth REST) · `src/openjarvis/connectors/gmail.py` | **REPLACE** | verletzt 08 §3 (Delta/Taxonomie/Keychain); approval-freier Schreibpfad | Referenz beim Mail-Modul-Adapter | Mutationen (`delete/archive`) im Personal-Betrieb | Mail-Modul (später) |
| C-09 | gmail_imap · `src/openjarvis/connectors/gmail_imap.py` | **REPLACE** | Default-UI-Pfad; kein UIDVALIDITY, falsche Thread-IDs, Klartext-App-Passwort | Referenz Mail-Modul | Personal-Betrieb; ADR-0017-Verstoß | Mail-Modul (später) |
| C-10 | outlook · `src/openjarvis/connectors/outlook.py` | **REPLACE** | erbt C-09-Defekte; irreführende Azure-UI | Referenz Mail-Modul | Personal-Betrieb | Mail-Modul (später) |
| C-11 | gcalendar · `src/openjarvis/connectors/gcalendar.py` | **REPLACE** | als Kalender-Adapter unbrauchbar (kein syncToken, TZ verworfen, keine Serienidentität, Schreib-PATCH ohne ETag/Approval) | Referenz beim Kalender-Modul (Google später als API/CalDAV-Adapter) | Mutationen (`accept/decline`); Personal-Betrieb | Kalender-Modul (Modul 2) |
| C-12 | gcontacts · `src/openjarvis/connectors/gcontacts.py` | **REMOVE** | zweite Kontakte-Wahrheit; künftiger Weg = CardDAV-Adapter des Moduls | — | Personal-Betrieb | `personal/jarvis.db` (Kontakte) |
| C-13 | gdrive · `src/openjarvis/connectors/gdrive.py` | **REUSE** | legitime spätere Cloud-Dokumentquelle; readonly-Scope | Dokumente-Modul | eigene fachliche Wahrheit; Klartexttoken | Dokumente-Modul (später) |
| C-14 | google_tasks · `src/openjarvis/connectors/google_tasks.py` | **REMOVE** | kein tragfähiger Grundstock; Aufgaben-Modul plant andere Adapter | — | Personal-Betrieb | Aufgaben-Modul (später) |
| C-15 | slack (Connector) · `src/openjarvis/connectors/slack_connector.py` | **ADAPT** | Wissensquelle; Cursor-No-Op, PII-Logging, Tokenablage umbauen | Wissens-/Nachrichtenquelle je ADR | Personal-Betrieb ohne Umbau | Dokumente-Modul (später); als Nachrichtenquelle keine |
| C-16 | notion · `src/openjarvis/connectors/notion.py` | **REUSE** | öffentliche API, echter Cursor | Dokumente-Modul | eigene fachliche Wahrheit | Dokumente-Modul (später) |
| C-17 | granola · `src/openjarvis/connectors/granola.py` | **REUSE** | bester externer Connector (Key-Validierung, Cursor, saubere Logs) | Dokumente-/Meeting-Quelle | eigene fachliche Wahrheit | Dokumente-Modul (später) |
| C-18 | dropbox · `src/openjarvis/connectors/dropbox.py` | **REUSE** | vorbildlicher serverseitiger Delta-Cursor; OAuth-Provider-Eintrag nachziehen | Dokumente-Modul | eigene fachliche Wahrheit | Dokumente-Modul (später) |
| C-19 | oura · `src/openjarvis/connectors/oura.py` | **ADAPT** | Life-OS-Gerätequelle; Cursor/Keychain umbauen | Life-OS-Modul | Personal-Betrieb ohne Umbau | Life-OS-Modul (später) |
| C-20 | strava · `src/openjarvis/connectors/strava.py` | **ADAPT** | Life-OS-Quelle | Life-OS-Modul | Personal-Betrieb ohne Umbau | Life-OS-Modul (später) |
| C-21 | spotify · `src/openjarvis/connectors/spotify.py` | **REMOVE** | kein Modulbezug; Datenquellen-Kriterien nicht erfüllt (Sicherheit: niedrig) | ggf. Life-OS-Reaktivierung per ADR | Personal-Betrieb | — |
| C-22 | weather · `src/openjarvis/connectors/weather.py` | **ADAPT** | nützliche Kontextquelle (Briefing); Key→Keychain, Fehlerpfad härten | T1-Briefing/Kontext | Klartext-Key produktiv | Cache (nicht kanonisch) |
| C-23 | github_notifications · `src/openjarvis/connectors/github_notifications.py` | **ADAPT** | sinnvolle Benachrichtigungsquelle; Dateinamen-Bug + Key-Ablage | Benachrichtigungsquelle je Modul | Personal-Betrieb ohne Fix | Cache/Benachrichtigungen |
| C-24 | hackernews · `src/openjarvis/connectors/hackernews.py` | **KEEP** | keine Härtung nötig: kein Secret, kein PII, fester öffentlicher Host, Tests vorhanden | Kontextquelle | — | Cache (nicht kanonisch) |
| C-25 | news_rss · `src/openjarvis/connectors/news_rss.py` | **ADAPT** | **SSRF-Gate (08 §3 Nr. 8)** und Parserhärtung erforderlich | Kontext-/Newsquelle nach Härtung | freie URL-Konfiguration ohne SSRF-Prüfung | Cache (nicht kanonisch) |

## §3 Connector-Infrastruktur (Kategorie d, in `connectors/`)

| ID | Komponente / Pfad | Entscheidung | Kurzbegründung |
|---|---|---|---|
| I-01 | `_stubs.py` (Document/SyncStatus/BaseConnector) `src/openjarvis/connectors/_stubs.py` | **REUSE** | sauberes Typfundament / DTO-Vorlage |
| I-02 | IngestionPipeline `src/openjarvis/connectors/pipeline.py` | **ADAPT** | Lösch-/Rebuild-Semantik ergänzen |
| I-03 | SyncEngine `src/openjarvis/connectors/sync_engine.py` | **ADAPT** | Cursor-Rückführungsdefekt (`:104`) |
| I-04 | SyncScheduler `src/openjarvis/connectors/scheduler.py` | **REMOVE** | tot, nie verdrahtet |
| I-05 | KnowledgeStore/knowledge.db `src/openjarvis/connectors/store.py` | **ADAPT** | Projektionsvertrag + Rebuild + Löschweitergabe (siehe §5) |
| I-06 | Chunker `src/openjarvis/connectors/chunker.py` | **ADAPT** | Doppelung mit `src/openjarvis/tools/storage/chunking.py` konsolidieren |
| I-07 | OllamaEmbedder `src/openjarvis/connectors/embeddings.py` | **REUSE** | lokal, fail-soft |
| I-08 | embedding_store `src/openjarvis/connectors/embedding_store.py` | **REUSE** | Rechte nachziehen |
| I-09 | attachment_store `src/openjarvis/connectors/attachment_store.py` | **REUSE** | inhaltsadressiert, 0600/0700 |
| I-10 | retriever `src/openjarvis/connectors/retriever.py` | **REUSE** | ok |
| I-11 | hybrid_search `src/openjarvis/connectors/hybrid_search.py` | **ADAPT** | gcalendar-Fachlogik entkoppeln |
| I-12 | oauth + google_auth `src/openjarvis/connectors/oauth.py`, `google_auth.py` | **REPLACE** | eigener Flow mit state+PKCE; Keychain (02 §2.4, ADR-0017) |
| I-13 | upload_router `src/openjarvis/server/upload_router.py` | **REUSE** | direkter Ingest-Pfad |

## §4 Gemeinsame Infrastruktur (Kategorie d) — 37 Einzelkomponenten mit je genau einer Entscheidung

Jede Komponente trägt **genau eine** Entscheidung; der Wartungszustand ist getrennt notiert.

| Nr. | Komponente / Leitpfad | Entscheidung | Wartungszustand | Kurzbegründung |
|---|---|---|---|---|
| 1 | Konfigurationssystem `src/openjarvis/core/config.py`, `core/paths.py` | ADAPT | aktiv | Env-Präzedenz mit Rust/Tauri vereinheitlichen; DEV-1 |
| 2 | Credential-/Secret-Verwaltung `src/openjarvis/core/credentials.py` | REPLACE | produktiv (Upstream) | Klartext + os.environ-Export; Keychain-only (ADR-0004/0017) |
| 3 | EventBus `src/openjarvis/core/events.py` | KEEP | produktiv | stabil, keine Härtung nötig |
| 4 | Registry-Grundlage `src/openjarvis/core/registry.py` | KEEP | produktiv | stabil |
| 5 | Ingestion-Pipeline `src/openjarvis/connectors/pipeline.py` | ADAPT | aktiv | Löschpfad fehlt (= I-02) |
| 6 | Dokumentmodell `src/openjarvis/connectors/_stubs.py` | REUSE | Legacy | DTO-Vorlage (= I-01) |
| 7 | Chunking `src/openjarvis/connectors/chunker.py` (+ `tools/storage/chunking.py`) | ADAPT | aktiv | Doppelimplementierung konsolidieren |
| 8 | Suchindex/FTS `src/openjarvis/connectors/store.py` | ADAPT | aktiv | Projektionsvertrag, Löschweitergabe, Rebuild |
| 9 | Embeddings `src/openjarvis/connectors/embeddings.py`, `embedding_store.py` | REUSE | Legacy | Rechte/Modellversionierung |
| 10 | Retrieval `src/openjarvis/connectors/retriever.py`, `hybrid_search.py` | ADAPT | aktiv | Fachlogik entkoppeln |
| 11 | Agent Runtime `src/openjarvis/agents/` (`_stubs.py`, `executor.py`, `manager.py`, `prompt_loader.py`) | ADAPT | aktiv | Registrierungsdefekte; Prompt-Fachlogik |
| 12 | Tool Registry `src/openjarvis/core/registry.py` + `src/openjarvis/tools/__init__.py` | ADAPT | aktiv | Resolver-Defaults; Whitelist je Modul |
| 13 | ToolExecutor `src/openjarvis/tools/_stubs.py` | ADAPT | aktiv | Confirmation nur 3 Tools; BoundaryGuard tot |
| 14 | Authentifizierung `src/openjarvis/server/auth_middleware.py` | KEEP | produktiv | Bearer + Bind-Safety; DEV-3 verankert |
| 15 | Berechtigungen/RBAC `src/openjarvis/security/capabilities.py` | REPLACE | verwaist | default-aus/default-open; Personal nutzt eigenes Modell (09/10) |
| 16 | Approvals (Upstream) `src/openjarvis/tools/approval_store.py`, `server/approval_routes.py` | REMOVE | verwaist | domänengeprägt; Personal-Approval-Kern eigenständig |
| 17 | Logging `src/openjarvis/cli/log_config.py` + modulweit | ADAPT | produktiv | PII-Redaktion + Log-Retention |
| 18 | Audit (Upstream) `src/openjarvis/security/audit.py` | ADAPT | produktiv | Preview-Politik + Retention; Personal-Audit getrennt |
| 19 | Fehlerbehandlung (verteilt; stille ImportError-Blöcke) | REPLACE | produktiv (Upstream) | keine geschlossene Taxonomie; Personal `src/personaljarvis/errors.py` |
| 20 | Scheduler (Task) `src/openjarvis/scheduler/scheduler.py`, `store.py` | ADAPT | Legacy/defekt | Dry-run success=True; kein Retry; nur hinter SchedulerPort |
| 21 | Worker/Hintergrund `src/openjarvis/agents/scheduler.py`, `server/connectors_router.py` (Backfill) | ADAPT | produktiv | Autostart schalten; Backfill entfernen |
| 22 | Lokale Modellanbindung `src/openjarvis/engine/` (`_discovery.py`, `ollama.py`, `cloud.py`) | ADAPT | produktiv | EgressGuard-Bindung für Cloud-Engines erforderlich |
| 23 | Backend-Kompositionswurzel `src/openjarvis/server/app.py` + `src/openjarvis/cli/serve.py` | ADAPT | aktiv | SendBlue-Restore entfernen; Wurzeln konvergieren; DEV-1 |
| 24 | Tauri-Komposition `frontend/src-tauri/` (`tauri.conf.json`, `src/lib.rs`, `capabilities/default.json`) | ADAPT | aktiv | DEV-2 offen (unscoped shell; `run_jarvis_command`) |
| 25 | Sidecarmechanismus `src/personaljarvis/contacts/bridge/`, `frontend/src-tauri/src/lib.rs`, `native/contacts-bridge/PROTOCOL.md` | REUSE | aktiv | Vorlage für EventKit; Symlink-/Arch-Validierung |
| 26 | Packaging `.github/workflows/desktop.yml`, `frontend.yml`, `native/contacts-bridge/build.sh` | ADAPT | aktiv | CI-Sidecar-Override; Frontend-CI ohne Tests |
| 27 | Signierung `frontend/src-tauri/*.entitlements`, `scripts/reseal-contacts-sidecar.sh`, `tauri.conf.json` | ADAPT | aktiv | Updater-Endpoint; Reseal in CI |
| 28 | UI-Routing/Navigation `frontend/src/App.tsx`, `components/Layout.tsx`, `components/Sidebar/Sidebar.tsx` | ADAPT | aktiv | Tests in CI; toter Code klären |
| 29 | Data-Sources-Oberfläche `frontend/src/pages/DataSourcesPage.tsx`, `lib/connectors-api.ts`, `types/connectors.ts` | REPLACE | aktiv | modulgebundene Oberflächen (14); kein Bearer, Auto-Backfill |
| 30 | Traces `src/openjarvis/traces/store.py` | ADAPT | produktiv | volle Prompts/Ergebnisse; Retention erforderlich |
| 31 | Telemetrie (lokal) `src/openjarvis/telemetry/store.py` | ADAPT | produktiv | PII gering (nicht null); Rechte + Retention |
| 32 | Workflow `src/openjarvis/workflow/engine.py` | ADAPT | ruhend | kein Personal-Nachweis; Sandbox-Bindung |
| 33 | Operators `src/openjarvis/operators/manager.py` | REMOVE | verwaist | nicht verdrahtet; tote Config-Keys |
| 34 | Skills `src/openjarvis/skills/` (`manager.py`, `data/*.toml`, `sources/`) | ADAPT | Legacy | Fachmanifeste entfernen/verifizieren; defekter `llm_call`-Verweis |
| 35 | A2A `src/openjarvis/a2a/` | REMOVE | verwaist | kein Aufrufweg; toter Config-Key |
| 36 | Evals `src/openjarvis/evals/` (`datasets/morning_brief.py`, `environments/lifelong_agent_env.py`) | ADAPT | ruhend | Kalender-/Mail-Fixtures abgrenzen |
| 37 | Sandbox `src/openjarvis/sandbox/` (+ `security/subprocess_sandbox.py`) | ADAPT | ruhend/experimentell | Confirmation-Pflicht (02 §2.4) unerfüllt |

Ergänzend (je genau eine Entscheidung): Personal-Basis `src/personaljarvis/base/` **KEEP** (aktiv); Daemon-Stub `src/openjarvis/daemon/` **REMOVE** (tot); Sessions `src/openjarvis/sessions/` + `server/session_store.py` + `rust/crates/openjarvis-sessions/` **ADAPT** (drei Schemata, DEC-D08); MCP `src/openjarvis/mcp/` **ADAPT** (Annotationslücke, Egress); Memory-Fakten `src/openjarvis/memory/` **ADAPT** (PII-Klartext, Retention); tools/storage `src/openjarvis/tools/storage/` **ADAPT**; Learning `src/openjarvis/learning/` **ADAPT** (ruhend; Prompt-Override-Pfad); Mining `src/openjarvis/mining/` **REMOVE** (deaktiviert, 02 §2.3); Speech `src/openjarvis/speech/` **ADAPT** (x86_64 durch onnxruntime blockiert); Rust-Workspace `rust/` **ADAPT** (Root-Vereinheitlichung); `src/openjarvis/intelligence/model_catalog.py` **KEEP**.

## §5 Kontrollierte Suchprojektion — Zielkomponente Z-1 (Kategorie c, NICHT IMPLEMENTIERT)

- **Status:** existiert nicht (BELEGT: keine `knowledge`/`store`-Referenz in `src/personaljarvis/`, keine `personaljarvis`-Referenz in `src/openjarvis/connectors/`). Sie darf **nicht** als vorhandener PROJECT-Connector geführt werden.
- **DOKUMENTIERT (normativ festgelegt):** kanonische Quelle ist `personal/jarvis.db` (06 §1); Projektion ausschließlich kanonisch → Index (AV-16); kein Rückschreiben aus Index/Memory/Tool (AV-35, DEC-013); Tombstone-/Löschweitergabe verpflichtend (06 §4); Index vollständig neu aufbaubar (06 §1); lokale Rollen/Metadaten bilden im Index keine eigene Wahrheit (06 §4, 16 §2).
- **UNGEKLÄRT (Moduleinstieg):** Granularität, Sensitivitätsfilter (DEC-D09), Zielspeicher (`knowledge.db` vs. eigener Personal-Index, 06 §2), Embedding-/Egress-Politik, Konsistenzfenster.
- **Bau:** erstmals im **Kontakte-Modul** (AV-33), als Bestandteil von dessen Abschluss (modules/contacts.md §19). Bis dahin gilt: `knowledge.db` erhält je Domäne erst dann wieder Einträge, wenn der Projektionspfad existiert; die alten Domänen-Connectoren (C-01/C-08…C-12/C-14) bleiben deaktiviert.

## §6 Verletzte Grenzen (Fachlogik in generischer Infrastruktur)

Analytisch getrennt (Kategorie d mit eingeschlossener Fachlogik → zu bereinigen im jeweils zuständigen Modul): (a) Orchestrator hardcodiert Morning-Digest-Intent `src/openjarvis/system/orchestrator.py:95-109`; (b) `src/openjarvis/tools/proactive_tools.py` importiert Gmail/GCal/iMessage direkt (Provider-Mutationen ohne Approval) — **Tool 56 `execute_pending_actions` = REMOVE**; (c) domänengeprägte Approval-Schlüssel `src/openjarvis/tools/approval_store.py`; (d) SendBlue-Restore `src/openjarvis/server/app.py:27-114,311`; (e) Quellnamen in Tool-Schemata; (f) `TOOL_CREDENTIALS` in `src/openjarvis/core/credentials.py`; (g) gcalendar-Logik in `src/openjarvis/connectors/hybrid_search.py`.

## §7 Persistenzentscheidungen (Auszug; kanonische Detailtabelle im Audit, Register-Bindung hier)

Die vom Eigentümer ausdrücklich zu erhaltenden Einzelentscheidungen (keine Sammel-KEEP):

| Speicher | Entscheidung |
|---|---|
| P-30a Cache-Verzeichnis `~/.openjarvis/cache/` | **KEEP** |
| P-30b GitHub-Skill-Cache `~/.openjarvis/skill-cache/github/` | **ADAPT** |
| P-30c Hermes-Skill-Cache `~/.openjarvis/skill-cache/hermes/` | **ADAPT** |
| P-30d OpenClaw-Skill-Cache `~/.openjarvis/skill-cache/openclaw/` | **ADAPT** |
| P-30e `~/.openjarvis/version-check.json` | **KEEP** |
| P-30f `~/.openjarvis/cli.log` | **ADAPT** |
| P-30g `~/.openjarvis/.state/` | **KEEP** |
| P-30h Eval-Dataset-Caches `src/openjarvis/evals/datasets/` | **ADAPT** |
| P-32a `~/Library/Messages/chat.db` | **ADAPT** (genau eine Speicherentscheidung) |
| K-31 iMessage-Daemon-Zugriffspfad `src/openjarvis/channels/imessage_daemon.py` | **REMOVE** (getrennte Komponentenentscheidung, keine zweite Speicherentscheidung für P-32a) |

Kanonische Datenbank `personal/jarvis.db` **KEEP** (Fachmodul-Basis); `knowledge.db` **ADAPT** (Projektionsziel, §5); Klartext-Stores `credentials.toml`, `connectors/*.json`, `cloud-keys.env` **REPLACE** (Keychain); `vault.enc/.vault_key` **REMOVE** (irreführender Parallelmechanismus); Tauri-Keychain **REUSE** (Vorbild ADR-0017). Weitere Speicher (`traces.db`, `telemetry.db`, `sessions.db`, `agents.db`, `approvals.db`, `digest.db`, `optimize.db`, `memory_facts.jsonl`, `SOUL/MEMORY/USER.md`, Frontend-`localStorage`): Entscheidungen und Retentionpflichten wie in §4 (Nr. 16/18/30/31) und im Audit; Speicher-Register 06 §2 ist entsprechend zu ergänzen.

## §8 Channels K-01 … K-32 (Kategorie e)

**Alle 30 registrierten Channels und die zwei unregistrierten Daemons (zusammen 32 Komponenten K-01 bis K-32): REMOVE** (Stilllegung in der Personal-Zielarchitektur; Reaktivierung einzelner Kanäle nur per ADR). Begründung: Kein Fachmodul der Reihenfolge 1–3 benötigt einen Versandkanal; jeder Kanal trägt Klartext-Secrets und ungeprüfte Sendewege ohne Approval-Bindung; das künftige Benachrichtigungen-Modul definiert Versandadapter neu über die ActionPipeline. Pfade `src/openjarvis/channels/<name>.py`; Sonderfälle: K-16 `whatsapp_baileys.py` (Node-Subprozess, Session-Keys auf Disk), K-31 `imessage_daemon.py` (macOS-only, osascript-Versand, arm64/x86_64 je nur statisch plausibel), K-32 `slack_daemon.py` (Tokens als argv, keine Tests).

## §9 Tool-Entscheidungen (Kategorie d/f, Auszug)

56 registrierte Tools + 5 definierte, aber nie registrierte Scheduler-Tools (`src/openjarvis/scheduler/tools.py:13,113,164,224,284` — **tot, REMOVE**). Provider-mutierendes Tool **56 `execute_pending_actions` `src/openjarvis/tools/proactive_tools.py:332` = REMOVE** (schreibt in Provider ohne Personal-Approval). `channel_send` für Personal-Daten gesperrt (folgt aus §8). Skill-Manifeste `src/openjarvis/skills/data/*.toml` mit Fachlogik (Kalender/Mail) = ADAPT (§4 Nr. 34). MCP-Fremdtools dynamisch, ohne aktive Server statisch nicht bestimmbar (UNGEKLÄRT). Erreichbarkeit korrigiert: keine direkte UI-Ausführung; API/CLI konfigurationsabhängig; MCP nur bei laufendem Server.

## §10 Autonom ausführbare Fähigkeiten (Kategorie f)

Autonomie ist verbindliches Zielbild, aber im Bestand nicht produktionsreif: Upstream-Scheduler defekt (§4 Nr. 20), Automations-/Operator-Fläche unverdrahtet oder tot (§4 Nr. 33), Browser-/Exec-Tools ohne Confirmation/SSRF (§4 Nr. 37, §9). Das verbindliche Modell steht in **ADR-0021** (Aktionsstufen, Automationsvertrag) und **ADR-0022** (KI-Arbeit, Internet, Browser-/App-Steuerung, Architekturpriorität). Produktionsreifer Bau erst im zuerst benötigenden Modul (frühestens T1-Alarme/Briefings, ADR-0024).

## §11 Verweise

Autorisierung: ADR-0020, DEC-044. Kategorien/Projektion: ADR-0020 §3/§4, 06 §1. Autonomie: ADR-0021/0022. Trading: ADR-0024. HV/Workspaces: ADR-0023. Boundary-Map (gröber): 02. Kontakte-Gates: modules/contacts.md §19, DEC-050.
