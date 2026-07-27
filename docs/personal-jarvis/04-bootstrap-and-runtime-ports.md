---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-6, AV-7, AV-31, AV-34
Zugehörige ADRs: ADR-0001
Verwandte DEC-Einträge: DEC-003, DEC-020, DEC-026
---

# 04 — PersonalBootstrap und Runtime-Ports

## §1 PersonalCompositionRoot (PersonalBootstrap)

**Genau eine Kompositionswurzel je Prozess** (AV-34). Sie ist die einzige Stelle, die Personal-Objekte erzeugt und verdrahtet — durchgehend Constructor Injection; **kein Service-Locator in Fachmodulen, keine Modul-Singletons, kein zweiter EventBus** (Personal-Ereignisse laufen über die DomainEventOutbox, 11 §2; der Upstream-Bus bleibt allein Upstream und wird nur vom OJRA berührt).

### Startreihenfolge (verbindlich, fail-closed)

1. Prozessrolle klären und **exklusive Sperre** erwerben (`personal/serve.lock`; identisch im CLI-In-Process-Modus, 05 §2, 07 §5).
2. Personal-Konfiguration laden (Backing des ConfigurationPort).
3. `DatabaseConnectionFactory` initialisieren (Dateirechte-Prüfung, Pragmas; 07 §1).
4. **Migrations-Ledger prüfen und Migrationen ausführen** (globales Modell 07 §6, inkl. Backup-Barriere) — Fehler ⇒ fail-closed.
5. `CredentialStore` initialisieren (Keychain-Probe; gesperrt/verweigert ⇒ fail-closed mit normalisiertem Fehlerzustand; 09 §4).
6. Auth initialisieren: Installationsgeheimnis sicherstellen, Session-Token-Aussteller starten (09 §1).
7. `OpenJarvisRuntimeAdapter` konstruieren; **nur die von registrierten Modulen benötigten Ports** bereitstellen (Versionsprüfung, fail-fast; §2).
8. Basisdienste konstruieren: AuditTrail (+ Checkpoint-Signierer), Egress-Guard, Verknüpfungsinfrastruktur, ActionPipeline, die drei Warteschlangen (ExternalActionOutbox, DomainEventOutbox, R2ExecutionQueue), RiskEngine (nur wenn R2-Module registriert sind).
9. Module komponieren (statische Build-Time-Modulliste): Repositories → Capability Services → Application Services; Router, Tool-Handler, Event-Consumer und Jobs werden eingesammelt, noch nicht aktiviert.
10. Personal-Router in die FastAPI-App registrieren; Tool-Handler über den ToolRegistrationPort registrieren; Scheduler-Reconciliation ausführen.
11. Worker starten, in dieser Reihenfolge: DomainEvent-Dispatcher → Sync-Worker → R1-Executor → Verifikations-/Mail-Reconciler → R2-Executor (nur falls R2-Module vorhanden und der Kill-Switch nicht gesetzt ist).
12. Readiness melden: Erst jetzt verlassen Module den Zustand `initializing`; **Personal-Router gelten erst als ready, wenn alle zwingenden Basisdienste (Schritte 3–8) erfolgreich initialisiert wurden.**

### Fail-closed-Regel

Scheitert Migration oder Sicherheitsinitialisierung (Schritte 4–6), startet **kein** Personal-Teilbetrieb: alle Personal-Router antworten 503 `personal_unavailable` mit Diagnose, keine Worker laufen, kein Tool wird registriert. Der Upstream-Teil von `jarvis serve` bleibt unberührt — Personal ist atomar verfügbar oder atomar nicht verfügbar.

### Shutdown-Reihenfolge (geordnet, invers)

Mutations-Annahme schließen (CommandBus-Gate, 503 retry-later) → R2-Executor stoppen → Sync-/R1-Executor stoppen (laufendes Item zu Ende) → DomainEvent-Dispatcher begrenzt drainen → Reconciler stoppen → Tool-Deregistrierung → DB-Verbindungen schließen → Sperre freigeben. Eingebunden über den FastAPI-Lifespan, damit ein `jarvis serve`-Stop immer geordnet durchläuft.

## §2 PersonalJarvisRuntime als Port-Bündel

Die Runtime ist **kein einzelnes Interface, sondern ein Bündel kleiner Ports**. Fachmodule erhalten per Konstruktor-Injektion **nur die Ports, die sie tatsächlich brauchen**; ungenutzte Ports werden gemäß Materialisierungsregel (AV-33) gar nicht erst implementiert.

| Port | Verantwortung | Bemerkungen |
|---|---|---|
| **ModelPort** | `complete(messages, schema?, model_hint?, egress_context)` — Text- und strukturierte Ausgaben | einziger Durchsetzungspunkt der Egress-Politik (12 §5); EgressContext ist Pflichtparameter |
| **MemoryIndexPort** | `index_upsert / index_delete / search / rebuild(scope)` | ausschließlich abgeleitete Daten; jederzeit neu aufbaubar (AV-16) |
| **ToolRegistrationPort** | `register(spec, handler)` | Handler münden immer in die ActionPipeline; nie direkte Adapter (AV-8) |
| **EventPort** | `publish / subscribe` für Personal-Domänenereignisse | Brücke zum Upstream-EventBus nur innerhalb des OJRA; gespeist vom DomainEvent-Dispatcher (11 §2) |
| **SchedulerPort** | `ensure_job / remove_job / list` (idempotent) | kanonische Definition bleibt im Modul; Registrierung ist abgeleitet und wird beim Start re-synchronisiert |
| **ConfigurationPort** | typisierter Lesezugriff auf Personal-Config und Pfade | schreibend nur über das Einstellungen-Modul |
| **RuntimeHealthPort** | Status von Engine, Index, Rust-Extension, Scheduler | Grundlage der Readiness-Meldungen (14) |

### Port-Regeln

1. Port-Signaturen verwenden ausschließlich Basistypen des Personal-Namensraums — **keine Upstream-Typen überqueren die Port-Grenze**; Konvertierung geschieht im OJRA (AV-7).
2. Abhängigkeitsrichtung: Fachmodule → Port-Abstraktionen; OJRA → implementiert Ports und kennt Upstream; Upstream kennt nichts davon (AV-6/AV-7).
3. Versionierung: Jeder Port trägt eine eigene semantische `PORT_VERSION`; der OJRA meldet implementierte Versionen; die Komposition prüft Kompatibilität beim Start (fail-fast); Contract-Tests je Port fixieren die Semantik (AV-27).
4. Port-Erweiterungen nur per ADR (AV-31) — das verhindert ein God-Interface strukturell.

## §3 OpenJarvisRuntimeAdapter (OJRA)

Der OJRA implementiert sämtliche Ports und nutzt intern zunächst `SystemBuilder` → `JarvisSystem` → `QueryOrchestrator`, Upstream-EventBus, Upstream-Scheduler und `tools/storage`. Contract-Tests fixieren die Port-Semantik, sodass der Unterbau später repariert oder ausgetauscht werden kann, ohne Fachmodule anzufassen. `jarvis serve`, `jarvis ask` und `jarvis chat` bleiben unverändert; eine Vereinheitlichung der Upstream-CLI-Pfade erfolgt nur bei belegtem Fehler oder konkretem Bedarf (DEC-003).

## §4 Integrationspunkt in `jarvis serve`

Genau **ein** bewachter Aufruf im Upstream-Server-Aufbau (App-Factory bzw. Lifespan): `personaljarvis.attach(app)` — hinter Feature-Schalter und `try/except ImportError`, sodass ein Upstream-Checkout ohne Personal-Code unverändert funktioniert. Pflichten (AV-34): Führung in der Abweichungsliste (18 DEV-3), ADR-Dokumentation (ADR-0001), zwei Tests (Personal aktiviert ⇒ Routen vorhanden; deaktiviert/fehlend ⇒ App identisch zu Upstream). Kein Umbau von `serve` selbst.
