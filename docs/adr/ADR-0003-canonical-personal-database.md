---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-11, AV-12, AV-13, AV-15, AV-16, AV-37
Zugehörige ADRs: ADR-0007, ADR-0010
Verwandte DEC-Einträge: DEC-004, DEC-019, DEC-020, DEC-022
---

# ADR-0003: Eine kanonische Personal-Datenbank

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Ein persönlicher Assistent hat zahlreiche Beziehungen zwischen Kontakten, Mails, Kalendern, Aufgaben, Dokumenten, Life OS und Trading. Zur Wahl standen eine Datenbank je Fachmodul (Isolationsvorteile) oder eine zentrale kanonische Datenbank (Beziehungsmodell). Upstream-Subsysteme (Sessions, Traces, Telemetrie) besitzen eigene Speicher.

## Entscheidung

1. **`~/.openjarvis/personal/jarvis.db`** ist die einzige kanonische Datenbank **aller Personal-Fachmodule** (SQLite; 0600; WAL; busy_timeout; `PRAGMA foreign_keys=ON`; versionierte lineare Migrationen; schema_version; keine Secrets).
2. Klare **Tabelleneigentümerschaft je Modul**, Repository-/Service-Grenzen, keine unkontrollierten Fremdzugriffe; modulübergreifende Abläufe in einer UnitOfWork-Transaktion (07).
3. **Getrennt bleiben:** semantischer Suchindex, Dokumentdateien (Blob-Store), Marktdaten-Cache, technische Traces, Temporäres; OpenJarvis-Memory ist abgeleiteter Index, nie kanonische Wahrheit. Jeder Speicher steht im **Speicher-Register** (06 §2).
4. Upstream-Subsysteme behalten zunächst ihre Speicher; **Chatverläufe werden langfristig in die Personal-Datenhoheit überführt** (Richtung entschieden, Zeitpunkt DEC-D08).
5. **Globales Migrationsmodell** (monotone IDs, Eigentümer, Abhängigkeiten, Prüfsummen-Ledger, Unveränderlichkeit, Backup-Barriere, fail-closed, forward-only; 07 §6).
6. Verknüpfungen und Zusammenführungen laufen über die Basis-Infrastruktur (ResourceLink, EntityAlias/MergeRedirect, azyklisch; 06 §5).

## Geprüfte Alternativen

- **Eine SQLite-DB je Fachmodul** — verworfen (Eigentümer-Entscheid): App-Level-Joins über alle Beziehungen, Migrations-/Backup-Zersplitterung; Isolationsvorteile wiegen das Beziehungsmodell nicht auf.
- **Gemeinsame DB ohne Eigentums-/Vertragsgrenzen** — verworfen: unkontrollierte Kopplung.
- **Externes DBMS (z. B. Postgres)** — verworfen: schwere Abhängigkeit, widerspricht schlankem Local-first-Betrieb.

## Konsequenzen

Beziehungen sind referenzintegritätsfähig; ein Schreibpunkt erfordert Ein-Writer-Disziplin (serve.lock, kurze Transaktionen, Worker nur im Serve-Prozess); Migrationen brauchen globale Koordination (Ledger); Backup/Restore wird über den SnapshotCoordinator mehr-speicher-konsistent (ADR-0010).

## Verweise

Primärdokumente: 06, 07. Regeln: AV-11–AV-16, AV-37.
