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

**Die Modulreihenfolge ist seit 2026-07-31 bis Modul 3 festgelegt (DEC-045, ADR-0019; §4.2):** Modul 1 **Kontakte** (DEC-030) → Modul 2 **Kalender** → Modul 3 **Trading Intelligence (T1**, ADR-0024/DEC-049**)**. Zwischen diesen Modulen wird kein anderes Fachmodul eingeschoben oder parallel begonnen; **nach Modul 3 wird die Reihenfolge bewusst neu entschieden** (DEC-D10 ist damit vollständig aufgelöst). Die Spalte „mögliche Adapter" nennt **nicht bindende Beispiele**, sofern nicht ausdrücklich als beschlossen gekennzeichnet; die endgültige Adapterwahl fällt je Modul (Abnahmeziel je Modul: DEC-D11).

## §1 Module (ungeordnet)

| Modul | Zweck / kanonischer Kern | Abhängigkeiten | mögliche Adapter (Beispiele) | Upstream-Verhältnis |
|---|---|---|---|---|
| Chat & Sessions | Konversation, Verlauf, Tool-Nutzung | PJR | — | **Upstream-getragen** (Chat-Seite, `sessions.db`); Personal ergänzt Pipeline-Tools; spätere Überführung der Verläufe: 06 §3 |
| Modelle & Inferenz | Modellwahl, Routing-Politik, Egress-Grants je Workspace | PJR | — | Upstream-getragen (Engines/Models-Seite); Personal ergänzt Richtlinien (12) |
| Kontakte | Personen, Rollen, Beziehungen, externe Identitäten | Basis | AppleContacts (CNContactStore über Swift-Sidecar, ADR-0016) als Erstadapter; CardDAV und lokale vCard als spätere Adapter | eigenes Modul; **Modul 1 (DEC-030, DEC-045)**; einziges aktives Fachmodul, nicht abgeschlossen (§4.1, DEC-050) |
| Kalender | Kalender, Termine, Teilnehmer | Kontakte (Teilnehmer) | AppleEventKit (öffentliche API; ADR-0016-Analogie: Swift-Sidecar-Muster der Contacts-Bridge) als Erstadapter; CalDAV, ICS-Feed (read-only) später | eigenes Modul; **Modul 2 (DEC-045)** |
| Mail | Konten, Ordner, Nachrichten-Metadaten, Versand | Kontakte | IMAP/SMTP, JMAP (Apple-Mail-App ist keine Datenquelle, 08 §4) | eigenes Modul |
| Aufgaben & Projekte | Aufgaben, Projekte, Verknüpfungen | Kontakte, Kalender | AppleEventKit-Reminders, CalDAV-Tasks, lokal | eigenes Modul |
| Dokumente & Wissen | Dokument-Metadaten, Sammlungen, Blob-Verweise | Basis | Dateisystem-Import; später Cloud-Quellen | eigenes Modul |
| Globale Suche | Query über kanonische DB + abgeleiteten Index | mehrere Module | — (nutzt MemoryIndexPort) | eigenes Modul |
| Life OS | Messwerte, Ziele, Provenienz | Kontakte optional | HealthKit-Export, CSV, Geräte-Quellen | eigenes Modul |
| Trading Intelligence (T1) | Instrumente-Referenzen, Watchlists, Alarmregeln, Briefing-Definitionen, Provenienz (Marktdaten nur Cache) | Basis, Benachrichtigungen | Markt-/Nachrichten-/Kursdatenquellen (Anbieter offen, ADR-0024 Punkt 4); Internetrecherche (ADR-0022) | eigenes Modul; **Modul 3 (DEC-045, DEC-049)**; R0/R1, keine R2-Fachoperation |
| Trading T2–T4 (Portfolio/Journal · Strategy Lab · Broker/Execution) | Positionen, Orders, Risikoregeln, Executions | Basis, T1 | BrokerAdapter (Ziel: DEC-D12, vor T4) | eigene Module je Stufe (ADR-0024); **Orders/Execution immer R2** (10); ohne Position nach Modul 3 |
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

Ein Modul darf erst beginnen, wenn: (1) die benötigten Basis-Teile benennbar sind; (2) mindestens ein realer Abnahme-Provider verfügbar ist (DEC-D11) **und für macOS-Module Abnahmehardware beider Zielarchitekturen — Apple Silicon arm64 und Intel x86_64 — zur Verfügung steht** (ADR-0018, DEC-042; Matrix in 15 §7); (3) die Risikoklassen seiner Operationen klassifiziert sind; (4) der UI-Scope definiert ist; (5) für R2-Module zusätzlich: RiskEngine-Regelwerk und Not-Aus-Konzept vor Baubeginn vorliegen. Trading wird nach diesen Kriterien eingeplant, nicht pauschal zuletzt. Diese Kriterien gelten unverändert für **alle** Module. Die **Reihenfolge der ersten drei Fachmodule ist in §4.2 festgelegt** (DEC-045, ADR-0019); die Reihenfolge nach Modul 3 wird bewusst neu entschieden.

### §4.1 Produktstart-Gate Kontakte (2026-07-28)

Der nach ADR-0016 Punkt 2 verpflichtende Spike G3a ist auf Apple Silicon arm64 **bestanden**; kein Kill-Kriterium ist eingetreten (ADR-0016 Punkt 8, DEC-043). Die Startkriterien aus §4 sind damit für das Modul „Kontakte" erfüllt.

**Die produktive Implementierung darf beginnen** und umfasst als **ein** vertikaler Zug: kanonische Contacts-Domäne · SQLite-Persistenz nach 06/07 · Native-Bridge-Vertrag nach 08 §3/§4 · Cursor-/Token-Modell und Voll-Diff-Fallback nach 11 §3 · Tombstones · Konflikt- und Echo-Unterdrückung · Berechtigungs- und Freigabemodell nach 09/10 · Audit und Logging nach 10 · Backend/API · Benutzeroberfläche nach 14 · Tests nach 15.

**Es gilt die vertikale Entwicklungsregel (ADR-0012, 19).** Das Modul ist erst abgeschlossen, wenn für die definierte Capability **vollständig** vorliegen: Datenmodell · Persistenz · Backend · Native Bridge · Berechtigungen und Freigaben · UI · Fehler- und Randfälle · Tests · Logging · **produktiver Live-Test auf arm64 und x86_64**. Eine horizontale, halbfertige Verteilung über mehrere Fachmodule ist unzulässig; ebenso eine nur lesende Vorstufe (AV-3).

**Der Modulabschluss bleibt gesperrt,** solange die Abnahmematrix in 15 §8 nicht in **beiden** Spalten vollständig bestanden ist. Spike-Evidenz ist Vor- bzw. Teilnachweis und ersetzt keine Abnahmezeile (15 §7 Nr. 4).

**Kein anderes Fachmodul beginnt parallel.**

### §4.2 Verbindliche Modulreihenfolge bis Modul 3 (2026-07-31, DEC-045, ADR-0019)

Die Reihenfolge der ersten drei Fachmodule ist festgelegt und ersetzt ADR-0012 Punkt 4:

1. **Modul 1 — Kontakte** (DEC-030). Einziges **aktives** Fachmodul; **nicht abgeschlossen**. Fertigmeldung und produktive Auslieferung sind an die acht Gates aus DEC-050 gebunden (kanonisch: [`modules/contacts.md`](modules/contacts.md) §19): vier technische Releaseblocker (DEV-1, DEV-2, CI-Sidecar-Build/-Einbindung/-Reseal, Updater auf eigenes Repository) und vier Plattform-/Modulgates (committed ARM64-Evidenz, vollständige produktive Intel-x86_64-Abnahme, Recovery der 116 Tombstones, Integration des Handoffs in `jarvis/rebuild-v1`). arm64 und x86_64 sind gleichwertig; **Intel ist kein Kompatibilitätstest** (ADR-0018).
2. **Modul 2 — Kalender.** Darf erst beginnen, wenn Kontakte vollständig abgenommen und integriert ist. Scope-Grenzen für den späteren Einstieg: Apple Calendar über öffentliche EventKit-APIs · mehrere Kalender und Accounts · kanonische Providerdaten und kontrollierte lokale Repräsentation · Initialimport · echte inkrementelle Synchronisation · stabile IDs · Löschungen und Tombstones · Ganztagstermine · Zeitzonen und Sommerzeitwechsel · Serien und Ausnahmen · Teilnehmer, Einladungen und Antwortstatus · Erinnerungen · Konflikterkennung · Create/Update/Delete · Approval-, Outbox- und Ausführungsprüfung · Suche und kontrollierte Projektion · arm64- und Intel-x86_64-Abnahme. **Ein EventKit-Spike oder Kalender-Produktcode entsteht in keinem früheren Auftrag; notwendige Spikes beginnen erst nach vollständiger Kontakte-Abnahme innerhalb des Kalender-Moduls.** Die alte `gcalendar`-Anbindung ist REPLACE (Register 20 §2, C-11), nie Vorstufe.
3. **Modul 3 — Trading Intelligence (T1)** (ADR-0024, DEC-049). Gestufte Trading-Architektur T1–T4; nur T1 ist eingeplant. T1-Scope, T1-Ausschlüsse und offene Moduleinstiegsentscheidungen: ADR-0024. R0/R1, keine R2-Fachoperation; Orders/Execution (ab T4) bleiben immer R2 (10, AV-18).

**Nach Modul 3 wird die weitere Reihenfolge bewusst neu entschieden.** Hausverwaltung (ADR-0023), Life OS, Mail und weitere Trading-Stufen bleiben verbindliche Zielbereiche ohne festgelegte Position. Es gilt durchgehend die Ein-Modul-Regel (ADR-0019): immer nur ein Fachmodul zu 100 Prozent, kein vorsorglicher Unterbau (AV-33).

## §5 Modulunterlagen (Konvention)

Je Modul entsteht mit seiner Umsetzung `docs/personal-jarvis/modules/<modul>.md` (Pflichtinhalt: 19). Verlinkung: Modulkarte (dieses Dokument), betroffene Verträge (08), Risikoklassifizierung (10), Egress-Labels (12), Testnachweise (15), Live-Abnahme-Protokoll. Das Verzeichnis wurde mit dem ersten Modul angelegt; die Unterlage des Kontakte-Moduls liegt unter [`modules/contacts.md`](modules/contacts.md) (Implementierungsplan, 2026-07-28).
