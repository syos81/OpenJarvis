---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-2 (Primärdokument), AV-3, AV-26, AV-28
Zugehörige ADRs: ADR-0012
Verwandte DEC-Einträge: DEC-018
---

# 19 — Definition of Done (vollständig abgeschlossenes Modul)

Ein Fachmodul gilt erst dann als **vollständig abgeschlossen**, wenn sämtliche folgenden Kriterien erfüllt und nachgewiesen sind. Erst danach beginnt das nächste Modul (AV-2). Kein Kriterium darf durch Platzhalter, Mocks oder Scheinimplementierungen in produktiven Pfaden erfüllt werden (AV-3).

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
- **Live-Abnahme** gegen einen echten Provider-Account bestanden und protokolliert (Anbieter gemäß DEC-D11; AV-26).

## §4 Rechte und Sicherheit

- Capability-/Workspace-Prüfungen aktiv; Credentials ausschließlich über den CredentialStore (09 §4).
- Egress-Labels des Moduls registriert; Egress-Tests grün (12).
- Für R1: Vorschau + Bestätigung + Audit + Ergebnisverifikation nachgewiesen. Für R2 zusätzlich: ApprovalIntent-Fluss, RiskEngine-Regeln, Recheck, Not-Aus, unveränderliche Protokollierung (10).

## §5 UI

- Vollständiges, gekapseltes Modul-Frontend (14 §1–2): echte Navigationssichtbarkeit nur in erlaubten Zuständen, vollständiger Einrichtungsfluss falls `configuration_required` sichtbar sein soll, Status-/Fehlerflächen, keine leeren Menüpunkte.
- Kontenverwaltungs-Slice für die Provider des Moduls (Bindings, Collections, Re-Auth).

## §6 Fehlerfälle

- Zustandsmaschinen (Verifikation, ggf. Mail, Konflikte, Circuit-Breaker) implementiert und getestet (11); `attention_required`-Pfade sichtbar; Offline-Verhalten definiert.

## §7 Tests

- Alle einschlägigen Suiten aus 15 §1 grün (Unit, Contract, Integration, Migration, Security, Zustandsmaschinen, native macOS soweit betroffen, UI-E2E, Kill-Switch/Sperren soweit betroffen).

## §8 Betrieb und Daten­sicherheit

- Moduldaten sind von der Snapshot-Registrierung erfasst; Restore-Roundtrip mit Moduldaten nachgewiesen (13).
- Scheduler-/Automation-Anteile idempotent re-registrierbar (04 §2 SchedulerPort).

## §9 Dokumentation und Register

- Modulunterlage `docs/personal-jarvis/modules/<modul>.md` erstellt (16 §5).
- Entscheidungsregister und Traceability-Matrix für berührte Zeilen aktualisiert; Glossar um neue verbindliche Begriffe ergänzt.
- Keine Deferred Decision vorweggenommen (17 §1); berührte Deferred Decisions sind vor Baubeginn entschieden worden.

## §10 Abschluss

- Live-Abnahme-Protokoll durch den Eigentümer bestätigt. Erst mit dieser Bestätigung gilt das Modul als abgeschlossen.
