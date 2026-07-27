---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-12 (Transaktions-Anteil), AV-13, AV-21 (Ein-Writer-Anteil), AV-37
Zugehörige ADRs: ADR-0003
Verwandte DEC-Einträge: DEC-004, DEC-020, DEC-022
---

# 07 — Persistenz, Transaktionen und Migrationen

## §1 DatabaseConnectionFactory

Einzige Stelle, die Verbindungen zu `personal/jarvis.db` erzeugt. Sie erzwingt je Verbindung: Prüfung der Dateirechte 0600, WAL-Modus, `busy_timeout`, `PRAGMA foreign_keys=ON`. Kein anderer Codepfad öffnet die kanonische Datenbank.

## §2 UnitOfWork-Vertrag

Ein Orchestrator öffnet eine UnitOfWork (Transaktionskontext); Repositories werden mit dieser UoW instanziiert und arbeiten auf derselben Verbindung; Commit/Rollback erfolgt genau einmal am Ende. Transaktionen sind kurz; **langlaufende externe Aktionen laufen nie in der SQLite-Transaktion**, sondern über Outbox und Zustandsmaschinen (11).

## §3 Repository-Grenzen und Application Orchestrator

- Jedes Modul bleibt Eigentümer seiner Tabellen und veröffentlicht **Repository-Verträge (Interfaces)** in einem `contracts`-Bereich; konkrete Implementierungen sind modulprivat.
- **Kein Modul importiert fremde Implementierungen** — die Auflösung geschieht ausschließlich in der PersonalCompositionRoot (Constructor Injection, 04 §1).
- **Application Orchestrator** (Basis-Konzept): Modulübergreifende Use-Cases (z. B. Kontakt-Zusammenführung mit Link-Umbau) koordinieren mehrere Repository-**Verträge** in **einer** UoW.

## §4 Datenkonventionen

Kanonische IDs: UUIDv7. Zeitstempel: UTC; kalendarische Daten tragen zusätzlich die IANA-Zeitzone am Datensatz (DEC-020).

## §5 Nebenläufigkeit und Prozessmodell

- Schreib-Worker (Sync, R1-Executor, DomainEvent-Dispatcher, Reconciler, R2-Executor) laufen **ausschließlich im Serve-Prozess**.
- Die CLI schreibt bei laufendem Server über die API; ohne Server im begrenzten In-Process-Modus (05 §2) — in beiden Fällen über denselben CommandBus.
- **Zweiter Schreibprozess ausgeschlossen:** exklusive Lock-Datei `personal/serve.lock` (fcntl-Lock; Inhalt PID + Port + Startzeit; Stale-Erkennung per PID-Prüfung). Die Lock-Datei dient CLI und Tauri zugleich zur Port-Discovery. Der In-Process-Modus erwirbt dieselbe Sperre.
- Sync-Jobs sind je (Konto × Collection) single-flight; WAL erlaubt parallele Leser.

## §6 Globales Migrationsmodell

Da alle Fachmodule dieselbe `jarvis.db` verwenden, gilt (AV-37):

1. **Globale, monotone Migration-ID** über alle Module hinweg; jede Migration trägt: ID, **Modul-Eigentümer**, Beschreibung, explizite `depends_on`-Liste (nur ≤ eigene ID; beim Lauf validiert), **Prüfsumme des Inhalts**.
2. **Migrations-Ledger** in der Datenbank: angewandte ID, Prüfsumme, Zeitpunkt, Softwareversion. Beim Start wird der Ledger verifiziert; unbekannte angewandte IDs oder Prüfsummen-Abweichungen ⇒ **fail-closed** (Personal nicht verfügbar, Diagnose, Restore-Anleitung).
3. **Veröffentlichte Migrationen sind unveränderlich** (Prüfsumme erzwungen; Korrektur = neue Migration).
4. **Backup-Barriere vor jeder Migrationsausführung** (Snapshot mindestens der betroffenen Speicher über den SnapshotCoordinator, 13 §3).
5. **Nur Vorwärtsmigrationen;** kein automatischer Downgrade wird versprochen — die getestete Rückfallstrategie ist der Restore des Vor-Migrations-Backups (13 §4).
6. **Modul-Deaktivierung:** Tabellen und Daten bleiben erhalten; keine automatische destruktive Deinstallation. Explizite Datenlöschung eines Moduls ist eine eigene, irreversible Operation und damit **R2** (10).
