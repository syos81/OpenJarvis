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

## Mutationen (Vertrag ab jetzt, Implementierung in Gate C)

Pflichtfelder je Mutation: `mutationId`, `idempotencyKey`, `approvalId`;
bei `update`/`delete` zusätzlich `targetProviderIdentifier` und — soweit
anwendbar — `expectedRevision`. Fehlen sie, antwortet die Bridge mit
`invalid_request` und benennt die fehlenden Felder. Sind sie vollständig,
antwortet sie mit `not_implemented`. **In keinem Fall findet ein
Store-Schreibzugriff statt.**

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
