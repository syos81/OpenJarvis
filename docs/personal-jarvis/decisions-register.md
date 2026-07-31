---
Status: normativ (Index)
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-30 (Entscheidungsweg)
Zugehörige ADRs: ADR-0001 bis ADR-0018
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
| DEC-009 | Toolchain: uv, Python exakt 3.12 (produktive Pflicht), Rust ≥ 1.88, maturin, Node 22 (Frontend/Tauri); macOS als Zielplattform, Linux sekundär; Zusatz-Bridges nicht unterstützt. **Die Plattformaussage ist durch DEC-042/ADR-0018 präzisiert: macOS arm64 und x86_64 sind gleichwertige Zielarchitekturen ab macOS 12.3** | accepted | Baseline (AV-29; 15 §6); präzisiert durch ADR-0018 | 2026-07-27 |
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
| DEC-030 | **Erstes Fachmodul: Kontakte** (Modulwahl-Teil von DEC-D10; die Gesamtreihenfolge bis Modul 3 wurde am 2026-07-31 mit DEC-045 nachgezogen) | accepted | Eigentümer-Entscheid; 16 | 2026-07-27 |
| DEC-031 | Native macOS-Bridge als Swift-Sidecar (JSON-Lines-stdio) mit verpflichtendem Spike (TCC, Signierung, CNChangeHistory, vereinheitlichte Kontakte, gepackte Tauri-App); bei Scheitern **kein** automatischer PyObjC-Wechsel, erneute Freigabe nötig (löst DEC-D01) | accepted | ADR-0016 | 2026-07-27 |
| DEC-032 | Gemeinsame providerneutrale CredentialStore-Schnittstelle mit nativer macOS-Keychain-Nutzung; identischer dokumentierter Service-/Account-Namensraum für Backend, CLI und Tauri-Hauptprozess; keyring-Bibliotheken hinter dem Vertrag zulässig; keine Geheimnisse an die React-SPA (löst DEC-D02) | accepted | ADR-0017 | 2026-07-27 |
| DEC-033 | Backup-Recovery: zufälliger 256-Bit-Recovery-Key als standardisierte 24-Wort-Darstellung mit Prüfsumme; optionale zusätzliche Passphrasen-Hülle (Argon2id); Offline-Verwahrung und Bestätigung durch erneute Eingabe bei der Einrichtung (löst DEC-D03) | accepted | Eigentümer-Entscheid; ADR-0010; 13 §2 | 2026-07-27 |
| DEC-034 | Desktop-E2E mit Playwright gegen den lokalen Entwicklungsstack mit Fake-Adapter; zusätzlich verpflichtender echter Tauri-Smoke- und Live-Test — auf macOS **je Zielarchitektur** (arm64 und x86_64) auf echter Hardware (löst DEC-D04; ergänzt durch DEC-042) | accepted | Eigentümer-Entscheid; 15 §1, 15 §7 | 2026-07-27 |
| DEC-035 | Desktop-Session-Token max. 8 Stunden, Rotation spätestens 30 Minuten vor Ablauf, sofortige Invalidierung bei App-Schließen oder Widerruf; WebSocket-Tickets einmalig und max. 30 Sekunden gültig (löst DEC-D05) | accepted | Eigentümer-Entscheid; ADR-0008; 09 §1 | 2026-07-27 |
| DEC-036 | Audit-Checkpoints: Verankerung in jedem vollständigen Backup; zusätzlich externer manueller Export nach jeder künftigen R2-Aktion und mindestens quartalsweise; für Modul 1 existiert keine R2-Fachaktion (löst DEC-D07) | accepted | Eigentümer-Entscheid; ADR-0010; 13 §5 | 2026-07-27 |
| DEC-037 | Sensitivität im Kontaktmodul: Namen, Kontaktdaten, Anschriften, Geburtstage, Rollen, Beziehungen, Organisationen, Bilder und Provider-IDs = S1; Freitextnotizen = S2. **Die globale Sensitivitätsmatrix (DEC-D09) bleibt offen** | accepted (modulbezogen) | Eigentümer-Entscheid; 12 §1 | 2026-07-27 |
| DEC-038 | Live-Abnahme des Kontaktmoduls bevorzugt in einem separaten macOS-Testbenutzer mit isoliertem Apple-Kontakte-Bestand und Präfix `ZZZ-JarvisTest-`; keine Abhängigkeit von einem bestimmten „Auf meinem Mac"-Container; produktive private Kontakte bleiben unverändert. **Die Abnahme ist auf beiden Zielarchitekturen (arm64 und x86_64) je auf echter Hardware zu erbringen; ein Ergebnis gilt nicht für die andere Architektur** (löst DEC-D11 für Modul 1; ergänzt durch DEC-042) | accepted | Eigentümer-Entscheid; 15 §1, 15 §7 | 2026-07-27 |
| DEC-039 | Initiale Workspaces: Privat, Arbeit, Hausverwaltung — konfigurierbare Werte, keine hartcodierte Fachlogik; umbenennbar, ergänzbar, später archivierbar (löst DEC-D15) | accepted | Eigentümer-Entscheid; 06 §6 | 2026-07-27 |
| DEC-040 | Backup-Ziele: tägliches lokales verschlüsseltes Backup; zusätzlich externes Volume, sobald verbunden, mit automatischem Nachholen ausgefallener Läufe; Aufbewahrung 30 tägliche und 12 monatliche vollständige Wiederherstellungspunkte; ein nicht verbundenes Volume blockiert den lokalen Betrieb nicht, erzeugt aber eine sichtbare Warnung (löst DEC-D16) | accepted | Eigentümer-Entscheid; ADR-0010; 13 §3 | 2026-07-27 |
| DEC-041 | Genehmigung der minimalen Integrationspunkte: **DEV-4** (readiness-gesteuerte Kontakte-Route, Navigationseintrag, minimal erforderliche sichere Tauri-Kommandos; keine Geheimnisse in der SPA, kein zweiter Ausführungspfad) und **DEV-5** (ausschließlich additive Personal-Dependency-Group in `pyproject.toml`; Standard-Abhängigkeiten und Wheel-Packaging unverändert) | accepted | ADR-0015; 18 DEV-4/DEV-5 | 2026-07-27 |
| DEC-042 | **Gleichwertige Dual-Architektur-Unterstützung für macOS:** Apple Silicon arm64 und Intel x86_64 sind gleichwertige produktive Zielplattformen mit **verbindlicher Mindestversion macOS 12.3** und identischem fachlichem Funktionsumfang. Für beide Architekturen muss jeweils nativer ausführbarer Code gebaut und nachgewiesen werden; Laufzeit-, Sicherheits-, TCC- und Live-Abnahmen erfolgen separat auf echter Hardware der jeweiligen Architektur; Signierung, Packaging und Update-Auslieferung müssen sicherstellen, dass für beide Architekturen der korrekte native Code bereitgestellt und überprüft wird. Ein Ergebnis gilt nie automatisch für die andere Architektur. **Rosetta ersetzt keine native Abnahme** (Rosetta übersetzt nur x86_64 → arm64; arm64 ist auf Intel nicht ausführbar). Ein Modul gilt auf macOS erst nach bestandener Abnahmematrix in **beiden** Spalten als abgeschlossen. Python exakt 3.12 bleibt produktive Pflicht; Linux bleibt sekundäres späteres Ziel. **Ob die Auslieferung als gemeinsames Universal-2-Artefakt oder als zwei getrennte architekturspezifische Pakete erfolgt, bleibt bis zur Entscheidung DEC-D17 offen** | accepted | ADR-0018; AV-29, 15 §6/§7, 19 | 2026-07-27 |
| DEC-043 | **Abnahme des Kontakte-Bridge-Spikes G3a:** Der nach ADR-0016 Punkt 2 verpflichtende Spike ist auf Apple Silicon arm64 bestanden — kein Kill-Kriterium eingetreten (28 ausführbare Phase-B-Gates bestanden, 0 fehlgeschlagen, 1 mangels zweitem Container nicht ausführbar; 187/187 kontaktfreie Prüfungen). Der native Swift-Sidecar bleibt die Implementierungsrichtung; der Objective-C-Shim bleibt ausschließlich für die aus Swift nicht erreichbare Change-History-API zulässig; **kein Wechsel auf PyObjC**. Der Spike **erlaubt den Beginn** der produktiven Kontakte-Implementierung (16 §4.1) und **erlaubt nicht** die Fertigmeldung des Moduls: Intel x86_64 bleibt gleichwertig und vollständig live abzunehmen, Mehrcontainer/Unified, echte Kontakteoperation aus der gepackten App und die vollständige TCC-Persistenzmatrix bleiben offen (Matrix: 15 §8). Notizen bleiben ohne besonderes Entitlement **nicht** zugesagt (`notesSupported=false`); Link/Unlink wird nicht als mutierende Capability zugesagt (08 §4). **DEC-D17 wird nicht vorweggenommen** | accepted | ADR-0016 Punkt 8; 08 §4, 15 §8, 16 §4.1, 19 §10 | 2026-07-28 |
| DEC-044 | **Übernahme des OpenJarvis-Reuse-Audit-Kanons.** Die Einzelentscheidungen des am 2026-07-31 formal abgenommenen Connector-, Capability- und Reuse-Audits (Kanon: Abschlussbericht · zweite vollständige Fassung des Ergänzungs-, Korrektur- und Abnahmeberichts · kanonischer Abnahme-Nachtrag · letztes Korrekturblatt) werden verbindlich übernommen und komponentenscharf im normativen Register [20](20-openjarvis-reuse-register.md) geführt; der Auditbericht wird nicht als Parallelkopie eingefroren. Klassen: KEEP/REUSE/ADAPT/PROJECT/REPLACE/REMOVE (REMOVE = Stilllegung; physisches Löschen nur nach gesonderter Freigabe). Erhaltene Einzelentscheidungen u. a. P-30a KEEP, P-30b/c/d ADAPT, P-30e KEEP, P-30f ADAPT, P-30g KEEP, P-30h ADAPT, P-32a ADAPT (genau eine Speicherentscheidung), K-31 REMOVE (getrennte Komponentenentscheidung) | accepted | ADR-0020 | 2026-07-31 |
| DEC-045 | **Verbindliche Modulreihenfolge bis Modul 3:** Modul 1 Kontakte → Modul 2 Kalender → Modul 3 Trading Intelligence (T1). Kein anderes Fachmodul dazwischen oder parallel ohne neue Architekturentscheidung; nach Modul 3 wird die Reihenfolge bewusst neu entschieden. **Löst DEC-D10 vollständig** (ersetzt ADR-0012 Punkt 4) | accepted | ADR-0019; 16 §4.2 | 2026-07-31 |
| DEC-046 | **Autonomie- und Hintergrundaktionsmodell:** Jarvis darf innerhalb vorher festgelegter, überprüfbarer Grenzen selbstständig im Hintergrund handeln. Sechs Aktionsstufen; vorab genehmigte gültige Automationsregeln (Automationsvertrag mit 15 Pflichtfeldern) werden ohne erneutes Approval je Ausführung ausgeführt; neue/riskante/R2-Aktionen benötigen aktuelle ausdrückliche Freigabe (R2 unverändert Approval-Center). Präzisiert 05 §5 (`automation`-Kontext); Voice-/Presence-Grundsatz bestätigt. Nur dokumentiert, kein Code | accepted | ADR-0021; 05 §5, 10 | 2026-07-31 |
| DEC-047 | **KI-Arbeit, Internet, Browser- und App-Steuerung als verbindliches Zielbild** mit Architekturpriorität (öffentliche API → Import/Export → Browserautomation → visuelle UI nur als Rückfall) und deterministischem Prompt-Injection-Schutz (externe Inhalte sind Daten, nie Anweisungen). Keine parallele Implementierung; Bau erst im zuerst benötigenden Modul | accepted | ADR-0022; 12, ADR-0009 | 2026-07-31 |
| DEC-048 | **Hausverwaltungs-Systemgrenzen und Workspace-Sicherheitskontexte:** Immoware24/Fachsystem bleibt fachliche Quelle, Nextcloud Dokumentenablage, Mailprovider Kommunikationsquelle; Jarvis verbindet/projiziert/plant und baut **keine** unbemerkte konkurrierende HV-Volldatenbank. Immoware24-Integrationsprüfung nach Prioritätenfolge (öffentliche API **UNGEKLÄRT**, nicht behauptet). Privat/Arbeit/HV/Trading als getrennte Daten- und Sicherheitskontexte (Workspaces); Mieter/Vermieter sind Rollen, HV ist Sicherheitsgrenze. HV als mehrere vertikale Module | accepted | ADR-0023; 06 §6, 08 §1, 12 §3 | 2026-07-31 |
| DEC-049 | **Gestufte Trading-Architektur T1–T4;** autonomes Live-Trading nur nach späterer eigener Entscheidung. Modul 3 = T1 Trading Intelligence (Intelligence, Alarme, Briefings; R0/R1, keine R2-Fachoperation); T2 Portfolio/Journal, T3 Strategy Lab, T4 Broker/Execution ohne Position. T1-Scope und -Ausschlüsse verbindlich; Anbieter/Assetklassen/Lizenzen als Moduleinstiegsentscheidungen offen. Orders bleiben immer R2 (AV-18) | accepted | ADR-0024; 10 §1–2, 16 §2 | 2026-07-31 |
| DEC-050 | **Acht blockierende Kontakte-Gates** (getrennt): technische Releaseblocker (1) DEV-1 Telemetrie, (2) DEV-2 Tauri-Capabilities, (3) CI-Sidecar-Build/-Einbindung/-Reseal, (4) Updater auf eigenes Repository/Releasekette; Plattform-/Modulgates (5) überprüfbare committed ARM64-Evidenz, (6) vollständige produktive Intel-x86_64-Abnahme (Build/Packaging/Signierung/Livelauf, macOS 12.7.6), (7) Recovery der 116 Tombstones, (8) Integration des Handoffs in `jarvis/rebuild-v1`. Alle acht sind für Fertigmeldung und produktive Auslieferung mit Kontakte-Modul blockierend; arm64 und x86_64 gleichwertig, Intel kein Kompatibilitätstest. arm64-Read-Sync ist **DOKUMENTIERT** (Evidenz nur als Prosa-Protokoll committed), nicht abgenommen | accepted | ADR-0019, ADR-0018; modules/contacts.md §19, 15 §8 | 2026-07-31 |

## §2 Vertagte Entscheidungen (Stand der 16 ursprünglichen Deferred Decisions)

Details, Optionen und unverbindliche Empfehlungen: 17 §2.

| ID | Titel | Status | Auslöser bzw. Auflösung |
|---|---|---|---|
| DEC-D01 | Native-Bridge-Technik (PyObjC vs. Swift-Helper) | **entschieden** | → DEC-031 (ADR-0016), 2026-07-27 |
| DEC-D02 | Keychain-Anbindung (`keyring` vs. native Security-Framework-Integration) | **entschieden** | → DEC-032 (ADR-0017), 2026-07-27 |
| DEC-D03 | Recovery-Key-Format und optionale Passphrase | **entschieden** | → DEC-033, 2026-07-27 |
| DEC-D04 | UI-E2E-Werkzeug | **entschieden** | → DEC-034, 2026-07-27 |
| DEC-D05 | Session-Token-TTL und Rotation | **entschieden** | → DEC-035, 2026-07-27 |
| DEC-D06 | Optionale native R2-Zweitbestätigung | **offen** | erstes R2-Modul |
| DEC-D07 | Audit-Checkpoint-Kadenz und externes Medium | **entschieden** | → DEC-036, 2026-07-27 |
| DEC-D08 | Chat-Migration in die Personal-Datenhoheit (Zeitpunkt) | **offen** | Planung des Chat-Moduls |
| DEC-D09 | Sensitivitätsmatrix einzelner Datentypen | **teilentschieden** | Kontakt-Modul-Klassifizierung → DEC-037; **globale Matrix weiterhin offen** (erstes LLM-nutzendes Modul) |
| DEC-D10 | Erstes Fachmodul und Modulreihenfolge | **vollständig entschieden** | Modulwahl → DEC-030; Reihenfolge bis Modul 3 → DEC-045 (ADR-0019); nach Modul 3 bewusste Neuentscheidung |
| DEC-D11 | Live-Abnahme-Anbieter | **entschieden für Modul 1** | → DEC-038; je weiterem Modul erneut festzulegen |
| DEC-D12 | Broker-Ziel | **teilentschieden** | Trading-Stufung T1–T4 und Abgrenzung Trading Intelligence → DEC-049 (ADR-0024); Broker-Zielanbieter bleibt offen, Auslöser präzisiert: vor Moduleinstieg T4 |
| DEC-D13 | Home-Server-Secret-Store | **offen** | Planung eines Home-Server-Betriebs |
| DEC-D14 | Mail-Skalenpolitik | **offen** | Planung des Mail-Moduls |
| DEC-D15 | Initiale Workspaces | **entschieden** | → DEC-039, 2026-07-27 |
| DEC-D16 | Backup-Ziele und Aufbewahrung | **entschieden** | → DEC-040, 2026-07-27 |
| DEC-D17 | **macOS-Auslieferungsformat** (ein signiertes Universal-2-Artefakt gegenüber zwei getrennten signierten Release-Artefakten für arm64 und x86_64) | **offen** | spätestens vor dem ersten produktiven Desktop-Release und vor endgültiger Festlegung von Updater-Manifest und Release-Artefakten (ADR-0018, DEC-042) |

**Zählung (neu berechnet, Stand 2026-07-31):** **50 akzeptierte Entscheidungen** (DEC-001…DEC-050; 43 wie am 2026-07-28 plus DEC-044…DEC-050 aus diesem Auftrag). **Deferred-Liste: 17 Einträge** (DEC-D01…DEC-D17), davon:

- **5 vollständig offen:** DEC-D06, DEC-D08, DEC-D13, DEC-D14, DEC-D17.
- **2 teilweise offen:** DEC-D09 (Kontakt-Modul-Klassifizierung entschieden → DEC-037; globale Sensitivitätsmatrix offen) und **DEC-D12 neu** (Trading-Stufung T1–T4 und Abgrenzung entschieden → DEC-049; Broker-Zielanbieter offen, Auslöser vor T4).
- **10 entschieden:** DEC-D01–D05, DEC-D07, **DEC-D10 (neu vollständig** → DEC-030 + DEC-045), DEC-D15, DEC-D16 sowie DEC-D11 (für Modul 1 aufgelöst → DEC-038; je künftigem Modul erneut).

Gegenüber dem Stand 2026-07-28 (6 vollständig offen, 1 teilweise offen) sind damit **DEC-D10** (jetzt vollständig entschieden) und **DEC-D12** (von vollständig offen auf teilweise offen) verändert; DEC-D09 bleibt teilweise offen.
