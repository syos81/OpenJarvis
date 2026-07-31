---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-2 (Primärdokument), AV-3, AV-26, AV-28
Zugehörige ADRs: ADR-0012, ADR-0018
Verwandte DEC-Einträge: DEC-018, DEC-042, DEC-043
---

# 19 — Definition of Done (vollständig abgeschlossenes Modul)

Ein Fachmodul gilt erst dann als **vollständig abgeschlossen**, wenn sämtliche folgenden Kriterien erfüllt und nachgewiesen sind. Erst danach beginnt das nächste Modul (AV-2). Kein Kriterium darf durch Platzhalter, Mocks oder Scheinimplementierungen in produktiven Pfaden erfüllt werden (AV-3).

**Auf macOS gilt zusätzlich durchgehend:** Jedes gerätebezogene Kriterium ist auf **beiden** gleichwertigen Zielarchitekturen (Apple Silicon arm64 und Intel x86_64, Mindestversion macOS 12.3) auf echter Hardware nachzuweisen. Ein Ergebnis der einen Architektur gilt niemals automatisch für die andere; Rosetta ersetzt keine native Abnahme (ADR-0018, DEC-042; Matrix in 15 §7).

## §1 Datenmodell

- Kanonische Entitäten gemäß Modulkarte (16 §2) implementiert; Tabelleneigentümerschaft eingetragen.
- Migrationen nach dem globalen Modell (07 §6): globale IDs, Eigentümer, Abhängigkeiten, Prüfsummen; Migrationstests grün.
- Speicher-Register (06 §2) aktualisiert (inkl. Backup-Kennzeichnung); externe Identitäten und Tombstone-/Historienregeln umgesetzt.

## §2 Backend

- Application-/Capability-Services über die PersonalCompositionRoot komponiert (04); alle Mutationen als Commands über den CommandBus (05, AV-35).
- Jede Operation mit deklarierter Risikoklasse und Initiation-Kontext-Verhalten (10, 05 §5); Lifecycle-Zustandsmaschine implementiert und über `/v1/personal/system/modules` gemeldet (14 §4).
- DomainEvents, Outbox-Anbindung und Index-Aktualisierung gemäß 11.

## §3 Adapter

- Fachvertrag der Capability definiert (08 §3) — erst jetzt, nicht auf Vorrat (AV-33).
- Mindestens die für das Modul beschlossenen Adapter implementiert; jeder besteht die zentrale Contract-Suite (15 §1 Nr. 2) inkl. deklarierter Verifikationstiefe.
- **Live-Abnahme** gegen einen echten Provider-Account bestanden und protokolliert (Anbieter gemäß DEC-D11; AV-26) — auf macOS **je Zielarchitektur** (15 §7).
- Native Bridges bzw. Sidecars liegen als **nativer ausführbarer Code beider** macOS-Zielarchitekturen vor, sind signiert und je Architektur getestet; das Auslieferungsformat ist dabei unerheblich (08 §4, ADR-0018, DEC-D17).

## §4 Rechte und Sicherheit

- Capability-/Workspace-Prüfungen aktiv; Credentials ausschließlich über den CredentialStore (09 §4).
- Egress-Labels des Moduls registriert; Egress-Tests grün (12).
- Für R1: Vorschau + Bestätigung + Audit + Ergebnisverifikation nachgewiesen. Für R2 zusätzlich: ApprovalIntent-Fluss, RiskEngine-Regeln, Recheck, Not-Aus, unveränderliche Protokollierung (10).

## §5 UI

- Vollständiges, gekapseltes Modul-Frontend (14 §1–2): echte Navigationssichtbarkeit nur in erlaubten Zuständen, vollständiger Einrichtungsfluss falls `configuration_required` sichtbar sein soll, Status-/Fehlerflächen, keine leeren Menüpunkte.
- Desktop-Abnahme (Entwicklungsbetrieb, gepackte App, App-Neustart) **je macOS-Zielarchitektur** bestanden (15 §1 Nr. 12, §7).
- Kontenverwaltungs-Slice für die Provider des Moduls (Bindings, Collections, Re-Auth).

## §6 Fehlerfälle

- Zustandsmaschinen (Verifikation, ggf. Mail, Konflikte, Circuit-Breaker) implementiert und getestet (11); `attention_required`-Pfade sichtbar; Offline-Verhalten definiert.

## §7 Tests

- Alle einschlägigen Suiten aus 15 §1 grün (Unit, Contract, Integration, Migration, Security, Zustandsmaschinen, native macOS soweit betroffen, UI-E2E, Kill-Switch/Sperren soweit betroffen).
- **Kontakte (Stand 2026-07-28):** Der Modulabschluss ist **gesperrt**. Die ausgefüllte Matrix in **15 §8** enthält in beiden Spalten `OPEN`-Zeilen; auf arm64 ist zusätzlich eine Zeile `NOT EXECUTABLE IN CURRENT ENVIRONMENT`, die bis zu ihrer Durchführung wie `OPEN` zählt. Der Beginn der produktiven Implementierung ist davon unberührt freigegeben (16 §4.1, ADR-0016 Punkt 8).
- Die **Dual-Architektur-Abnahmematrix (15 §7)** ist in **beiden** Pflichtspalten vollständig bestanden und mit Architektur, macOS-Version, Swift-/SDK-Version, Zertifikat, Testbenutzer und Datum protokolliert. Spike-Ergebnisse gelten als technische Vor- bzw. Teilnachweise und ersetzen keine Matrixzeile.

## §8 Betrieb und Daten­sicherheit

- Moduldaten sind von der Snapshot-Registrierung erfasst; Restore-Roundtrip mit Moduldaten nachgewiesen (13) — auf macOS **je Zielarchitektur** (13 §7, 15 §7).
- Scheduler-/Automation-Anteile idempotent re-registrierbar (04 §2 SchedulerPort).

## §9 Dokumentation und Register

- Modulunterlage `docs/personal-jarvis/modules/<modul>.md` erstellt (16 §5).
- Entscheidungsregister und Traceability-Matrix für berührte Zeilen aktualisiert; Glossar um neue verbindliche Begriffe ergänzt.
- Keine Deferred Decision vorweggenommen (17 §1); berührte Deferred Decisions sind vor Baubeginn entschieden worden.

## §10 Abschluss

- Live-Abnahme-Protokoll durch den Eigentümer bestätigt. Erst mit dieser Bestätigung gilt das Modul als abgeschlossen.
- **Auf macOS ist der Abschluss zusätzlich an das vollständige Bestehen beider Spalten der Dual-Architektur-Abnahmematrix gebunden** (15 §7, ADR-0018). Module, deren Abnahme nur auf einer Architektur vorliegt, gelten als **nicht** abgeschlossen — auch rückwirkend.

## §11 Vollständiger Abnahmekatalog (ADR-0019, 2026-07-31)

Ergänzend und ausdrücklich verbindlich: Ein Fachmodul ist erst zu 100 Prozent abgeschlossen, wenn **alle** folgenden Bestandteile vorliegen und nachgewiesen sind — keiner darf mit „vorerst ausreichend", Platzhaltern oder offenen Gates übersprungen werden (AV-3, ADR-0019):

fachliches und kanonisches Datenmodell · versionierte Migrationen · Repository- und Transaktionslogik · Backend und API · öffentliche Provideranbindung · Initialimport und inkrementelle Synchronisation · Cursor-, Änderungs- und Löschsemantik · Create-, Update- und Delete-Strecken, soweit sie zum beschlossenen Modulumfang gehören · Berechtigungen und Plattformrechte · Approvals, Outbox und Ausführungsprüfung · Sicherheits- und Datenschutzgrenzen · vollständige Benutzeroberfläche · **Suche und kontrollierte Projektion** (kanonisch → Index, kein Rückschreiben, Löschweitergabe; ADR-0020 §4, Register 20 §5) · Fehlerfälle und verständliche Nutzerzustände · Logging, Audit und **Provenienz** · **Export** · **getestete Wiederherstellung** · **Retention und Löschweitergabe** · automatisierte Tests · Produktions-Build · Packaging · Signierung · **produktiver Livelauf auf arm64** · **produktiver Livelauf auf Intel-x86_64** · Modul- und Betriebsdokumentation · abschließender Qualitätsaudit · sauberer Commit und kontrollierte Integration.

Die beiden macOS-Zielarchitekturen sind gleichwertig; **Intel x86_64 ist kein Kompatibilitätstest** (ADR-0018, DEC-042). Ein neues Fachmodul beginnt erst, wenn das vorherige diesen Katalog vollständig erfüllt hat (Ein-Modul-Regel, ADR-0019).
