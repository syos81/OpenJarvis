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

> **Allgemeiner Blockabschluss: normativ ausschliesslich in
> [`docs/governance/openjarvis-dauerregeln.md`](../governance/openjarvis-dauerregeln.md)
> §15.** Dieses Dokument definiert den allgemeinen Abschluss eines normalen
> Blocks nicht zweitens. Es führt die **fachlichen und modulspezifischen**
> Anforderungen an ein vollständig abgeschlossenes Fachmodul; wo unten eine
> allgemeine Prozesspflicht stand, steht heute der Verweis.

Ein Fachmodul gilt erst dann als **vollständig abgeschlossen**, wenn die folgenden fachlichen Kriterien erfüllt und nachgewiesen sind. Kein Kriterium darf durch Platzhalter, Mocks oder Scheinimplementierungen in produktiven Pfaden erfüllt werden (AV-3). Ob ein weiteres Modul parallel läuft, richtet sich nach den Dauerregeln §2 und §20, nicht nach diesem Dokument.

**Auf macOS gilt für gerätebezogene Kriterien:** Apple Silicon arm64 und Intel x86_64 bleiben gleichwertige native Releaseziele (Mindestversion macOS 12.3); ein Ergebnis der einen Architektur gilt niemals automatisch für die andere, und Rosetta ersetzt keine native Abnahme (ADR-0018, DEC-042). **Wann eine native Abnahme erneut verlangt wird, regeln die Dauerregeln §14** — nicht jede Änderung löst eine erneute Abnahme beider Architekturen aus.

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
- Desktop-Abnahme (Entwicklungsbetrieb, gepackte App, App-Neustart) bestanden (15 §1 Nr. 12, §7); je macOS-Zielarchitektur nach Massgabe der Dauerregeln §14. Für UI genügt zusätzlich die Eigentümer-Sichtprüfung, wenn keine automatisierbare Wahrheit fehlt (Dauerregeln §13).
- Kontenverwaltungs-Slice für die Provider des Moduls (Bindings, Collections, Re-Auth).

## §6 Fehlerfälle

- Zustandsmaschinen (Verifikation, ggf. Mail, Konflikte, Circuit-Breaker) implementiert und getestet (11); `attention_required`-Pfade sichtbar; Offline-Verhalten definiert.

## §7 Tests

- Alle einschlägigen Suiten aus 15 §1 grün (Unit, Contract, Integration, Migration, Security, Zustandsmaschinen, native macOS soweit betroffen, UI-E2E, Kill-Switch/Sperren soweit betroffen).
- **Kontakte (Stand 2026-07-28):** Der Modulabschluss ist **gesperrt**. Die ausgefüllte Matrix in **15 §8** enthält in beiden Spalten `OPEN`-Zeilen; auf arm64 ist zusätzlich eine Zeile `NOT EXECUTABLE IN CURRENT ENVIRONMENT`, die bis zu ihrer Durchführung wie `OPEN` zählt. Der Beginn der produktiven Implementierung ist davon unberührt freigegeben (16 §4.1, ADR-0016 Punkt 8).
- Soweit die Dauerregeln §14 für den betroffenen plattformspezifischen Pfad eine native Abnahme verlangen, ist die zugehörige Zeile der Matrix (15 §7) bestanden und mit Architektur, macOS-Version, Swift-/SDK-Version, Zertifikat, gebundenem Abnahmescope und Datum protokolliert. Spike-Ergebnisse gelten als technische Vor- bzw. Teilnachweise und ersetzen keine Matrixzeile.

## §8 Betrieb und Daten­sicherheit

- Moduldaten sind von der Snapshot-Registrierung erfasst; der Recovery-Nachweis folgt der Definition von `restore_path_verified` in den Dauerregeln §3 (13, 13 §7). Ein isolierter zerstörungsfreier Roundtrip wird verwendet, wenn er verfügbar ist; andernfalls treten enger Mutationsscope, Baseline-/Nachkontrolle und Änderungs-Freeze an seine Stelle. Plattformwiederholung nach Dauerregeln §14.
- Scheduler-/Automation-Anteile idempotent re-registrierbar (04 §2 SchedulerPort).

## §9 Dokumentation und Register

- Modulunterlage `docs/personal-jarvis/modules/<modul>.md` erstellt (16 §5).
- Entscheidungsregister und Traceability-Matrix für berührte Zeilen aktualisiert; Glossar um neue verbindliche Begriffe ergänzt.
- Keine Deferred Decision vorweggenommen (17 §1); berührte Deferred Decisions sind vor Baubeginn entschieden worden.

## §10 Abschluss

- Live-Abnahme-Protokoll durch den Eigentümer bestätigt, soweit die Funktion nach Dauerregeln §13 überhaupt eine Live-Abnahme verlangt. Erst mit dieser Bestätigung gilt das Modul als abgeschlossen.
- Auf macOS gilt für die native Plattformabnahme die Auslöseregel der Dauerregeln §14 (geänderter plattformspezifischer Pfad, nicht mehr übertragbare frühere Abnahme, anstehender Release-Smoke). Eine pauschale Wiederholung beider Spalten nach jedem Block ist nicht mehr verbindlich; die Matrix (15 §7) bleibt das Format für die dann tatsächlich verlangten Zeilen.
