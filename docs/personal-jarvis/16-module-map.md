---
Status: normativ (Adapter-Nennungen sind gekennzeichnete, nicht bindende Beispiele)
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-2 (Modulgrenzen-Anteil), AV-11/AV-12 (Entitäten-Zuordnung), AV-33
Zugehörige ADRs: ADR-0002, ADR-0012, ADR-0016, ADR-0018
Verwandte DEC-Einträge: DEC-012, DEC-018, DEC-030, DEC-031, DEC-042, DEC-043
---

# 16 — Modulkarte

**Dieses Dokument enthält keine Modulreihenfolge.** Als **erstes Fachmodul wurde am 2026-07-27 „Kontakte" gewählt (DEC-030)**; die **Gesamtreihenfolge aller weiteren Module bleibt ausdrücklich offen** und wird erst nach gesonderter Freigabe entschieden. Die Spalte „mögliche Adapter" nennt **nicht bindende Beispiele**, sofern nicht ausdrücklich als beschlossen gekennzeichnet; die endgültige Adapterwahl fällt je Modul (Abnahmeziel je Modul: DEC-D11).

## §1 Module (ungeordnet)

| Modul | Zweck / kanonischer Kern | Abhängigkeiten | mögliche Adapter (Beispiele) | Upstream-Verhältnis |
|---|---|---|---|---|
| Chat & Sessions | Konversation, Verlauf, Tool-Nutzung | PJR | — | **Upstream-getragen** (Chat-Seite, `sessions.db`); Personal ergänzt Pipeline-Tools; spätere Überführung der Verläufe: 06 §3 |
| Modelle & Inferenz | Modellwahl, Routing-Politik, Egress-Grants je Workspace | PJR | — | Upstream-getragen (Engines/Models-Seite); Personal ergänzt Richtlinien (12) |
| Kontakte | Personen, Rollen, Beziehungen, externe Identitäten | Basis | AppleContacts (CNContactStore über Swift-Sidecar, ADR-0016) als Erstadapter; CardDAV und lokale vCard als spätere Adapter | eigenes Modul; **gewähltes erstes Fachmodul (DEC-030)** |
| Kalender | Kalender, Termine, Teilnehmer | Kontakte (Teilnehmer) | CalDAV, AppleEventKit, ICS-Feed (read-only) | eigenes Modul |
| Mail | Konten, Ordner, Nachrichten-Metadaten, Versand | Kontakte | IMAP/SMTP, JMAP (Apple-Mail-App ist keine Datenquelle, 08 §4) | eigenes Modul |
| Aufgaben & Projekte | Aufgaben, Projekte, Verknüpfungen | Kontakte, Kalender | AppleEventKit-Reminders, CalDAV-Tasks, lokal | eigenes Modul |
| Dokumente & Wissen | Dokument-Metadaten, Sammlungen, Blob-Verweise | Basis | Dateisystem-Import; später Cloud-Quellen | eigenes Modul |
| Globale Suche | Query über kanonische DB + abgeleiteten Index | mehrere Module | — (nutzt MemoryIndexPort) | eigenes Modul |
| Life OS | Messwerte, Ziele, Provenienz | Kontakte optional | HealthKit-Export, CSV, Geräte-Quellen | eigenes Modul |
| Trading | Konten, Positionen, Orders, Risikoregeln | Basis, Benachrichtigungen | BrokerAdapter (Ziel: DEC-D12) | eigenes Modul; **immer R2** (10) |
| Automationen | Trigger → Bedingung → Aktion über Capability-Operationen | alle Capabilities | — (nutzt SchedulerPort) | eigenes Modul |
| Benachrichtigungen | zentrale Zustands-/Konflikt-/Freigabe-Hinweise | alle | — | eigenes Modul; bis dahin modul-lokale Statusflächen |
| Voice | Diktat/Vorlesen im Personal-Kontext | Chat | — (Upstream-Speech via PJR; Speech lokal-first; **Cloud-STT/TTS nur über den EgressGuard**, 12 §5; Port-/Adaptertechnik erst mit dem Voice-Modul) | Upstream-Speech gekapselt |
| Backup & Wiederherstellung | UI, Kataloge, Zeitpläne über dem Backup-Kern | Basis | — | eigenes Modul; **Backup-Kern ist Basis-Bestandteil** (13 §1) |
| Einstellungen & Kontenverwaltung | Workspaces, ProviderAccounts, Bindings, CredentialReferences, Modulstatus | Basis | — | eigenes Modul; wächst als vertikaler Bestandteil jedes Moduls |

## §2 Kanonische Entitäten je Modul (Datenhoheit, Single Source)

- **Einstellungen & Kontenverwaltung:** `workspaces` · `provider_accounts` · `capability_bindings` · `provider_collections` (inkl. Workspace-Zuordnung) · CredentialReferences (Verweise, nie Secrets) · `settings`.
- **Kontakte:** `contacts` (+ normalisierte Kindtabellen E-Mail/Telefon/Adresse) · `contact_roles` (contact × workspace × Rolle) · `contact_relations` (typisiert, mit Objektbezug) · `organizations` + Mitgliedschaften · `contact_external_ids` · Historie/Tombstones.
- **Kalender:** `calendars` · `events` (UTC + IANA-Zeitzone; Wiederholungsregel roh; materialisierte Instanzen sind abgeleitet) · `event_attendees` (contact_id nullable + Roh-E-Mail) · `event_external_ids` · Tombstones.
- **Mail:** `mail_folders` · `messages` (Header-Metadaten, Flags, Snippet kanonisch; Bodies/Anhänge im Blob-Store) · `mail_outbox`. Löschregel: Papierkorb-Semantik des Providers wird gespiegelt, nie stillschweigend expunged. Skalenpolitik: DEC-D14.
- **Aufgaben & Projekte:** `projects` · `tasks` (Status, Fälligkeit; Bezüge über die Basis-Verknüpfungsinfrastruktur, 06 §5).
- **Dokumente & Wissen:** `documents` (Metadaten, Hash, Blob-Referenz, Quelle) · `collections` · Verknüpfungen. Abgeleitet: Chunking/Embeddings im Index.
- **Globale Suche:** keine kanonischen Entitäten außer `saved_searches`; konsumiert Read-APIs und Index.
- **Life OS:** `metric_definitions` · `metric_samples` (Wert, Einheit, Zeitpunkt, **Provenienz**: Quelle, Import-Charge, Rohreferenz) · `goals`.
- **Trading:** `broker_accounts` · `positions` · `orders` (Zustandsmaschine, 11 §6 Nr. 6) · `executions` · `risk_rules` (Änderung R2) · `portfolio_snapshots`. Marktdaten nur im Cache, nie kanonisch.
- **Automationen:** `automations` (Trigger/Bedingung/Aktion als Referenzen auf Capability-Operationen) · `automation_runs`.
- **Benachrichtigungen:** `notifications` (Quelle, Schwere, Zustand).
- **Voice:** Einstellungen; Transkripte gehören dem Chat (Upstream) — nur Verweise.
- **Backup:** `backup_catalog` (Läufe, Manifeste, Prüfsummen).
- **Basis (Sicherheit/Infrastruktur):** `approval_intents` · `audit_log` · `outbox`-Tabellen (drei Warteschlangen) · `sync_state` · ResourceLink-/EntityAlias-Tabellen · Migrations-Ledger.

## §3 Basis

„Basis" bezeichnet die gemeinsamen Fundamentteile: PJR-Ports (nur benötigte) + OJRA, DB-Kern (ConnectionFactory/UoW/Migrations-Runner), CredentialStore, ActionPipeline-Kern, Audit (+ Checkpoint-Signierer), Outboxes + R1-Executor (R2-Executor erst mit dem ersten R2-Modul), Verknüpfungsinfrastruktur, Installations-Token-Auth, **Backup-Kern**, Kontenverwaltungs-Slice, Egress-Guard. Materialisierung strikt nach AV-33: nur in dem Umfang, den das unmittelbar nächste Modul zwingend braucht (Ausnahme Backup-Kern, DEC-024).

## §4 Startkriterien je Modul (keine Reihenfolge)

Ein Modul darf erst beginnen, wenn: (1) die benötigten Basis-Teile benennbar sind; (2) mindestens ein realer Abnahme-Provider verfügbar ist (DEC-D11) **und für macOS-Module Abnahmehardware beider Zielarchitekturen — Apple Silicon arm64 und Intel x86_64 — zur Verfügung steht** (ADR-0018, DEC-042; Matrix in 15 §7); (3) die Risikoklassen seiner Operationen klassifiziert sind; (4) der UI-Scope definiert ist; (5) für R2-Module zusätzlich: RiskEngine-Regelwerk und Not-Aus-Konzept vor Baubeginn vorliegen. Trading wird nach diesen Kriterien eingeplant, nicht pauschal zuletzt. Diese Kriterien gelten unverändert für **alle** Module nach dem ersten; die **Reihenfolge der weiteren Module bleibt offen** und wird nicht in diesem Dokument festgelegt.

### §4.1 Produktstart-Gate Kontakte (2026-07-28)

Der nach ADR-0016 Punkt 2 verpflichtende Spike G3a ist auf Apple Silicon arm64 **bestanden**; kein Kill-Kriterium ist eingetreten (ADR-0016 Punkt 8, DEC-043). Die Startkriterien aus §4 sind damit für das Modul „Kontakte" erfüllt.

**Die produktive Implementierung darf beginnen** und umfasst als **ein** vertikaler Zug: kanonische Contacts-Domäne · SQLite-Persistenz nach 06/07 · Native-Bridge-Vertrag nach 08 §3/§4 · Cursor-/Token-Modell und Voll-Diff-Fallback nach 11 §3 · Tombstones · Konflikt- und Echo-Unterdrückung · Berechtigungs- und Freigabemodell nach 09/10 · Audit und Logging nach 10 · Backend/API · Benutzeroberfläche nach 14 · Tests nach 15.

**Es gilt die vertikale Entwicklungsregel (ADR-0012, 19).** Das Modul ist erst abgeschlossen, wenn für die definierte Capability **vollständig** vorliegen: Datenmodell · Persistenz · Backend · Native Bridge · Berechtigungen und Freigaben · UI · Fehler- und Randfälle · Tests · Logging · **produktiver Live-Test auf arm64 und x86_64**. Eine horizontale, halbfertige Verteilung über mehrere Fachmodule ist unzulässig; ebenso eine nur lesende Vorstufe (AV-3).

**Der Modulabschluss bleibt gesperrt,** solange die Abnahmematrix in 15 §8 nicht in **beiden** Spalten vollständig bestanden ist. Spike-Evidenz ist Vor- bzw. Teilnachweis und ersetzt keine Abnahmezeile (15 §7 Nr. 4).

**Parallelarbeit:** Die frühere pauschale Regel „Kein anderes Fachmodul beginnt parallel" ist als allgemeine Norm abgelöst; verbindlich sind die Dauerregeln §2, §19 und §20 ([`docs/governance/openjarvis-dauerregeln.md`](../governance/openjarvis-dauerregeln.md)) — eine Risk Lane und eine davon unabhängige Safe Product Lane dürfen gleichzeitig laufen, und Module blockieren einander nur bei echter technischer Abhängigkeit. Die Reihenfolge der weiteren Module bleibt unverändert offen.

## §5 Modulunterlagen (Konvention)

Je Modul entsteht mit seiner Umsetzung `docs/personal-jarvis/modules/<modul>.md` (Pflichtinhalt: 19). Verlinkung: Modulkarte (dieses Dokument), betroffene Verträge (08), Risikoklassifizierung (10), Egress-Labels (12), Testnachweise (15), Live-Abnahme-Protokoll. Das Verzeichnis wurde mit dem ersten Modul angelegt; die Unterlage des Kontakte-Moduls liegt unter [`modules/contacts.md`](modules/contacts.md) (Implementierungsplan, 2026-07-28).
