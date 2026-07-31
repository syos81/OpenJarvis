---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-11, AV-12 (Eigentums-Anteil), AV-15, AV-16
Zugehörige ADRs: ADR-0003
Verwandte DEC-Einträge: DEC-004, DEC-011, DEC-019, DEC-020
---

# 06 — Datenhoheit und Speicher-Register

## §1 Kanonizität

`~/.openjarvis/personal/jarvis.db` ist die **einzige kanonische Datenbank für alle Personal-Jarvis-Fachmodule** (AV-11). OpenJarvis-eigene technische Subsysteme behalten zunächst ihre Speicher. Memory und Suchindizes sind **ausschließlich abgeleitet und jederzeit vollständig neu aufbaubar** (AV-16); OpenJarvis-Memory ist nie kanonische Wahrheit.

## §2 Speicher-Register (verbindlich)

| Speicher | Kanonisch für | Eigentümer | Art | Backup | Migration |
|---|---|---|---|---|---|
| `personal/jarvis.db` | alle Fachmodul-Entitäten, Approvals, Audit, Outboxes, SyncState, Links | jeweiliges Fachmodul / Basis | fachlich | **ja (primär)** | — |
| `personal/files/` (Blob-Store) | Dokument-/Anhang-Inhalte (inhaltsadressiert) | Dokumente / Mail | fachlich | **ja** | — |
| macOS-Keychain | Secrets | CredentialStore | fachlich | **nein** (separater R2-Export, 09 §4) | — |
| Upstream `sessions.db` | Chatverläufe/Sessions | Upstream-Chat | **fachlich relevant, technisch verwaltet** | **ja (sekundär)** | **ja, geplant** (§3) |
| Upstream `traces.db`, `telemetry.db` | Agent-Traces, lokale Metriken | Upstream | technisch | nein | nein |
| Upstream `scheduler.db` | technische Job-Registrierungen | Upstream | technisch (aus kanonischen Definitionen re-synchronisierbar) | nein | nein |
| Upstream Memory-/Index-Speicher, Personal-Suchindex | abgeleitete Such-/Kontextdaten | abgeleitet | technisch | nein (Rebuild) | nein |
| Upstream `agents.db`, `optimize.db`, `audit.db` | ruhende Upstream-Subsysteme | Upstream | technisch | nein | nein |
| `config.toml` (+ Personal-Preset) | Konfiguration (ohne Secrets) | Einstellungen | fachlich-technisch | **ja** | — |
| Caches (z. B. Marktdaten, Skill-Cache), Temporäres | flüchtig | jeweilige Quelle | technisch | nein | nein |

Neue Speicher dürfen nur mit Register-Eintrag (Eigentümer, Art, Backup, Migration) entstehen.

**Ergänzung 2026-07-31 (Reuse-Audit, ADR-0020/DEC-044):** Der abgenommene Audit hat weitere faktisch vorhandene Upstream-Speicher belegt, die hier bisher nicht einzeln geführt sind (u. a. `approvals.db`, `digest.db`, `knowledge_graph.db`, `memory_facts.jsonl`, `blobs/`, `embeddings/`, `traces.db`, Frontend-`localStorage`). Ihre Einzelentscheidungen (KEEP/ADAPT/REPLACE/REMOVE) und Retentionpflichten stehen im Register [20](20-openjarvis-reuse-register.md) §4/§7. Vor produktiver Nutzung im Personal-Betrieb sind die als ADAPT/REPLACE markierten Speicher entweder in dieses Register aufzunehmen oder stillzulegen; keiner darf eine zweite fachliche Wahrheit führen (AV-16). `~/.openjarvis/knowledge.db` bleibt ausschließlich **abgeleiteter Projektionszielspeicher** (Zielkomponente Z-1, 20 §5) und erhält je Fachdomäne erst dann wieder Einträge, wenn der kontrollierte Projektionspfad existiert.

## §3 Entscheidung Chatverläufe

Chatverläufe sind fachliche Personal-Daten. Sie **werden langfristig in die Personal-Datenhoheit überführt** — als kanonische Chat-Tabellen, sobald „Chat & Sessions" als Fachmodul vertikal behandelt wird (Migration per dann zu erstellendem ADR; Zeitpunkt = DEC-D08). Bis dahin bleiben sie Upstream-Subsystem und werden im Backup als sekundärer Speicher gesichert (DEC-019).

## §4 Datenhoheits-Grundregeln

1. **Tabelleneigentümerschaft:** Jede Tabelle gehört genau einem Modul; Fremdzugriff nur über dessen Application-/Capability-Services bzw. veröffentlichte Verträge — nie per direktem SQL (AV-12; Transaktionsmechanik in 07).
2. **Externe Identitäten:** je Modul eigene Mapping-Tabellen (`<modul>_external_ids`: Binding/Collection, externe ID, ETag/Version, Sync-Stand) — Grundlage für Idempotenz, Konflikt- und Dublettenerkennung.
3. **Löschen und Historie:** Synchronisierte Entitäten werden soft-deleted (Tombstone bis zur bestätigten Provider-Löschung, danach Purge nach Aufbewahrungsfrist); merge-/undo-fähige Module führen eine Entitätshistorie; jede R1/R2-Mutation steht zusätzlich im Audit. Backups respektieren Löschungen — kein Wiederauferstehen außer durch expliziten Restore.
4. **Konventionen:** kanonische IDs als UUIDv7; Zeitpunkte in UTC, bei kalendarischen Daten zusätzlich IANA-Zeitzone am Datensatz (DEC-020; Persistenzdetails in 07).
5. Kanonische Entitäten je Modul: siehe Modulkarte 16 §2 (Single Source dort).

## §5 Verknüpfungsinfrastruktur (Basis-Eigentum)

- **ResourceIdentity:** typisierte kanonische Adresse jeder Entität (`resource_type` + UUIDv7).
- **ResourceLink:** gerichtete, typisierte Kante (from, to, LinkType, Metadaten, erstellendes Modul, Zeitpunkt) — Eigentümer: **Basis**; Module registrieren ihre LinkTypes (z. B. `about_contact`, `attached_to`, `relates_to`). Beziehungen zwischen Kontakten, Mails, Dokumenten, Terminen, Aufgaben u. a. hängen damit an keinem Fachmodul.
- **EntityAlias / MergeRedirect — azyklisch per Konstruktion:** `entity_alias(old_id → canonical_id)` mit `old_id` als Primärschlüssel, Constraint `old_id ≠ canonical_id` und Service-Regel: Vor dem Einfügen wird das Ziel **bis zur terminalen ID aufgelöst** — Aliase zeigen immer auf terminale kanonische IDs (Wald, keine Zyklen). Maximale Kettenlänge als Resolver-Schranke (Verletzung ⇒ Integritätsfehler, `attention_required`); **Path Compression** bei erfolgreicher Auflösung; Schreibpfade normalisieren opportunistisch auf die kanonische ID.
- **MergeRecord (unveränderlich):** vollständige Quell-Snapshots, Zielzustand, feldweise Entscheidung, Akteur, Zeitpunkt, geplante Provider-Folgen; append-only, audit-verknüpft.
- **Undo ohne Rückwärts-Redirect:** Undo erzeugt eine **neue kanonische Entität** aus dem Quell-Snapshot plus ein explizites **Reversal Event** (Referenz auf den MergeRecord); bestehende Aliase bleiben historisch wahr; Links werden — soweit im MergeRecord dem Quell-Datensatz zugeordnet — durch die Reversal-Routine als neue, auditierte Schreibvorgänge umgehängt. **Externe Provider-Identitäten werden je Provider/Binding separat behandelt** (per-Binding-Reversal-Plan).
- **Merge-Zustandsfolge:** `merge_proposed → approved → merged_locally → provider_sync_pending → synchronized | partially_synchronized → (optional) reversed`; `partially_synchronized` benennt je Binding den Ist-Zustand (Sync-Mechanik: 11).

## §6 Begriffsmodell Workspace / Rolle / Tag / Organisation / Identität / Beziehung

*Dieser Abschnitt beschreibt ausschließlich die Modellsemantik und die Beziehungen dieser Begriffe zueinander. Die verbindlichen Begriffsdefinitionen stehen allein in [glossary.md](glossary.md); hier wird keine konkurrierende Definition geschaffen.*

- **Workspace** — konfigurierbarer Kontextraum (Beispiele: Privat, Arbeit, Hausverwaltung), Filter- und Berechtigungsdimension; **nie hart codiert** (DEC-011). Initiale Belegung: DEC-D15.
- **Rolle** — Funktion eines Kontakts **innerhalb** eines Workspace (Beispiele: Familie, Freund, Kollege, Mieter, Eigentümer, Vermieter, Dienstleister, Auftraggeber); ein Kontakt kann gleichzeitig mehrere Rollen in mehreren Workspaces besitzen.
- **Tag** — freies, nicht berechtigungswirksames Etikett.
- **Organisation** — eigene Entität mit Mitgliedschaften.
- **Externe Identität** — Provider-Repräsentanz einer kanonischen Entität (§4 Nr. 2).
- **Beziehung** — typisierte, gerichtete Kante zwischen zwei Ressourcen (§5) mit Eigentümer beim definierenden Modul.
