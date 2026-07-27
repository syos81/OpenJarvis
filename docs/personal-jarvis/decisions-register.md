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
| DEC-030 | **Erstes Fachmodul: Kontakte** (löst DEC-D10; Gesamtreihenfolge bleibt offen) | accepted | Eigentümer-Entscheid; 16 | 2026-07-27 |
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
| DEC-D10 | Erstes Fachmodul und Modulreihenfolge | **entschieden (Modulwahl)** | erstes Fachmodul = Kontakte → DEC-030; Gesamtreihenfolge weiterhin offen |
| DEC-D11 | Live-Abnahme-Anbieter | **entschieden für Modul 1** | → DEC-038; je weiterem Modul erneut festzulegen |
| DEC-D12 | Broker-Ziel | **offen** | weit vor dem Trading-Modul |
| DEC-D13 | Home-Server-Secret-Store | **offen** | Planung eines Home-Server-Betriebs |
| DEC-D14 | Mail-Skalenpolitik | **offen** | Planung des Mail-Moduls |
| DEC-D15 | Initiale Workspaces | **entschieden** | → DEC-039, 2026-07-27 |
| DEC-D16 | Backup-Ziele und Aufbewahrung | **entschieden** | → DEC-040, 2026-07-27 |
| DEC-D17 | **macOS-Auslieferungsformat** (ein signiertes Universal-2-Artefakt gegenüber zwei getrennten signierten Release-Artefakten für arm64 und x86_64) | **offen** | spätestens vor dem ersten produktiven Desktop-Release und vor endgültiger Festlegung von Updater-Manifest und Release-Artefakten (ADR-0018, DEC-042) |

**Zählung:** 42 akzeptierte Entscheidungen. **6 vollständig offene Deferred Decisions: DEC-D06, DEC-D08, DEC-D12, DEC-D13, DEC-D14, DEC-D17.** **DEC-D09 bleibt teilweise offen** (Kontakt-Modul-Klassifizierung entschieden, globale Sensitivitätsmatrix offen) und wird weder als vollständig erledigt noch als vollständig offen gezählt. DEC-D10 und DEC-D11 sind für Modul 1 aufgelöst; ihre modul- bzw. reihenfolgebezogenen Restanteile werden je künftigem Modul erneut entschieden. **DEC-D17 ist der erste Eintrag über die 16 ursprünglichen Deferred Decisions hinaus** (registriert 2026-07-27 aus ADR-0018/DEC-042); die Deferred-Liste umfasst damit 17 Einträge.
