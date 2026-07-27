---
Status: normativ (oberste Norm)
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1 bis AV-37 (dieses Dokument ist ihr Primärdokument in Kurzform; Mechanik in 02–19)
Zugehörige ADRs: ADR-0001 bis ADR-0014
Verwandte DEC-Einträge: alle (siehe decisions-register.md)
---

# 01 — Architekturverfassung Personal Jarvis (AV-1 bis AV-37)

## §1 Präambel und Geltung

Diese Verfassung ist der oberste normative Bestandteil der am **2026-07-27** freigegebenen **Architektur-Baseline v3** (Zielarchitektur v2 vollständig + v3-Präzisierungen). Sie gilt für alle Arbeiten auf dem Branch `jarvis/rebuild-v1` ab dem Baseline-Tag `openjarvis-baseline-2026-07-27`. Die Baseline bedeutet nicht, dass jede interne Implementierungsentscheidung für immer unveränderlich ist — Änderungen folgen §3 und §4.

## §2 Normenhierarchie

Bei Widersprüchen gilt folgende Rangfolge:

1. **Diese Architekturverfassung (01).**
2. **Akzeptierte ADRs** — spätere ADRs können Details der Fachdokumente ändern; ein Konflikt mit der Verfassung erfordert einen Verfassungs-ADR.
3. **Normative Fachdokumente 02–19** — innerhalb derer das je Regel in der [Traceability-Matrix](traceability-matrix.md) bestimmte Primärdokument.
4. **Glossar** (Terminologie).
5. **Erläuternde Inhalte** (00, 03, Diagramme, Ablaufbeispiele) — niemals maßgeblich.

Entdeckte Widersprüche sind Defekte: redaktionelle werden mit Änderungsvermerk korrigiert; inhaltliche laufen über das ADR-Verfahren. Nach freigegebener Materialisierung sind die Repo-Dokumente die maßgebliche Referenz (nicht der Chat-Verlauf der Baseline-Erstellung).

## §3 Geschützte Bereiche

Unveränderlich bzw. **nur per ausdrücklich freigegebenem ADR** änderbar sind:

1. die Architekturverfassung,
2. Modul- und Datenhoheitsgrenzen,
3. die Abhängigkeitsrichtung,
4. die Providerneutralität,
5. die kanonische Datenhaltung,
6. die Sicherheits- und Freigaberegeln,
7. der einheitliche Ausführungspfad,
8. die Local-first- und Egress-Regeln,
9. die Backup- und Recovery-Pflichten,
10. die Definition eines vollständig abgeschlossenen Moduls.

## §4 ADR-Verfahren

Technische Implementierungsdetails dürfen später **ausschließlich** über das ADR-Verfahren geändert werden, wenn:

- ein konkreter technischer Grund vorliegt,
- Alternativen geprüft wurden,
- Auswirkungen und Migration dokumentiert sind,
- Tests und Rückfallstrategie feststehen,
- der Eigentümer (Nutzer) die Änderung ausdrücklich freigegeben hat.

ADRs liegen unter `docs/adr/`, sind fortlaufend nummeriert und tragen den Status `proposed → accepted | rejected | superseded`. Jeder ADR verlinkt betroffene AV-Regeln, Primärdokumente und DEC-Einträge. Die bewusst offenen Entscheidungen bleiben als **Deferred Decisions** dokumentiert (17, decisions-register.md) und werden jeweils **vor der ersten betroffenen Implementierung** entschieden.

## §5 Verfassungsregeln

### Grundsätze

- **AV-1** — OpenJarvis bleibt schlanke, offene, allgemeine Basis; Personal-Code ist additiv; Upstream-Dateien werden nur über die geführte Abweichungsliste (18) berührt.
- **AV-2** — Module werden vertikal vollständig fertiggestellt (Datenmodell, Backend, Adapter, Rechte, UI, Fehlerfälle, Tests, Live-Abnahme), eines nach dem anderen (19).
- **AV-3** — Keine Platzhalter, Fake-Daten, leeren Menüpunkte oder Scheinimplementierungen in produktiven Pfaden; Test-Doubles sind nur in Tests zulässig.
- **AV-4** — Providerneutralität: Fachlogik kennt nur Verträge; native Frameworks existieren ausschließlich in der Adapterschicht (08).
- **AV-5** — Local-first und Datensouveränität: kanonische Daten bleiben lokal; jeder Cloud-Abfluss ist explizit, klassifiziert und auditiert (12).

### Grenzen

- **AV-6** — Fachmodule importieren nur PJR-Ports, Basistypen, Capability- und Repository-**Verträge** sowie Eigenes — nie Upstream-Interna, nie fremde Implementierungen (04, 07).
- **AV-7** — Nur der OpenJarvisRuntimeAdapter berührt Upstream; keine Upstream-Typen überqueren Port-Grenzen (04).
- **AV-8** — Sprachmodelle erreichen Zustandsänderungen ausschließlich über Pipeline-Tools; Endpunkte, Regeln und Adapter sind für sie unerreichbar (05, 12).
- **AV-9** — Die UI spricht nur die API; Modul-Frontends sind build-time registriert, die Navigation ist readiness-gesteuert (14).
- **AV-10** — Adapter werden nur von Capability Services aufgerufen, persistieren nichts und deklarieren ihre Verifikationstiefe (08).

### Daten

- **AV-11** — `personal/jarvis.db` ist die einzige kanonische Datenbank **der Fachmodule**; jeder weitere Speicher steht im Speicher-Register mit Eigentümer, Art, Backup- und Migrationsstatus (06).
- **AV-12** — Jede Tabelle hat genau einen Modul-Eigentümer; Fremdzugriff nur über dessen Verträge; modulübergreifende Schreibvorgänge nur per UnitOfWork über die DatabaseConnectionFactory (07).
- **AV-13** — Migrationen sind linear, versioniert, getestet und haben einen Backup-Punkt (07, 13).
- **AV-14** — Externe Schreibvorgänge laufen nur über Outbox und Zustandsmaschinen; Verifikationszustände sind ehrlich (`unverified` nur bei deklarierter Providergrenze; nie stiller Erfolg). Fachänderung, ExternalActionOutbox-Eintrag, DomainEvent und Audit-Stufe werden in **einer** Transaktion geschrieben; abgeleitete Wirkungen laufen ausschließlich über die DomainEventOutbox (at-least-once, idempotente Consumer, sichtbarer Lag); der Upstream-EventBus ist nie kanonische Ereigniswahrheit (05, 11).
- **AV-15** — Löschungen sind tombstone-basiert; Merges laufen über EntityAlias/MergeRedirect und sind rückverfolgbar; Verknüpfungen über die Basis-Infrastruktur. Aliase zeigen stets auf terminale kanonische IDs (azyklisch, Kettenlimit, Path Compression); Merges erzeugen unveränderliche MergeRecords; Undo erzeugt neue Entitäten bzw. Reversal Events, niemals Rückwärts-Redirects (06).
- **AV-16** — Memory und Suchindizes sind ausschließlich abgeleitet und jederzeit vollständig neu aufbaubar (06).

### Sicherheit

- **AV-17** — Jede Capability-Operation deklariert R0/R1/R2 samt Initiation-Kontext. `user_direct` mit vollständiger Vorschau gilt als explizite Bestätigung; assistierte/automatisierte R1 brauchen separate Freigabe; R2 läuft immer über das Approval-Center mit dauerhaftem Intent, deterministischer RiskEngine, Zustands-Recheck unmittelbar vor Ausführung, Not-Aus und unveränderlicher Protokollierung (05, 10).
- **AV-18** — Trading-Orders sind immer R2; kein Sprachmodell platziert Orders oder ändert Risikoregeln (10).
- **AV-19** — R2-Executor und R2-Kill-Switch sind von Sync- und R1-Verarbeitung getrennt; ein R2-Not-Aus stoppt nie Sync/R1 (10, 11).
- **AV-20** — Secrets existieren nur im CredentialStore (OS-Schlüsselbund); Auflösung ist zweckgebunden je Adapter, Konto und Zweck; Secrets stehen nie in SQLite, Dateien, `os.environ`-Broadcasts, Logs, Traces, Fehlermeldungen oder normalen Backups; Secret-Export nur als R2-Operation (09).
- **AV-21** — Lokale API-Zugriffe nur mit kurzlebigen, scope-begrenzten Session-Tokens (SPA) bzw. dem Keychain-Installationsgeheimnis (CLI/Tauri-Hauptprozess); die SPA erhält das Installationsgeheimnis nie; WebSocket-Authentifizierung vor `accept()`; Origin-Allowlist; genau ein Schreibprozess über die exklusive Sperre — auch im CLI-In-Process-Modus (09, 07).
- **AV-22** — Egress ist fail-closed: Regeln der Form Workspace × Capability × Datentyp × Sensitivität × Provider × Umfang × Redaction mit Default `none`; unklassifizierte Inhalte gelten als S2 und werden blockiert; der EgressGuard berechnet die effektive Klasse über den vollständigen Payload; Herabstufung durch Aufrufer ist unmöglich; Redaction erzeugt neue, explizit klassifizierte Derivate; Credentials/Tokens/Schlüssel sind absolut non-egress; Cloud-Audits speichern Metadaten und Hashes, nicht den Payload; Provider-Eigenschaften (Caching, Logging, Trainingsnutzung) sind Regelbestandteil; Freigaben sind R1, Freigaben für S2 oder Umfang `full` sind R2; Modellantworten sind untrusted und füllen nur den erwarteten Schema-Slot (12).
- **AV-23** — Backups sind immer verschlüsselt (DEK) und sichern alle registrierten fachlich relevanten Speicher über den SnapshotCoordinator mit Schreib-Barriere; eine Recovery-Hülle existiert; der Recovery Key wird nie automatisch in dasselbe Backup geschrieben; nur vollständig erfolgreiche Läufe sind wiederherstellbar; Restore aktiviert ausschließlich einen vollständig geprüften Stand atomar; der Restore-Drill umfasst den Verlust von Mac und Keychain; der Backup-Kern funktioniert ab dem ersten kanonischen Datenbestand (13).
- **AV-24** — Das Audit-Log ist append-only und hash-verkettet, manipulationsevident über signierte Checkpoints (Schlüssel im Keychain, Checkpoints in Backup-Manifesten, manueller externer Export; Checkpoint-Pflicht nach jeder R2-Ausführung); vollständige Unveränderlichkeit wird ohne externe Vertrauensinstanz nicht behauptet (10, 13).
- **AV-25** — Externe Telemetrie bleibt deaktiviert (Code-Default und Presets; Abweichung DEV-1 in 18); lokale technische Metriken sind erlaubt (02, 18).

### Qualität

- **AV-26** — Zentrale Contract-Suiten je Vertrag, Port und Store; jeder Provideradapter besteht sie und zusätzlich die Live-Abnahme, bevor er als fertig gilt (15).
- **AV-27** — Die Port-/OJRA-Semantik ist durch Contract-Tests fixiert; Upstream-Übernahmen erfolgen nur nach dem Kriterienkatalog (02) mit Prüfung, Tests, eigenem Commit und Dokumentation.
- **AV-28** — Migrations-, Security-, Wiederanlauf-/Recovery-, Kill-Switch- und Restore-Tests sind Pflichtbestandteil (15).
- **AV-29** — Unterstützt ist ausschließlich die definierte Toolchain: uv, Python exakt 3.12, Rust stable ≥ 1.88, maturin, Node.js 22+ für Frontend/Vite/Tauri; macOS Apple Silicon primär, Linux sekundär; die Node-Zusatz-Bridges (WhatsApp-Baileys, Claude-Code-Runner) sind nicht unterstützt; nichts anderes wird behauptet (15 §6).

### Prozess

- **AV-30** — Jede Abweichung von dieser Verfassung sowie jede spätere Architekturänderung erfordert einen vom Nutzer freigegebenen ADR (§4).
- **AV-31** — Port- und Vertragsänderungen sind ADR-pflichtig.
- **AV-32** — Bewusste Upstream-Abweichungen stehen abschließend in der Abweichungsliste (18) und werden bei jeder Upstream-Übernahme erneut geprüft.
- **AV-33** — **Materialisierungsregel:** Gemeinsame Grundlagen entstehen nur, wenn das unmittelbar folgende Modul sie zwingend braucht; kein vorsorgliches Framework. Ausnahme kraft Beschlusses: der Backup-Kern funktioniert ab dem ersten kanonischen Datenbestand (DEC-024).
- **AV-34** — Es gibt genau eine PersonalCompositionRoot je Prozess; Verdrahtung ausschließlich per Constructor Injection; kein Service-Locator, keine Modul-Singletons, kein zweiter EventBus; Start- und Shutdown-Reihenfolge gemäß 04; Migrations- oder Sicherheitsfehler führen zu fail-closed ohne Teilbetrieb; der `serve`-Integrationspunkt ist genau ein bewachter Aufruf mit ADR-, Test- und Abweichungslisten-Pflicht (04, 18).
- **AV-35** — Alle Mutationen — API, CLI, Chat-Tools, Automationen — laufen als typisierte Commands über den ApplicationCommandBus durch dieselbe Validierung, Pipeline, Rechte, Auditierung und Zustandsmaschinen; direkte Zugriffe auf Adapter oder fremde Repository-Implementierungen sowie jeder zweite produktive Ausführungsweg sind verboten; R2-Ausführung nur im Serve-Prozess (05).
- **AV-36** — Jedes Modul führt die Lifecycle-Zustandsmaschine aus 14; die Navigation zeigt nur kompilierte Module in erlaubten Zuständen; `configuration_required` ist nur mit vollständigem, echtem Einrichtungsfluss sichtbar.
- **AV-37** — Migrationen folgen dem globalen Modell aus 07 (globale monotone ID, Modul-Eigentümer, Abhängigkeiten, Prüfsummen-Ledger, Unveränderlichkeit veröffentlichter Migrationen, Backup-Barriere, fail-closed, forward-only); Modul-Deaktivierung ist nie destruktiv; die Datenlöschung eines Moduls ist R2.
