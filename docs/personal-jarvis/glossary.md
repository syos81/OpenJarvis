---
Status: normativ (Terminologie)
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: alle (Begriffsgrundlage)
Zugehörige ADRs: ADR-0001 bis ADR-0018
Verwandte DEC-Einträge: alle
---

# Glossar

Einzige normative Definitionsquelle für verbindliche Fachbegriffe. Kein anderes Dokument definiert Begriffe neu (01, AV-Regelwerk; 00 §3).

## Laufzeit und Komposition

- **PersonalCompositionRoot (PersonalBootstrap)** — Die einzige Kompositionswurzel je Prozess; erzeugt und verdrahtet alle Personal-Objekte per Constructor Injection, führt Start-/Stop-Reihenfolge aus (04 §1).
- **PersonalJarvisRuntime (PJR)** — Bündel kleiner, versionierter Ports, das Fachmodulen als einziger Zugang zur Basis dient; kein einzelnes God-Interface (04 §2).
- **OpenJarvisRuntimeAdapter (OJRA)** — Einzige Komponente, die OpenJarvis-Interna berührt; implementiert die PJR-Ports über SystemBuilder/JarvisSystem/QueryOrchestrator, EventBus, Scheduler und Memory-Backends (04 §2).
- **ModelPort** — Port für LLM-Vervollständigungen (Text und strukturierte Ausgaben); verpflichtender Durchsetzungspunkt der Egress-Politik für LLM-Aufrufe (04 §2, 12 §5).
- **MemoryIndexPort** — Port für den ausschließlich abgeleiteten Such-/Kontextindex (upsert/delete/search/rebuild).
- **ToolRegistrationPort** — Port zur Registrierung von LLM-Tools; Handler münden immer in die ActionPipeline.
- **EventPort** — Port für Personal-Domänenereignisse; Brücke zum Upstream-EventBus nur innerhalb des OJRA.
- **SchedulerPort** — Port für idempotente Job-Registrierung; kanonische Definition bleibt im Modul, Registrierung ist abgeleitet.
- **ConfigurationPort** — Port für typisierten Lesezugriff auf Personal-Konfiguration und -Pfade.
- **RuntimeHealthPort** — Port für den Status der Basisdienste (Engine, Index, Rust-Extension, Scheduler).
- **Port-Version** — Semantische Version je Port; Kompatibilität wird beim Start geprüft (fail-fast).
- **Integrationspunkt** — Der genau eine bewachte Aufruf in `jarvis serve`, der Personal anbindet (04 §4, 18 DEV-3).

## Commands und ActionPipeline

- **Command** — Typisiertes, validierbares Objekt für genau einen mutierenden Use-Case mit genau einem Handler (05 §1).
- **ApplicationCommandBus** — Der einzige logische Schreibpfad: API, CLI, Chat-Tools und Automationen erzeugen dieselben Commands (05 §1).
- **CommandBus-Gate** — Kontrollierter Schaltpunkt am ApplicationCommandBus, der die Annahme neuer Mutationen vorübergehend schließt (geordneter Shutdown, Backup-Barriere); Lesezugriffe bleiben möglich (04 §1, 13 §3).
- **Application Service** — Use-Case-Orchestrierung eines Moduls; einziger Schreibzugriff auf dessen Tabellen.
- **Application Orchestrator** — Basis-Konzept für modulübergreifende Use-Cases; koordiniert mehrere Repository-Verträge in einer UnitOfWork (07 §3).
- **Capability Service** — Führt Capability-Operationen über die ActionPipeline aus; einzige Aufrufstelle von Provideradaptern.
- **ActionPipeline** — Verbindliche Stufenkette jeder zustandsändernden Operation (05 §4).
- **Initiation-Kontext** — Herkunft eines Pipeline-Durchlaufs: `user_direct`, `llm_assisted`, `automation`, `system`; bestimmt die Bestätigungsform (05 §5).
- **Vorschau** — Vollständige, verständliche Darstellung des Effekts einer Operation vor Bestätigung/Freigabe.
- **Verifikationszustand** — Ergebnisstatus der Provider-Verifikation: `verified`, `provider_acknowledged`, `pending_verification`, `unverified`, `verification_failed` (05 §6).
- **IdempotencyKey** — Eindeutiger Schlüssel je externer Schreiboperation zur Verhinderung/Erkennung von Doppelausführung.
- **In-Process-Modus** — Begrenzter CLI-Betrieb ohne laufenden Server: derselbe PersonalBootstrap, exklusive Sperre, keine dauerhaften Worker (05 §2).

## Provider und Adapter

- **Capability** — Providerneutrale Fähigkeit (z. B. calendar, contacts, mail, tasks, broker) mit eigenem kleinem Fachvertrag.
- **Provider** — Katalogeintrag eines Anbieters/Systems (z. B. „icloud", „generic-caldav", „apple-system") mit deklarierten möglichen Fähigkeiten (08 §1).
- **ProviderAccount** — Konkrete Konteninstanz des Nutzers; auch der lokale macOS-Systemspeicher ist ein ProviderAccount (Provider „apple-system").
- **CredentialReference** — Zweckgebundener Verweis auf ein Keychain-Item; nie das Geheimnis selbst (09 §4).
- **CapabilityBinding** — Verbindung ProviderAccount × Capability × AdapterDefinition × CredentialReference × Konfiguration; ein Konto kann mehrere besitzen.
- **AdapterDefinition** — Registrierte Adapter-Implementierung mit Fähigkeit, Protokoll, Config-Schema und Discovery-Merkmalen.
- **ProviderCollection** — Externe Sammlung innerhalb eines Bindings (konkreter Kalender, Adressbuch, Ordner); trägt die Workspace-Zuordnung.
- **Provideradapter** — Implementierung eines Fachvertrags gegen einen Provider; zustandslos bzgl. kanonischer Daten, persistiert nichts.
- **Native Bridge** — Eng begrenzte Anbindung von macOS-Frameworks (EventKit, CNContactStore) ausschließlich innerhalb der Adapterschicht (08 §4).
- **Swift-Sidecar (Contacts-Bridge)** — Die beschlossene Ausprägung der Native Bridge für Kontakte: ein dünner, signierter Swift-Hilfsprozess mit JSON-Lines-Protokoll über stdio, der ausschließlich zwischen CN-Objekten und Adapter-DTOs übersetzt — ohne Fach-, Workspace-, Merge-, Risiko- oder Audit-Logik und ohne eigene kanonische Speicherung (ADR-0016, DEC-031).
- **Capability Discovery** — Meldung eines Adapters, welche Operationen der konkrete Provider/Account unterstützt.
- **Fehlertaxonomie** — Geschlossene Menge normalisierter Adapterfehler (08 §3 Nr. 5).

## Daten und Persistenz

- **Kanonische Datenbank** — `~/.openjarvis/personal/jarvis.db`; einzige kanonische Datenbank aller Personal-Fachmodule (06 §1).
- **Speicher-Register** — Verbindliche Tabelle aller Speicher mit kanonischem Inhalt, Eigentümer, Art, Backup- und Migrationsstatus (06 §2).
- **Blob-Store** — Inhaltsadressierte Dateiablage `~/.openjarvis/personal/files/` für Dokument-/Anhang-Inhalte.
- **Abgeleiteter Index** — Such-/Kontextindex (inkl. OpenJarvis Memory); jederzeit vollständig neu aufbaubar, nie kanonische Wahrheit.
- **Tabelleneigentümerschaft** — Jede Tabelle gehört genau einem Modul; Fremdzugriff nur über dessen Verträge (AV-12).
- **Repository-Vertrag** — Veröffentlichte Schnittstelle eines Modul-Repositories; Implementierungen bleiben modulprivat.
- **DatabaseConnectionFactory** — Einzige Stelle, die Verbindungen zur kanonischen DB erzeugt und Pragmas/Rechte erzwingt (07 §1).
- **UnitOfWork (UoW)** — Transaktionskontext; Repositories arbeiten auf derselben Verbindung, Commit/Rollback genau einmal (07 §2).
- **Migrations-Ledger** — Tabelle der angewandten Migrationen mit Prüfsummen; wird beim Start verifiziert, fail-closed (07 §6).
- **Globale Migration-ID** — Monotone, modulübergreifende Kennung jeder Migration mit Eigentümer und Abhängigkeiten.
- **serve.lock** — Exklusive Prozesssperre (`personal/serve.lock`) mit PID+Port; verhindert zweite Schreibprozesse, dient der Port-Discovery (07 §5).
- **Tombstone** — Löschmarkierung synchronisierter Entitäten bis zur bestätigten Provider-Löschung; verhindert Wiederauferstehen.
- **ResourceIdentity** — Typisierte kanonische Adresse jeder Entität (`resource_type` + UUIDv7) (06 §5).
- **ResourceLink** — Gerichtete, typisierte Kante zwischen zwei Ressourcen; Eigentum der Basis-Verknüpfungsinfrastruktur.
- **LinkType** — Registrierter Typ einer ResourceLink-Kante (z. B. `about_contact`, `attached_to`).
- **EntityAlias / MergeRedirect** — Verweis von alter/ersetzter ID auf eine terminale kanonische ID; azyklisch, mit Kettenlimit und Path Compression (06 §5).
- **MergeRecord** — Unveränderlicher Datensatz einer Zusammenführung (Quell-Snapshots, Ziel, Entscheidung, Folgen).
- **Reversal Event** — Explizites Ereignis der Merge-Rückabwicklung; erzeugt neue kanonische Entität, nie Rückwärts-Redirects.
- **Workspace** — Konfigurierbarer Kontextraum (z. B. Privat, Arbeit, Hausverwaltung); Filter- und Berechtigungsdimension, nie hart codiert.
- **Rolle** — Funktion eines Kontakts innerhalb eines Workspace (z. B. Familie, Mieter, Dienstleister); mehrfach möglich.
- **Tag** — Freies, nicht berechtigungswirksames Etikett.
- **Organisation** — Eigene Entität mit Mitgliedschaften.
- **Externe Identität** — Provider-Repräsentanz einer kanonischen Entität (`<modul>_external_ids` mit externer ID, ETag/Version, Sync-Stand).
- **Beziehung** — Typisierte, gerichtete Kante zwischen zwei Ressourcen mit Eigentümer beim definierenden Modul.

## Sicherheit, Risiko und Audit

- **Risikoklasse** — `R0` (lokal oder extern lesend, ohne Zustandsänderung), `R1` (extern schreibend, versendend oder verändernd), `R2` (finanziell, irreversibel, sicherheitskritisch oder mit erheblichen Folgen) (10 §1).
- **ApprovalIntent** — Dauerhafter Freigabe-Datensatz einer R2-Operation mit Zustandsmaschine (10 §3).
- **Approval-Center** — UI-Fläche für R2-Freigaben; R1-Bestätigungen erscheinen inline am Ort der Aktion.
- **RiskEngine** — Deterministische, rein codebasierte Regelprüfung für R2; für Sprachmodelle unerreichbar; Regeländerungen sind selbst R2.
- **R2-Kill-Switch** — Globaler Not-Aus, der ausschließlich den R2-Executor stoppt (10 §4).
- **AuditTrail / audit_log** — Append-only, hash-verkettetes Ereignisprotokoll aller Pipeline-Stufen (10 §5).
- **Audit-Checkpoint** — Signierter Fixpunkt des Chain-Head (Ed25519, Schlüssel im Keychain); in Backup-Manifesten und als externer Export (13 §5).
- **Chain-Head** — Aktueller letzter Hash der Audit-Kette.
- **CredentialStore** — Vertrag für Geheimnisverwaltung; produktiv ausschließlich OS-Schlüsselbund (09 §4).
- **Installationsgeheimnis** — Dauerhaftes Geheimnis im Keychain; nur Backend und Tauri-Hauptprozess lesen es; nie in der SPA (09 §1).
- **Desktop-Session-Token (Session-Token)** — Kurzlebiges, widerrufbares, scope-begrenztes Token je Desktop-Sitzung/Fenster; nur im Arbeitsspeicher; authentifiziert die HTTP-Anfragen der SPA und die Anforderung von WebSocket-Tickets; wird beim App-Schließen widerrufen (09 §1).
- **WebSocket-Ticket** — Kryptografisch zufälliges, **einmalig verwendbares**, höchstens 30 Sekunden gültiges, nur im Backend-Arbeitsspeicher gehaltenes Ticket, gebunden an Desktop-Session-ID, Fenster-ID, erlaubten Origin, Scope `personal:ws` und den vorgesehenen WebSocket-Endpunkt; einziges Handshake-Credential für WebSockets, vor `accept()` atomar verbraucht; Werte werden aus Logs/Fehlern/Traces redigiert (09 §1, DEC-029).
- **Dev-Modus** — Ausdrücklich aktivierter Entwicklungsbetrieb mit separatem kurzlebigem Token; nie das Installationsgeheimnis.
- **Sensitivitätsklasse** — `S0` (technisch/nicht personenbezogen), `S1` (personenbezogen), `S2` (besonders sensibel); Unklassifiziertes gilt als S2 (12 §1).
- **EgressContext / EgressPayload** — Kontext bzw. aus etikettierten Fragmenten zusammengesetzte Nutzlast eines Cloud-Abfluss-Aufrufs.
- **EgressGuard** — Zentrale, fail-closed Durchsetzungskomponente für **jeden** Cloud-Abfluss von Personal-Daten; berechnet die effektive Höchstklasse über den vollständigen Payload; verpflichtend am ModelPort und ebenso für jeden anderen Cloud-Dienst mit Personal-Daten (z. B. spätere Cloud-STT/TTS) (12 §2, §5).
- **Egress-Regel** — Freigabe der Form Workspace × Capability × Datentyp × Sensitivität × Provider × Umfang × Redaction × Nutzerfreigabe.
- **Redaction-Derivat** — Neues, explizit klassifiziertes Ableitungsfragment; verändert nie die Klassifizierung des Originals.
- **Non-Egress** — Absolute Klasse (Credentials, Auth-Tokens, Schlüsselmaterial); durch keine Regel freigebbar.

## Sync, Outboxes und Events

- **ExternalActionOutbox** — Transaktional geschriebene Warteschlange externer Schreiboperationen; abgearbeitet vom R1-Executor (11 §1).
- **DomainEventOutbox** — Transaktional geschriebene Warteschlange abgeleiteter interner Wirkungen; abgearbeitet vom DomainEvent-Dispatcher.
- **R2ExecutionQueue** — Getrennte Warteschlange freigegebener R2-Intents; abgearbeitet ausschließlich vom R2-Executor.
- **Sync-Worker** — Worker im Serve-Prozess für die Pull-Synchronisation je (Konto × Collection), single-flight (11 §3).
- **R1-Executor** — Worker im Serve-Prozess, der ExternalActionOutbox-Einträge ausführt (Adapter-Aufruf, Read-back, Abschluss); pausierbar über Konto-/Capability-Sperren, vom R2-Kill-Switch unberührt (11 §1).
- **R2-Executor** — Separater Worker ausschließlich für freigegebene R2-Intents aus der R2ExecutionQueue; einziger vom globalen R2-Kill-Switch gestoppter Bereich (10 §4, 11 §1).
- **DomainEvent-Dispatcher** — Verarbeitet DomainEvents at-least-once an idempotente Consumer (Index, Benachrichtigungen, EventPort, Statistiken, Scheduler-Reconciliation).
- **Consumer-Cursor** — Fortschrittsmarke eines Event-Consumers zur Idempotenz.
- **Dead-Letter / attention_required** — Endzustand nach erschöpften Wiederholungen; erzeugt sichtbare Aufmerksamkeit.
- **Index-Lag** — Sichtbarer Abstand zwischen letzter Event-Sequenz und Consumer-Cursor.
- **SyncState / Cursor** — Persistierter Synchronisationsstand je (Konto × Collection) mit opakem Fortschrittsmarker.
- **Circuit-Breaker** — Konto-bezogene Schutzschaltung bei wiederholten Transportfehlern (`degraded`, Half-Open-Probe).
- **Reconciler** — Hintergrundprozess, der offene Verifikations- und `uncertain_outcome`-Zustände nachträglich auflöst.
- **Outbox-Muster** — Verbindliches Muster: kanonische Änderung und Warteschlangeneintrag in einer Transaktion; externe Ausführung danach.

## Backup und Recovery

- **SnapshotCoordinator** — Koordiniert konsistente Mehr-Speicher-Backups über eine kurze Schreib-Barriere (13 §3).
- **Backup-Barriere** — Kurzzeitige Pause neuer Mutationen (CommandBus-Gate) für konsistente Snapshots; auch vor Migrationen.
- **DEK** — Datenverschlüsselungsschlüssel des Backup-Repositories (AES-256-GCM).
- **Recovery Key** — Einmalig erzeugter, offline zu verwahrender Schlüssel; wird nie automatisch in dasselbe Backup geschrieben.
- **Recovery-Wortliste** — Die beschlossene Darstellung des Recovery Keys: ein zufälliger 256-Bit-Schlüssel als standardisierte 24-Wort-Folge mit Prüfsumme, offline zu verwahren und bei der Einrichtung durch erneute Eingabe zu bestätigen; eine zusätzliche Passphrasen-Hülle (Argon2id) ist optional (DEC-033).
- **Schlüsselhülle (Envelope)** — Mit Keychain, Recovery Key oder Passphrase verschlüsselte DEK-Kopie im Repository-Header.
- **Backup-Manifest** — Abschlussdokument eines Laufs (Bestandteile, Prüfsummen, Versionen, Snapshot-Zeitpunkte, Audit-Checkpoint); nur `complete`-Läufe sind wiederherstellbar.
- **Atomare Aktivierung** — Umschalten auf einen vollständig geprüften Restore-Stand in einem Schritt; nie ein Mischstand.
- **Restore-Drill** — Dokumentierter Wiederherstellungstest auf leerer Installation, ausdrücklich inkl. Verlust von Mac und Keychain.

## UI und Module

- **Modul-Manifest (Frontend)** — Build-time registrierte Beschreibung eines Modul-Frontends (ID, Titel, Icon, Routen, Nav-Platz).
- **Readiness** — Laufzeitmeldung des Backends je Modul (`/v1/personal/system/modules`); Navigation zeigt nur kompiliert ∧ betriebsbereit.
- **Modul-Lifecycle** — Zustandsmaschine `not_installed · disabled · initializing · migration_required · configuration_required · permission_required · ready · degraded · error · shutting_down` (14 §4).
- **Basis** — Die gemeinsam genutzten Fundamentteile (Ports/OJRA, DB-Kern, CredentialStore, Pipeline, Audit, Outboxes, Verknüpfungsinfrastruktur, Auth, Backup-Kern, Kontenverwaltungs-Slice, Egress-Guard); materialisiert je Bedarf des nächsten Moduls (16 §3).

## Prozessbegriffe

- **Architektur-Baseline** — Die am 2026-07-27 freigegebene Zielarchitektur v2+v3 einschließlich Verfassung.
- **Materialisierungsregel** — Gemeinsame Grundlagen entstehen nur, wenn das unmittelbar nächste Modul sie zwingend braucht (AV-33; Ausnahme: Backup-Kern).
- **Deferred Decision** — Bewusst vertagte Entscheidung; darf nicht vorweggenommen werden (17).
- **Abweichungsliste** — Abschließende Liste bewusster Upstream-Abweichungen; jede Abweichung besitzt einen eigenen akzeptierten ADR (18).
- **Normenhierarchie** — Rangfolge der Dokumente bei Widersprüchen (01 §2).
- **Definition of Done (DoD)** — Vollständigkeitskriterien eines Moduls (19).
- **ADR** — Architecture Decision Record mit Status `proposed → accepted | rejected | superseded`; Änderungsweg für geschützte Bereiche.
- **Live-Abnahme** — Dokumentierte Abnahme eines Provideradapters gegen einen echten Provider-Account; auf macOS je Zielarchitektur zu erbringen (15 §7).

## Zielplattformen und Abnahme

- **Zielarchitektur** — Eine der beiden gleichwertigen produktiven macOS-Prozessorarchitekturen von Personal Jarvis: **Apple Silicon arm64** und **Intel x86_64**, jeweils ab **macOS 12.3**. Beide erhalten denselben fachlichen Funktionsumfang; keine Fachfunktion darf auf eine Architektur beschränkt sein. Linux ist sekundäres späteres Ziel und keine Zielarchitektur dieser Baseline (AV-29, ADR-0018, DEC-042).
- **Dual-Architektur-Abnahme** — Die verbindliche Abnahmematrix mit zwei Pflichtspalten (arm64, x86_64). Ein Gesamt-PASS existiert ausschließlich, wenn beide Spalten vollständig bestanden sind; ein Ergebnis der einen Architektur gilt niemals automatisch für die andere. Auf macOS Voraussetzung des Modulabschlusses (15 §7, 19).
- **Native Hardware-Abnahme** — Nachweis eines geräteabhängigen Kriteriums (TCC, Codesigning, Packaging, Store-Zugriff, gepackte App, Backup/Restore, Live-Abnahme) auf physischer Hardware der jeweiligen Zielarchitektur. **Rosetta 2 ist kein Ersatz:** es übersetzt ausschließlich x86_64 → arm64, der umgekehrte Weg existiert nicht; ein unter Rosetta ausgeführter x86_64-Build ersetzt daher keine Prüfung auf echter Intel-Hardware, und die arm64-Abnahme ist auf Intel-Hardware technisch unmöglich (15 §7, ADR-0018).
- **Universal 2** — Auslieferungsformat, bei dem ein einziges signiertes macOS-Artefakt den nativen Code beider Zielarchitekturen als Slices enthält (Alternative: zwei getrennte signierte architekturspezifische Release-Artefakte). **Die Wahl des Auslieferungsformats ist als DEC-D17 offen registriert** (17 §3); der Begriff ist hier nur definiert, nicht festgelegt. Unabhängig vom Format gilt unverändert: Für beide Architekturen muss nativer ausführbarer Code bereitgestellt und überprüft werden, und die Dual-Architektur-Abnahme bleibt in vollem Umfang Pflicht.
