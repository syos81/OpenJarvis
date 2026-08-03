# Phase A des App-Prozess-Mutationskanals, 2026-08-03

Branch `feat/contacts-app-process-mutation-phase-a-2026-08-03`, Basis
`3a4cb54` (ADR-0020 integriert), isolierter Worktree.

**Phase A baut den Transport — nicht den Provider.** In diesem Stand gibt es
keinen `CNSaveRequest`, kein `CNMutableContact`, keinen Contacts-Schreibcode
und keinen Sidecar-Schreibpfad. Der native Kanal ist ein Fake hinter einem
Entwicklungs-Gate; im Release ist er fail-closed.

## 1. Bestands- und Lückenmatrix gegen ADR-0020

Legende: **erfüllt** · **teilweise** · **fehlt** · **widerspricht** ·
→A = wird in Phase A implementiert · →B..F = spätere Phase.

### 1.1 Backend-Kern

| Vertragspunkt (ADR-0020) | Ist-Zustand | Bewertung | Phase |
|---|---|---|---|
| Freigabe ≠ Ausführung, kein Hintergrundexecutor | `grant`/`execute` getrennt, kein Scheduler | erfüllt | — |
| Outbox-Claim als Serialisierungspunkt | `ExternalActionOutbox.claim()` bedingtes UPDATE, `NOT_CLAIMABLE` | erfüllt | — |
| `provider_send_started` **vor** dem Send, committed | Audit in Claim-UnitOfWork | erfüllt | — |
| `attempt_count` = begonnene Sendversuche (Outbox kanonisch) | wie ADR-0019 §5b | erfüllt | — |
| `recover_interrupted()` beim Start ⇒ `outcome_unknown` | `bootstrap.py` | erfüllt | — |
| `finalize_pending` (C2), Spiegel + Audit | vorhanden, idempotent bei `succeeded` | erfüllt | — |
| Reconcile ohne Namenssuche | `application/reconcile.py` `_judge` | erfüllt | — |
| `resolve_outcome_manually` (5a) | vorhanden, terminal, ohne Providerkontakt | erfüllt | — |
| **`preview_digest` bindet die Freigabe** (L1) | persistiert, **nie geprüft** | widerspricht | **→A** |
| **Feldvertrag v1 auch für Update** (L2) | `update` nutzt ältere `PATCHABLE_FIELDS` | widerspricht | **→A** (Validierung) / →E (Providerweg) |
| **Audit-`stage`-CHECK in der DB** (L3) | nur Python-Menge | fehlt | **→A** |
| **Deklarative Übergangstabelle** (L5) | Wächter verstreut, `_set_state` ohne Vorzustandsprüfung | fehlt | **→A** |
| `manually_resolved_applied` (ADR-0020 §4.1) | nicht vorhanden | fehlt | **→A** |
| Claim-Token nur als Digest | Outbox speichert `claim_token` **im Klartext** | widerspricht | **→A** |
| `operation_id`, `claim_expires_at`, `execution_order_issued_at`, `execution_report_digest`, `error_class`, `error_digest` | nicht vorhanden | fehlt | **→A** |
| ExecutionOrder/ExecutionReport | existieren nicht (Kern rief den Sidecar selbst) | fehlt | **→A** |
| Idempotente Settle-Route | existiert nicht | fehlt | **→A** |
| App-Kanal-Capability-Handshake | existiert nicht | fehlt | **→A** |
| Provider-Aufruf im Kern (`execute` Phase B) | vorhanden (Sidecar) | widerspricht dem neuen Kanal | **→A** (stillgelegt) |

### 1.2 Provider-/Native-Schicht

| Vertragspunkt | Ist-Zustand | Bewertung | Phase |
|---|---|---|---|
| Sidecar `create` produktiv | **implementiert** (`opCreate`, echter `CNSaveRequest`) | widerspricht ADR-0020 §10.2 | **→A** (deaktiviert) |
| Sidecar `update`/`delete` | `not_implemented` | erfüllt | — |
| Sidecar-Handshake `createImplemented` | `true` | widerspricht | **→A** (`false`) |
| `PROTOCOL.md` beschreibt `mutationsImplemented=false` (L4) | Drift zum Code | widerspricht | **→A** (berichtigt) |
| Tauri-Command für ExecutionOrder | existiert nicht | fehlt | **→A** (Fake) |
| Nativer Save im App-Prozess | existiert nicht (nur Spike) | fehlt | →B |
| Read-back nativ | nur Sidecar/Spike | fehlt | →B |
| Lese-/Sync-/Diagnosepfade des Sidecars | vollständig | erfüllt, unverändert | — |

### 1.3 API und Frontend

| Vertragspunkt | Ist-Zustand | Bewertung | Phase |
|---|---|---|---|
| `POST …/execute` | ruft den Provider **im Backend** | widerspricht dem Kanal | **→A** (Claim-Endpunkt daneben; `execute` bleibt bestehen, aber fail-closed ohne Provider) |
| `POST …/claim-app-execution` | fehlt | fehlt | **→A** |
| `POST …/settle-app-execution` | fehlt | fehlt | **→A** |
| Lesende Statusroute für Reload | `GET /mutations/{id}` vorhanden | erfüllt | — |
| Frontend-Transportdienst | fehlt | fehlt | **→A** |
| Frontend berechnet Digests | tut es nicht | erfüllt | — |
| Frontend entscheidet Terminalzustände | tut es nicht | erfüllt | — |
| Rohe Identifier in öffentlichen Modellen | maskiert (ADR-0019 §2 umgesetzt) | erfüllt | — |

**Ergebnis:** Phase A implementiert 12 fehlende und korrigiert 6
widersprechende Punkte. Alles Native (echter Save, Read-back) bleibt
ausdrücklich Phase B.

## 2. Migration 0008 (additiv)

Neuaufbau von `personal_external_action_outbox` (SQLite kann CHECKs nicht
ändern) plus additive Spalten und ein neuer Zustands-CHECK für
`contacts_mutations`:

| Spalte (Outbox) | Zweck |
|---|---|
| `operation_id` | fachliche Kennung des einen Ausführungsversuchs |
| `claim_token_digest` | **ersetzt** `claim_token`; SHA-256, nie Klartext |
| `claim_expires_at` | Verfall **vor** Ausgabe/Validierung |
| `execution_order_issued_at` | ab hier ist kein neuer Claim mehr zulässig |
| `execution_report_digest` | bindet das Settle idempotent |
| `provider_completed_at` | aus dem Report |
| `error_class` / `error_digest` | geschlossene Klasse + PII-armer Digest |

Invarianten als CHECK: `state <> 'claimed' OR claim_token_digest IS NOT NULL`,
`claim_expires_at > claimed_at`, `execution_order_issued_at >= claimed_at`,
`error_class IN (<geschlossene Menge>)`, `length(claim_token_digest) = 64`,
`length(execution_report_digest) = 64`. Eindeutigkeit: `ux_outbox_operation`
auf `operation_id`. `contacts_mutations` erhält
`manually_resolved_applied` im Zustands-CHECK; `personal_audit_log` erhält
den fehlenden `stage`-CHECK (L3).

**Die produktive Datenbank wird in diesem Auftrag nicht migriert** — die
Migration läuft ausschließlich gegen temporäre Testdatenbanken.

## 3. Transportverträge

`ExecutionOrderV1` und `ExecutionReportV1` sind in **drei** Sprachen
definiert:

- Python: `contacts/application/execution_contracts.py` — **normativ**
- TypeScript: `frontend/src/personal/contacts/api.ts` (dort liegt der
  gesamte HTTP-Verkehr des Moduls; der Transportdienst darüber hat keine
  eigene Netzschicht)
- Rust: `frontend/src-tauri/src/contacts_execution.rs`

Gegen Drift sichern zwei Mechanismen, beide gegen die **Python-Quelle**:

1. `tests/personal/contacts/test_state_machine_drift.py` liest die
   Feldnamen der Python-Dataclasses und verlangt sie wörtlich in den
   TypeScript- und Rust-Strukturen; dasselbe für Ausgänge, Operationen,
   Fehlerklassen, Auditstufen und den Zustandsvorrat gegen den SQL-CHECK.
2. Goldene Kanonisierungsvektoren in
   `frontend/src-tauri/src/contacts_execution.rs`
   (`goldene_vektoren_stimmen_mit_dem_kern_ueberein`) halten Rust und Kern
   auf **bitgleicher** JSON-Kanonform — sonst wären die Digests
   verschieden und die Nachrechnung wertlos.

## 4. Claim- und Replay-Vertrag

Der Claim ist atomar (eine UnitOfWork): Zustand prüfen → Freigabe gegen
**beide** Digests verbrauchen → `operation_id` + 32-Byte-CSPRNG-Token
erzeugen → nur Digest persistieren → `attempt_number` festschreiben →
`claimed_at`/`claim_expires_at` setzen → Order bauen →
`execution_order_issued_at` setzen → Audit `execution_claimed` **und**
`provider_send_started`.

**Nach erfolgreicher Ausgabe gibt es keinen zweiten Claim** — weder durch
Verfall noch durch Reload, Absturz oder fehlenden Report. Der einzige Weg
ist `outcome_unknown` → Reconcile bzw. manueller Abschluss. Ein Claim, der
**vor** der Ausgabe scheitert (Zustand, Capability, Digest, Approval), ist
`failed_before_send` — dort wurde beweisbar nichts übergeben.

## 5. Fake-Tauri-Gate

Das Command `personal_contacts_execute_mutation` führt in Phase A **keinen**
Contacts-Code aus. Ohne Entwicklungs-Gate antwortet es
`not_sent / provider_channel_disabled_before_send`. Mit Gate
(`OPENJARVIS_CONTACTS_FAKE_EXECUTION=1`, nur Debug-Builds — im
Release-Profil ist der Zweig auskompiliert) liefert es fünf deterministische
Ergebnisse, gesteuert über ein Feld des kanonischen Payloads:
`applied`, `not_applied_before_send`, `outcome_unknown_after_send`,
`readback_failed_after_send`, `provider_exception_after_send`. Der Fake
erzeugt nie eine reale Providerkennung (nur `fake:`-Digest), ruft nie
Contacts, schreibt nie in eine Datenbank und läuft je Claim genau einmal.

## 6. Settle-Idempotenz

Das Settle rechnet den Report-Digest serverseitig nach und speichert ihn.
Ein zweites Settle mit identischem Digest ist ein No-op mit identischer
Antwort; ein abweichender zweiter Report ist `settle_conflict` (409) ohne
Zustandsänderung. Das Settle erhöht `attempt_number` nie, ruft nie den
Provider und nie Tauri, und entscheidet den Zustand allein serverseitig.

## 7. Zustandsautomat

`contacts/application/state_machine.py` ist die einzige Wahrheit:
`ERLAUBTE_UEBERGAENGE`, `TERMINAL`, `NACH_SEND`. `_set_state` prüft den
Vorzustand gegen die Tabelle. Statiktests halten Python-Vorrat, SQL-CHECK,
API-Schema, Frontend-Typen und ADR-0020 deckungsgleich.

## 8. Was Phase A **nicht** tut

Kein `CNSaveRequest`, kein `CNMutableContact`, kein Contacts-Schreibaufruf,
kein Spike-Aufruf, kein Sidecar-Schreibpfad, kein Sync, keine produktive
Mutation, keine Freigabeausführung gegen die Live-Datenbank, keine
TCC-Änderung. Phase B (nativer Create-Pfad) ist **nicht begonnen**;
ARM64-Abnahme und M2-Pixelabnahme bleiben offen.

## 9. Umgesetzte Artefakte (Stand dieses Commits)

| Schicht | Datei | Inhalt |
|---|---|---|
| Migration | `base/db/migrations/versions/m0008_app_process_channel.py` | Outbox-Neuaufbau (Token-**Digest** statt Klartext, `operation_id`, Verfall, Auftragsausgabe, Report-Digest, Fehlerklasse/-digest, `provider_completed_at`), `manually_resolved_applied`, Audit-`stage`-CHECK |
| Vertrag | `contacts/application/execution_contracts.py` | `ExecutionOrderV1`, `ExecutionReportV1`, geschlossene Mengen, fail-closed Parser, Größenlimits, `report_digest` |
| Automat | `contacts/application/state_machine.py` | Übergangstabelle, `TERMINAL`, `NACH_SEND`, `pruefe_uebergang` |
| Kanal | `contacts/application/app_channel.py` | Handshake, `provider_write_enabled = False` als Konstante |
| Dienst | `contacts/application/app_execution.py` | Claim (Freigabe gegen **beide** Digests, Token-Digest, Verfall, `provider_send_started` vor der Antwort) und idempotentes Settle |
| API | `contacts/api/routes.py`, `api/schemas.py` | `GET /app-channel`, `POST …/claim-app-execution`, `POST …/settle-app-execution` |
| Outbox | `base/outbox.py` | `token_digest`, Digest-Spalte, `recover_claimed_as_unknown` (Wiederanlauf **ohne** Rohtoken) |
| Freigabe | `base/approvals.py` | `consume` bindet Payload **und** Vorschau (L1) |
| Audit | `base/audit.py` | Stufen `execution_order_issued`, `mutation_settled` |
| Sidecar | `native/contacts-bridge/src/sidecar.swift` | alle Write-Capabilities `false`; `create` endet in `capability_denied` **vor** jeder Store-Berührung |
| Rust | `frontend/src-tauri/src/contacts_execution.rs` | Auftragsvalidierung, Digest-Nachrechnung, fünf deterministische Fake-Ausgänge hinter Debug-Gate, Release fail-closed |
| Tauri | `frontend/src-tauri/src/lib.rs` | ein Command `personal_contacts_execute_mutation` mit Einmalwächter je `operation_id` |
| Frontend | `contacts/api.ts`, `contacts/data/executionTransport.ts` | HTTP im Client, Ablauf im Transport; kein Digest, kein Terminalzustand, kein Retry |

## 10. Sidecar-Deaktivierung — Beleg

Der gebaute Sidecar meldet im Handshake `createImplemented: false`,
`updateImplemented: false`, `deleteImplemented: false`,
`mutationsImplemented: false` (live gegen das gebaute Binary geprüft).
`opCreate` antwortet vor jeder Store-Berührung mit
`not_sent / capability_denied`. Der darunterliegende Save-Code (Preflight,
ObjC-Grenze, Uncaught-Letztdiagnose) bleibt als **Beweis- und
Diagnosehistorie** erhalten und wird nie mehr erreicht. Lese-, Sync- und
Diagnosepfade sind unverändert.

## 11. Release-Gate

`provider_write_enabled` ist in Phase A eine **Konstante** (`False`), kein
Schalter. Das Fake-Gate (`OPENJARVIS_CONTACTS_FAKE_EXECUTION=1`) wirkt nur
in Debug-Builds; im Release-Profil ist der Zweig auskompiliert
(`#[cfg(debug_assertions)]`) und keine Umgebungsvariable kann ihn erwecken.
Ohne Gate antwortet das Command `not_sent /
provider_channel_disabled_before_send`.

## 12. Gates und Abnahme (x86_64, macOS 12.7.6)

### 12.1 Testläufe

| Gate | Ergebnis |
|---|---|
| `pytest tests/personal/contacts` | 1103 gesammelt, 1094 bestanden, 9 übersprungen, 0 fehlgeschlagen |
| `pytest tests/personal` | 1094 bestanden, 9 übersprungen |
| `make test` | 8326 bestanden, 65 übersprungen |
| Vitest Kontakte (`src/personal/contacts`) | 5 Dateien, 121 bestanden |
| `npm test` (gesamt) | 6 Dateien, 127 bestanden |
| `npx tsc --noEmit` | fehlerfrei |
| `cargo test` (`frontend/src-tauri`) | 74 bestanden, davon 11 in `contacts_execution` |
| `cargo test` (`rust/`) | 418 bestanden |
| Wheel-Bau + Import in isoliertem Python 3.12 | erfolgreich; `provider_write_enabled=False`, 16 Zustände |
| `git diff --check` | sauber |
| Ruff (Kontakte/Base/Tests) | 80 Befunde — **unverändert** gegenüber der Basis; die sieben neuen Python-Dateien: 0 |
| `mkdocs build --strict` | 18 Warnungen — **unverändert** gegenüber der Basis, keine betrifft Kontakte |

Die neun verbleibenden Übersprungenen sind **sämtlich** arm64-Artefakte, die
auf diesem Intel-Gerät nicht gebaut werden können (Sidecar, Bundle,
Cross-Build) — keiner betrifft den Kanal.

**Erst spät bemerkt, deshalb ausdrücklich:** Die ersten Läufe meldeten 1065
bestanden bei 38 Übersprungenen. Ursache war ein unvollständiges
Environment — dem Worktree fehlten zwischenzeitlich optionale
Abhängigkeiten, wodurch 29 Tests still übersprungen wurden, darunter die
Paketierungstests, die anschliessend einen echten Fehler fanden (12.2).
Nach `uv sync` mit allen benötigten Extras laufen sie. Die hier
ausgewiesenen Zahlen stammen aus dem vollständigen Environment.

Zwei Läufe von `npm test` **unter gleichzeitiger Volllast** (Python-Suite und
Rust-Build parallel) meldeten 4 bzw. 3 Fehler, sämtlich Zeitüberschreitungen
in den DEV-Fixture-Nullaufruftests (`bootstrap.test.tsx`,
`ContactsPage.test.tsx`). Allein ausgeführt sind dieselben Tests grün
(127/127). Das ist eine Zeitempfindlichkeit dieser Tests, kein Befund am
Kanal — festgehalten, weil sie unter Last erneut auftreten wird.

### 12.2 Gepackte App

Release-Bau `--target x86_64-apple-darwin --bundles app`, danach von innen
nach aussen mit dem **produktiven** Zertifikat „de.kluender.jarvis" neu
versiegelt:

* `codesign --verify --deep --strict`: gültig.
* DR App: `identifier "de.kluender.jarvis" and certificate leaf = H"34a4…"`;
  DR Sidecar: `identifier "de.kluender.jarvis.contacts-bridge"` mit demselben
  Blatt — zertifikatsgebunden statt cdhash-gebunden, damit eine einmal
  erteilte TCC-Berechtigung Neubauten überlebt.
* Hardened Runtime aktiv; Entitlement
  `com.apple.security.personal-information.addressbook` in App **und**
  Sidecar vorhanden.

**Korrektur im Verlauf, offen protokolliert:** Zwischenzeitlich war das
Bundle mit dem Zertifikat „Personal Jarvis Contacts Spike" versiegelt — aus
der Gewohnheit der Spike-Phase. Das widerspricht dem eigenen Vertrag des
Repos: `test_keine_spike_identitaet_im_paket` verbietet jede Spike-Identität
in Info.plist und Signatur des Pakets, während
`test_sidecar_signatur_ist_nicht_ad_hoc` und
`test_sidecar_designated_requirement_ist_zertifikatsgebunden` zugleich eine
zertifikatsgebundene Signatur verlangen — zusammen also genau das produktive
Zertifikat. Diese drei Tests waren zunächst **übersprungen**, weil dem
Environment die Paketierungsabhängigkeiten fehlten (siehe 12.1); nach deren
Nachinstallation haben sie den Fehler gefunden, und das Bundle wurde mit
`de.kluender.jarvis` neu versiegelt. Für Phase A ist der Zwischenstand
folgenlos, weil in diesem Durchlauf ohnehin kein Kontaktzugriff und damit
keine TCC-Entscheidung stattfand.

Statische Befunde am Release-Binary:

| Prüfung (App-Binary `openjarvis-desktop`) | Befund |
|---|---|
| `OPENJARVIS_CONTACTS_FAKE_EXECUTION` als Zeichenkette | **0 Treffer** — das Gate ist im Release nicht einmal benennbar |
| `CNSaveRequest` / `CNMutableContact` (Symbole und Zeichenketten) | **0 Treffer** |
| `provider_channel_disabled_before_send` | vorhanden — der einkompilierte Zweig ist der fail-closed |

Im **Sidecar**-Binary finden sich weiterhin vier Treffer auf
`CNSaveRequest`/`CNMutableContact`: das ist der stillgelegte Save-Pfad, der
als Beweis- und Diagnosehistorie erhalten bleibt (§10) und seit ADR-0020
nicht mehr erreicht wird — `opCreate` antwortet davor mit
`capability_denied`, das ebenfalls im Binary steht.

### 12.3 Sicherer Livedurchlauf

Gestartet wurde die gepackte App, **ohne** den Kontaktebereich zu öffnen:
kein Sync, keine Mutation, keine Freigabe, kein Tauri-Mutationskommando,
kein Kontakt gelesen oder geschrieben.

| Prüfung | Befund |
|---|---|
| Backend erreichbar | ja (`/health` meldet `Engine unhealthy` — Ollama läuft nicht; das ist der Modellstatus, nicht der Serverstatus) |
| `GET /v1/personal/contacts/app-channel` | `provider_write_enabled: false`, `create_supported: true`, `update/delete: false`, `channel: app_process` |
| Sidecar-Prozess während der Laufzeit | keiner |
| Sidecar-Handshake aus dem Bundle (kontaktfrei) | `mutationsImplemented/create/update/delete` alle `false`, `ping` ok |
| Cmd+Q bis Prozessende | **2,64 s** (Grenze 8 s), nur über SIGTERM |
| Restprozesse | 0 |
| Port 8000 | frei |
| `serve.lock` | entfernt |

### 12.4 Produktive Datenbank — ehrlicher Befund

Die Datei ist **nicht** byteidentisch: der Start der gebauten App wendet
Migration 0008 an (Ledgereintrag `0008`, 2026-08-03T18:11:24Z). Das ist die
beabsichtigte Wirkung dieses Commits, kein Nebeneffekt des Livedurchlaufs.

Vor dem Start wurde eine byteidentische Sicherung angelegt
(`personal/jarvis.db.pre-0008.bak`, 0600 im 0700-Ordner) und die Migration
**zuerst auf einer Kopie** geprüft. Zeilenweiser Vergleich Sicherung ↔
produktive Datenbank über alle 26 Tabellen:

* abweichend: `personal_migration_ledger` (7 → 8 Zeilen) und
  `personal_external_action_outbox` (5 → 5 Zeilen; `claim_token` entfällt, acht
  Spalten kommen hinzu, **alle gemeinsamen Spalten Zeile für Zeile
  identisch**);
* alle übrigen 24 Tabellen inhaltlich unverändert, insbesondere `contacts`
  mit 117 Zeilen vor und nach dem Lauf.

Kein Datensatz ging verloren, keiner wurde verändert. Wer Byteidentität
braucht, hat sie in der Sicherung.

> **Nachtrag 2026-08-03 (Härtung).** Dieser Zustand wurde zurückgenommen:
> Die produktive Datenbank steht wieder byteidentisch auf dem Vor-0008-Stand,
> und der Smoke läuft seither in einem Wegwerfprofil. Was oben steht, bleibt
> als Protokoll des Fehlstands stehen; der aktuelle Stand ist Abschnitt 13.

## 13. Härtung der Abnahme (2026-08-03, Nachtrag)

Drei Punkte des ersten Phase-A-Abschlusses waren nicht tragfähig. Sie sind
hier geschlossen; kein Satz der Abschnitte 1–12 wurde dafür gelöscht oder
umgeschrieben.

### 13.1 Der Smoke lief gegen die produktive Datenbank

**Ursache, belegt.** `open` startet über LaunchServices; die geerbte
Umgebung ist die von `launchd`, nicht die der Shell. Ein `export
OPENJARVIS_HOME=…` vor dem Aufruf erreicht die App also nicht. Die App
selbst reicht an ihr Backend nur weiter, was sie ausdrücklich setzt
(`OPENJARVIS_PERSONAL_ENABLED`, `PERSONAL_JARVIS_CONTACTS_SIDECAR` in
`lib.rs`); alles Übrige stammt aus ihrer eigenen Umgebung. Ohne Zutun endet
`openjarvis.core.paths.get_config_dir` damit bei `~/.openjarvis`, und
`PersonalBootstrap` migriert die dortige Datei. Es war kein Tippfehler im
Aufruf, sondern ein fehlender Vertrag.

**Wiederherstellung.** Die migrierte Datei wurde zuerst forensisch gesichert
(`personal/jarvis.db.post-0008.forensic.bak`), dann durch eine Kopie der
Vor-Migrationssicherung ersetzt — über `os.replace`, also atomar innerhalb
desselben Dateisystems, mit vorherigem `fsync` und anschliessendem
Verzeichnis-`fsync`. Die WAL- und SHM-Beidateien wurden dabei entfernt: sie
gehören zur ersetzten Datenbank, und ein Neustart mit fremdem WAL ist ein
Datenverlustrisiko. Keine Gegenmigration, kein einzelnes `UPDATE`.

| Nachweis | Wert |
|---|---|
| SHA-256 vor Migration | `f73bab74…7852b855` |
| SHA-256 nach Fehl-Smoke | `ccff1189…10407c1f` |
| SHA-256 nach Wiederherstellung | `f73bab74…7852b855` (byteidentisch zur Sicherung) |
| Ledger nach Wiederherstellung | 7 Einträge, `0008` **nicht** enthalten |
| Outbox-Schema | wieder 0007 (16 Spalten, `claim_token`) |
| `PRAGMA integrity_check` | ok |
| Kontakte / External Identities | 117 / 117 |
| Mutationen / Audit-Ereignisse | 5 / 40 |
| offene Tombstones | 0 |
| Rechte | Datei 0600, Verzeichnis 0700 |

Beide Sicherungen bleiben liegen (0600 im 0700-Ordner) und werden nicht
automatisch entfernt.

**Neuer Vertrag.** `scripts/personal/phase_a_smoke.py` legt ein
0700-Wegwerfprofil an (eigenes `OPENJARVIS_HOME`, eigene `config.toml` mit
abgeschaltetem Analytics, eigene Datenbank, eigene Sperre) und übergibt es
über `open --env OPENJARVIS_HOME=…`. Vor dem Start prüft er fail-closed:
Profil vorhanden und 0700, Analytics aus, **wirksamer** Datenbankpfad —
erfragt beim Produktivcode selbst, nicht nachgebaut — liegt im Profil, zeigt
nicht auf die produktive Datei und nicht in `~/.openjarvis`, und die
produktive Datei existiert mit einem Vergleichshash. Der produktive Pfad
wird dabei **ohne** `OPENJARVIS_HOME` bestimmt; sonst prüfte die Bedingung
gegen genau die Datei, die sie meiden soll. Scheitert eine Bedingung,
startet nichts.

Das Werkzeug liegt bewusst unter `scripts/` und nicht im Paket: ein
Abnahmehelfer im Wheel wäre Testlogik im Produktpfad. Am Produktpfad selbst
wurde nichts geändert — `OPENJARVIS_HOME` gab es vorher.

### 13.2 Ein Release meldete Create als unterstützt

Der erste Stand meldete `create_supported: true` bei
`provider_write_enabled: false`. Das war irreführend: Phase B hat nicht
begonnen, ein nativer Save existiert nicht. **Unterstützt heisst ab jetzt
ausführbar.**

| Feld | Release (jeder Build dieses Stands) |
|---|---|
| `channel` | `app_process` |
| `channel_mode` | `disabled` |
| `provider_write_enabled` | `false` |
| `create_supported` | `false` |
| `update_supported` | `false` |
| `delete_supported` | `false` |

Der synthetische Kanal (`fake_debug_capabilities`) ist die einzige Stelle,
die überhaupt eine Schreibfähigkeit erzeugt. Er ist ein Aufruf, kein
Schalter: er steht in keiner Route, keinem Startpfad und keiner
Umgebungsvariablen — ein gepacktes Release erreicht ihn nicht. Sein
`channel_mode` heisst ausdrücklich `fake_debug`, damit niemand die Wahrheit
im Flag sucht statt im Modus.

Weiter gilt:

* Der Claim prüft **`provider_write_enabled` UND** die Fähigkeit *genau
  dieser* Operation (`darf_ausfuehren`). Ein Kanal mit `create` beansprucht
  damit kein `delete`. Ohne Fähigkeitssatz gibt es gar keinen Auftrag.
* Widersprüchliche oder unbekannte Handshakes werfen
  (`InconsistentCapabilities`): Operation ohne Schreibrecht, Schreibrecht bei
  abgeschaltetem Kanal, fremder Kanal, unbekannter Modus.
* Das Frontend wendet dieselbe Konjunktion an (`kanalErlaubt`) und kann
  nichts freischalten — es liest ausschliesslich die Serverantwort.
* Der Sidecar bleibt bei allen Schreibfähigkeiten `false`.
* Die Statusfläche sagt im Klartext: **„Transport vorbereitet,
  Provider-Schreiben deaktiviert."**

### 13.3 Die Fixture-Tests waren unter Last unzuverlässig

**Ursache, belegt und nicht geraten.** In jsdom gibt es kein Layout, also
meldet der Listencontainer `clientHeight === 0`. Die Fensterung der Liste
hing an `viewport > 0` — sie war damit **inert**, und jeder Render stellte
*alle* Zeilen in den DOM (1.000 im Bootstrap-Szenario). Jeder Tastendruck
von `userEvent.type` löste einen weiteren solchen Render aus. Darüber lag
die entprellte Suche (150 ms), deren Ergebnis die Liste **nach** dem
`waitFor` noch einmal austauschte: ein offener Timer, der den Test
überholte. Die Zusicherungen hingen an RTLs Standardfenster von **1000 ms**
— nicht am 5-Sekunden-Testtimeout. Unter paralleler Last reichte das nicht.

**Behebung.**

* Die Liste fenstert jetzt auch ohne gemessene Höhe (`ANNAHME_VIEWPORT`,
  2000 px). Das ist kein Testzugeständnis, sondern behebt dieselbe
  Verschwendung im ersten Browser-Frame vor der Messung.
* Die Bootstrap-Tests warten nicht mehr auf Uhrzeit: `montiere` rendert in
  `act`, lässt Mikrotasks und den Entprell-Timer ablaufen und hinterlässt
  keinen offenen Timer.
* Der Demo-Endpunkttest wartet auf einen echten Endzustand — die Änderung
  von `aria-setsize`, die erst *nach* der entprellten Suche eintreten kann —
  statt auf „die Liste existiert", was schon vorher wahr war.

Keine Wiederholung, kein pauschal erhöhter Timeout, kein serialisierter oder
entfernter Test.

| Test | vorher (unter Last) | jetzt (unter Last) |
|---|---|---|
| Nullaufruf, volles Szenario | 4906 ms → Fehler | 676 ms |
| Nullaufruf, Bearbeiten | 1485 ms → Fehler | 438 ms |
| Demo-Endpunkte | 5243 ms → Fehler | 754 ms |

**Stabilitätsnachweis:** Kontakte-Suite 5× nacheinander (je 130/130),
`npm test` 5× (je 136/136), zusätzlich 3× parallel zu `make test` und einem
Cargo-Build (je 136/136). Null Timeouts, null Wiederholungen, in jedem Lauf
dieselbe Testanzahl.

### 13.4 Gepackte App und isolierter Smoke

Neu gebaut (`--target x86_64-apple-darwin`), von innen nach aussen mit dem
produktiven Zertifikat `de.kluender.jarvis` versiegelt:

| Prüfung | Befund |
|---|---|
| Architektur App / Sidecar | Mach-O 64-bit x86_64 / x86_64 |
| `codesign --verify --deep --strict` | gültig |
| Hardened Runtime | `flags=0x10000(runtime)` in App **und** Sidecar |
| DR App | `identifier "de.kluender.jarvis" and certificate leaf = H"34a4…"` |
| DR Sidecar | `identifier "de.kluender.jarvis.contacts-bridge"`, dasselbe Blatt |
| Spike-Identität | 0 Treffer in beiden Signaturen |
| Entitlement `…addressbook` | in App und Sidecar vorhanden |
| `OPENJARVIS_CONTACTS_FAKE_EXECUTION` im App-Binary | 0 Treffer |
| `CNSaveRequest`/`CNMutableContact` im App-Binary | 0 Treffer |
| Binary im Git-Diff | keins (`binaries/.gitignore`, `target/` ungetrackt) |

Der Smoke lief ausschliesslich im Wegwerfprofil:

| Prüfung | Befund |
|---|---|
| Vorbedingungen | erfüllt (Profil 0700, wirksamer Pfad im Profil, produktive Datei mit Vergleichshash) |
| App startet, temporäres Backend gesund | ja |
| Migration 0008 | **nur** in der temporären Datenbank (Ledger 1–8, 0 Kontakte) |
| Release-Handshake | `channel_mode: disabled`, `provider_write_enabled: false`, `create/update/delete_supported: false` |
| Sidecar-Prozesse während der Laufzeit | 0 |
| Sidecar-Handshake aus dem Bundle | alle vier Schreibfähigkeiten `false` |
| Kontaktebereich / Sync / Mutation / Tauri-Kommando | nicht geöffnet, nicht ausgelöst |
| Cmd+Q bis Prozessende | **1,07 s** — nur `quit`, **kein** Signal geschickt, weder SIGTERM noch SIGKILL |
| Restprozesse | 0 |
| Port 8000 | frei |
| Temporäre Sperre | freigegeben; die `serve.lock`-Datei bleibt nach `ProcessLock.release` bewusst liegen (Sperre hängt am Deskriptor, Datei dient der Port-Discovery) und verschwindet mit dem Profil |
| Produktive Datenbank vor/nach | `f73bab74…7852b855` = `f73bab74…7852b855`, Ledger weiterhin 7 |

**Nebenbefund, festgehalten:** Die gepackte App startet ihr Backend über
`uv run jarvis serve`. `uv run` synchronisiert dabei die Projektumgebung auf
die Standardgruppen des Lockfiles und **entfernt** die optionalen Extras
(dev, server, docs). Wer nach einem Smoke Tests, Ruff oder MkDocs laufen
lässt, muss vorher `uv sync` mit den Extras wiederholen — sonst wirken
fehlende Werkzeuge wie ein Testbefund. Das betrifft nur den Arbeitsbaum,
nicht das Produkt.

## 13. Offen

Phase B (nativer Create-Pfad im App-Prozess) ist **nicht begonnen**. Es gibt
in diesem Stand keinen `CNSaveRequest`, kein `CNMutableContact`, keinen
Contacts-Schreibaufruf, keinen Sync und keine produktive Mutation. Die
ARM64-Abnahme (Phase C/D) und die M2-Pixelabnahme des Frontends bleiben
unverändert offen.
