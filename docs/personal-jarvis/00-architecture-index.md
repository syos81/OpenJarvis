---
Status: erläuternd
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: — (Navigationsdokument; Normenhierarchie siehe 01 §2)
Zugehörige ADRs: ADR-0001 bis ADR-0014 (Übersicht)
Verwandte DEC-Einträge: siehe decisions-register.md
---

# 00 — Architektur-Index Personal Jarvis

Dieses Dokument ist **nicht normativ**. Es dient der Navigation durch den Architektur-Dokumentenkorpus der freigegebenen **Architektur-Baseline v3** (Freigabe 2026-07-27) für „Personal Jarvis auf OpenJarvis-Basis" im Repository-Fork (Branch `jarvis/rebuild-v1`, Baseline-Tag `openjarvis-baseline-2026-07-27`).

## 1. Dokumentenkorpus

| Nr. | Dokument | Status | Inhalt |
|---|---|---|---|
| 00 | [Architektur-Index](00-architecture-index.md) | erläuternd | Navigation, Lesereihenfolge |
| 01 | [Architekturverfassung](01-architecture-constitution.md) | **normativ (oberste Norm)** | AV-1–AV-37, geschützte Bereiche, ADR-Verfahren, Normenhierarchie |
| 02 | [OpenJarvis-Bestandskarte](02-openjarvis-boundary-map.md) | normativ | Nutzung/Kapselung/Deaktivierung des Upstream-Bestands, Pick-Kriterien |
| 03 | [Systemkontext](03-system-context.md) | erläuternd | Kontextdiagramm, Schichten, Prozessmodell |
| 04 | [Bootstrap & Runtime-Ports](04-bootstrap-and-runtime-ports.md) | normativ | PersonalCompositionRoot, Port-Bündel |
| 05 | [Command- & ActionPipeline](05-command-and-action-pipeline.md) | normativ | Einheitlicher Schreibpfad, Pipeline, Kontexte, Verifikationszustände |
| 06 | [Datenhoheit & Speicher-Register](06-data-ownership-and-storage-register.md) | normativ | Kanonizität, Speicher-Register, Begriffsmodell, Verknüpfungen/Merge |
| 07 | [Persistenz, Transaktionen & Migrationen](07-persistence-transactions-and-migrations.md) | normativ | ConnectionFactory, UnitOfWork, Ein-Writer, globales Migrationsmodell |
| 08 | [Provider-, Konto- & Adaptermodell](08-provider-account-and-adapter-model.md) | normativ | Provider/Account/Binding/Collection, Adapterverträge, Apple-native |
| 09 | [Sicherheit, Authentifizierung & Credentials](09-security-authentication-and-credentials.md) | normativ | Installationsgeheimnis, Session-Tokens, CredentialStore |
| 10 | [Risiko, Approvals, Audit & R2](10-risk-approvals-audit-and-r2.md) | normativ | R0/R1/R2, Approval-Lifecycle, RiskEngine, Audit-Bedrohungsmodell |
| 11 | [Sync, Outboxes, Events & Konflikte](11-sync-outboxes-events-and-conflicts.md) | normativ | Drei Warteschlangen, Domain Events, Sync/Konflikte, Referenzabläufe |
| 12 | [Egress & Modell-Sicherheit](12-egress-and-model-security.md) | normativ | Fail-closed-Egress, Sensitivitätsklassen, Antwortbehandlung |
| 13 | [Backup, Recovery & Audit-Checkpoints](13-backup-recovery-and-audit-checkpoints.md) | normativ | Schlüsselarchitektur, SnapshotCoordinator, Restore, Checkpoints |
| 14 | [UI & Modul-Lifecycle](14-ui-and-module-lifecycle.md) | normativ | Build-time-Registrierung, Readiness, Zustandsmaschine |
| 15 | [Tests & Quality-Gates](15-testing-and-quality-gates.md) | normativ | Testtaxonomie, Gates, Toolchain, Konformitätsprüfung |
| 16 | [Modulkarte](16-module-map.md) | normativ | 15 Module ohne Reihenfolge, Basis, Startkriterien |
| 17 | [Deferred Decisions](17-deferred-decisions.md) | normativ | 16 vertagte Entscheidungen, Vorwegnahme-Verbot |
| 18 | [Upstream-Abweichungen](18-upstream-deviations.md) | normativ | Abweichungsliste mit ADR-/Test-Pflicht |
| 19 | [Definition of Done](19-definition-of-done.md) | normativ | Vollständigkeitskriterien je Modul |
| — | [Glossar](glossary.md) | normativ (Terminologie) | Einzige Definitionsquelle verbindlicher Begriffe |
| — | [Entscheidungsregister](decisions-register.md) | normativ (Index) | Akzeptierte und vertagte Entscheidungen |
| — | [Traceability-Matrix](traceability-matrix.md) | normativ (Index) | AV-Regel → Primärdokument → Testtyp → Durchsetzungsstelle |

ADRs: [docs/adr/](../adr/) — ADR-0001 bis ADR-0014, alle im Status `accepted` (ADR-0001–0012: Baseline-Rückdokumentation; ADR-0013/0014: eigene ADRs der Upstream-Abweichungen DEV-1/DEV-2).

## 2. Lesereihenfolge

Empfohlener Einstieg: 01 (Verfassung) → 03 (Kontext) → 04–05 (Laufzeit und Ausführungspfad) → 06–08 (Daten und Provider) → 09–13 (Sicherheit) → 14–16 (UI und Module) → 17–19 (Offenes, Abweichungen, DoD).

## 3. Kennungen und Verweise

- **AV-x** — Regel der Architekturverfassung (01).
- **ADR-xxxx** — Architecture Decision Record (docs/adr/).
- **DEC-nnn / DEC-Dnn** — akzeptierte bzw. vertagte Entscheidung (decisions-register.md, 17).
- **„NN §M"** — Dokumentnummer und Abschnitt in diesem Korpus.

Jede verbindliche Regel steht genau einmal in ihrem Primärdokument (siehe traceability-matrix.md); alle anderen Stellen verweisen. Bei Widersprüchen gilt die **Normenhierarchie in 01 §2**.

## 4. Hinweise

- `docs/` ist zugleich mkdocs-Quellverzeichnis der Upstream-Dokumentation. Dieser Korpus ist **nicht** in `mkdocs.yml` aufgenommen; `mkdocs.yml` bleibt unverändert. Sollte der Branch je in einen Docs-Build oder Deploy geraten, ist zuvor eine Ausschluss-Entscheidung zu treffen.
- Die Dokumente materialisieren die im Chat freigegebene Baseline v2+v3. Nach freigegebener Materialisierung sind **diese Repo-Dokumente** die maßgebliche Referenz.
- Spätere Modulunterlagen entstehen je Modul unter `docs/personal-jarvis/modules/<modul>.md` (Konvention in 16 §5, Pflicht in 19); das Verzeichnis wird erst mit dem ersten Modul angelegt.
