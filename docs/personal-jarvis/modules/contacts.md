---
Status: normativ (Modulunterlage, 16 §5)
Architektur-Baseline: v3
Freigabedatum: 2026-07-28
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-2, AV-3, AV-4, AV-9, AV-11, AV-14, AV-26, AV-29, AV-33, AV-35, AV-37
Zugehörige ADRs: ADR-0001, ADR-0003, ADR-0005, ADR-0006, ADR-0007, ADR-0012, ADR-0015, ADR-0016, ADR-0018
Verwandte DEC-Einträge: DEC-004, DEC-012, DEC-020, DEC-030, DEC-031, DEC-038, DEC-041, DEC-042, DEC-043; offen: DEC-D17
---

# Modul „Kontakte" — produktiver Implementierungsplan

**Dieses Dokument plant die Umsetzung. Es trifft keine neue Architekturentscheidung und ändert keine bestehende.** Bei jedem Widerspruch gelten die normativen Dokumente 01–19 und die ADRs.

---

## §1 Ausgangsstand

| Größe | Wert |
|---|---|
| Branch / HEAD | `jarvis/rebuild-v1` @ `1c6e7223`, synchron mit origin |
| Erstes Fachmodul | Kontakte (DEC-030) |
| Native Bridge | Swift-Sidecar mit eng begrenztem Objective-C-Shim (ADR-0016, DEC-031) |
| Zielarchitekturen | arm64 **und** x86_64, gleichwertig, ab macOS 12.3 (ADR-0018, DEC-042) |
| Spike G3a | auf arm64 bestanden, kein Kill-Kriterium (DEC-043); Abnahmestand: 15 §8 |
| Intel-Live-Abnahme | offen |
| Notizen | ohne besonderes Entitlement **nicht** zugesagt (08 §4) |
| Link/Unlink unified | **nicht** als mutierende Capability zugesagt (08 §4) |
| DEC-D17 | offen — Auslieferungsformat |
| Entwicklungsform | vertikal, ein Modul (ADR-0012, 19) |

**Verifizierte Repository-Fakten, auf denen dieser Plan aufbaut:**

1. Es existiert **kein** `personaljarvis`-Paket. Alles Personal-seitige ist neu.
2. Der editierbare Install legt `<repo>/src` direkt in `sys.path` (`_editable_impl_openjarvis.pth`). Ein neues Top-Level-Paket `src/personaljarvis/` ist damit importierbar, **ohne** `[tool.hatch.build.targets.wheel]` zu ändern — genau die Grenze aus DEV-5.
3. `src/openjarvis/server/app.py` besitzt eine App-Factory `create_app()` mit `include_router(...)`-Kette (Zeilen 309–316) — der eine bewachte Integrationspunkt aus 04 §4 hat dort seinen Platz.
4. Das Frontend nutzt React Router (`frontend/src/App.tsx:186–196`), Zustand (`frontend/src/lib/store.ts`), einen zentralen API-Client (`frontend/src/lib/api.ts` mit `apiFetch`/`authHeaders`/`getBase`) und eine statische Navigationsliste (`frontend/src/components/Sidebar/Sidebar.tsx:56–62`).
5. Tauri kennt genau **einen** Sidecar-Präzedenzfall (Ollama) mit `binaries/`-Verzeichnis, `.gitignore` für heruntergeladene Binaries und `scripts/download-ollama.sh`.
6. `frontend/src-tauri/capabilities/default.json` erlaubt heute pauschal `shell:allow-execute`/`spawn`/`stdin-write`/`kill` plus einen Sidecar-Scope für `binaries/ollama`.
7. Der Rust-Workspace liegt unter `rust/crates/`; `rust/` ist der Präzedenzfall für ein nicht-Python-Top-Level-Verzeichnis.

## §2 Scope — was zum produktiven Modul gehört

Kanonische Contacts-Domäne · SQLite-Persistenz in `personal/jarvis.db` · Migrationen nach dem globalen Modell · Apple-Contacts-Provider als Erstadapter · Native-Bridge-Client und Sidecar-Prozessmanagement · produktiver JSON-Lines-Vertrag · Autorisierungsstatus (TCC) · Capability-Modell · Initialimport · Delta-Synchronisation über Change-History-Token · Voll-Diff-Fallback · Tombstones · Echo-Unterdrückung · Konfliktmodell · `outcome_unknown` · Create/Update/Delete · Freigaben für mutierende Aktionen · Audit und Logging · Backend/API · Benutzeroberfläche · Fehler- und Randfälle · Tests · Packaging · Abnahme auf arm64 **und** x86_64.

Zusätzlich im Scope, weil das Modul es zwingend braucht (AV-33, Basis nach 16 §3): DatabaseConnectionFactory, UnitOfWork, Migrations-Ledger, PersonalCompositionRoot, ApplicationCommandBus, ActionPipeline, AuditTrail, ExternalActionOutbox, DomainEventOutbox, Approval-Kern (R1), CredentialStore-Anbindung, Installations-/Session-Token-Auth, Backup-Kern-Registrierung. **Nur in dem Umfang, den Kontakte tatsächlich benötigt** — kein Vorratsbau.

## §3 Nicht-Scope

- **Notizen als produktive Fähigkeit.** `notesSupported=false`; kein Entitlement ohne eigenen ADR. Ein nicht lesbares Notizfeld wird **nie** als leere Notiz gespeichert oder gesendet.
- **Link/Unlink vereinheitlichter Kontakte** als mutierende Capability.
- Private oder undokumentierte Apple-APIs.
- Unkontrollierte automatische Mutationen; jede Mutation ist vorgangsgebunden und freigegeben.
- Globaler Cleanup nach Namenspräfix oder Suchmuster — in keiner Form, auch nicht in Tests gegen den produktiven Store.
- **Ein zweites Fachmodul.** Kein Kalender-, Mail- oder Aufgabenanteil, auch nicht vorbereitend.
- R2-Executor und RiskEngine (Kontakte enthält keine R2-Operation außer der Modul-Datenlöschung, die nicht Teil dieses Moduls ist).
- Dubletten-**Auto**-Merge. Der Merge-Ablauf (11 §6 Nr. 3) wird in diesem Modul **nicht** materialisiert; er braucht Referenzen aus weiteren Modulen. Der Datenbestand wird jedoch merge-fähig entworfen (§5).
- Änderung des Auslieferungsformats (DEC-D17). Während der Entwicklung wird je Architektur gebaut — das ist Arbeitsweise, keine Vorentscheidung.

## §4 Traceability

| Entscheidung | Produktive Komponente | Erwartete Dateien | Tests | Live-Abnahme |
|---|---|---|---|---|
| ADR-0001 / DEC-003 (Runtime-Fassade) | `PersonalJarvisRuntime`-Ports + OJRA | `src/personaljarvis/runtime/ports/*.py`, `runtime/ojra.py` | Port-Contract-Suite | — |
| ADR-0003 / DEC-004 (kanonische DB) | ConnectionFactory, UoW | `src/personaljarvis/base/db/factory.py`, `unit_of_work.py` | Rechte-, Pragma-, WAL-Test | — |
| AV-37 / 07 §6 (globales Migrationsmodell) | Ledger + Runner | `base/db/migrations/runner.py`, `ledger.py`, `versions/` | Migrationstests, Prüfsummen-Fehlversuch | — |
| ADR-0005 / DEC-013 (CommandBus, eine Schreibspur) | CommandBus + ActionPipeline | `base/command_bus.py`, `base/pipeline/*.py` | „Kein zweiter Schreibpfad"-Test | — |
| ADR-0006 / DEC-005 (Risikoklassen) | R0/R1-Klassifizierung je Operation | `contacts/application/commands.py` | Klassifizierungstest je Operation | — |
| ADR-0007 / DEC-014 (Outboxes) | ExternalActionOutbox, DomainEventOutbox | `base/outbox/*.py` | Transaktions-, Idempotenz-, Retry-Test | — |
| ADR-0016 / DEC-031 (Swift-Sidecar) | Sidecar + Bridge-Client | `native/contacts-bridge/**`, `contacts/bridge/*.py` | Protokoll-Contract gegen Fake **und** echt | arm64, x86_64 |
| ADR-0016 Pkt. 4 (Dünnheit) | Sidecar ohne Fachlogik | `native/contacts-bridge/src/*.swift` | Struktur-/Review-Test: keine Normalisierung im Sidecar | — |
| ADR-0018 / DEC-042 (Dual-Arch) | Build je Architektur, `minimumSystemVersion 12.3` | `native/contacts-bridge/build.sh`, `frontend/src-tauri/tauri.conf.json` | Build-Matrix-Test, `minos`-Assertion | beide Spalten 15 §8 |
| ADR-0012 / DEC-018 (vertikal) | ein zusammenhängender Zug | dieses Dokument, §11 | Gate-Abschlusskriterien | — |
| ADR-0015 / DEC-041 (DEV-4/DEV-5) | Nav-Eintrag, Route, Session-Token-Kommando, `[dependency-groups] personal` | `frontend/src/App.tsx`, `Sidebar.tsx`, `src-tauri/src/lib.rs`, `pyproject.toml` | Readiness-Sichtbarkeit, App identisch ohne Personal, Standard-Auflösung unverändert | — |
| DEC-020 (Konventionen) | Namensraum `personaljarvis`, Präfix `/v1/personal/`, UUIDv7, UTC+IANA | durchgehend | ID-/Zeit-Konventionstest | — |
| DEC-038 (Live-Abnahme im Testbenutzer) | Abnahmeprotokoll | `docs/testing/` (neu, je Architektur) | — | `jarvisspike`, beide Architekturen |
| DEC-043 (Spike-Abnahme) | Startfreigabe, kein PyObjC | dieses Dokument | — | — |
| 08 §4 Capability-Grenzen | `notesSupported=false`, kein Link/Unlink | `contacts/domain/capabilities.py` | Capability-Discovery-Test, „Notiz nie leer"-Test | — |
| 12 §1 (Egress-Labels) | S0/S1/S2 je Kontaktfeld | `contacts/domain/labels.py` | Egress-Guard-Test | — |
| 14 §4 (Lifecycle) | Modulzustandsmaschine | `contacts/lifecycle.py` | Zustandsübergangstests | — |
| 13 (Backup) | Snapshot-Registrierung | `base/backup/registry.py` | Restore-Roundtrip | beide Architekturen |
| **DEC-D17 (offen)** | — | — | — | **wird nicht entschieden** |

## §5 Kanonisches Datenmodell

Alle Tabellen gehören dem Modul Kontakte, liegen in `personal/jarvis.db`, IDs sind UUIDv7, Zeitstempel UTC (07 §4).

### §5.1 Kerntabellen

**`contacts`** — PK `id` (UUIDv7). Spalten: `workspace_id` · `contact_type` (`person|organization`) · `given_name` · `middle_name` · `family_name` · `previous_family_name` · `name_prefix` · `name_suffix` · `phonetic_given_name` · `phonetic_family_name` · `nickname` · `display_name` (abgeleitet, deterministisch im Kern erzeugt — **nicht** vom Sidecar) · `organization_name` · `department_name` · `job_title` · `is_me_card` (Bool) · `birthday_year`/`birthday_month`/`birthday_day` (je NULL-fähig; ein Geburtstag ohne Jahr ist gültig) · `image_available` (Bool) · `thumbnail_blob_ref` (NULL-fähig, Verweis in den Blob-Store, **kein** Base64 in der DB) · `created_at` · `updated_at` · `deleted_at` (NULL-fähig) · `is_tombstone` (Bool). Index auf (`workspace_id`, `is_tombstone`), auf `display_name`, auf `updated_at`.

**Kindtabellen, normalisiert** (je PK `id`, FK `contact_id` ON DELETE RESTRICT, `position` für stabile Reihenfolge, `label_raw` und `label_normalized`):
`contact_emails` (`value_raw`, `value_normalized`) · `contact_phones` (`value_raw`, `value_normalized_e164` NULL-fähig) · `contact_postal_addresses` (`street`, `city`, `state`, `postal_code`, `country`, `iso_country_code`) · `contact_dates` (`kind`, `year`/`month`/`day`) · `contact_url_addresses` · `contact_social_profiles` (`service`, `username`, `url`) · `contact_instant_messages` (`service`, `username`).
Unique-Index je (`contact_id`, `position`) gegen Doppel-Einfügungen. **Korrektur 2026-07-28 (Gate-A-Audit):** Der ursprünglich vorgesehene Wert-Unique je (`contact_id`, `kind`, `value_normalized`) entfällt — Apple erlaubt denselben Wert unter mehreren Labels auf einer Karte, ein Wert-Unique machte einen gültigen Provider-Zustand unspeicherbar (im Audit reproduziert; Migration 0003). Wertgleichheit innerhalb eines Kontakts ist Fachlogik (Dubletten-Kandidaten), kein Constraint. **Kein** globales Unique — Dubletten über Kontakte hinweg sind ein Fachfall, kein Constraint (11 §3: nie Auto-Merge).

**`contact_roles`** (16 §2) — (`contact_id`, `workspace_id`, `role`), PK zusammengesetzt. `role` ist die produktive Grundlage der UI-Kategorien **Privat · Arbeit · HV · Mieter · Vermieter** (§10). Rollen sind lokal, werden **nie** zum Provider gepusht.

**`contact_relations`** (16 §2) — typisierte Beziehung (`from_contact_id`, `to_contact_id` NULL-fähig, `relation_type`, `label_raw`, `target_name_raw`). Apple liefert Beziehungen als freien Text; ein nicht auflösbarer Bezug bleibt als `target_name_raw` erhalten und wird **nicht** geraten.

**`organizations`** + `organization_memberships` (16 §2) — kanonische Organisation getrennt vom Freitext `organization_name`; die Verknüpfung entsteht nur durch bestätigte Nutzeraktion.

**`contact_external_ids`** — (`contact_id`, `provider_account_id`, `container_identifier`, `provider_identifier`, `unified_identifier` NULL-fähig, `provider_revision`, `key_set_version`, `last_seen_at`). Unique auf (`provider_account_id`, `provider_identifier`). **`unified_identifier` ist ausschließlich lesend** und wird nie als Schreibziel verwendet (belegte Identifier-Instabilität, Spike `getUnified`).

**`contact_field_availability`** — (`contact_id`, `field`, `state`) mit `state ∈ {present, absent, unavailable_by_capability}`. **Der einzige Ort, an dem „Notiz nicht lesbar" von „Notiz leer" unterschieden wird.** Für `note` steht dort dauerhaft `unavailable_by_capability`, solange `notesSupported=false`. Kein Sync-, Diff- oder Konfliktpfad darf ein Feld im Zustand `unavailable_by_capability` als leer behandeln.

### §5.2 Sync- und Herkunftsfelder

In `contact_external_ids` bzw. `contacts`: `provider_revision` (Provider-Stand) · `local_revision` (monoton je Kontakt, lokal) · `source_updated_at` · `imported_at` · `last_seen_at` · `deleted_at` · `is_tombstone` · `sync_state` (`in_sync | local_pending | remote_pending | conflicted | attention_required`) · `conflict_state` · `last_mutation_id` · `last_approval_id` · `last_audit_id` · `field_completeness` (`full | partial`, mit Verweis auf `contact_field_availability`).

**`contacts_sync_state`** — je (`provider_account_id`, `container_identifier`): `cursor_token` (opak, Base64 der Change-History) · `cursor_taken_at` · `last_full_diff_at` · `key_set_version` · `mode` (`delta | full_diff_required`) · `circuit_state`.

**`contacts_tombstones`** — (`provider_account_id`, `provider_identifier`, `deleted_at`, `reason`, `retain_until`). Aufbewahrung mindestens bis zur bestätigten Provider-Löschung, danach nach Aufbewahrungsregel; eingehende Syncs prüfen gegen Tombstones (kein Wiederauferstehen, 11 §3).

**`contacts_mutations`** — (`mutation_id` UUIDv7, `command`, `target_contact_id`, `target_provider_identifier`, `idempotency_key`, `approval_id`, `state`, `outcome`, `created_at`, `settled_at`). `outcome ∈ {succeeded, failed, outcome_unknown}`. **Ein Datensatz mit `outcome_unknown` wird nie automatisch weiterverarbeitet.**

### §5.3 Speicherregeln

JSON-Spalten werden **nicht** für fachlich abfragbare Felder verwendet; Mehrfachwerte sind normalisiert (Suche, Dubletten-Kandidaten, Index). JSON ist zulässig für: rohe Provider-Antwort-Digests im Audit und den unveränderlichen Snapshot im MergeRecord. Thumbnails liegen im Blob-Store, nicht in der DB (06 §2).

**Migrationsreihenfolge** (globale monotone IDs, Eigentümer `contacts` bzw. `base`, mit `depends_on` und Prüfsumme, 07 §6): `base` — Ledger, Audit, Outboxes, Approvals, SyncState-Rahmen, ResourceIdentity/ResourceLink, EntityAlias · dann `contacts` — Kern, Kindtabellen, Rollen, Relationen, Organisationen, externe IDs, Feldverfügbarkeit, Tombstones, Mutationen. Jede Migration ist nach Veröffentlichung unveränderlich; Korrektur ist eine neue Migration.

## §6 Sync-Modell

### §6.1 Initialimport

Autorisierungsprüfung (TCC-Status lesen, **nie** ungefragt anfordern) → Containerinventar → vollständige Enumeration mit fixiertem `key_set_version` → kanonische Normalisierung **im Kern** (der Sidecar normalisiert nicht) → eine UoW je Batch mit Upsert + `contact_external_ids` + DomainEvent + Audit → **Cursor erst nach vollständigem, als `complete:true` bestätigtem Durchlauf** speichern → `last_full_diff_at` setzen.

**Abbruchregel:** Eine Enumeration ohne Abschlussmarker wird **verworfen**. Sie wird nie als Löschmenge interpretiert. Der Lauf beginnt neu; der bisherige Bestand bleibt unangetastet.

### §6.2 Delta-Sync

Gespeicherten Cursor senden → Ereignisse verarbeiten (`add|update|delete|dropEverything|other`) → Echo-Unterdrückung über `transactionAuthor` **und** zusätzlich über `contacts_mutations` (zwei unabhängige Wege, weil `transactionAuthor` erst ab macOS 12 greift und ein Provider ihn nicht garantiert) → Tombstone-Abgleich → Upsert in UoW → **Cursor aus der Antwort persistieren, nicht neu vom Store lesen**.

Zustände von `contacts_sync_state.mode`:

```
delta ──(ungültiger/abgelaufener Token | dropEverything | keySetVersion-Wechsel)──▶ full_diff_required
full_diff_required ──(vollständiger Voll-Diff mit Abschlussmarker)──▶ delta
delta ──(Transportfehler ≥ Schwelle)──▶ circuit_open ──(Half-Open-Probe erfolgreich)──▶ delta
```

`dropEverything` ist ein **legitimes Resync-Signal**, kein Fehler: es führt kontrolliert nach `full_diff_required`, nie zu Löschungen. Prozessabbruch oder unvollständige Antwort lassen den Cursor unverändert — der nächste Lauf wiederholt idempotent.

### §6.3 Voll-Diff-Fallback

Vollständige Enumeration → Vergleich gegen den lokalen Bestand je (`provider_account_id`, `provider_identifier`) → Zuordnung: nur lokal ⇒ Löschkandidat, nur extern ⇒ Neuanlage, beidseitig ⇒ Feldvergleich. **Eine Löschung entsteht ausschließlich aus einem vollständigen Diff mit Abschlussmarker.** Fehlt der Marker, wird der gesamte Lauf verworfen.

## §7 Mutationsmodell

### §7.1 Regeln

Jede Mutation trägt: eine **`mutation_id`**, einen **`idempotency_key`**, eine **`approval_id`**, eine **explizite Ziel-ID** (`provider_identifier`) und den `initiation_context`. Verbindlich:

- **Keine Mutation anhand eines Namens, Präfixes oder Suchmusters.** Ziel ist immer eine zuvor gelesene Identität.
- **Keine Mutation an einem Kontakt, den der Vorgang nicht als Ziel führt.**
- **Kein automatischer Retry bei `outcome_unknown`.**
- **Kein globaler Cleanup.**
- Schreiben auf den `unified_identifier` ist verboten; Ziel ist immer der Rohdatensatz.

### §7.2 Zustandsmaschine je Mutation

**Präzisierung 2026-07-29 (Gate C, verbindlich).** Der Zustandsvorrat ist gegenüber dem ursprünglichen Entwurf geschärft und wortgleich mit dem CHECK-Constraint der Tabelle `contacts_mutations` (Migration 0004) — es gibt genau **eine** Wahrheit:

```
prepared → awaiting_approval → approved → executing → succeeded
                             ↘ rejected                ↘ failed_before_send
                             ↘ expired                 ↘ outcome_unknown
                             ↘ cancelled                     ↓
                                                      reconcile_required
                                                        ↙       ↓        ↘
                                                 succeeded   failed   manual_decision_required
```

Alte Namen des Entwurfs bilden sich ab als: `draft`/`validated`/`previewed` → `prepared` · `pending_approval` → `awaiting_approval` · `verifying` → `executing` · `completed` → `succeeded` · `denied` → `rejected` · `aborted` → `cancelled`.

**Die sicherheitsrelevante Neuerung ist die Trennung von `failed_before_send` und `outcome_unknown`.** Der Entwurf kannte nur `failed` und konnte damit „nachweislich nichts gesendet" nicht von „möglicherweise gesendet" unterscheiden. Nur der erste Fall ist gefahrlos wiederholbar.

**`outcome_unknown` ist weder Erfolg noch Fehlschlag.** Der Übergang nach `reconcile_required` löst **zuerst einen Lesevorgang** aus (Read/Reconcile gegen den Store), bevor irgendetwas anderes geschieht. Bleibt der Ausgang danach unklar, endet der Vorgang in `manual_decision_required` mit `attention_required` in der UI — **niemals** in einer automatischen Wiederholung. `failed` entsteht ausschließlich **nach** einem eindeutigen Abgleich; eine Wiederholung ist dann eine **neue freigabepflichtige Mutation**, kein Retry. **Auch `failed_before_send` ist terminal** (Gate-C-Audit 2026-07-29): dort wurde nachweislich nichts gesendet, aber Vorschau und Freigabe des Vorgangs sind verbraucht — sein Outbox-Eintrag wird geschlossen und erscheint nie wieder als fällig; ein neuer Versuch ist ebenfalls eine neue freigabepflichtige Mutation.

**Präzisierung 2026-08-01 ([ADR-0019](../../adr/ADR-0019-provider-mutation-architecture.md), verbindlich; seit demselben Tag im Code umgesetzt — Migration 0006).** Für die Provider-Implementierung wird der Erfolgspfad um einen Zustand erweitert: `executing → provider_applied_pending_reconcile → succeeded`. Der neue Zustand hält die Zwischenlage „Provideränderung bestätigt und belegt, kanonische Nachführung noch offen" fest; aus ihm ist **nie** ein weiterer Send erlaubt, `recover_interrupted()` fasst ihn nicht an, und die Auflösung läuft ausschließlich über den nutzergestarteten Abgleich. `succeeded` setzt fortan **alle vier** Bedingungen voraus: Provideränderung bestätigt, Read-back erfolgreich, kanonischer Spiegel nachgeführt, Audit abgeschlossen. Die Ausführung selbst ist eine **eigene ausdrückliche Nutzeraktion** über `POST …/mutations/{mutation_id}/execute` — `approve` löst sie niemals aus; es gibt keinen Hintergrundexecutor, keinen Scheduler und keinen automatischen Retry. Zieladressierung, Feldvertrag v1, Sidecar-Schreib- und Ergebnisvertrag, Capability-Brücke und die Reihenfolge Create → Update → Delete stehen normativ in ADR-0019.

### §7.3 Konfliktfälle und ihre definierte Behandlung

| Fall | Verhalten |
|---|---|
| Externe Änderung zwischen Vorschau und Ausführung | Versionsbedingung schlägt fehl ⇒ Konfliktdatensatz (lokal/extern/Basis), Objekt `conflicted`, keine Überschreibung |
| Lokale und externe Änderung am selben Feld | Dreiwege-Auflösung durch den Nutzer; automatische Zusammenführung **nur** bei disjunkten Feldern |
| Kontakt extern gelöscht, lokal geändert | kein stiller Verlust: Tombstone + Konfliktdatensatz mit dem lokalen Stand, Nutzer entscheidet Neuanlage oder Verwerfen |
| Container nicht mehr vorhanden | Binding `degraded`, betroffene Operationen blockiert, Bestand bleibt lesbar |
| Capability-Unterschied zwischen Containern | je Binding deklariert; die UI zeigt die Grenze am Datensatz |
| Notiz nicht lesbar | `unavailable_by_capability`; **nie** als leer gewertet, nie überschrieben, nie gesendet |
| Me-Karte | schreibgeschützt in v1: lesbar und gekennzeichnet, keine Mutation |
| Unified Contact | nur lesend über `unified_identifier`; Schreiben ausschließlich auf den Rohdatensatz |

## §8 Berechtigungen und Freigaben

Es wird **keine neue Berechtigungsarchitektur** entworfen. Verwendet werden ausschließlich die bestehenden Muster aus 05, 09, 10 und 14.

| Aktion | Klasse | Freigabeform |
|---|---|---|
| Kontakte lesen, suchen, filtern (kanonische DB) | R0 | keine Einzelbestätigung |
| Sync auslösen (lesend) | R0 | keine Einzelbestätigung |
| TCC-Autorisierung anfordern | — | **ausdrückliche Nutzeraktion**, nie automatisch, nie beim Start |
| Kontakt erstellen | R1 | `user_direct` mit Vollvorschau ⇒ der Speichern-Klick ist die Bestätigung; `llm_assisted`/`automation` ⇒ separate Freigabe |
| Kontakt ändern | R1 | wie oben, Vorschau feldweise (vorher/nachher) |
| Kontakt löschen | R1 | wie oben, Vorschau mit vollständigem Datensatz-Snapshot |
| Lokale Rolle/Kategorie setzen | R0 | rein lokal, kein Provider-Push |

**Trennung von Freigabe und Ausführung:** Die Freigabe erzeugt einen Datensatz in `contacts_mutations` mit `approval_id`; die Ausführung erfolgt danach über die ExternalActionOutbox durch den R1-Executor — **nie** synchron im Request. Abgelaufene Freigaben (`expired`) werden nicht ausgeführt; der Vorgang beginnt neu mit frischer Vorschau. `outcome_unknown` erscheint als eigener, sichtbarer Zustand mit der Handlungsanweisung „zuerst abgleichen", nicht als Fehler.

**Präzisierung 2026-08-01 ([ADR-0019](../../adr/ADR-0019-provider-mutation-architecture.md), verbindlich):** Der „R1-Executor" ist **kein Hintergrundprozess**. Ausgeführt wird ausschließlich auf eine **eigene ausdrückliche Nutzeraktion** (`POST …/mutations/{mutation_id}/execute` mit `user_initiated: true`) — auch bei `initiation_context = user_direct` sind Freigabe und Ausführung zwei getrennte Aktionen; ein Klick bestätigt nie beides. Die Risikoklassen-Tabelle oben nennt für „Kontakt löschen" den Stand R1; ADR-0019 §7 schlägt **Delete als R2** vor (ausdrücklich nicht beschlossen) — vor jeder Delete-Implementierung ist DEC-D06 zu entscheiden.

**Audit** (10 §5): je Pipeline-Stufe ein Eintrag in derselben Transaktion wie die Fachänderung — `command_received`, `validated`, `previewed`, `approved`, `dispatched`, `provider_result`, `verified`, `reconciled`. R1 erzeugt keine signierten Checkpoints (das ist R2-Mechanik).

## §9 Backend- und API-Vertrag

### §9.1 Der produktive Bridge-Vertrag ist nicht der Spike-Vertrag

Der Spike-Vertrag (`spikes/contacts-bridge-g3a/PROTOCOL.md`) wird **nicht** blind übernommen. Begründete Einordnung je Operation:

| Spike-Operation | Entscheidung | Begründung |
|---|---|---|
| `ping`, `caps`, `shutdown` | **stabilisieren** | Handshake, Fähigkeitsauskunft und grazioser Ausstieg sind produktiv nötig und im Spike bewährt |
| `containers` | **stabilisieren** | Grundlage der ProviderCollections (08 §1) |
| `enumerate` | **stabilisieren**, erweitert um verpflichtende `keySetVersion` in **jeder** Antwort | Voll-Diff-Fallback ist Pflichtbestandteil (ADR-0016 Pkt. 5) |
| `changes` | **stabilisieren** | Delta-Pfad; `currentToken` kommt aus der Antwort, nie aus einem zweiten Store-Read |
| `token` | **entfernen** | Verleitet dazu, den Cursor neben dem Drain zu lesen — genau der Fehler, den 11 §3 verbietet |
| `get` | **stabilisieren** | Read-back nach Mutation |
| `getUnified` | **umbenennen zu `getUnifiedReadOnly`** | Der Name suggeriert einen gleichwertigen Zugriffsweg; die belegte Identifier-Instabilität macht ihn zu einem reinen Lesepfad |
| `create`, `update`, `delete` | **ersetzen** durch Varianten mit Pflichtfeldern `mutationId`, `idempotencyKey`, `expectedRevision` | Die Spike-Varianten kennen weder Idempotenz noch Versionsbedingung; ohne beides ist 11 §3 nicht erfüllbar |
| `updateViaUnified` | **nicht übernehmen** | War eine Hazard-Probe; Schreiben auf unified contacts ist ausgeschlossen (§7.1) |
| `requestAuthorization` | **stabilisieren, aber gegattert** | Produktiv nur auf ausdrückliche Nutzeraktion; das Env-Gate des Spikes wird durch einen expliziten Kommandoparameter ersetzt |
| `enumerateProbe`, `isolationSummary` | **nicht übernehmen** | Diagnosewerkzeuge des Spikes |
| Spike-Rail (`ZZZ-JarvisTest-`-Präfixzwang) | **nicht übernehmen** | Produktiv ist die Vorgangsbindung aus §7.1 die Sicherung, nicht ein Namenspräfix |

Das DTO bleibt in seiner Serialisierungsgarantie (sortierte Schlüssel, explizite `null`, keine locale-abhängige Formatierung) und wird um `fieldAvailability` je Risikofeld erweitert, damit `unavailable_by_capability` überhaupt transportierbar ist. **Normalisierung, Hashing, Anzeigenamen-Bildung bleiben im Kern** (ADR-0016 Pkt. 4).

### §9.2 Öffentliche Verträge

Alle Routen unter `/v1/personal/contacts/` (DEC-020), alle mutierenden über den CommandBus (AV-35).

| Vertrag | Input | Output | Fehler | Recht | Idempotenz | Datenschutz |
|---|---|---|---|---|---|---|
| `GET /v1/personal/contacts` | Filter (Workspace, Rolle, Suchtext, Cursor) | Seite kanonischer Kontakte | `PermissionDenied`, `ProviderInvalid` | R0 + Session-Token | — | keine Provider-Rohdaten |
| `GET /v1/personal/contacts/{id}` | ID | Kontakt inkl. `field_availability` | `NotFound` | R0 | — | Thumbnail nur als Referenz |
| `POST /v1/personal/contacts` | Command `CreateContact` | `mutation_id`, Zustand | `ValidationFailed`, `Conflict`, `PermissionDenied` | R1 + Freigabe | `idempotency_key` | Vorschau enthält den vollen Effekt |
| `PATCH /v1/personal/contacts/{id}` | Command `UpdateContact` + `expected_revision` | `mutation_id`, Zustand | `Conflict`, `NotFound` | R1 + Freigabe | `idempotency_key` | feldweise Vorschau |
| `DELETE /v1/personal/contacts/{id}` | Command `DeleteContact` + `expected_revision` | `mutation_id`, Zustand | `Conflict`, `NotFound` | R1 + Freigabe | `idempotency_key` | Snapshot im Audit |
| `POST /v1/personal/contacts/sync` | Konto, Modus | Sync-Lauf-ID | `PermissionDenied`, `TransientNetwork` | R0 | single-flight je (Konto × Collection) | — |
| `GET /v1/personal/contacts/sync/status` | — | Cursor-Alter, Modus, Circuit, Rückstand | — | R0 | — | — |
| `POST /v1/personal/contacts/authorization` | `{"request": true}` | TCC-Status | `PermissionDenied` | ausdrückliche Nutzeraktion | einmalig je `notDetermined` | — |
| `GET /v1/personal/contacts/capabilities` | Konto | Capability-Deklaration inkl. `notesSupported=false` | — | R0 | — | — |
| `GET /v1/personal/contacts/mutations` | Filter | Mutationen inkl. `outcome_unknown` | — | R0 | — | — |
| `POST /v1/personal/contacts/mutations/{id}/reconcile` | ID | neuer Zustand | `NotFound` | R0 (nur lesend abgleichend) | — | — |

Fehlernormalisierung ausschließlich auf die geschlossene Taxonomie aus 08 §3 Nr. 5. **Keine rohe Provider-Exception verlässt den Adapter.**

Tauri-seitig entsteht **kein** neuer fachlicher Pfad: der Desktop nutzt dieselben HTTP-Routen mit Session-Token (DEV-4).

## §10 Benutzeroberfläche

Im bestehenden Design (React Router, Zustand, `frontend/src/lib/api.ts`, `components/ui/*`), als gekapseltes Modulverzeichnis `frontend/src/personal/contacts/` mit genau drei gemeinsamen Berührungen (DEV-4): eine Route in `App.tsx`, ein Navigationseintrag in `Sidebar.tsx`, ein Session-Token-Kommando in `lib.rs`.

**Navigationsregel (14 §2):** Der Eintrag „Kontakte" ist sichtbar nur bei kompiliertem Modul **und** erlaubtem Betriebszustand aus `/v1/personal/system/modules`. Kein Menüpunkt ohne vollständiges Backend.

Flächen: Kontaktliste (virtualisiert, serverseitige Suche und Paginierung) · Suchfeld · Filterleiste mit den Kategorien **Privat · Arbeit · HV · Mieter · Vermieter** aus `contact_roles` · Detailansicht mit Container-/Kontoherkunft, Sync-Status, `field_availability`-Hinweisen · Editor für Erstellen und Bearbeiten mit **vollständiger Vorschau vor dem Speichern** · Löschdialog mit vollständigem Snapshot · Freigabefläche für vorbereitete Mutationen · Konfliktansicht (lokal/extern/Basis, feldweise) · Zustand `outcome_unknown` mit der Aktion „Abgleichen" statt „Wiederholen".

Pflicht-Randzustände, jeder mit echtem Inhalt statt Platzhalter (AV-3): TCC nicht erteilt (Schritt-für-Schritt-Anleitung zu den Systemeinstellungen) · leere Liste (Erstimport anbieten) · Fehler (konkrete Diagnose) · Bridge nicht erreichbar / offline (kanonische Daten bleiben lesbar, Schreiben gesperrt mit Begründung) · Ladezustände (Skeletons, kein Layout-Sprung) · `degraded` je Binding.

Barrierefreiheit und Tastatur: vollständige Tab-Reihenfolge, sichtbarer Fokus, `aria-live` für Sync- und Mutationszustände, Listennavigation mit Pfeiltasten, `Enter` öffnet, `Escape` schließt Dialoge, alle Aktionen ohne Zeigegerät erreichbar, Kontrastwerte nach WCAG AA.

**Der Hinweis auf nicht lesbare Notizen erscheint als eigener Zustand am Feld** — nicht als leeres Eingabefeld, das ein Speichern zum Datenverlust machen würde.

## §11 Interne Gates (ein Modul, fünf Umsetzungsgrenzen)

Die Gates sind **interne** Grenzen eines einzigen vertikalen Zuges. Kein Gate ist ein auslieferbares Teilmodul; der Navigationseintrag erscheint erst in Gate D.

### Gate A — Produktfundament

**Inhalt:** `minimumSystemVersion` 10.15 → **12.3** · Paketgerüst `src/personaljarvis/` · additive `[dependency-groups] personal` · PersonalCompositionRoot · ConnectionFactory/UoW · Migrations-Ledger und Runner · Basis-Migrationen · Contacts-Kernmigrationen · Repository-**Verträge** · Fehler- und Capability-Typen · Egress-Labels · Lifecycle-Gerüst.
**Abhängigkeiten:** keine.
**Tests:** Migrationstests inkl. Prüfsummen-Fehlversuch · Rechte-/Pragma-/WAL-Test · Ledger-fail-closed · „Standard-Auflösung ohne Personal-Gruppe unverändert" (DEV-5) · `minos`-Assertion.
**Live:** keine.
**Commit-Grenze:** ein Commit `feat(contacts): establish personal foundation and schema`.
**Abbruch:** Ledger nicht fail-closed zu bekommen; `src/personaljarvis` nicht importierbar ohne Änderung an `[tool.hatch.build.targets.wheel]`.
**Fertig:** Migrationen laufen auf leerer und auf migrierter DB, alle Tests grün, kein Produktpfad berührt.

### Gate B — Native Lesen und Synchronisieren

**Inhalt:** produktiver Sidecar unter `native/contacts-bridge/` (Swift + ObjC-Shim, aus dem Spike **konsolidiert**, nicht kopiert) · Build je Architektur · Signierung · Prozessmanagement mit Dual-Drainer und graziösem Shutdown · Bridge-Client · Autorisierungsstatus · Initialimport · Delta · Voll-Diff · Tombstones · Echo-Unterdrückung.
**Abhängigkeiten:** Gate A.
**Tests:** Protokoll-Contract gegen Fake **und** echten Sidecar · Invalid-Token · `dropEverything` · unvollständige Enumeration wird verworfen · Tombstone-kein-Wiederauferstehen · Echo-Unterdrückung über beide Wege · Prozessabsturz und Wiederanlauf.
**Live:** erster Lesezugriff im Testbenutzer `jarvisspike` auf arm64, danach auf x86_64.
**Commit-Grenze:** `feat(contacts): add native bridge and read synchronization`.
**Abbruch:** der konsolidierte Sidecar erfüllt die Dünnheits-Verbote nicht; die Delta-API ist auf x86_64 nicht erreichbar.
**Fertig:** Initialimport und zwei aufeinanderfolgende Delta-Läufe reproduzierbar; zweiter Drain leer.

### Gate C — Produktive Mutationen

**Inhalt:** Create/Update/Delete mit `mutation_id`, `idempotency_key`, `expected_revision` · ActionPipeline · Freigabefluss · ExternalActionOutbox und R1-Executor · Read-back und Verifikationszustände · `outcome_unknown` mit Reconcile · Audit.
**Abhängigkeiten:** Gate B.
**Tests:** Idempotenz bei doppeltem Dispatch · Konflikt bei veralteter Revision · `outcome_unknown` löst **keinen** Retry aus · Reconcile-Pfad · „keine Mutation ohne Ziel-ID" · „keine Mutation an fremdem Datensatz" · Audit-Kette lückenlos.
**Live:** CRUD im Testbenutzer auf arm64, danach auf x86_64.
**Commit-Grenze:** `feat(contacts): add approved mutations with reconciliation`.
**Abbruch:** `outcome_unknown` lässt sich nicht deterministisch von Erfolg und Fehlschlag trennen.
**Fertig:** alle Mutationspfade inklusive Konflikt und `outcome_unknown` reproduzierbar; kein Fremdkontakt berührt.

### Gate D — Backend und Oberfläche

**Inhalt:** Routen, Commands, Queries · Modul-Readiness · Navigationseintrag, Route, Session-Token-Kommando (DEV-4) · Liste, Suche, Kategorien, Detail, Editoren, Freigabefläche, Konfliktansicht · alle Randzustände · Barrierefreiheit.
**Abhängigkeiten:** Gate C.
**Tests:** API-Tests je Vertrag · Navigationssichtbarkeit nur bei Readiness · App identisch ohne Personal · Capability-Regressionstest der Tauri-Kommandofläche · UI-Tests je Randzustand · Tastatur- und `aria-live`-Tests · „kein Geheimnis in der SPA".
**Live:** Desktop-Entwicklungsbetrieb je Architektur.
**Commit-Grenze:** `feat(contacts): add backend api and module ui`.
**Abbruch:** ein Randzustand ließe sich nur mit Platzhalter darstellen (AV-3).
**Fertig:** jede Fläche an echte Daten angebunden, kein leerer Menüpunkt.

### Gate E — Modulabschluss

**Inhalt:** vollständige Testsuiten · Packaging und Signierung je Architektur · gepackte App mit **echter** Kontakteoperation · App-Neustart · Backup-/Restore-Roundtrip · vollständige TCC-Persistenzmatrix · Mehrcontainer-/Unified-Test · Live-Abnahme auf beiden Architekturen · Matrix 15 §8 vollständig · Registerpflege.
**Abhängigkeiten:** Gate D.
**Abbruch:** eine Pflichtzeile bleibt `OPEN` — dann bleibt der Abschluss gesperrt; kein Ersatznachweis, keine Umdeutung.
**Fertig:** 15 §8 in **beiden** Spalten vollständig `PASS`, 19 vollständig erfüllt, Eigentümerbestätigung liegt vor.

## §12 Dateigenaue Änderungsmatrix

Legende: **N** neu · **Ä** vorhandene Datei ändern · **W** unverändert wiederverwenden · **R** Spike-Datei nur als Referenz · **K** Spike-Datei produktiv konsolidieren · **X** ausdrücklich nicht übernehmen.

| Datei / Verzeichnis | Art | Gate | Zweck | Abhängig von | Tests | Risiko |
|---|---|---|---|---|---|---|
| `frontend/src-tauri/tauri.conf.json` | Ä | A/B | `minimumSystemVersion` → `12.3` (Gate A); `externalBin: ["binaries/jarvis-contacts"]` (Gate B) | — | `minos`-Assertion, externalBin-Tests, Desktop-Build | mittel — Build-Auswirkung |
| `pyproject.toml` | Ä | A | additive `[dependency-groups] personal`; **`[tool.hatch.build.targets.wheel]` unberührt** | — | Auflösungstest DEV-5 | niedrig |
| `src/personaljarvis/__init__.py` | N | A | `attach(app)` als einziger Integrationspunkt | — | Personal an/aus | niedrig |
| `src/personaljarvis/bootstrap.py` | N | A | PersonalCompositionRoot, Startreihenfolge 04 §1 | — | fail-closed-Test | hoch — Reihenfolge sicherheitsrelevant |
| `src/personaljarvis/base/db/factory.py`, `unit_of_work.py` | N | A | ConnectionFactory, UoW (07 §1/§2) | bootstrap | Rechte, Pragmas, WAL | mittel |
| `src/personaljarvis/base/db/migrations/{runner,ledger}.py`, `versions/` | N | A | globales Migrationsmodell (07 §6) | factory | Prüfsummen, fail-closed | hoch — Datenverlustpfad |
| `src/personaljarvis/base/{command_bus,audit,outbox,approvals}/…` | N | A/C | eine Schreibspur, Audit, Outboxen, R1-Freigaben | migrations | Pipeline-, Idempotenz-, Auditkettentests | hoch |
| `src/personaljarvis/runtime/ports/*.py`, `runtime/ojra.py` | N | A | Port-Bündel + Adapter (04 §2/§3) | bootstrap | Port-Contract-Suite | mittel |
| `src/personaljarvis/contacts/domain/*.py` | N | A | Entitäten, Labels, Capabilities, `field_availability` | base | Domain-Unit-Tests | niedrig |
| `src/personaljarvis/contacts/repositories/*.py` | N | A | Verträge + modulprivate Implementierungen (07 §3) | domain | Repository-Tests gegen Testdatenbank | mittel |
| `src/personaljarvis/contacts/bridge/{client,process,protocol}.py` | N | B | Bridge-Client, Prozessmanagement, produktiver Vertrag | Sidecar | Contract gegen Fake und echt | hoch — Deadlock-/Zombie-Risiko |
| `src/personaljarvis/contacts/sync/{initial,delta,full_diff,tombstones}.py` | N | B | Sync-Pfade | bridge, repositories | Invalid-Token, `dropEverything`, Abbruch | hoch |
| `src/personaljarvis/contacts/application/{commands,handlers,queries}.py` | N | C/D | Commands, Handler, Leseabfragen | base, sync | Mutations- und Konflikttests | hoch |
| `src/personaljarvis/contacts/api/routes.py` | N | D | `/v1/personal/contacts/*` | application | API-Tests je Vertrag | mittel |
| `src/personaljarvis/contacts/lifecycle.py` | N | A/D | Zustandsmaschine 14 §4 | base | Übergangstests | niedrig |
| `src/openjarvis/server/app.py` | Ä | A | **genau ein** bewachter `attach`-Aufruf (DEV-3) | `personaljarvis` | Personal an/aus, App identisch | mittel — Upstream-Berührung |
| `native/contacts-bridge/src/{sidecar,main}.swift` | K | B | produktiver Sidecar aus dem Spike konsolidiert | — | Dünnheits-Review, Protokoll-Contract | hoch |
| `native/contacts-bridge/src/JCChangeHistoryShim.{h,m}` | K | B | ausschließlich Selektor-Weiterleitung | — | Struktur-Review | mittel |
| `native/contacts-bridge/build.sh` | K | B | Build je Architektur mit Host-Erkennung | — | Build-Matrix | mittel |
| `native/contacts-bridge/PROTOCOL.md` | K | B | produktiver Vertrag nach §9.1 | — | Contract-Suite | mittel |
| `native/contacts-bridge/.gitignore` | N | B | `build/` — keine Mach-O im Repo | — | — | niedrig |
| `frontend/src-tauri/scripts/build-contacts-sidecar.sh` | N | B/E | Sidecar je Triple nach `binaries/` | build.sh | Packaging-Test | mittel |
| `frontend/src-tauri/binaries/.gitignore` | Ä | B | `jarvis-contacts-*` ergänzen | — | — | niedrig |
| `frontend/src-tauri/capabilities/default.json` | W | B | **unverändert.** Korrektur 2026-07-29: Der Sidecar wird vom **Python-Backend** gestartet (`bridge/process.py`, `subprocess.Popen`), nicht von Tauri. Ein `shell:allow-execute`-Scope gilt der **Webview** — er gäbe der SPA einen zweiten fachlichen Ausführungspfad und verstieße gegen AV-35 und DEV-4. Es wird deshalb **kein** Contacts-Scope hinzugefügt. Die Verengung der pauschalen Shell-Rechte bleibt DEV-2/ADR-0014 | — | Capability-Regressionstest (Abwesenheit geprüft) | hoch — Sicherheitsfläche |
| `frontend/src-tauri/src/lib.rs` | Ä | D | **nur** Session-Token-Kommando (DEV-4) | — | Kommandoflächen-Test | mittel |
| `frontend/src/App.tsx` | Ä | D | eine readiness-gesteuerte Route | Modul-UI | Sichtbarkeitstest | niedrig |
| `frontend/src/components/Sidebar/Sidebar.tsx` | Ä | D | ein Navigationseintrag | dito | Sichtbarkeitstest | niedrig |
| `frontend/src/personal/contacts/**` | N | D | gekapseltes Modul-Frontend | API | UI- und A11y-Tests | mittel |
| `frontend/src/lib/api.ts` | W | D | bestehender Client wird **wiederverwendet** | — | — | — |
| `frontend/src/components/ui/*` | W | D | bestehende Bausteine | — | — | — |
| `tests/personal/contacts/**` | N | A–E | Unit, Migration, Repository, Contract, Sync, Mutation, API | — | — | — |
| `docs/personal-jarvis/modules/contacts.md` | Ä | A–E | diese Unterlage fortschreiben | — | — | — |
| `docs/personal-jarvis/15-…md` §8 | Ä | E | Matrixzeilen nach jeder Live-Abnahme | Live | — | hoch — Wahrheitspflicht |
| `docs/testing/contacts-live-*-{arm64,x86_64}-*.md` | N | B/C/E | Live-Abnahmeprotokolle je Architektur | Live | — | — |
| `src/openjarvis/connectors/apple_contacts.py` | X | — | **Altlast**, read-only AddressBook-SQLite; wird nicht Grundlage (§13) | — | — | — |
| `spikes/contacts-bridge-g3a/{driver,phase_b,authorize,*_probe,reconstruct_results}.py` | R | — | Referenz; **kein** Produktcode | — | — | — |
| `spikes/contacts-bridge-g3a/test_*.py` | R | — | Referenz für die produktiven Suiten | — | — | — |
| `spikes/contacts-bridge-g3a/{app-Info.plist,tauri-spike.conf.json,g12-lib-rs.patch}` | X | — | Spike-Packaging-Artefakte | — | — | — |
| `docs/testing/**` (7 Dateien) | W | — | historische Evidenz, **unverändert** | — | — | — |

## §13 Bestehende Konflikte und Altlasten

1. **`minimumSystemVersion: "10.15"`** in `frontend/src-tauri/tauri.conf.json:47` widerspricht der verbindlichen Untergrenze 12.3. Bestätigter Produktdefekt (ADR-0018 §2, 15 §6). **Korrektur im ersten Commit von Gate A.**
2. **Doppelte Wahrheit „Kontakte" — offener zweiter Wahrheits- und Datenquellenpfad.** `src/openjarvis/connectors/apple_contacts.py` (482 Zeilen) liest die AddressBook-SQLite read-only, ist bei `openjarvis.connectors` registriert, erscheint in der Data-Sources-Oberfläche und wird im Research-Prompt als Quelle beworben. Er ist **kein** Vorläufer des Moduls (DEC-012, AV-3); das Personal-Modul greift **nie** darauf zu — statisch belegt (0 Treffer für `apple_contacts` und `openjarvis.connectors` unter `src/personaljarvis/`).

   Er bleibt **vorerst unangetastet**: ein Umbau wäre eine Upstream-Abweichung und ist nicht Teil des laufenden Auftrags. Er ist damit aber **nicht erledigt**, sondern eine offene Verpflichtung. Solange er erreichbar ist, kann ein Klick auf „Sync Now" das rohe Adressbuch — inklusive Notizen, Geburtstagen und Adressen, ohne Redaktion, ohne Tombstones, ohne Änderungserkennung — am gesamten Moduldesign vorbei in `~/.openjarvis/knowledge.db` und deren FTS-Index schreiben. Das ist zugleich eine zweite Datenwahrheit **und** ein Datenschutzpfad, der die Zusicherungen des Moduls nicht einhält.

   **Vor Abschluss des Kontakte-Moduls ist dafür gesondert zu entscheiden und umzusetzen:** deaktivieren (Registrierung, UI-Eintrag und Research-Prompt-Erwähnung entfernen), entfernen, oder auf die kanonische Personal-Jarvis-Datenbank umleiten. Ohne diese Entscheidung ist §16 nicht erfüllt.
3. **Kein `personaljarvis`-Paket vorhanden** — die gesamte Basis entsteht neu, streng nach AV-33 im Umfang dieses Moduls.
4. **Spike-Teile, die nicht Produktcode werden dürfen:** die Sicherheitsrail über das Namenspräfix, `enumerateProbe`, `isolationSummary`, `updateViaUnified`, das Env-Gate für `requestAuthorization`, `phase_b.py`, `reconstruct_results.py`, sämtliche Diagnosewerkzeuge.
5. **Absolute Pfade in Spike-Quellen** (`/Users/Shared/JarvisContactsSpike/...`) — sie beschreiben das Übergabepaket. Produktive Pfade kommen ausschließlich aus dem ConfigurationPort.
6. **Getrackter Build-Cache:** `frontend/tsconfig.tsbuildinfo` ist versioniert und ändert sich bei jedem `tsc -b`. Bestehende Hygiene-Altlast; **nicht** Teil dieses Moduls, hier nur festgehalten.
7. **Pauschale Tauri-Shell-Rechte** in `capabilities/default.json` (`shell:allow-execute/spawn/stdin-write/kill` ohne Scope). Die Verengung ist als **DEV-2 / ADR-0014** geführt und laut 02 §2.4 **Pflicht vor produktivem Personal-Desktop-Betrieb** — sie wird in Gate B mitgeführt, aber unter ihrer eigenen Abweichung, nicht als Contacts-Entscheidung.
8. **`site/`, `:memory:`, `MagicMock`, `desktop/`** im Repository-Wurzelbereich: bekannte Hygiene-Funde, laut 02 §2.4 bewusst liegen gelassen. Keine Bereinigung ohne gesonderte Freigabe.

## §14 Test- und Dual-Arch-Abnahmeplan

| Testart | Umgebung | Gate |
|---|---|---|
| Domain-, Label-, Capability-Unit-Tests | kontaktfrei | A |
| Migrationstests (leer, migriert, Prüfsummenbruch, unbekannte ID) | lokale Testdatenbank | A |
| Repository-Tests | lokale Testdatenbank | A |
| Port-Contract-Suite | kontaktfrei | A |
| Bridge-Protokoll-Contract | **Fake-Sidecar** und **echter Sidecar ohne Store-Zugriff** (`ping`/`caps`/`shutdown`) | B |
| Sync-Tests (Delta, `dropEverything`, Invalid-Token, Abbruch, Wiederanlauf) | Fake-Sidecar mit Skript-Antworten | B |
| Voll-Diff- und Tombstone-Tests | Fake-Sidecar + Testdatenbank | B |
| Konflikt- und Dreiwege-Tests | Testdatenbank | C |
| Mutation-, Approval-, Idempotenz-Tests | Testdatenbank | C |
| `outcome_unknown`- und Reconcile-Tests | Fake-Sidecar mit Abbruchsimulation | C |
| API-Tests | FastAPI-Testclient | D |
| UI-Tests inklusive Randzustände, Tastatur, `aria-live` | Vitest | D |
| Tauri-Kommandoflächen-Regression | `cargo test` | D |
| Packaging und Signierung | lokal je Architektur | E |
| **Live: Autorisierung, Enumerate, CRUD, Delta, Cleanup** | Testbenutzer `jarvisspike`, **echte arm64-Hardware** | B/C/E |
| **Live: dieselben Zeilen** | Testbenutzer, **echte x86_64-Hardware** | B/C/E |
| Mehrcontainer-/Unified-Test | Installation mit **zwei** Containern, je Architektur | E |
| Gepackte App mit echter Kontakteoperation | je Architektur | E |
| App-Neustart, TCC-Persistenz (Rebuild, Versions-Bump, Verschieben, Quarantäne) | je Architektur | E |
| Backup-/Restore-Roundtrip | je Architektur | E |

**Rosetta zählt in keiner Zeile** (ADR-0018 §5). Ein arm64-Ergebnis ist nie ein Intel-Nachweis und umgekehrt. Jede Live-Zeile trägt Architektur, macOS-Version, Swift-/SDK-Version, Zertifikatsbezeichnung, Testbenutzer und Datum (15 §7 Nr. 3).

## §15 Risiken und offene Punkte

**Blockiert den Implementierungsbeginn:** keines.

**Befund 2026-07-29 (Gate B, dokumentiert, nicht korrigiert):** `.github/workflows/desktop.yml:256` setzt beim Release-Build `TAURI_CONFIG` mit `{"bundle":{"externalBin":["binaries/ollama"]}}`. Dieser Wert **ersetzt** das `externalBin`-Array aus `tauri.conf.json` — ein CI-Release würde den Contacts-Sidecar damit **nicht** bündeln. Die Korrektur berührt einen Upstream-Workflow und ist nach 02 §3 nicht ohne gesonderte Freigabe zulässig; sie ist **vor dem ersten produktiven Desktop-Release** fällig. Lokale Builds sind nicht betroffen.

**Kann innerhalb eines Gates entschieden werden:**

| Risiko | Gate | Umgang |
|---|---|---|
| Ablageort des produktiven Sidecars (`native/contacts-bridge/` + Kopie nach `binaries/<triple>`) | B | dem Ollama-Präzedenzfall folgen; Auflösung über `current_exe()`, **nie** über PATH |
| Sidecar-Prozessmanagement (Deadlock, Zombie, Neustart) | B | Dual-Drainer vor dem ersten Write; im Spike belegt |
| Schemaevolution der DTOs | B | `key_set_version` in jeder Antwort; Wechsel erzwingt Voll-Diff |
| Nur-Vorwärts-Migrationen | A | Restore des Vor-Migrations-Backups als getestete Rückfallstrategie (13 §4) |
| `outcome_unknown` in der Praxis | C | Read-/Reconcile-Pflicht vor jeder Folgeaktion; nie automatischer Retry |
| Cross-Build gegen nativen Build | B/E | Entwicklung baut nativ je Host; **Abnahme ausschließlich nativ auf echter Hardware** |
| Signaturrotation | E | Designated Requirement zertifikatsbasiert (im Spike belegt) — ein Rebuild entwertet die Berechtigung nicht; **die Persistenz über Versions-Bump und Verschieben ist noch offen** |
| Intel-SDK-Stand (Swift 5.7.2 / SDK 13.1) | B | beide Contacts-Eigenschaften sind dort vorhanden (in ADR-0018 belegt); Build-Assertion auf `minos 12.3` |
| macOS-12.3-Kompatibilität | A/E | `minimumSystemVersion` korrigieren; Abnahme auf einer 12.3-Installation ist Teil von Gate E |

**Abgenommen am 2026-07-31 — beide Architekturen.** Der Lese- und Sync-Pfad einschliesslich Auditierung und Neustart ist auf **arm64 und x86_64** produktiv abgenommen. Damit sind die beiden in ADR-0018 festgelegten Produktionsziele gleichwertig auf echter Hardware validiert; Mehrcontainer, Vollabgleich, Delta, Neustart, Cursorfortsetzung und Auditspur sind auf jeder von beiden belegt.

| | arm64 (Apple Silicon) | x86_64 (Intel) |
|---|---|---|
| Vollaufnahme | Initialimport, 2 Container, 115 Kontakte | Wiederherstellung (116 reaktiviert) + Voll-Diff, 2 Container, 117 Kontakte |
| Tombstones entstanden | 0 | 0 |
| Delta-Audit-Runs | 4 | 4 |
| Ereignisse je Delta-Lauf | 0 | 0 |
| Cursorfortsetzung über echten Neustart | erfolgreich | erfolgreich |
| unerwartete Voll-Diffs | keine | keine |
| autonomer Sync | keiner | keiner |
| Evidenz | [`…arm64…`](../../testing/contacts-arm64-read-sync-validation-2026-07-31.md) | [`…x86_64…`](../../testing/contacts-x86_64-read-sync-validation-2026-07-31.md) |

**Die Intel-Wiederherstellung ist abgeschlossen:** die 116 am 2026-07-30 irrtümlich lokal gelöschten Spiegelkontakte sind auf **denselben** lokalen Kennungen reaktiviert, ohne Duplikate; die zugehörigen Tombstone-Historien sind als abgeglichen markiert statt gelöscht. Bei Apple war nichts verändert.

Ein künstlicher Provider-`DELETE`-Livetest ist auf keiner der beiden Architekturen Voraussetzung des Abschlusses; der Pfad ist automatisiert abgedeckt.

**Blockiert weiterhin ausschließlich den Modulabschluss:**

1. **Provider-Mutationen — Anlegen ist implementiert, Bearbeiten und Löschen nicht.** Architektur eingefroren in [ADR-0019](../../adr/ADR-0019-provider-mutation-architecture.md) (DEC-044); **Phase M2 (`create`) ist seit dem 2026-08-01 im Code umgesetzt** und wartet auf die x86_64-Live-Abnahme. Danach M3 (arm64-Gegenprüfung), M4 (Update), M5 (Delete). **Delete zusätzlich verriegelt hinter DEC-D06.** `update` und `delete` liefern im Sidecar weiterhin `not_implemented`.
2. **Alter OpenJarvis-Apple-Contacts-Connector** — deaktivieren, entfernen oder auf die kanonische Personal-Jarvis-Datenbank umleiten (§13.2, §16 Nr. 7).
3. **Abschliessender Cross-Architecture-Test der Mutationen** — sobald sie existieren, auf beiden Architekturen auf echter Hardware.
4. **Backup-/Restore-Roundtrip je Architektur**, soweit als Modulabschluss vorgesehen.
5. **Übernahme auf `jarvis/rebuild-v1`** — der Stand liegt bis dahin ausschliesslich auf dem Handoff-Branch.

**Erledigt am 2026-07-31: Datenschutz-Härtung des `SyncStatusOut`-Vertrags.** `GET /sync/status` gibt keine rohen Konto- oder Containerkennungen mehr heraus, sondern `provider_type`, `account_ref` und `container_ref`; `has_cursor` heisst `cursor_present`, dazu kommen `requires_full_diff` und `last_successful_run_at`. Die Maskierung ist dieselbe Bildung wie in der Auditspur (`sync.audit.container_ref`), damit ein `C-…` in Bericht, Datenbank und API denselben Container bezeichnet. Persistenz, Sync und Sidecar arbeiten unverändert mit den echten Kennungen — gehärtet ist ausschliesslich der Transport. Befund aus der x86_64-Abnahme (§8 C dort).

**Noch offen an diesem Vertrag:** ein stabiler technischer Fehlercode, `retryable` und Aggregatzahlen je Zeile. `contacts_sync_state` hat dafür keine Spalten; sie zu ergänzen verlangte eine Migration **und** einen Schreibpfad in der Sync-Logik. **Entschieden am 2026-08-01 (ADR-0019 §8):** dafür wird **keine** eigene Migration angelegt; die Felder kommen erst, wenn eine verlässliche fachliche Quelle und ein klarer UI-Verbraucher existieren.

### §15.1 Umsetzungsstand Create (Phase M2, 2026-08-01)

| Baustein | Ort |
|---|---|
| Zustand `provider_applied_pending_reconcile` + `readback_digest` | Migration `0006` |
| Geschlossener Feldvertrag v1 | `application/field_contract.py` |
| Sidecar-`create` (ein `CNSaveRequest`, Read-back, Ergebnisvertrag) | `native/contacts-bridge/src/sidecar.swift` |
| Provider und Abgleichleser | `application/bridge_provider.py` |
| Ausführungsroute `POST …/mutations/{id}/execute` | `api/routes.py` |
| C1/C2 und `finalize_pending` | `application/mutation_service.py` |
| Capability-Brücke Handshake → `ContactCapabilitySet` | `domain/capabilities.py` |

**Feldvertrag v1 — die geschlossene Feldmenge.** Zwölf skalare Textfelder (`given_name`, `middle_name`, `family_name`, `previous_family_name`, `name_prefix`, `name_suffix`, `nickname`, `phonetic_given_name`, `phonetic_family_name`, `organization_name`, `department_name`, `job_title`), dazu `contact_type` (nur beim Anlegen), `birthday` sowie die Listen `emails`, `phones` (je 10), `postal_addresses` (5), `urls` (10) und `dates` (5). Labels kommen aus geschlossenem Vorrat: `home`/`work`/`other`, bei Telefon zusätzlich `mobile`/`main`, bei Datumsangaben nur `other`. Listen werden kanonisch sortiert — die Reihenfolge ist in v1 nicht frei wählbar, dafür ist der Read-back-Vergleich unabhängig von der Reihenfolge, die Apple liefert.

**Nicht in v1** und nur über eine Vertragsversion v2 erreichbar: Notizen, Kontaktbild, Me-Karte als Ziel, Link/Unlink, soziale Profile, Sofortnachrichten, Beziehungen, Gruppen, `sub_locality`.

**Belegte Grenze des Abgleichs.** `CNChangeHistoryFetchRequest` kennt nur `excludedTransactionAuthors`; ein `includedTransactionAuthors` existiert nicht, und `CNChangeHistoryEvent` trägt keinen Autor (SDK-Befund macOS 12–13). Ein `create`, dessen Antwort verlorenging, lässt sich deshalb **nicht** über den eigenen Transaktionsautor wiederfinden. Der Abgleich urteilt dann mehrdeutig und ein Mensch entscheidet; eine Namens- oder Ähnlichkeitssuche findet nicht statt.

**Live-Testplan für die x86_64-Abnahme** (noch nicht ausgeführt): genau **ein** eigens angelegter Testkontakt mit Präfix `ZZZ-JarvisTest-` (DEC-038) in einem ausdrücklich benannten Container. Ablauf: Anlage vorbereiten → Vorschau prüfen → freigeben → **getrennt** ausführen → Read-back und lokalen Spiegel prüfen → Auditkette prüfen → Kontakt anschliessend in Apple Kontakte von Hand entfernen. Bestehende private Kontakte bleiben unberührt; es wird nichts bearbeitet und nichts gelöscht.

**Bleibt DEC-D17:** Universal 2 gegenüber zwei getrennten Artefakten. Dieser Plan entscheidet es **nicht** und darf es nicht vorwegnehmen (17 §3 Nr. 2a).

**Dauerhafte Capability-Grenzen, keine Risiken:** Notizen ohne Entitlement nicht verfügbar; Link/Unlink nicht als mutierende Capability; Me-Karte in v1 schreibgeschützt.

## §16 Definition of Done für dieses Modul

Es gilt 19 unverändert und vollständig. Zusätzlich modulspezifisch:

1. Matrix 15 §8 in **beiden** Spalten vollständig `PASS`; kein `OPEN`, kein `NOT EXECUTABLE IN CURRENT ENVIRONMENT`.
2. `notesSupported=false` ist deklariert, in der UI sichtbar und durch einen Test abgesichert, der beweist, dass ein nicht lesbares Notizfeld **nie** als leer geschrieben wird.
3. Kein Codepfad kann eine Mutation ohne Ziel-ID, ohne Freigabe oder ohne Idempotenzschlüssel auslösen — durch Test belegt.
4. `outcome_unknown` führt nachweislich zu keinem automatischen Retry.
5. Speicher-Register (06 §2), Entscheidungsregister, Traceability-Matrix und Glossar sind aktualisiert (19 §9).
6. Live-Abnahme-Protokoll je Architektur liegt vor und ist vom Eigentümer bestätigt (19 §10).
7. Der zweite Kontakte-Datenpfad aus §13.2 (`src/openjarvis/connectors/apple_contacts.py`) ist entschieden und umgesetzt — deaktiviert, entfernt oder auf die kanonische Datenbank umgeleitet. Ein Modul, das eine einzige Datenwahrheit zusichert, ist nicht fertig, solange daneben ein zweiter Schreibweg in einen durchsuchbaren Index offen steht.

## §17 Erster produktiver Implementierungsauftrag (Gate A)

**Auftrag:** Fundament und Schema des Kontakte-Moduls anlegen. Genau dieser Umfang, nichts darüber hinaus.

1. `frontend/src-tauri/tauri.conf.json`: `bundle.macOS.minimumSystemVersion` von `"10.15"` auf `"12.3"`.
2. `pyproject.toml`: additive `[dependency-groups] personal`. **`[tool.hatch.build.targets.wheel]`, bestehende Extras und Standard-Abhängigkeiten bleiben unverändert** (DEV-5).
3. `src/personaljarvis/` anlegen: `__init__.py` mit `attach(app)`, `bootstrap.py` mit der Startreihenfolge aus 04 §1 (fail-closed), `base/db/` mit ConnectionFactory und UnitOfWork, `base/db/migrations/` mit Ledger, Runner und den ersten Basis- plus Contacts-Migrationen, `contacts/domain/` mit Entitäten, Egress-Labels, Capability-Deklaration und `field_availability`, `contacts/repositories/` mit Verträgen und modulprivaten Implementierungen, `contacts/lifecycle.py`.
4. `src/openjarvis/server/app.py`: **genau ein** bewachter Aufruf `personaljarvis.attach(app)` hinter Feature-Schalter und `try/except ImportError` (DEV-3, 04 §4). Kein weiterer Umbau von `create_app`.
5. `tests/personal/contacts/` anlegen mit: Migrationstests (leere DB, migrierte DB, Prüfsummenbruch, unbekannte angewandte ID), Rechte-/Pragma-/WAL-Test, Ledger-fail-closed-Test, Repository-Tests gegen eine temporäre Testdatenbank, Domain- und Capability-Tests, „Notiz nie leer"-Test, Personal-an/aus-Test und der DEV-5-Auflösungstest.
6. Verifikation vor dem Commit: `make test` · `npx tsc --noEmit` · `npm test` · `cargo test` · `uv run mkdocs build` · `git diff --check`.

**Verboten in Gate A:** jeder Sidecar-Start, jede Contacts-Store-Operation, jedes `requestAuthorization`, jede UI-Fläche, jede Route unter `/v1/personal/contacts/`, jede Änderung an `docs/testing/`, an `spikes/**` oder an `src/openjarvis/connectors/apple_contacts.py`.

**Abgeschlossen, wenn:** Migrationen auf leerer und migrierter Datenbank durchlaufen, der Ledger bei Prüfsummenabweichung fail-closed reagiert, alle neuen Tests grün sind, die vier bestehenden Suiten unverändert grün bleiben und `minimumSystemVersion` auf `12.3` steht.

## §18 Verweise

Primärdokumente: 04 (Bootstrap/Ports), 05 (CommandBus/Pipeline), 06 (Datenhoheit), 07 (Persistenz/Migrationen), 08 (Adaptermodell, Capability-Grenzen), 09 (Auth/Credentials), 10 (Risiko/Approvals/Audit), 11 (Sync/Outboxes/Konflikte), 12 (Egress), 13 (Backup), 14 (UI/Lifecycle), 15 §7/§8 (Abnahme), 16 §2/§3/§4.1 (Modulkarte), 17 (Deferred Decisions), 18 (DEV-2/DEV-3/DEV-4/DEV-5), 19 (Definition of Done).
ADRs: [ADR-0001](../../adr/ADR-0001-personal-runtime-facade.md), [ADR-0003](../../adr/ADR-0003-canonical-personal-database.md), [ADR-0005](../../adr/ADR-0005-command-bus-and-action-pipeline.md), [ADR-0006](../../adr/ADR-0006-risk-r0-r1-r2.md), [ADR-0007](../../adr/ADR-0007-transactional-outboxes.md), [ADR-0012](../../adr/ADR-0012-vertical-module-development.md), [ADR-0015](../../adr/ADR-0015-personal-integration-touchpoints.md), [ADR-0016](../../adr/ADR-0016-swift-contacts-bridge.md), [ADR-0018](../../adr/ADR-0018-dual-architecture-macos-support.md), [ADR-0019](../../adr/ADR-0019-provider-mutation-architecture.md).
Spike-Evidenz (historisch, unverändert), Einstiegspunkt: [contacts-bridge-arm64-phase-b-live-2026-07-28.md](../../testing/contacts-bridge-arm64-phase-b-live-2026-07-28.md) — die weiteren sechs Berichte sind in ADR-0016 verlinkt. Spike-Quellen (Referenz, kein Produktcode), Vertragsstand: `spikes/contacts-bridge-g3a/PROTOCOL.md` (im Repository, außerhalb des Doku-Baums).
