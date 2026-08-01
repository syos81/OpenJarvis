# Kontakte-Bridge — produktiver JSON-Lines-Vertrag

**Produktiv, Gate B.** Dies ist **nicht** der Spike-Vertrag
(`spikes/contacts-bridge-g3a/PROTOCOL.md`); die Abweichungen sind in
`docs/personal-jarvis/modules/contacts.md` §9.1 begründet.

## Transport

Ein UTF-8-JSON-Objekt je Zeile über stdin/stdout. **`stdout` ist ausschließlich
Protokollkanal** — jede Diagnose geht nach `stderr`, niemals mit
personenbezogenen Daten (Namen, E-Mails, Nummern, Identifiern).

## Hülle

**Anfrage:**
```json
{"protocolVersion":1,"requestId":<int>,"operation":"<name>","payload":{}}
```

**Erfolg:**
```json
{"protocolVersion":1,"requestId":<int>,"ok":true,"result":{}}
```

**Fehler:**
```json
{"protocolVersion":1,"requestId":<int>,"ok":false,
 "error":{"code":"<geschlossene Menge>","message":"<Text>","retryable":<bool>}}
```

**Streaming** (nur `enumerate`): Zwischenzeilen
`{"protocolVersion":1,"requestId":<int>,"stream":"item","item":{…}}`,
abgeschlossen durch die reguläre Erfolgsantwort mit `complete:true` und
`count`. **Eine ohne `complete:true` beendete Enumeration ist ungültig und darf
nie als Löschmenge interpretiert werden.**

Eine **inkompatible `protocolVersion` wird fail-closed** mit
`protocol_mismatch` abgelehnt.

## Handshake

Erste Zeile nach dem Start, ohne vorherige Anfrage:

```json
{"type":"ready","protocolVersion":1,
 "bundleIdentifier":"de.kluender.jarvis.contacts-bridge",
 "transactionAuthor":"de.kluender.jarvis.contacts-bridge",
 "keySetVersion":1,"authorizationStatus":"<status>",
 "operations":[…],"capabilities":{…}}
```

## Capabilities

| Feld | Wert | Begründung |
|---|---|---|
| `notesSupported` | `false` | `CNContactNoteKey` erfordert das Entitlement `com.apple.developer.contacts.notes`. Der Schlüssel wird **nicht** angefordert; das Feld meldet `unavailable_by_capability` — **nie** eine leere Notiz (08 §4, Plan §3). |
| `linkUnlinkSupported` | `false` | `CNSaveRequest` besitzt keine Link-/Unlink-API. Belegter Plattformbefund. |
| `unifiedReadOnly` | `true` | Der `unifiedIdentifier` ist belegt instabil und nie Schreibziel. |
| `meCardReadOnly` | `true` | Me-Karte ist in v1 schreibgeschützt (Plan §7.3). |
| `changeHistorySupported` | `true` | Delta-Pfad über den Objective-C-Shim. |
| `fullDiffFallbackSupported` | `true` | Pflichtbestandteil (ADR-0016 Punkt 5). |
| `mutationsImplemented` | `false` | Bis Gate C liefern `create`/`update`/`delete` `not_implemented`. |

## Operationen

| Operation | Payload | Ergebnis (Auszug) | Store-Zugriff |
|---|---|---|---|
| `ping` | — | `{"pong":true}` | nein |
| `caps` | — | Handshake-Felder | nein |
| `authorizationStatus` | — | `{"authorizationStatus":"…"}` | nein |
| `requestAuthorization` | `{"request":true}` | `{"granted","authorizationStatus","promptAttempted"}` | Dialog |
| `containers` | — | `{"containers":[…],"keySetVersion"}` | ja |
| `enumerate` | `{"containerIdentifier"?}` | streamt DTOs, dann `{"count","complete":true,"keySetVersion"}` | ja |
| `changes` | `{"startingToken"?}` | `{"events","count","currentToken","keySetVersion"}` | ja |
| `get` | `{"providerIdentifier"}` | `{"contact"}` | ja |
| `getUnifiedReadOnly` | `{"providerIdentifier"}` | `{"contact","unifiedIdentifier","identifierChanged","readOnly":true}` | ja |
| `create`/`update`/`delete` | siehe unten | bis Gate C `not_implemented` | **nein** |
| `shutdown` | — | `{"bye":true}` → `exit(0)` | nein |

**`requestAuthorization` erfolgt ausschließlich auf ausdrückliche
Nutzeraktion** — `payload.request` muss `true` sein. Es gibt kein Env-Gate und
keinen impliziten Weg; ein Start des Sidecars fordert **nie** Berechtigungen an.

**Es existiert bewusst keine `token`-Operation.** Der Cursor stammt
ausschließlich aus der `changes`-Antwort; ein zweiter Store-Read für den Cursor
ist der Fehler, den 11 §3 verbietet.

## Mutationen (`create` implementiert seit M2; `update`/`delete` nicht)

Pflichtfelder je Mutation: `mutationId`, `idempotencyKey`, `approvalId`,
`mutationContractVersion`, `fieldContractVersion`; bei `create` zusätzlich
`containerIdentifier` und `fields` (Feldvertrag v1). `update`/`delete`
antworten weiterhin `not_implemented` — ohne Store-Zugriff.

Geschlossener Ergebnisvertrag von `create` (immer `ok:true`):
`outcome ∈ {applied, not_sent, outcome_unknown}`. `applied` trägt
`providerIdentifier`, `containerIdentifier` und den Read-back-DTO;
`not_sent` ist ausschließlich **vor** jeder Store-Übergabe möglich.

**Objective-C-Exception-Grenze (seit 2026-08-01, ADR-0019 §4a):** Der eine
`executeSaveRequest:error:` läuft in einer `@try/@catch`-Grenze
(`JCContactsSaveShim`). Eine gefangene `NSException` ergibt
`outcome: outcome_unknown` mit `errorCode: objc_exception`,
`exceptionName` (bereinigter Klassenname), `reasonPresent`,
`reasonDigest` (SHA-256 des unveränderten Reason-Texts) und
`processMustTerminate: true`. Danach schreibt der Sidecar genau diese eine
Antwort, flusht und beendet sich mit `exit(0)` — der Host liest die Antwort
vor dem Exit; ein Exit **ohne** Antwort bleibt ein Prozessfehler
(`child_signalled`/`child_exited`). Wirft Apples Dispatch-Pfad selbst (dann erreicht kein `@catch` die
Ausnahme), stirbt der Prozess weiterhin per SIGABRT — der beim Start
installierte Uncaught-Handler schreibt zuvor best-effort
`[contacts-bridge] uncaught_objc_exception name=<bereinigt>
reasonDigest=<sha256|unavailable>` nach stderr und füllt das **vor** dem
Save vorbereitete Diagnoseartefakt über den bereits offenen Deskriptor
(`source: "uncaught"`); ohne Wurf wird die vorbereitete leere Datei wieder
entfernt. Der volle `reason` erscheint niemals in
stdout/stderr; nur der ausdrücklich per
`OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH` aktivierte Diagnosemodus
legt ihn als exklusive 0600-Datei in einen benutzereigenen 0700-Ordner.

Es gibt **keinen** Präfix-Rail: produktiv sichert die Vorgangsbindung
(Ziel-ID, Freigabe, Idempotenzschlüssel), nicht ein Namensmuster.

## DTO

Deterministische Serialisierung: sortierte Schlüssel, explizite `null`-Werte
statt weggelassener Felder, keine locale-abhängige Formatierung.

`fieldAvailability` je Risikofeld mit `present | absent |
unavailable_by_capability` — der **einzige** Ort, an dem „nicht lesbar" von
„leer" unterschieden wird. `fieldCompleteness` ist `full` oder `partial`.
`isMeCard` kennzeichnet die Me-Karte.

**Bewusst außen vor:** Normalisierung, Hashing, Anzeigenamen-Bildung, Fach-,
Risiko- und Auditlogik — all das bleibt im Kern (ADR-0016 Punkt 4).

## Fehlercodes (geschlossen)

`tcc_denied` · `not_found` · `conflict` · `invalid_request` · `forbidden` ·
`provider_error` · `unsupported` · `internal` · `not_implemented` ·
`protocol_mismatch` · `invalid_token`

Die Abbildung auf `CapabilityError` erfolgt außerhalb der Bridge (08 §3 Nr. 5).

## Lebenszyklus

Nicht-JSON-Zeilen werden mit `invalid_request` beantwortet; der Kanal bleibt
funktionsfähig. Der Host startet **beide** Drainer (stdout und stderr) **vor**
dem ersten Write. `{"operation":"shutdown"}` → Antwort → `exit(0)`; EOF auf
stdin beendet den Prozess ebenfalls mit `exit(0)`.
