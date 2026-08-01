---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-08-01
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-10, AV-33, AV-35
Zugehörige ADRs: ADR-0005 (Command-Bus), ADR-0006 (Risikoklassen), ADR-0007 (Outbox), ADR-0016 (Swift-Sidecar), ADR-0018 (Dual-Architektur)
Verwandte DEC-Einträge: DEC-031, DEC-042, DEC-043, DEC-044 (dieser ADR); DEC-D06 (offen, Voraussetzung für Delete), DEC-D17 (offen, unberührt)
---

# ADR-0019: Architektur der Apple-Contacts-Provider-Mutationen (Create/Update/Delete)

- **ADR-Status:** accepted
- **Datum:** 2026-08-01

Dieser ADR friert die Architektur ein, nach der Personal Jarvis Kontakte bei
Apple Contacts anlegt, ändert und löscht. Er entscheidet **Architektur**, keine
Implementierung: bei seiner Annahme existierte im Produktcode weder ein
`CNSaveRequest` noch ein produktiver Aufrufer von `execute()`. Jede
Implementierung folgt der Phasenfolge in §9 und beginnt erst nach
ausdrücklicher Freigabe des Eigentümers je Phase.

> **Umsetzungsstand 2026-08-01:** Phase **M2 (nur `create`)** ist im Code
> umgesetzt. Der Sidecar hat seither **genau einen** Schreibpfad; `update` und
> `delete` bleiben `not_implemented`. Die Live-Abnahme auf x86_64 steht noch
> aus. Die drei Präzisierungen aus der Umsetzung sind unten jeweils an ihrer
> Stelle vermerkt (Read-back-Digest, Abgleichgrenze, Ergebnisvertrag).

## Kontext: verifizierter Ist-Zustand (2026-08-01, Commit `0892459`)

Read-only nachgeprüft am Stand `0892459f47f57fb6deaf1745a1c1d13601518825`
(Branch `handoff/contacts-read-flow-2026-07-29`, Intel x86_64, macOS 12.7.6):

**Belegte Fakten** (Quelltextbefund, nicht Schlussfolgerung):

1. `ContactsMutationService.prepare()` und `grant()` berühren den Provider
   nicht: `self._provider` kommt in `mutation_service.py` genau zweimal vor —
   Konstruktor (Z. 144) und `execute()` Phase B (Z. 315).
2. `execute()` hat **keinen produktiven Aufrufer**: keine HTTP-Route, kein
   Executor, kein Timer, kein Frontend-Aufruf; ausschließlich Tests rufen es.
3. Der produktiv verdrahtete Provider ist `_UnavailableProvider`
   (`lifecycle.py`) und antwortet `failed_before_send`/`not_implemented`.
4. Der Sidecar (`native/contacts-bridge/src/sidecar.swift`) beantwortet
   `create`/`update`/`delete` nach Pflichtfeldvalidierung mit
   `not_implemented`; `mutationsImplemented: false` steht im Handshake.
5. `CNSaveRequest`/`CNMutableContact` kommen im Produktcode **nicht** vor —
   nur in Verbotslisten (Tests, `contacts_authorization.rs`), Kommentaren und
   im abgeschlossenen Spike `spikes/contacts-bridge-g3a/` (laut ADR-0016
   ausdrücklich kein Produktcode).
6. Es gibt keinen produktiven `ReconcileReader`: die Route
   `POST /mutations/{id}/reconcile` liest `module.reconcile_reader`, das
   Attribut wird nirgends gesetzt → fail-closed 503.
7. Die Handshake-Fähigkeiten erreichen den Kern nicht:
   `ContactsModule._capabilities` bleibt nach `start()`
   `default_capabilities()` (alles außer `read_supported` False);
   `mutationsImplemented` endet in `BridgeStatus`.
8. Nach einem Providererfolg führt `_settle()` den kanonischen Spiegel nicht
   nach: die einzigen Schreibziele in `mutation_service.py` sind
   `contacts_mutations` (Z. 216, 592, 653), nie `contacts` oder
   `contact_external_ids`.
9. Öffentliche Mutationsmodelle tragen rohe Identifier:
   `PreparedMutationOut.target_provider_identifier`/`.container_identifier`,
   `MutationOut.provider_account_id`/`.container_identifier`,
   `ReconcileOut.provider_identifier`, `ContactDetailOut.provider_accounts`/
   `.containers`/`.write_target`; die Eingaben `_MutationBase`/
   `CreateContactIn`/`UpdateContactIn`/`DeleteContactIn` verlangen sie.
10. Freigabekern: `risk_class="R1"` ist in `prepare()` fest verdrahtet;
    `grant()` weist `llm_assisted`/`automation`/`system` als Entscheider ab;
    die Freigabe wird beim Send über den `payload_digest` **verbraucht**.
11. Idempotenz: `ux_mutations_idempotency (provider_account_id,
    idempotency_key)` und `ux_outbox_idempotency (module, idempotency_key)`;
    `prepare()` mit bekanntem Schlüssel gibt denselben Vorgang zurück.
12. `recover_interrupted()` läuft beim Start (`bootstrap.py`) und stuft jede
    unterbrochene Ausführung fail-closed als `outcome_unknown` ein.
13. Testlage: 100 Tests in `test_mutation_pipeline.py` +
    `test_pipeline_hardening.py` grün, ausschließlich Fakes und temporäre
    Datenbanken; die API-Suite hält den Provider-Aufrufzähler in jedem
    Ablauf auf null.

**Schlussfolgerungen** (aus den Fakten abgeleitet): Die Pipeline
Vorbereiten → Freigeben → Ausführen → Abgleichen ist vollständig gebaut und
abgesichert, aber an fünf Stellen bewusst nicht geschlossen: Sidecar-Schreibpfad,
produktiver Provider, produktiver Ausführungsweg, produktiver Abgleichleser,
Capability-Brücke. Zusätzlich fehlen die lokale Nachführung nach Providererfolg
und die Identitätshärtung der Mutationsverträge.

## Entscheidung

### 1. Verbindlicher Ausführungsablauf

```
Benutzeranweisung
  → prepare (validieren, Ziel binden, Vorschau, Freigabeanforderung, Outbox)
  → kanonische Vorschau (wird angezeigt, nie persistiert — nur Digests)
  → ausdrückliche menschliche Freigabe          [eigene Nutzeraktion]
  → separate ausdrückliche Ausführung           [eigene Nutzeraktion]
  → genau ein Provideraufruf (außerhalb jeder DB-Transaktion)
  → exakter Read-back des konkret geschriebenen Providerkontakts
  → kanonische lokale Nachführung (atomar in einer UnitOfWork)
  → Auditabschluss
```

Verbindlich:

- **`approve` löst niemals `execute` aus.** Freigabe und Ausführung sind zwei
  getrennte Nutzeraktionen mit getrennten Routen.
- **Ausführung ausschließlich über**
  `POST /v1/personal/contacts/mutations/{mutation_id}/execute` — unter `/v1/`
  (Bearer-`AuthMiddleware`, 09 §1), mit Workspace-Kopf, und mit einem
  Anforderungskörper, der die ausdrückliche Nutzeraktion trägt
  (`{"user_initiated": true}` als `Literal[True]`, Muster wie
  `RecoveryRunIn`). Kein Aufruf ohne diesen Körper.
- **Kein Hintergrundexecutor, kein Scheduler, kein automatischer Retry.**
- **Genau ein zulässiger Sendversuch je Mutation.** Serialisierungspunkt ist
  der Outbox-Claim; `failed_before_send` und alle Endzustände bleiben
  terminal, ein neuer Versuch ist eine neue freigabepflichtige Mutation.
- **`outcome_unknown` führt ausschließlich in den Abgleich** (`reconcile`).
- **Der Abgleich sucht niemals über Namen oder Ähnlichkeit.** Zuordnung
  ausschließlich über einen belegten stabilen Bezug: die vom Provider
  gemeldete Identität. *(Präzisierung 2026-08-01: der ursprünglich zusätzlich
  vorgesehene Transaktionsautor-Marker ist über die öffentliche Apple-API
  nicht erreichbar — Begründung in §4.)* Fehlt die Identität ⇒
  `manual_decision_required`.

### 2. Öffentliche und interne Identitäten

Öffentliche APIs geben keine rohen Apple-Identifier heraus und nehmen keine
entgegen. Interne Persistenz (`contacts_mutations`, `contact_external_ids`,
`contacts_sync_state`), Sync-Logik und Sidecar arbeiten unverändert mit den
echten Kennungen; die Maskierung liegt allein an der Transportgrenze
(`api/redaction.py`, dieselbe Bildung wie die Auditspur).

**Zieladressierung der Eingaben:**

| Kommando | Öffentliche Zieladresse | Interne Auflösung |
|---|---|---|
| `update`, `delete` | kanonische lokale `contact_id` (Pfadparameter, wie heute) | `contact_id` → `contact_external_ids` → (`provider_account_id`, `container_identifier`, `provider_identifier`); genau **eine** externe Identität erforderlich, sonst fail-closed `ambiguous_target` |
| `create` | maskierte `container_ref` (+ `account_ref`) | Rückwärtsauflösung über die bekannten Container aus `contacts_sync_state`: `container_ref()` je Kennung berechnen, genau **ein** Treffer erforderlich; kein Treffer ⇒ `unknown_container_ref`, mehrere ⇒ `ambiguous_container_ref` — beides fail-closed, nie geraten |

`target_provider_identifier` und `provider_account_id` verschwinden aus den
Eingabemodellen (`_MutationBase`, `CreateContactIn`, `UpdateContactIn`,
`DeleteContactIn`). `expected_revision` bleibt öffentlich, wird für `update`
und `delete` **Pflicht** und bezeichnet die **lokale** Revision
(`contacts.local_revision`), die das Detailmodell dafür ausweist — sie ist
keine Apple-Kennung.

**Ausgabemodelle** (`PreparedMutationOut`, `MutationOut`, `MutationDetailOut`,
`ReconcileOut`, `ContactDetailOut`) — erlaubt sind ausschließlich:

- lokale `contact_id`, lokale `mutation_id`, `approval_id`, `correlation_id`
- maskierte `account_ref`, maskierte `container_ref`, `provider_type`
- Zustand, Vorschau (Feldname, vorher, geplant), `target_label`,
  Digests, Zeitstempel, Versuchszähler, technische Fehlercodes,
  aggregierte Zählwerte

Nicht öffentlich (weder als Feld noch im Fehlertext): `provider_identifier`,
`container_identifier`, `provider_account_id`, Cursor oder Token, Apple-interne
Kennungen jeder Art, Dateipfade. Konkret ersetzt werden:
`PreparedMutationOut.target_provider_identifier` → `contact_id`;
`…container_identifier` → `container_ref`; `MutationOut.provider_account_id` →
`provider_type` + `account_ref`; `MutationOut.container_identifier` →
`container_ref`; `ReconcileOut.provider_identifier` → entfällt (die
`contact_id` genügt); `ContactDetailOut.provider_accounts` → `account_refs`;
`…containers` → `container_refs`; `…write_target` → `writable: bool` +
`revision: str` (serverseitig abgeleitet — die Oberfläche zielt fortan über
die `contact_id`, die sie ohnehin führt).

Die Regressionssuite `test_sync_status_privacy.py` wird auf die
Mutationsverträge ausgedehnt (gleiche Prüfmuster: kein Rohwert, kein
Teilstring, geschlossene Feldmenge).

### 3. Geschlossener Feldvertrag v1

Das freie `fields: dict[str, Any]` wird durch einen **versionierten,
geschlossenen Vertrag** ersetzt (`field_contract_version = 1`). Unbekannte
Feldnamen sind `invalid_request` — fail-closed, keine Durchreichung. Der
Vertrag ist aus dem vorhandenen Read-Modell abgeleitet (Domänenmodell,
Mapper, Sidecar-DTO); es wird nichts zugesagt, was der Lesepfad nicht belegt.

**Skalare Textfelder** — alle: Typ `string`, optional, Create ✓, Update ✓,
Löschen eines Wertes durch ausdrückliches `null` (leerer String nach
Whitespace-Strip ist `invalid_request`), Normalisierung nur im Kern
(Whitespace-Strip; der Sidecar normalisiert nie), Validierung: keine
Steuerzeichen, Länge ≤ 256, Label entfällt, Read-back verlustfrei ✓:

| API-Name | Apple-Ziel (`CNMutableContact`) |
|---|---|
| `given_name` | `.givenName` |
| `middle_name` | `.middleName` |
| `family_name` | `.familyName` |
| `previous_family_name` | `.previousFamilyName` |
| `name_prefix` | `.namePrefix` |
| `name_suffix` | `.nameSuffix` |
| `nickname` | `.nickname` |
| `phonetic_given_name` | `.phoneticGivenName` |
| `phonetic_family_name` | `.phoneticFamilyName` |
| `organization_name` | `.organizationName` |
| `department_name` | `.departmentName` |
| `job_title` | `.jobTitle` |

**`contact_type`** — `"person" | "organization"`, nur Create (Update ✗: eine
Typänderung ist in v1 nicht zugesagt), Apple-Ziel `.contactType`, Read-back
verlustfrei ✓.

**`birthday`** — Objekt `{year?: int, month: int, day: int}`, optional,
Create ✓, Update ✓, Löschen durch `null`, Apple-Ziel `.birthday`
(`DateComponents`; Jahr optional), Validierung wie im Domänenmodell
(Monat 1–12, Tag 1–31), Label entfällt, Read-back verlustfrei ✓.

**Etikettierte Listen** — Update ersetzt die **gesamte benannte Liste**
(Item-Identität ist in v1 nicht Vertragsbestandteil); Löschen aller Werte
durch ausdrückliche leere Liste `[]`; `null` ist für Listen
`invalid_request`; Reihenfolge = Positionsreihenfolge; Read-back
verlustfrei ✓ (für den geschlossenen Labelvorrat):

| API-Name | Elementform | Max. | Labels (geschlossen) | Apple-Ziel | Validierung |
|---|---|---|---|---|---|
| `emails` | `{label, value}` | 10 | `home\|work\|other\|null` | `.emailAddresses` (`CNLabeledValue<NSString>`) | enthält `@`, kein Whitespace, ≤ 254 |
| `phones` | `{label, value}` | 10 | `home\|work\|mobile\|main\|other\|null` | `.phoneNumbers` (`CNPhoneNumber(stringValue:)`) | nicht leer, ≤ 64; E.164-Normalform entsteht nur im Kern-Spiegel |
| `postal_addresses` | `{label, street?, city?, state?, postal_code?, country?, iso_country_code?}` | 5 | `home\|work\|other\|null` | `.postalAddresses` (`CNMutablePostalAddress`) | Komponenten ≤ 256; `iso_country_code` 2 Zeichen |
| `urls` | `{label, value}` | 10 | `home\|work\|other\|null` | `.urlAddresses` | nicht leer, ≤ 512 |
| `dates` | `{label, year?, month, day}` | 5 | `other\|null` (frei benannte Anlässe erst mit v2) | `.dates` | wie `birthday` |

Der geschlossene Labelvorrat bildet auf die Apple-Standardlabels ab
(`CNLabelHome`, `CNLabelWork`, `CNLabelPhoneNumberMobile`,
`CNLabelPhoneNumberMain`, `CNLabelOther`); der Lesepfad normalisiert sie
bereits heute verlustfrei zurück (`normalize_label`). **Freie Labels sind in
v1 nicht zugesagt** (`invalid_request`).

**Ausgeschlossen in v1** — unverändert nicht Vertragsbestandteil, jede
Aufnahme braucht eine Vertragsversion v2 und ggf. einen eigenen ADR:
Notizen (`notesSupported=false`, Entitlement-Grenze), Kontaktbild/Thumbnail,
Me-Karte als Ziel, Link/Unlink, `social_profiles`, `instant_messages`,
`relations`, Gruppenmitgliedschaften, `sub_locality` (im Read-Modell
vorhanden, aber vom Sidecar-DTO nicht ausgegeben — ein Schreibvertrag dafür
wäre nicht read-back-verlustfrei), unbekannte freie Felder.

**Keine stillen Feldlöschungen:** `update` verändert ausschließlich
ausdrücklich angegebene Felder; nicht genannte Felder — auch außerhalb des
v1-Vertrags liegende wie Notizen oder Bilder — bleiben unangetastet, weil der
Sidecar auf der `mutableCopy` des gezielt gelesenen Kontakts nur die
benannten Eigenschaften setzt.

### 4. Sidecar-Schreibvertrag

Der Sidecar bleibt dünn (ADR-0016 Punkt 4 gilt unverändert). Er **darf**:
den geschlossenen Feldvertrag validieren, `CNMutableContact` erzeugen bzw.
aus einem gezielt über den Identifier gelesenen Kontakt ableiten,
`CNSaveRequest` ausführen, `transactionAuthor` (= Bundle-Identifier des
Sidecars, identisch mit `TRANSACTION_AUTHOR` im Kern) setzen, den konkret
geschriebenen Kontakt erneut lesen (`shouldRefetchContacts = true`,
macOS ≥ 12.3 — der Grund der Mindestversion aus ADR-0018) und eine
technische, PII-arme Antwort liefern. Er **darf nicht**: Freigaben
entscheiden, Domänenregeln bewerten, Kontakte anhand von Namen suchen,
automatisch wiederholen, lokale Rollen oder Kategorien kennen oder direkt in
`personal/jarvis.db` schreiben.

**Anfragen** (zusätzlich zu den bereits erzwungenen Pflichtfeldern
`mutationId`, `idempotencyKey`, `approvalId`; alle Mutationen tragen
`contractVersion` und `fieldContractVersion`):

| Operation | Nutzlast |
|---|---|
| `create` | `containerIdentifier`, `contactType?`, `fields` (v1) |
| `update` | `targetProviderIdentifier`, `fields` (v1), `expectedPrevious` (vorherige Werte **genau der benannten Felder**, aus dem lokalen Spiegel) |
| `delete` | `targetProviderIdentifier`, `expectedFieldsDigest` (Digest des v1-Feldstands aus dem lokalen Spiegel) |

`expectedPrevious`/`expectedFieldsDigest` schließen das Zeitfenster zwischen
Spiegel und Provider: der Sidecar liest das Ziel, vergleicht die benannten
Felder mit dem erwarteten Vorzustand und lehnt bei Abweichung **vor** dem
Save als Konflikt ab. Zusammen mit der Pflicht-`expected_revision` gegen den
lokalen Spiegel (die seit der Vorbereitung unveränderte Revision) ist damit
durchgehend belegt: **ausgeführt wird genau das, was der Mensch in der
Vorschau gesehen hat** — oder nichts.

**Geschlossener Ergebnisvertrag** (genau drei Ausgänge):

| Ausgang | Bedeutung | Inhalt |
|---|---|---|
| `applied` | Provideränderung bestätigt **und** belegt | `providerIdentifier`; vollständiger Read-back-DTO des geschriebenen Kontakts (bei `delete` stattdessen der Beleg der bestätigten Abwesenheit: gezielter Fetch ⇒ `recordDoesNotExist`) |
| `not_sent` | nachweislich kein `execute(save)` an den Store übergeben | `errorCode` aus der geschlossenen Menge (`invalid_request`, `not_found`, `conflict`, `forbidden`, `tcc_denied`, `unsupported`, `provider_error`); terminal für diesen Vorgang |
| `outcome_unknown` | Save möglicherweise übergeben | `errorCode`; gilt auch, wenn der Save bestätigt wurde, aber der Read-back scheitert (`readback_failed_after_save`) — der geschlossene Vertrag kennt kein „angewandt ohne Beleg", der Abgleich liefert den Beleg nach |

Aus Kernsicht gilt zusätzlich: Timeout, Prozessabbruch oder Protokollfehler
während einer mutierenden Operation ⇒ `outcome_unknown`. Für Mutationen gilt
ein eigener Anfrage-Timeout (Vorgabe 120 s statt der allgemeinen 30 s), denn
ein Timeout ist hier nie folgenlos, sondern erzeugt Abgleicharbeit.

**Präzisierung 2026-08-01 (Umsetzung M2): der Read-back-Digest entsteht im Kern.** Dieser ADR nannte `readBackDigest` ursprünglich als Feld der Sidecar-Antwort. Bei der Umsetzung stellte sich heraus, dass seine Bildung die **Rücknormalisierung der Apple-Rohlabels** verlangt (`_$!<Work>!$_` → `work`) — und Normalisierung ist nach ADR-0016 Punkt 4 ausdrücklich Kernaufgabe und dem Sidecar verboten. Ein im Sidecar gebildeter Digest wäre für den Kern ausserdem nicht nachrechenbar, und zwei Digest-Bildungen wären zwei Wahrheiten. **Deshalb:** der Sidecar liefert den zurückgelesenen Datensatz als DTO, der Kern projiziert ihn auf den Feldvertrag v1 und bildet daraus den Beleg (`application.field_contract.readback_digest`). Die Eigenschaft bleibt unverändert — deterministisch, plattformstabil, ohne Kennung, Pfad oder Zeitstempel, mit eingebundener Vertragsversion.

**Idempotenz im Sidecar:** Der Sidecar darf sich prozesslokal
(`idempotencyKey` → Ergebnis) erinnern und eine Wiederholung mit demselben
Schlüssel mit dem gemerkten Ergebnis beantworten. Das ist eine
**Robustheitshilfe und keine Exactly-once-Garantie** — das Gedächtnis stirbt
mit dem Prozess. Die tatsächliche Garantie „höchstens ein Send je Mutation"
erbringt allein der Kern (Outbox-Claim, verbrauchte Freigabe, terminale
Zustände, kein automatischer Retry) und sie ist **at-most-once**, nicht
exactly-once: der Preis ist `outcome_unknown` plus Abgleich, nie ein
Doppelsend.

**Abgleichleser:** Für `create`-Abgleiche ohne gemeldete Identität erhält der
Sidecar eine **rein lesende** Probe-Operation, die die Change-History
**einschließlich** des eigenen Transaktionsautors abfragt (der normale
`changes`-Pfad schließt ihn gerade aus) und Add-Ereignisse des eigenen
Autors liefert. Der Kern ordnet ausschließlich darüber zu — niemals über
Namen. Liefert die Probe nichts Eindeutiges, endet der Abgleich in
`manual_decision_required`.

### 5. Providererfolg und lokale Nachführung

Das bestehende Zustandsmodell kann die Zwischenlage „Provideränderung
bestätigt, aber lokale Nachführung offen" **nicht** eindeutig abbilden:
`reconcile_required` ist heute die Arbeitsphase eines laufenden Abgleichs aus
`outcome_unknown` — ein bestätigter Providererfolg wäre darin von einem
ungewissen Ausgang nicht unterscheidbar, und `recover_interrupted()` würde
einen Abbruch nach bestätigtem Save fälschlich als unbekannt einstufen.
Deshalb wird der Zustandsvorrat **additiv** erweitert:

```
executing → provider_applied_pending_reconcile → succeeded
```

- **Phase C1** (kleine UnitOfWork, unmittelbar nach der Providerantwort
  `applied`): Outbox-Eintrag als gesendet-und-erfolgreich schließen,
  `provider_identifier` und `readback_digest` festschreiben, Zustand
  `provider_applied_pending_reconcile`, Audit `provider_result_received`.
- **Phase C2** (eigene UnitOfWork): kanonische Nachführung des Spiegels aus
  dem Read-back über den vorhandenen Mapper (`create`: neue `contacts`-Zeile
  + `contact_external_ids`-Zeile, `target_contact_id` nachtragen; `update`:
  `merge_into_existing`, `local_revision` schreitet fort; `delete`:
  Tombstone mit eigenem Grund `deleted_by_own_mutation`), Zustand
  `succeeded`, Audit `mutation_completed` — **atomar in dieser einen
  UnitOfWork**.

Eine Mutation gilt erst als `succeeded`, wenn **alle vier** Bedingungen
erfüllt sind: Provideränderung bestätigt, Read-back erfolgreich, kanonischer
Spiegel nachgeführt, Audit abgeschlossen. Der Provideraufruf selbst bleibt
außerhalb jeder Datenbanktransaktion.

Scheitert C2 oder stirbt der Prozess dazwischen, bleibt der Vorgang sichtbar
in `provider_applied_pending_reconcile`: **kein weiterer Send ist erlaubt**,
`recover_interrupted()` fasst diesen Zustand nicht an (es behandelt nur
`executing`), und die Auflösung läuft über den vorhandenen, ausdrücklich
nutzergestarteten Abgleich: erneut lesen, Spiegel nachführen, abschließen.
`MutationState.NEEDS_RECONCILE` wird um den neuen Zustand erweitert; ebenso
die Echo-Sperrmenge `IN_FLIGHT_STATES` (Kern) und der Zustandsvorrat des
Domänen-Enums — das eigene Provider-Ereignis kann eintreffen, während die
Nachführung noch aussteht.

**Notwendige additive Migration** (benannt, **nicht** implementiert; nächste
freie Nummer, derzeit 0006): Neuaufbau von `contacts_mutations` nach dem
0004-Muster mit (a) `provider_applied_pending_reconcile` im
Zustands-CHECK und (b) neuer Spalte `readback_digest TEXT` (Digest, kein
Inhalt). Weitere Tabellen sind nicht betroffen.

### 6. Capability-Brücke und Vertragsversionierung

```
Sidecar-Handshake → BridgeStatus → ContactCapabilitySet
```

Der Handshake deklariert zusätzlich: `mutationContractVersion: 1`,
`fieldContractVersion: 1`, `createSupported`, `updateSupported`,
`deleteSupported` (einzeln, boolesch). Der Kern führt als Konstante seinen
eigenen unterstützten Vertragsstand und schaltet **je Operation** frei:

```
create_supported = handshake.createSupported
                   ∧ handshake.mutationContractVersion == KERN_VERSION
                   ∧ handshake.fieldContractVersion == KERN_FELD_VERSION
```

(analog `update_supported`, `delete_supported` — Create schaltet Update und
Delete **nicht** mit frei). Regeln: standardmäßig alles False; fehlender,
unbekannter oder nicht parsbarer Handshake ⇒ False; Versionsungleichheit ⇒
False — damit kann weder ein alter Sidecar von einem neuen Kern noch ein
neuer Sidecar von einem alten Kern versehentlich freigeschaltet werden. Die
Ableitung geschieht einmal bei `start()` im Lifecycle; `capabilities` und UI
bleiben fail-closed (`mutations_available` bleibt False, solange die Brücke
nichts belegt). Jede Mutationsanfrage an den Sidecar trägt beide Versionen;
der Sidecar lehnt fremde Stände mit `invalid_request` ab.

### 7. Risikoklassen (Architekturvorschlag — nicht beschlossen)

Als Vorschlag festgehalten, **ausdrücklich nicht entschieden** (17 §1:
Empfehlungen sind unverbindlich): **Create R1, Update R1, Delete R2.**

Für Delete beginnt **keine** Produktimplementierung, bevor **DEC-D06**
(optionale native R2-Zweitbestätigung) entschieden ist — Kontakte-Delete wäre
die erste R2-Operation des Systems. Vor Delete sind festzulegen: die
zusätzliche In-App-Bestätigung, ggf. die native zweite Bestätigung, die
genaue Darstellung des zu löschenden Kontakts in der Vorschau
(vollständiger Snapshot, §7.3 des Modulplans), und dass es keine
automatische Kaskade gibt (genau ein Datensatz je Vorgang). Create und
Update benötigen unverändert Vorschau, Freigabe und die separate
Execute-Aktion; der heute fest verdrahtete Wert `risk_class="R1"` wird mit
der Delete-Implementierung je Kommando differenziert.

### 8. `SyncStatusOut`

Die Identifier-Härtung vom 2026-07-31 (Commit `0892459`) bleibt unverändert.
Es gibt **keine** Migration allein für `error_code`, `retryable` oder
zusätzliche Aggregatzahlen im Statusvertrag: diese Felder werden erst
ergänzt, wenn eine verlässliche fachliche Quelle (Spalten mit definiertem
Schreibpfad in der Sync-Logik) und ein klarer UI-Verbraucher existieren.

### 9. Verbindliche Implementierungsreihenfolge

| Phase | Inhalt | Abschlusskriterium |
|---|---|---|
| **M1** | Architektur und ADRs: dieser ADR, geschlossener Feldvertrag v1, Identitätsvertrag, Ergebnis- und Zustandsvertrag, Capability-Brücke spezifiziert | dieser Commit |
| **M2** | **Ausschließlich Create, vertikal:** Sidecar-`create` + Read-back, Bridge-Provider im Kern, Migration (Zustand + `readback_digest`), Execute-Route, lokale Nachführung, Audit, Identitätshärtung der Mutationsverträge, Feldvertrag v1 im Transport, Capability-Brücke, UI, Fake- und kontaktfreie native Tests; danach Intel-x86_64-Livetest mit einem eigens angelegten Testkontakt | Live-Abnahme x86_64 |
| **M3** | arm64-Gegenprüfung von Create auf echter Hardware (DEC-042: kein Ergebnis gilt automatisch für die andere Architektur) | Live-Abnahme arm64 |
| **M4** | Update vollständig, Abnahme auf **beiden** Architekturen | beide Abnahmen |
| **M5** | **Zuerst DEC-D06 entscheiden**, dann Delete vollständig, Abnahme auf **beiden** Architekturen | DEC-D06 + beide Abnahmen |

Keine parallele Implementierung aller drei Operationen. Jede Phase beginnt
erst nach ausdrücklicher Freigabe des Eigentümers.

### 10. Architektur-Red-Team

| Szenario | Erwarteter Zustand | Weiterer Send? | Reconcile-Verhalten | Benutzeranzeige | Audit-Ausgang |
|---|---|---|---|---|---|
| Doppelte Ausführung nach Timeout | `outcome_unknown` (Freigabe verbraucht, Outbox-Claim vergeben); zweiter `execute`-Aufruf wird typisiert abgewiesen | **nein** | liest; Urteil `applied`/`not_applied`/`ambiguous` | „Ausgang ungeklärt — zuerst abgleichen" | `provider_send_started` → `outcome_unknown(timeout)`; kein zweites `provider_send_started` |
| Prozessabbruch direkt nach erfolgreichem Save (vor C1) | Zeile bleibt `executing`; `recover_interrupted()` ⇒ `outcome_unknown(interrupted)` | nein | liest ⇒ `applied` ⇒ `succeeded` + Nachführung über den Abgleichweg | „Ausgang ungeklärt — zuerst abgleichen" | `outcome_unknown(recovered)` → `reconcile_succeeded` → `mutation_completed(viaReconcile)` |
| Save bestätigt, Read-back scheitert | Sidecar antwortet `outcome_unknown(readback_failed_after_save)` ⇒ Kern `outcome_unknown` | nein | liest, findet den Beleg ⇒ `succeeded` | wie oben | wie oben |
| Read-back ok, lokale Transaktion (C2) scheitert | `provider_applied_pending_reconcile` (C1 ist festgeschrieben) | **nein — nie** | kein Urteil nötig: erneut lesen, Spiegel nachführen, abschließen | „Beim Provider angewandt — lokale Übernahme ausstehend" | `provider_result_received(applied)`; `mutation_completed` erst nach C2 |
| Veraltete Freigabe nach zwischenzeitlicher Provideränderung | Spiegel aktuell: `RevisionConflict` im Precheck ⇒ `failed_before_send`; Spiegel veraltet: Sidecar-`expectedPrevious`-Vergleich ⇒ `not_sent(conflict)` ⇒ `failed_before_send` | nein | entfällt (nichts gesendet) | „Der Kontakt hat sich geändert — neue Vorschau nötig" | `failed_before_send(sent=false)` |
| Falscher/unbekannter Container (Create) | Auflösung der `container_ref` scheitert fail-closed (`unknown_container_ref`/`ambiguous_container_ref`) vor `prepare`; providerseitige Ablehnung (z. B. Nur-Lese-Container) ⇒ `not_sent(forbidden)` ⇒ `failed_before_send` | nein | entfällt | Fehlermeldung mit technischem Code, keine Rohkennung | Vorgang entsteht nicht bzw. `failed_before_send` |
| Kontakt zwischen Prepare und Execute gelöscht | Spiegel weiß es: Zielauflösung scheitert ⇒ `failed_before_send`; Provider weiß es zuerst: Sidecar-Fetch ⇒ `not_sent(not_found)` ⇒ `failed_before_send` | nein | entfällt | „Der Kontakt existiert nicht mehr" | `failed_before_send(sent=false)` |
| Kontakt zwischen Prepare und Execute verändert | wie „veraltete Freigabe": Revisionspflicht + `expectedPrevious` fangen beide Wege | nein | entfällt | „neue Vorschau nötig" | `failed_before_send(sent=false)` |
| Sidecar- und Kernversion inkompatibel | Capability-Brücke schaltet nicht frei ⇒ `prepare` scheitert typisiert (`CapabilityNotDeclared`); zur Laufzeit lehnt der Sidecar fremde Vertragsstände mit `invalid_request` ab ⇒ `not_sent` | nein | entfällt | „Änderungen sind nicht freigeschaltet" | kein Vorgang bzw. `failed_before_send` |
| Mehrfacher Klick auf Execute | erster Aufruf gewinnt den Outbox-Claim (BEGIN IMMEDIATE); jeder weitere wird mit `AlreadySettled`/`MutationNotExecutable` abgewiesen | genau **einer** | unverändert | zweiter Klick zeigt den aktuellen Zustand | genau ein `provider_send_started` |
| App-Neustart während der Ausführung | vor C1: wie Prozessabbruch (⇒ `outcome_unknown`); zwischen C1 und C2: `provider_applied_pending_reconcile` bleibt bestehen | nein | wie in den beiden Zeilen oben | zustandsgetreue Anzeige | lückenlos: jede Stufe wurde vor dem Abbruch festgeschrieben |
| Eigener Change-History-Echo | Primär filtert der Provider (`excludedTransactionAuthors`); sekundär sperrt der Kern (`EchoSuppressionLedger`, `IN_FLIGHT_STATES` inkl. des neuen Zustands) | — | — | keine Doppelanzeige, kein Wiederauferstehen | Sync-Auditspur zählt das Ereignis nicht als Fremdänderung |
| Maskierungsreferenz kollidiert (zwei Container, gleiche `container_ref`) | Auflösung findet ≥ 2 Treffer ⇒ `ambiguous_container_ref`, fail-closed; nichts wird geraten | nein | entfällt | Fehlermeldung; Ausweg ist ein anderer Zielcontainer | kein Vorgang entsteht |
| Provider-Identifier wechselt (Apple-interne Neuvergabe) | Zielauflösung geschieht **frisch bei Execute** aus dem Spiegel; kennt der Provider die Kennung nicht mehr ⇒ `not_sent(not_found)` ⇒ `failed_before_send`; der nächste Delta/Voll-Diff führt den Spiegel nach, danach neuer Vorgang | nein | entfällt | „Der Kontakt existiert nicht mehr — nach dem nächsten Abgleich erneut versuchen" | `failed_before_send(sent=false)` |
| Create erfolgreich, Antwort geht verloren | Kern sieht Protokoll-/Prozessfehler ⇒ `outcome_unknown` | nein | Autor-Probe der Change-History (nie Namen) ⇒ Identität belegt ⇒ `succeeded` + Nachführung; kein Beleg ⇒ `manual_decision_required` | „Ausgang ungeklärt — zuerst abgleichen" | `outcome_unknown` → `reconcile_*`; bei Mehrdeutigkeit `manual_decision_required` |

## Konsequenzen

- Die fünf offenen Enden (Sidecar-Schreibpfad, Provider, Ausführungsweg,
  Abgleichleser, Capability-Brücke) haben jetzt einen festgeschriebenen
  Vertrag; M2 implementiert davon ausschließlich den Create-Strang.
- Die Mutationsverträge der API werden im Zuge von M2 identitätsgehärtet —
  dieselbe Grenze, die `/sync/status` seit `0892459` zieht.
- `contacts_mutations` braucht genau eine additive Migration (Zustand +
  `readback_digest`); `personal_approvals`, Outbox und Audit bleiben
  unverändert.
- Delete ist doppelt verriegelt: hinter M4 **und** hinter der offenen
  Entscheidung DEC-D06.
- DEC-D17 (Auslieferungsformat) wird durch diesen ADR nicht berührt.
