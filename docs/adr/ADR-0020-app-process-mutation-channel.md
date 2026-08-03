---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-08-03
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-10, AV-33, AV-35
Zugehörige ADRs: ADR-0005 (Command-Bus), ADR-0006 (Risikoklassen), ADR-0007 (Outbox), ADR-0014 (Tauri-Capabilities), ADR-0016 (Swift-Sidecar), ADR-0018 (Dual-Architektur), ADR-0019 (Mutationsarchitektur)
Verwandte DEC-Einträge: DEC-044 (Basis), DEC-045 (dieser ADR); DEC-D06 (offen, Voraussetzung für Delete), DEC-D17 (offen, unberührt)
---

# ADR-0020: Der App-Prozess-Mutationskanal (Backend → Claim → Frontend → Tauri → Contacts.framework → Settle)

- **ADR-Status:** accepted
- **Datum:** 2026-08-03

Dieser ADR friert den **Transportkanal** der Apple-Contacts-Mutationen ein.
Er ersetzt **additiv** die Kanalfestlegung aus ADR-0019 §4 (CLI-Sidecar als
Schreibkanal); alle übrigen Festlegungen von ADR-0019 — Freigabekern,
at-most-once, Feldvertrag v1, Ergebnisvertrag, Zustandserweiterungen,
Red-Team-Tabelle — gelten unverändert weiter und werden hier nur dort
präzisiert, wo der Kanalwechsel es erzwingt. Er entscheidet **Architektur,
keine Implementierung**: bei seiner Annahme existiert kein produktiver
App-Prozess-Schreibpfad, und in diesem Auftrag wird keiner gebaut.

## 1. Kontext: belegter Ist-Zustand (2026-08-03, Commit `999265d`)

Getrennt nach Beweislage. **Belegt** (Quelltext-/Livebefund, read-only
nachgeprüft):

1. **Der CLI-Sidecar-Create ist implementiert und crasht live.** `opCreate`
   (`native/contacts-bridge/src/sidecar.swift:744-925`) führt einen echten
   `CNSaveRequest` aus — mit ObjC-Grenze (§4a), Uncaught-Letztdiagnose und
   Schreibstack-Preflight (§4b). Vier x86_64-Livetests (2026-08-01/02)
   endeten trotz allem in `NSInternalInconsistencyException`: Der Save lief
   auf einem `NSPersistentStoreCoordinator` **ohne angehängte Stores**. Der
   Preflight machte daraus ein sicheres `not_sent`
   (`write_stack_unavailable`) — der nackte CLI-Prozess **kann** den
   Apple-Schreibstack auf diesem System nicht initialisieren; der Lesepfad
   desselben Prozesses läuft fehlerfrei.
2. **Der App-Prozess-Save funktioniert.** Der AppSave-Spike (Worktree
   `Jarvis-Next-Contacts-AppSave-Spike`, `19f36d9`) hat am 2026-08-02 auf
   x86_64 live **APPLIED** geliefert: ein `CNSaveRequest` im
   Jarvis.app-Prozess (Tauri), ein Kontakt im lokalen Container, Read-back
   bestätigt, manuell rückstandslos gelöscht. Ablauf: Autorisierung lesen →
   genau ein lokaler Container → Lese-Preflight → **ein** Save →
   Read-back (`JCContactsAppSaveSpike.m:269-356`).
3. **Die Backend-Pipeline ist vollständig und gehärtet.** `prepare → grant →
   execute` mit Outbox-Claim (bedingtes UPDATE, `base/outbox.py:144`),
   verbrauchter Freigabe mit Digestbindung (`base/approvals.py:194`),
   `provider_send_started` **vor** dem Provider-Aufruf in derselben
   UnitOfWork (`mutation_service.py:384-392`), `recover_interrupted()` beim
   Start (fail-closed → `outcome_unknown`), `finalize_pending` (C2),
   `reconcile` ohne Namenssuche, `resolve_outcome_manually` (5a) und
   16-stufiger, hash-verketteter Auditspur.
4. **Der Ausführungsweg ist heute In-Process:** `execute()` ruft den
   Provider (`ContactsBridgeMutationProvider.apply`) im **Backend-Prozess**,
   der je Aufruf einen Sidecar-Prozess startet. Es gibt weder Claim-Token
   nach außen noch eine Settle-Route — beides existierte nie, weil der Kern
   selbst sendete.
5. **Tauri kennt genau zwei Contacts-Kommandos** (Status, TCC-Anfrage),
   beide lesend bzw. dialogauslösend; der Spike-Code (Env-Gate, Phrase,
   Nonce, fixe Payload) liegt ausschließlich im Spike-Worktree.

**Belegte Vertragslücken** (Audit 2026-08-03, unten normativ geschlossen):

- L1: `preview_digest` wird persistiert, aber **nirgends geprüft** —
  `consume()` bindet nur den `payload_digest`.
- L2: `update` validiert gegen die ältere Allowlist
  `commands.PATCHABLE_FIELDS` statt gegen den Feldvertrag v1; die Listen
  widersprechen sich (`social_profiles`, `instant_messages`).
- L3: `personal_audit_log.stage` hat keinen DB-CHECK; die geschlossene
  Stufenmenge lebt nur in Python.
- L4: `PROTOCOL.md` behauptet `mutationsImplemented=false` und widerspricht
  damit dem implementierten Sidecar-Create.
- L5: Es gibt keine deklarative Übergangstabelle; `_set_state` prüft keinen
  Vorzustand (die Wächter liegen verstreut an den Aufrufstellen).

**Akzeptierte Architektur** (aus ADR-0019, unverändert): at-most-once mit
`outcome_unknown` statt Retry; Freigabe ≠ Ausführung; keine Namenssuche;
keine rohen Identifier in öffentlichen Verträgen; Feldvertrag v1;
`succeeded` erst nach Provider-Beleg + Read-back + Spiegel + Audit.

**Hypothese (PROBABLE, nicht bewiesen):** Der CLI-Crash ist eine
Eigenschaft des nackten, GUI-losen Prozesskontexts (fehlende
AddressBookCore-Initialisierung). **Nicht** Entscheidungsgrundlage — die
Entscheidung stützt sich allein auf die beiden belegten Fakten 1 und 2.

## 2. Entscheidung im Kern

**Produktive Apple-Contacts-Writes laufen ausschließlich im
Tauri-App-Prozess.** Der Kanal ist:

```
Backend (prepare → Vorschau → Freigabe)
  → Backend claimt genau einen Sendversuch          [POST …/execute]
  → kurzlebiger, gebundener Ausführungsauftrag      [ExecutionOrder v1]
  → Frontend transportiert (dumm, entscheidet nichts)
  → Tauri-Command validiert und führt nativ aus     [ein CNSaveRequest]
  → Read-back bzw. Abwesenheitsnachweis             [im selben Command]
  → typisiertes Ergebnis                            [ExecutionReport v1]
  → Frontend sendet an idempotente Settle-Route     [POST …/settle]
  → Backend führt Spiegel, External-ID, Mutation, Audit nach
```

Der CLI-Sidecar bleibt für **Lesen, Sync und Diagnose** zulässig und
verliert seine produktive Schreibroute (§10). Der AppSave-Spike-Code wird
**nicht** als Produktcode übernommen; extrahiert werden dürfen die
benannten neutralen Hilfsfunktionen (§10.3).

### 2.1 Schichtverantwortung (normativ, je Schritt genau eine Schicht)

| # | Schritt | Verantwortliche Schicht |
|---|---|---|
| 1 | Draft erstellen/ändern | Frontend (Editor); keine Providerlogik |
| 2 | Kanonische Vorschau | Backend (`prepare`, Feldvertrag v1) |
| 3 | Digest-Bindung Payload+Vorschau | Backend (`base/digest.py`, einzige Quelle) |
| 4 | Freigabe exakt dieser Bindung | Mensch via Backend (`grant`; nie `llm_assisted`/`automation`/`system`) |
| 5 | Claim genau eines Sendversuchs | Backend (Outbox `claim()`, BEGIN IMMEDIATE) |
| 6 | Kurzlebiger Ausführungsauftrag | Backend erzeugt, Frontend hält ihn nur im Speicher |
| 7 | Auftrag/Claim/Digest/Typ validieren | Tauri (Rust), fail-closed vor jedem FFI |
| 8 | Native Operation | Tauri-App-Prozess (ObjC/Swift-Helfer, Contacts.framework) |
| 9 | Höchstens ein `CNSaveRequest` je Claim | Native Schicht (ein `executeSaveRequest`-Aufruf im Codepfad) + Rust-Einmalwächter |
| 10 | Read-back / Abwesenheitsnachweis | Native Schicht, im selben Command |
| 11 | Typisiertes Ergebnis | Tauri → Frontend (geschlossenes Schema) |
| 12 | Settle | Frontend ruft, Backend entscheidet; Route idempotent |
| 13 | Spiegel/External-ID/Mutation/Audit | Backend (`finalize_pending`-Familie, UnitOfWork) |
| 14 | Antwortverlust ⇒ nie erneuter Send | Backend (Claim verbraucht) + Tauri (Einmalwächter) |
| 15 | Unklar ⇒ `outcome_unknown` + Reconcile | Backend; niemals Retry |

Das Frontend entscheidet **nie** über Terminalzustände, interpretiert keine
Fehlklassen um und hält keinen Auftrag über die Sitzung hinaus.

## 3. Operation- und Claim-Identität

| Wert | Entsteht | Persistenz | Transport | Audit | UI/Logs |
|---|---|---|---|---|---|
| `mutation_id` | `prepare` | `contacts_mutations` (36 Zeichen) | ja | ja | ja (lokale Kennung) |
| `approval_id` | `prepare` | `personal_approvals` | nein (nur Backend-intern) | ja | ja |
| `operation_id` | Claim | Outbox-Zeile (neue Spalte) | ja | ja | ja |
| `claim_token` | Claim | **nur als SHA-256-Digest** (`claim_token_digest`, ersetzt den heutigen Klartext) | ja (einmalig, im Auftrag) | nur Digest | **nie** |
| `payload_digest` | `prepare` | ja | ja | ja | ja (Hexwert unbedenklich) |
| `preview_digest` | `prepare` | ja | ja | ja | ja |
| `operation_type` | `prepare` | `command` | ja | ja | ja |
| `provider_target` | `prepare`/Claim | intern roh (`contacts_mutations.container_identifier` / `target_provider_identifier`) | ja — **nur im Auftrag**, nie in einer normalen API-Antwort | maskiert (`container_ref`/`account_ref`) | **nie roh** |
| `provider_identifier_digest` | Ergebnis | Outbox-/Mutationszeile | ja | ja | ja (nur Digest) |
| `expected_revision` | `prepare` | ja | ja | ja | ja (lokale Revision) |
| `attempt_number` | Claim | Outbox `attempt_count` (kanonisch, ADR-0019 §5b) | ja | ja | ja |
| `claimed_at` | Claim | Outbox | nein | ja | ja |
| `claim_expires_at` | Claim | Outbox (neue Spalte) | ja | ja | ja |
| `send_started_at` | Claim (identisch mit `provider_send_started`-Audit) | `execution_started_at` | nein | ja | ja |
| `provider_completed_at` | Settle (aus dem Report) | Mutationszeile | ja (im Report) | ja | ja |
| `settled_at` | Settle | Outbox `settled_at` | nein | ja | ja |

Verbindlich:

- **Replay-Schutz:** Der `claim_token` ist 32 Bytes CSPRNG, wird genau
  einmal im Ausführungsauftrag transportiert und nur als Digest persistiert.
  Settle verlangt den Klartext-Token; das Backend vergleicht den Digest.
  Ein zweites Settle mit demselben Token ist idempotent (Antwort =
  gespeichertes Ergebnis, keine Zustandsänderung); ein Settle mit fremdem
  oder fehlendem Token ist `settle_conflict` (409) und ändert nichts.
- **Verbrauchter Claim:** Die Outbox kennt je Subjekt höchstens einen
  Claim (`NOT_CLAIMABLE`-Menge, unverändert). Ein zweiter `execute` nach
  Claim scheitert typisiert; ein zweiter Tauri-Aufruf mit derselben
  `operation_id` scheitert am prozesslokalen Einmalwächter und liefert
  das gemerkte Ergebnis, ohne den nativen Pfad erneut zu betreten.
- **`send_started` bleibt beim Claim.** Sobald der Ausführungsauftrag das
  Backend verlassen haben **kann**, muss das System annehmen, dass ein
  Send geschieht — die Crash-Wahrheit von ADR-0019 gilt kanalunabhängig.
  Deshalb wird `provider_send_started` weiterhin in der Claim-Transaktion
  auditiert, **bevor** der Auftrag die Antwort verlässt.
- **Claim-Verfall:** `claim_expires_at = claimed_at + 10 min`. Der Verfall
  wirkt ausschließlich **vor** der nativen Validierung: Tauri lehnt einen
  abgelaufenen Auftrag als `expired_claim_before_send` ab (`not_sent`).
  Nach Ablauf **ohne** Settle stuft der vorhandene Wiederanlauf- bzw. ein
  ausdrücklich nutzergestarteter Abgleich den Vorgang als
  `outcome_unknown` ein. **Ein verfallener Claim erlaubt niemals einen
  neuen Send**, denn `provider_send_started` ist bereits festgeschrieben —
  ob der alte Auftrag noch irgendwo ausgeführt wurde, ist prinzipiell
  unbeweisbar; der einzige Weg ist der Abgleich (Fakten 12/15, ADR-0019).
- **Absturzmatrix zwischen den Zeitpunkten:** vor Claim-Commit ⇒ kein
  Vorgangsschaden (Claim nie vergeben); nach Claim, vor Tauri-Aufruf ⇒
  `recover_interrupted`/Ablauf ⇒ `outcome_unknown`; nach Save, vor Report ⇒
  Tauri-Einmalwächter hält das Ergebnis prozesslokal — stirbt die App, gilt
  `outcome_unknown` + Reconcile; nach Report, vor Settle ⇒ Frontend darf
  das Settle mit demselben Token wiederholen (idempotent), sonst
  `outcome_unknown` + Reconcile; nach Settle ⇒ terminal bzw.
  `provider_applied_pending_reconcile` → `finalize_pending`.

## 4. At-most-once-Zustandsautomat

Die Auftragszustände bilden auf den bestehenden, migrierten Zustandsvorrat
ab (m0007, 15 Werte). **Abbildungstabelle** (Auftragsbegriff → persistenter
Zustand):

| Auftragsbegriff | Persistenter Zustand | Anmerkung |
|---|---|---|
| `prepared` | `prepared` → sofort `awaiting_approval` | wie heute |
| `awaiting_approval` | `awaiting_approval` | |
| `approved` | `approved` | |
| `claimed` | `executing` | Outbox `claimed` + Audit `execution_claimed` |
| `send_started` | `executing` (Audit-Stufe `provider_send_started`) | keine eigene Spalte — der Auditeintrag ist die Wahrheit |
| `provider_applied` | `provider_applied_pending_reconcile` | via Settle mit `outcome=applied` |
| `provider_not_applied` | `failed_before_send` | via Settle mit `outcome=not_sent` (Beweis „nichts übergeben") |
| `failed_before_send` | `failed_before_send` | Precheck/Claim-Fehler ohne Auftragsausgabe |
| `outcome_unknown` | `outcome_unknown` | Settle `outcome=outcome_unknown`, Verfall, Absturz, Antwortverlust |
| `settled_applied` | `succeeded` | erst nach C2 (Spiegel + Audit) |
| `settled_not_applied` | `failed_before_send` (terminal) | Settle schließt Outbox |
| `manual_decision_required` | `manual_decision_required` | |
| `manually_resolved_not_applied` | `manually_resolved_not_applied` | 5a, unverändert |
| `manually_resolved_applied` | **neu**, terminal (§4.1) | |

**Zulässige Übergänge** (alles andere ist verboten; die Implementierung
Phase A führt eine **deklarative Übergangstabelle** ein und schließt damit
L5):

```
prepared → awaiting_approval
awaiting_approval → approved | rejected | expired | cancelled
approved → executing                      [Claim; genau einmal]
approved → failed_before_send             [Precheck scheitert vor Claim-Ausgabe]
executing → provider_applied_pending_reconcile   [Settle applied]
executing → failed_before_send            [Settle not_sent]
executing → outcome_unknown               [Settle unknown | Verfall | recover_interrupted]
provider_applied_pending_reconcile → succeeded   [finalize_pending / Reconcile]
outcome_unknown → reconcile_required      [Reconcile Phase A]
reconcile_required → succeeded | failed | manual_decision_required
outcome_unknown | manual_decision_required → manually_resolved_not_applied
outcome_unknown | manual_decision_required → manually_resolved_applied   [§4.1]
```

**Terminal:** `succeeded`, `rejected`, `expired`, `cancelled`, `failed`,
`failed_before_send`, `manually_resolved_not_applied`,
`manually_resolved_applied`. Terminal heißt: kein Übergang hinaus, kein
Claim, kein Settle mit Wirkung, kein Send — je ein Audit-Ereignis pro
Übergang (bestehende 16 Stufen + neu `mutation_settled` und
`mutation_outcome_manually_resolved` mit `decision=applied_observed`).

**Verhaltensmatrix** (ergänzt die Red-Team-Tabelle aus ADR-0019 §10 um die
Kanalfälle):

| Fall | Verhalten |
|---|---|
| Doppelter Claim | zweiter `execute` ⇒ `MutationNotExecutable`/`AlreadySettled`; Outbox-`rowcount != 1` ist der Serialisierungspunkt |
| Doppelter Tauri-Aufruf | Einmalwächter je `operation_id` liefert das gemerkte Ergebnis; **kein** zweiter nativer Pfad |
| Doppeltes Settle | gleicher Token ⇒ idempotente Antwort; fremder Token ⇒ 409 `settle_conflict`, keine Änderung |
| Frontend-Neuladen zwischen Claim und Settle | Auftrag ist verloren (nur im Speicher) ⇒ kein Send mehr möglich aus dem Frontend; Vorgang läuft in Verfall ⇒ `outcome_unknown` ⇒ Reconcile |
| App-Absturz | wie Neuladen; war der Save schon durch, findet der Reconcile den Beleg |
| Backend-Absturz nach Claim | `recover_interrupted()` ⇒ `outcome_unknown`; ein evtl. noch laufender Tauri-Save wird beim Settle gegen den Zustand geprüft — Settle auf `outcome_unknown` ist zulässig und trägt das Ergebnis nach (idempotent, ohne neuen Send) |
| Netzverlust Frontend↔Backend beim Settle | Frontend wiederholt **nur das Settle** (idempotent, gleicher Token); nie den Tauri-Aufruf |
| Save erfolgreich, Antwort verloren | `outcome_unknown` ⇒ Reconcile über Autor-Probe/Identifier — nie Namen |
| Exception vor Save (Preflight/Validierung) | `not_sent` ⇒ `failed_before_send`; beweisbar nichts übergeben |
| Exception nach Save-Übergabe | `outcome_unknown` (`objc_exception`), Uncaught-Diagnose; **niemals** `not_sent` |
| Automatische Wiederholung nach `send_started` | **verboten — ausnahmslos.** Kein Timer, kein Executor, kein „Retry"-Knopf; ein neuer Versuch ist eine neue freigabepflichtige Mutation |

### 4.1 Neuer Terminalzustand `manually_resolved_applied`

Symmetrie zu 5a: Der Mensch hat den Provider außerhalb von Jarvis geprüft
und die Änderung **gesehen**, aber der Abgleich kann sie nicht beweisen
(z. B. Create ohne gemeldete Identität und ohne Autor-Probe-Treffer).
Route: dieselbe `resolve-outcome`-Route mit `decision: "applied_observed"`,
`evidence: "manual_provider_inspection"` — geschlossene Literale, kein
Freitext. Verbindlich:

- Zulässig nur aus `outcome_unknown`/`manual_decision_required` mit
  verbrauchter Freigabe; kein Providerkontakt; Outbox wird endgültig
  geschlossen; zweiter Aufruf ⇒ 409.
- **Der Spiegel wird dabei nicht erfunden.** Ohne Provider-Beleg entsteht
  keine `contacts`-Zeile und keine External-ID aus der Mutation; der
  Kontakt kommt — falls wirklich vorhanden — über den nächsten regulären
  Sync als normaler Provider-Import in den Spiegel. Der Auditeintrag
  `outcome_unknown` bleibt stehen; der Abschluss ist ein eigenes, späteres
  Ereignis.

## 5. Transportvertrag (ExecutionOrder / ExecutionReport, v1)

Geschlossene, versionierte Schemas; Serialisierung JSON (UTF-8,
`extra="forbid"` im Backend, `deny_unknown_fields` in Rust). Der Auftrag
enthält **nur**, was der native Save braucht.

**ExecutionOrder v1** (Antwort von `POST /mutations/{id}/execute`):

```
schema_version: 1
operation_id: uuid
claim_token: hex64            # einmalig; nie loggen, nie persistieren (nur Digest)
claim_expires_at: iso8601
operation_type: "create" | "update" | "delete"
mutation_contract_version: 1
field_contract_version: 1
payload_digest: hex64
expected_revision: string|null        # lokale Revision (update/delete)
target:                               # Zielbindung, roh NUR hier
  container_identifier: string|null   # create
  provider_identifier: string|null    # update/delete
transaction_author: "de.kluender.jarvis.contacts-bridge"
fields: <kanonischer v1-Feldpayload>  # create/update; delete: expected_fields_digest
expected_previous: {…}|null           # update: Vorwerte genau der benannten Felder
readback:
  required: true
  keys: "field_contract_v1"           # geschlossene Key-Menge
```

**ExecutionReport v1** (Ergebnis des Tauri-Commands, Body des Settle):

```
schema_version: 1
operation_id: uuid
claim_token: hex64                    # nur im Settle-Body an das Backend
outcome: "applied" | "not_sent" | "outcome_unknown"
send_attempted: bool                  # false nur bei not_sent
save_request_count: 0 | 1             # nie > 1; Vertragsbruch = outcome_unknown
provider_identifier_digest: hex64|null
provider_identifier: string|null      # roh NUR im Settle-Body (Backend braucht ihn
                                      # für External-ID); nie in UI/Logs/normaler API
readback_status: "confirmed" | "absent_confirmed" | "failed" | "not_attempted"
readback_contact: <BridgeContact-DTO>|null   # Kern bildet daraus den readback_digest
readback_revision: string|null
provider_completed_at: iso8601|null
error_class: <geschlossene Menge, §9>|null
error_digest: hex64|null              # SHA-256 des Rohgrunds; Rohtext verlässt den
                                      # App-Prozess nie
diagnostic_artifact_present: bool
```

Nicht zulässig im Transport: rohe Approval-Objekte, Audit-Historie,
Datenbankzeilen, frei interpretierbare Strings als Ergebnis,
Frontend-Entscheidungen über Terminalzustände. Weitere Regeln:

- **Größenlimit:** Order ≤ 64 KiB, Report ≤ 256 KiB (Read-back-DTO ohne
  Bilddaten — `thumbnail` wird im Read-back nie transportiert); darüber
  fail-closed `schema_mismatch`.
- **Unbekannte Felder:** Ablehnung auf jeder Grenze (Backend, Rust,
  Settle) — nie ignorieren.
- **Versionskonflikt:** `schema_version`/Vertragsversionen ≠ erwartet ⇒
  `schema_mismatch`, `not_sent`, fail-closed; kein Downgrade-Pfad.
- **Tauri-Allowlist:** genau **ein** neues Command
  (`personal_contacts_execute_mutation`), registriert wie die beiden
  bestehenden; keine generische Invoke-Fläche; Capability-Gate nach
  ADR-0014 (Command nur für das Hauptfenster).
- **Capability-Gate fachlich:** Das Command prüft vor jedem FFI:
  Feature-Flag der Phase (standardmäßig aus), TCC `authorized`,
  Vertragsversionen, Claim-Gültigkeit, Digest. Jede Ablehnung ist
  `not_sent` mit geschlossenem `error_class`.
- **Digest-Prüfung in Tauri:** Rust berechnet den `payload_digest` aus dem
  transportierten `fields`-Payload mit der **normativen Kanonisierung**
  (§6) nach und vergleicht mit dem Auftragswert; Abweichung ⇒
  `digest_mismatch`, `not_sent`. Damit ist gebunden: ausgeführt wird
  exakt, was vorbereitet, gezeigt und freigegeben wurde (L1 wird
  zusätzlich geschlossen: `consume()` bindet künftig `payload_digest`
  **und** `preview_digest`).

## 6. Kanonisierung und Digest — eine normative Quelle

**Die einzige normative Implementierung ist der Kern:**
`base/digest.py` (`canonical_json`: `sort_keys=True`,
`separators=(",",":")`, `ensure_ascii=False`) über
`field_contract.canonical_payload()`. Frontend **berechnet nie** einen
Digest (es transportiert nur); Rust reimplementiert die Kanonisierung
nach dieser Spezifikation und wird durch **geteilte Testvektoren**
(goldene Dateien, aus dem Kern generiert, im Repo eingecheckt) auf
Bit-Gleichheit gehalten — jede Abweichung bricht den Build. Regeln:

| Aspekt | Regel |
|---|---|
| Unicode | NFC-Normalisierung vor Digest und vor Save; Vergleich im Read-back ebenfalls auf NFC |
| Whitespace | Skalare: führend/folgend gestrippt; leerer String nach Strip = `invalid_request` (kein „leeren durch Leerstring") |
| `null` | ausdrückliches Löschen eines Skalars; in Kanonform als Feld **abwesend** plus Eintrag in `cleared_fields`-Liste (sortiert) |
| Fehlende Felder | nicht Teil der Operation, nicht im Digest, werden nie angefasst |
| Listenreihenfolge | Positionsreihenfolge ist fachlich; sie geht **unverändert** in Kanonform und Digest ein |
| Mehrwert-Duplikate | exakt gleiche `(label, value)`-Paare ⇒ `invalid_request` |
| Labels | geschlossener Vorrat (`home|work|mobile|main|other|null`), kanonisch klein; Apple-Rohlabels (`_$!<Work>!$_`) existieren nur jenseits der FFI-Grenze — Rücknormalisierung ist Kernaufgabe |
| Telefonnummern | Digest über den **eingegebenen** Wert (getrimmt, NFC); E.164 entsteht nur im Kern-Spiegel und geht nie in den Digest (Apple gibt formatiert zurück — der Read-back-Vergleich läuft über die v1-Projektion, nicht Rohstring-Gleichheit) |
| E-Mail | getrimmt, NFC, keine Groß-/Kleinschreibungs-Normalisierung (lokaler Teil ist case-sensitiv) |
| Adressen | Komponenten einzeln getrimmt/NFC; `iso_country_code` ASCII-lowercase, 2 Zeichen |
| Datumswerte | `{year?, month, day}` als Ganzzahlen, keine Strings; kein Zeitanteil, keine Zeitzone |
| Binärdaten/Bilder | **nie** Digest-Bestandteil, nie im Transport (v1 schreibt keine Bilder) |
| Lokale Kategorien | Jarvis-lokal, verlassen den Mac nie, sind **nicht** Teil von Payload, Vorschau-Digest oder Save |

Derselbe kanonische Payload ist die Grundlage für: Vorschau (Anzeige),
`payload_digest` (Freigabe + Transport + Tauri-Prüfung), nativen Save
(Feldsetzung) und Read-back-Vergleich (`readback_digest` im Kern,
ADR-0019-Präzisierung unverändert).

## 7. Vollständiger Feldvertrag (Matrix)

Vertragsstand: `field_contract_version = 1` — **eine** Quelle
(`application/field_contract.py`) für Create **und** Update; die alte
Update-Allowlist (`commands.PATCHABLE_FIELDS`) wird in Phase A durch den
v1-Vertrag ersetzt (schließt L2). Legende: ✓ = zugesagt, — = nicht
relevant, v2 = bewusst zurückgestellt (braucht Vertragsversion v2 und ggf.
eigenen ADR).

**Skalare (Typ string, ≤ 256, Strip+NFC, Löschen per `null`, Read-back
verlustfrei, Revision-relevant, mehrfach ✗, Label ✗):**

| API-Name (intern/Draft/Preview identisch) | CN-Ziel | Create | Update | v1 |
|---|---|---|---|---|
| `given_name` | `.givenName` | ✓ | ✓ | ✓ |
| `middle_name` | `.middleName` | ✓ | ✓ | ✓ |
| `family_name` | `.familyName` | ✓ | ✓ | ✓ |
| `previous_family_name` | `.previousFamilyName` | ✓ | ✓ | ✓ |
| `name_prefix` | `.namePrefix` | ✓ | ✓ | ✓ |
| `name_suffix` | `.nameSuffix` | ✓ | ✓ | ✓ |
| `nickname` | `.nickname` | ✓ | ✓ | ✓ |
| `phonetic_given_name` | `.phoneticGivenName` | ✓ | ✓ | ✓ |
| `phonetic_family_name` | `.phoneticFamilyName` | ✓ | ✓ | ✓ |
| `organization_name` | `.organizationName` | ✓ | ✓ | ✓ |
| `department_name` | `.departmentName` | ✓ | ✓ | ✓ |
| `job_title` | `.jobTitle` | ✓ | ✓ | ✓ |

`contact_type` (`person|organization` → `.contactType`): Create ✓,
Update ✗ (Typwechsel nicht zugesagt). `birthday`
(`{year?,month,day}` → `.birthday`): Create ✓, Update ✓, Löschen `null`.

**Etikettierte Listen (Update ersetzt die ganze benannte Liste; `[]` löscht
alle Werte; `null` ist `invalid_request`; Reihenfolge = Position;
Duplikate verboten; Read-back verlustfrei für den geschlossenen
Labelvorrat):**

| API-Name | Form | Max | Labels | CN-Ziel | Validierung |
|---|---|---|---|---|---|
| `emails` | `{label,value}` | 10 | home/work/other/null | `.emailAddresses` | `@`, kein Whitespace, ≤ 254 |
| `phones` | `{label,value}` | 10 | home/work/mobile/main/other/null | `.phoneNumbers` | nicht leer, ≤ 64 |
| `postal_addresses` | `{label,street?,city?,state?,postal_code?,country?,iso_country_code?}` | 5 | home/work/other/null | `.postalAddresses` | Komponenten ≤ 256; ISO 2 Zeichen |
| `urls` | `{label,value}` | 10 | home/work/other/null | `.urlAddresses` | nicht leer, ≤ 512 |
| `dates` | `{label,year?,month,day}` | 5 | other/null | `.dates` | wie `birthday` |

**Explizit dokumentierte Nicht-v1-Felder** (gelesen ≠ schreibbar; jede
Oberfläche muss sie als nicht produktiv speicherbar darstellen — der
Frontend-Editor kennzeichnet sie heute bereits als „erst mit erweitertem
Feldvertrag übertragbar"):

| Feld | Lesepfad heute | Schreiben | Grund |
|---|---|---|---|
| `note` | nur Verfügbarkeit (`unavailable_by_capability`) | **nie in v1** | Apple-Entitlement fehlt bewusst; unlesbar ≠ leer — Überschreibungsgefahr |
| Kontaktbild / `thumbnail` | `imageAvailable`, `thumbnail_bytes` (Blob verworfen) | v2 | Binärkanonisierung + Größen offen |
| `social_profiles` | ✓ (label/service/username/url) | v2 | Apple-Service-Vokabular nicht geschlossen |
| `instant_messages` | ✓ (label/service/username) | v2 | wie `social_profiles` |
| `relations` | ✓ (label/name, unaufgelöst) | v2 | Freitext-Zielnamen — Identitätsrisiko |
| `non_gregorian_birthday` | nicht gelesen | v2 | erst Lesepfad, dann Schreibvertrag |
| `phonetic_middle_name` | nicht gelesen | v2 | wie oben |
| `sub_locality`/`sub_administrative_area` | teilw. Modell, nicht im DTO | v2 | nicht read-back-verlustfrei |
| Gruppen (`CNGroup`) | nicht gelesen | v2 | eigener Objekttyp, eigene ADR-Frage |
| Me-Card-Status | ✓ (`isMeCard`) | **nie Ziel** | Schutzregel: Me-Karte ist kein Mutationsziel (Precheck) |
| Container-/Account-Zugehörigkeit | ✓ (maskiert) | Create-Ziel, nie Update | Move zwischen Containern ist v2+ |
| Jarvis-Kategorien | lokal | **lokal-only** | verlassen den Mac nie (bestehender Vertrag) |
| unlesbare/redigierte Felder | `field_availability` | **nie** | `unavailable_by_capability` gilt nie als leer; `NEVER_WRITABLE` erzwingt es |

## 8. Create-, Update-, Delete-Verträge

### 8.1 Create

- **Ziel:** explizit gewählte, maskierte `container_ref`; Auflösung
  rückwärts über `contacts_sync_state` (genau ein Treffer, sonst
  fail-closed — ADR-0019 §2 unverändert). **Kein stiller
  Default-Container:** existiert genau ein bekannter Container mit
  erhobenem Typ, darf die Oberfläche ihn vorauswählen; die Wahl bleibt
  sichtbar und Teil der Vorschau. Lokale Konten: die Container-Art
  (`local`/`cardDAV`/…) steht in der Vorschau.
- **Nativ:** genau ein `CNMutableContact`, genau ein
  `addContact:toContainerWithIdentifier:`, genau ein `CNSaveRequest` mit
  `transactionAuthor`; unmittelbar davor der Lese-Preflight (§4b-Muster,
  jetzt im App-Prozess), unmittelbar danach der Identifier-basierte
  Read-back (`shouldRefetchContacts` bzw. gezielter Fetch).
- **Identität:** Der vom Save gelieferte `provider_identifier` ist der
  einzige Identitätsbeweis. Save-Erfolg **ohne** Identifier ⇒
  `outcome_unknown (applied_without_identifier)` — niemals Namenssuche.
  Read-back-Fehler nach Save ⇒ `outcome_unknown (readback_failed_after_save)`.
- **Settle applied:** External-ID-Zeile + `contacts`-Zeile entstehen
  atomar in C2 (`finalize_pending`), `target_contact_id` wird nachgetragen,
  Echo-Unterdrückung über `transactionAuthor` + `IN_FLIGHT_STATES`.
- **Ähnlicher Kontakt existiert bereits:** kein Duplikatabgleich in v1 —
  Create legt an, was freigegeben wurde; eine Duplikatwarnung ist
  UI-Vorschau-Aufgabe (lokaler Spiegel), nie ein Providerkriterium.
- **Kein automatischer Re-Send nach Timeout — ausnahmslos.**

### 8.2 Update

- **Ziel:** ausschließlich `provider_identifier` aus
  `contact_external_ids` (genau eine externe Identität, sonst
  `ambiguous_target`); öffentliche Adressierung bleibt die lokale
  `contact_id`. `expected_revision` (lokal) ist Pflicht.
- **Nativ:** gezielter Fetch des Zielkontakts unmittelbar vor dem Save
  (`unifyResults=false`); Vergleich der **benannten** Felder mit
  `expected_previous` (v1-Projektion) — Abweichung ⇒ `not_sent (conflict)`
  vor jeder Übergabe. Dann `mutableCopy`, **nur** die benannten
  Eigenschaften setzen, genau ein Update-Request, genau ein
  `CNSaveRequest`, Read-back.
- **Patch-Semantik:** nie Vollobjekt; nicht genannte Felder — auch
  Nicht-v1-Felder wie Notizen und Bilder — bleiben unangetastet (die
  `mutableCopy` trägt sie weiter). Explizites Löschen: Skalar `null`,
  Liste `[]`. Fehlende Payload-Felder löschen **nie**.
- **Unlesbare Felder:** `unavailable_by_capability` ist nie „leer";
  `NEVER_WRITABLE` weist jeden Schreibversuch ab; die `mutableCopy`
  schützt den Bestand auch dann, wenn der Lesepfad ein Feld nicht sieht.
- **Mehrwertfelder:** Listenersatz je benannter Liste (Item-Identität ist
  v2); Labelwechsel = Listenersatz; Reihenfolge = Position.
- Read-back-Vergleich über die v1-Projektion; Fremdänderungen an **nicht
  benannten** Feldern sind kein Konflikt.

### 8.3 Delete

- **Ziel/Revision:** wie Update (Identifier + Pflicht-`expected_revision`);
  zusätzlich `expected_fields_digest` des lokalen v1-Feldstands — der
  native Pfad liest das Ziel, projiziert, vergleicht den Digest und lehnt
  bei Abweichung als `conflict` ab: gelöscht wird nur, was der Mensch in
  der Vorschau (vollständiger Snapshot) gesehen hat.
- **Schutzregeln:** Me-Karte nie (Precheck + nativer Doppelcheck);
  Container-/Kontobindung wird gegen die External-ID geprüft; genau ein
  Datensatz je Vorgang, keine Kaskade.
- **Risikoklasse — Entscheidung:** Delete ist **R2**. Der bisherige
  „unverbindliche Vorschlag" (ADR-0019 §7) wird hiermit verbindlich:
  Create R1, Update R1, Delete R2. Für R2 gilt zwingend eine
  **zusätzliche In-App-Bestätigung** im Ausführungsschritt (nicht nur bei
  der Freigabe): der Execute-Claim für Delete verlangt
  `{"user_initiated": true, "confirm_delete": true}`. Ob darüber hinaus
  eine **native** Zweitbestätigung (Betriebssystem-Dialog) nötig ist,
  bleibt **DEC-D06** — vor deren Entscheidung wird Delete nicht
  implementiert (Phase F ist dahinter verriegelt).
- **Nativ:** genau ein Delete-Request, genau ein `CNSaveRequest`; danach
  Abwesenheitsnachweis: gezielter Fetch ⇒ `recordDoesNotExist` bei
  weiterhin gültigem Containerzugriff. „Nicht lesbar" (z. B. TCC entzogen)
  ist **kein** Löschnachweis ⇒ `outcome_unknown`.
- **Lokal (C2):** `contacts.is_tombstone = 1` + `deleted_at`
  (Schema-Invariante), Tombstone-Historienzeile mit eigenem Grund
  `deleted_by_own_mutation`, External-ID-Nachführung, Audit. Die
  Twei-Semantiken-Trennung (Kontaktzeile vs. Löschnachweis-Historie,
  `diagnostics.py`) gilt unverändert.

## 9. Geschlossene Fehlerklassen

| Klasse | Phase | `send_attempted` | Zustand | Retry | Reconcile | Manuell | Audit |
|---|---|---|---|---|---|---|---|
| `invalid_claim` | vor Send | nein | `failed_before_send`* | nein | nein | nein | `failed_before_send` |
| `expired_claim_before_send` | vor Send | nein | `outcome_unknown`** | nein | ja | ggf. | `outcome_unknown` |
| `digest_mismatch` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `schema_mismatch` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `capability_denied` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `not_authorized` (TCC) | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `target_not_found` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `revision_conflict` / `conflict` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `invalid_payload` / `unsupported_field` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `container_unavailable` / `write_stack_unavailable` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `provider_channel_disabled_before_send` | vor Send | nein | `failed_before_send` | nein | nein | nein | `failed_before_send` |
| `provider_exception` (`objc_exception`) | nach Send | ja | `outcome_unknown` | **nie** | ja | ggf. | `outcome_unknown` |
| `provider_save_error` | nach Übergabe | ja | `outcome_unknown` | nie | ja | ggf. | `outcome_unknown` |
| `readback_failed` (`readback_failed_after_save`) | nach Send | ja | `outcome_unknown` | nie | ja | ggf. | `outcome_unknown` |
| `response_lost` | nach Send | unbekannt ⇒ ja | `outcome_unknown` | nie | ja | ggf. | `outcome_unknown` |
| `app_process_crash` | nach Claim | unbekannt ⇒ ja | `outcome_unknown` | nie | ja | ggf. | `outcome_unknown` |
| `backend_unreachable_for_settle` | nach Send | ja | (Frontend wiederholt nur Settle) → sonst `outcome_unknown` | nie | ja | ggf. | `outcome_unknown` |
| `settle_conflict` | Settle | — | unverändert | nein | nein | nein | kein Übergang (409) |

\* `invalid_claim` **vor** Auftragsausgabe (Backend) ⇒ `failed_before_send`;
ein ungültiger Claim **im Report** ist `settle_conflict`.
\** Verfall nach Auftragsausgabe: ob gesendet wurde, ist unbeweisbar —
fail-closed `outcome_unknown` (lehnt Tauri selbst vor dem FFI ab und liefert
das beweisbar, darf das Settle `not_sent` tragen ⇒ `failed_before_send`).

**Präzisierung 2026-08-03 (Phase A):** `provider_channel_disabled_before_send`
ist die Klasse des Stands, in dem der Transport steht und der native Save
noch nicht existiert (Phase A) bzw. das Produktgate aus ist. Sie gehört zu
den Vor-Send-Klassen: Der App-Prozess lehnt **vor** jeder Übergabe ab, es
wurde beweisbar nichts gesendet.

Diagnose ist überall PII-arm: Fehlerklassen sind geschlossene Bezeichner;
Rohgründe existieren nur als `error_digest` bzw. — ausdrücklich aktiviert —
als 0600-Artefakt im 0700-Benutzerordner (§4a-Regeln gelten im App-Prozess
unverändert).

## 10. App-Prozess und Sidecar — normative Abgrenzung

1. **Produktive Writes: ausschließlich Tauri-App-Prozess.**
2. **CLI-Sidecar: Lesen, Sync, Diagnose.** Die produktive Schreibroute des
   Sidecars wird in Phase A **deaktiviert**: `create` antwortet wieder
   `not_implemented` (wie `update`/`delete`), `createImplemented: false` im
   Handshake; der Save-Code wandert in die geteilte native Bibliothek. Der
   Kern akzeptiert `createSupported` nur noch aus der
   **App-Kanal-Capability** (Tauri-Handshake), nie aus dem
   Sidecar-Handshake. `PROTOCOL.md` wird dabei berichtigt (L4).
3. **Spike-Code:** wird nicht Produktcode. **Extrahierbar** (neutrale
   Helfer, bereits doppelt erprobt): SHA-256-Hex, Namens-/Domain-Sanitizer,
   Diagnoseartefakt-Maschinerie (prepare/commit/discard, 0600/0700-Regeln),
   Uncaught-Handler mit Kette, Ops-Block-Muster (produktiv + Fakes),
   Container-Wahl nach Typ, Lese-Preflight, Einmal-Save, Read-back.
   **Nicht übertragbar:** Env-Gate, Bestätigungsphrase, Nonce, fixe
   Payload, Einmal-Statemachine, Szenario-Entry, Beweis-Telemetrie.
   Produktiv ersetzt die Approval/Outbox/Claim-Kette Phrase und Nonce.
   Spike-Abweichung wird korrigiert: `NSError` nach Save-Übergabe ist
   `outcome_unknown` (ADR-0019 §4a), nie `SaveError`-not-sent.
4. **TCC/Entitlements/Signatur:** App-Bundle behält
   `com.apple.security.personal-information.addressbook` +
   `NSContactsUsageDescription`; Hardened Runtime; Designated Requirement
   zertifikatsgebunden; der Sidecar behält sein Adressbuch-Entitlement für
   den Lesepfad. **Keine automatische TCC-Manipulation, kein
   `tccutil reset`** durch Produktcode; nicht autorisierter Zugriff ⇒
   `not_authorized`, `not_sent`, UI verweist auf die Systemeinstellungen.
5. **Dual-Architektur-Pflicht (DEC-042):** x86_64 **und** ARM64 nativ;
   keine Abnahme gilt für die jeweils andere Architektur; der
   ARM64-AppSave-Beweis steht aus (Phase C).

## 11. Read-back und Reconcile

| Operation | Read-back | Urteil |
|---|---|---|
| Create | gezielter Fetch über den gemeldeten Identifier; v1-Projektion; `readback_digest` im Kern | `applied` (Beleg), `not_applied` (Identifier nie existent **und** Autor-Probe leer), `ambiguous` sonst |
| Update | gezielter Fetch; Vergleich **nur der benannten Felder** (v1-Projektion) | `applied` (alle benannten Felder tragen den Zielwert), `not_applied` (alle tragen den Vorwert), `ambiguous` (teilweise) ⇒ `manual_decision_required` |
| Delete | gezielter Fetch ⇒ `recordDoesNotExist` bei gültigem Containerzugriff | `applied` (bestätigt abwesend), `not_applied` (weiter vorhanden), `ambiguous` (nicht lesbar/Zugriff unklar) |

Reconcile (unverändert ADR-0019 + Kanalregeln): niemals Namens- oder
Ähnlichkeitssuche; niemals ein zweiter Provider-Send; niemals erfundene
Daten — ohne Provider-Beleg keine Spiegelzeile; Create-Zuordnung nur über
gemeldete Identität oder die Autor-Probe der Change-History; Mehrdeutigkeit
endet in `manual_decision_required`, menschlicher Abschluss nach §4.1/5a.

## 12. Implementierungsphasen (Entry/Exit hart)

| Phase | Inhalt | Entry | Exit |
|---|---|---|---|
| **A** | Schemas (Order/Report), Migration (Outbox: `operation_id`, `claim_expires_at`, `claim_token_digest`; Audit-`stage`-CHECK, L3), deklarative Übergangstabelle (L5), Claim-Erweiterung von `execute`, Settle-Route, Feldvertrag-v1-Vereinheitlichung (L2), `preview_digest`-Bindung (L1), Sidecar-Write-Deaktivierung (§10.2), Fake-Tauri im Test, **kein Providerwrite** | dieser ADR gepusht + Eigentümerfreigabe | alle kontaktfreien Tests grün; API-Suite hält Provider-Zähler auf 0; Statiktests §14 grün |
| **B** | nativer Create-Pfad im App-Prozess (geteilte Bibliothek aus §10.3), Tauri-Command, Feature-Gate standardmäßig aus, kontaktfreie native Tests (Fake-Ops) | A-Exit + Freigabe | x86_64: kontaktfreie Suite grün; **ein** kontrollierter Intel-Livetest (eigener Testkontakt) BESTANDEN |
| **C** | ARM64-AppSave-Spike + Cross-Architecture-Bestätigung des Create-Pfads | B-Exit + M2-Pro-Zugang | nativer ARM64-Livebeweis (DEC-042) |
| **D** | produktives Create aktivieren (Capability an) | C-Exit + Freigabe | Live-Abnahme x86_64 **und** ARM64 |
| **E** | Update vollständig (v1-Vertrag, `expected_previous`) | D-Exit + Freigabe | beide Architekturen abgenommen |
| **F** | **zuerst DEC-D06 entscheiden**, dann Delete (R2, `confirm_delete`) | E-Exit + DEC-D06 | beide Architekturen abgenommen |
| **G** | Abschlussaudit, ADR-Status-Nachtrag, Merge | F-Exit | Auditbericht + Eigentümerfreigabe |

Keine Phase beginnt ohne ausdrückliche Freigabe des Eigentümers. Die
ADR-0019-Phasen M2–M5 werden hierauf abgebildet (M2→B/D, M3→C, M4→E,
M5→F); der Sidecar-Create aus dem alten M2 wird in A zurückgebaut.

## 13. Testmatrix

| Bereich | Unit (kontaktfrei) | Integration Fake-Provider | Intel-Live | ARM64-Live |
|---|---|---|---|---|
| Schema Order/Report (Versionen, unbekannte Felder, Limits) | A | A | — | — |
| Digest-Kanonisierung (goldene Vektoren Kern↔Rust) | A | A | — | — |
| Claim (Einmaligkeit, Verfall, `send_started`-Reihenfolge) | A | A | — | — |
| Replay/doppelter Tauri-Aufruf/doppeltes Settle | A | A | — | — |
| Frontend-Neuladen / App-Absturz / Backend-Absturz / Antwortverlust | A (Zustands-Sim) | A | B (gezielt) | C/D |
| Exception vor/nach Save (Fake-Ops werfen) | B | B | — | — |
| Read-back-Fehler | B | B | — | — |
| Create (Feldmatrix, Container, Identifier) | B | B | B (1 Testkontakt) | C/D |
| Update (`expected_previous`, Patch, unlesbare Felder) | E | E | E | E |
| Delete (R2-Bestätigung, Abwesenheitsnachweis, Tombstones) | F | F | F | F |
| Revision-Konflikt | A/E | E | E | E |
| Me-Card-/Container-Schutz | A | B | B | C |
| TCC-Matrix (nicht autorisiert ⇒ `not_sent`) | B (Fake) | B | B | C |
| Signierung/Entitlements/x86_64/ARM64 | Packaging-Tests | — | B/D | C/D |
| Audit (Kette, Stufen-CHECK, je Übergang ein Ereignis) | A | A | B | — |
| Tombstone-Semantik (`diagnostics.py`-Aggregate) | vorhanden | F | F | — |
| Backup/Restore (Mutation über Neustart/Wiederherstellung) | A (`recover_interrupted`) | A | D | D |

Echte-Provider-Tests existieren ausschließlich als ausdrücklich
freigegebene Einzel-Livetests mit eigens angelegten Testkontakten — nie in
CI, nie automatisch.

## 14. Architekturprüfungen (statisch, mit diesem ADR eingecheckt)

`tests/personal/contacts/test_mutation_channel_contract_static.py` erzwingt
dokument- und quelltextbasiert: (1) dieser ADR existiert mit allen
normativen Ankern; (2) kein zweiter Save-Versuch nach `send_started`
(genau eine `provider.apply`-Aufrufstelle; kein Retry-Konstrukt); (3) die
Settle-/Reconcile-Schicht löst keinen Provider-Send aus (`reconcile.py`
ruft nie `provider.apply`); (4) unlesbare Felder sind nie schreibbar
(`note` ∈ `NEVER_WRITABLE`); (5) keine Namenssuche im Abgleich; (6) keine
rohen Provider-Identifier in der normalen UI (bestehende Muster + Anker);
(7) kein Spike-/DEV-Gate im Produktpfad (`OPENJARVIS_CONTACTS_APP_SAVE_SPIKE`
kommt im Hauptstand nicht vor); (8) Delete nur mit zusätzlicher
Bestätigung (Anker + DEC-D06-Riegel); (9) keine Mutation ohne
Approval-Digestbindung (`consume(...digest)`-Aufrufstelle vorhanden).

## Konsequenzen

- Der Sidecar-Create (altes M2) wird zurückgebaut — der einzige jemals
  produktiv implementierte Provider-Schreibpfad hat live nie funktioniert
  und wird durch den bewiesenen App-Prozess-Kanal ersetzt.
- `execute` wird vom „Send-Endpunkt" zum **Claim-Endpunkt**; neu entstehen
  ExecutionOrder/ExecutionReport v1, die Settle-Route und ein Tauri-Command.
- Vier belegte Vertragslücken (L1–L4) und die fehlende Übergangstabelle
  (L5) erhalten normative Schließungen mit Phase-A-Pflicht.
- `manually_resolved_applied` ergänzt den menschlichen Abschluss
  symmetrisch — ohne jemals Spiegeldaten zu erfinden.
- Delete ist verbindlich R2 und doppelt verriegelt (Phase F + DEC-D06).
- Offen und unberührt: ARM64-Abnahmen (Phase C/D; DEC-042), M2-Pixelabnahme
  des Frontends (unabhängig vom Mutationskanal), DEC-D17.
