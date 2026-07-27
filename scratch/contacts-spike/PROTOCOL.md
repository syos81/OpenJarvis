# Kontakte-Sidecar-Protokoll — SPIKE G3a (ADR-0016)

Technische Protokollspezifikation des im Spike gebauten Kontakte-Sidecars.
**Nicht produktiv** — dieses Dokument beschreibt Spike-Code, keinen Vertrag
im Sinne von `docs/personal-jarvis/08-provider-account-and-adapter-model.md`.

## Transport

Ein UTF-8-JSON-Objekt je Zeile über stdin/stdout (JSON-Lines). `stdout` ist
**ausschließlich Protokollkanal** — jede Diagnose geht nach `stderr`, niemals
mit personenbezogenen Daten (Namen, E-Mails, Telefonnummern, Identifiern).

## Handshake

Erste Zeile nach dem Start, ohne vorherige Anfrage:

```json
{"type":"ready","protocol":1,"authorizationStatus":"<status>",
 "keySetVersion":1,"transactionAuthor":"de.jarvis.contacts-spike",
 "caps":["ping","caps","containers","enumerate","changes","token",
         "get","getUnified","create","update","updateViaUnified",
         "delete","shutdown"],
 "limits":{"mutationsRestrictedToPrefix":"ZZZ-JarvisTest-",
           "linkUnlinkSupported":false}}
```

`linkUnlinkSupported:false` ist keine Spike-Einschränkung, sondern ein
belegter Plattformbefund: `CNSaveRequest` bietet keine Link-/Unlink-API
(nur add/update/delete Contact/Group/Member).

## Envelope

**Anfrage:**
```json
{"id": <beliebig, vom Aufrufer gewählt>, "op": "<name>", "params": {...}}
```

**Erfolgsantwort:**
```json
{"id": <gleiche id>, "ok": true, "result": {...}}
```

**Fehlerantwort:**
```json
{"id": <gleiche id>, "ok": false,
 "error": {"code": "<geschlossene Menge>", "message": "<Text>", "retryable": <bool>}}
```

**Fehlercodes (geschlossen):** `tcc_denied`, `not_found`, `conflict`,
`invalid_request`, `forbidden`, `provider_error`, `unsupported`, `internal`
sowie **SPIKE-ONLY** `operation_disabled` (siehe Abschnitt
„SPIKE-ONLY: requestAuthorization"). Die Abbildung auf `CapabilityError`
erfolgt außerhalb des Sidecars.

**Streaming** (nur `enumerate`): null oder mehr Zwischenzeilen
`{"id":<id>,"stream":"item","item":{...}}`, abgeschlossen durch die reguläre
Erfolgsantwort mit `result.complete:true` und `result.count`. Eine ohne
`complete:true` beendete Enumeration ist ungültig und darf **nie** als
Löschmenge interpretiert werden.

## Operationen

| op | Params | Ergebnis (Auszug) | Bemerkung |
|---|---|---|---|
| `ping` | — | `{"pong":true}` | kein Store-Zugriff |
| `caps` | — | Handshake-Felder wiederholt | kein Store-Zugriff |
| `containers` | — | `{"containers":[{"identifier","name","type"}]}` | `type ∈ local\|exchange\|cardDAV\|unassigned` |
| `enumerate` | — | streamt DTOs, dann `{"count","complete":true,"keySetVersion"}` | Voll-Diff-Fallback, aus reinem Swift verfügbar |
| `changes` | `{"startingToken"?: base64}` | `{"events":[...],"count","currentToken"}` | Delta-Pfad über ObjC-Shim; `events[].type ∈ add\|update\|delete\|dropEverything\|other` |
| `token` | — | `{"currentToken": base64,"bytes"}` | `store.currentHistoryToken` |
| `get` | `{"identifier"}` | `{"contact": DTO}` | nicht-vereinheitlicht (Roh-Datensatz) |
| `getUnified` | `{"identifier"}` | `{"contact","requestedIdentifier","returnedIdentifier","identifierChanged"}` | belegt Identifier-Instabilität bei unified contacts |
| `create` | Feld-Set (siehe DTO) + optional `containerIdentifier` | `{"identifier","verified"}` | **Spike-Rail:** nur `givenName`/`familyName` mit Präfix `ZZZ-JarvisTest-` |
| `update` | `{"identifier", ...Felder}` | `{"identifier","viaUnified":false,"verified","readBack":DTO}` | Rail: nur Testdatensätze |
| `updateViaUnified` | wie `update` | wie `update`, `viaUnified:true` | Hazard-Probe (G11 W2), keine Produktionsempfehlung |
| `delete` | `{"identifier"}` | `{"identifier","deleted","snapshot":DTO}` | Rail: nur Testdatensätze |
| `shutdown` | — | `{"bye":true}` | graziöser Exit(0) danach |

Alle Store-Operationen prüfen zuerst `CNContactStore.authorizationStatus`
und liefern bei fehlender Autorisierung `tcc_denied`.

## DTO (deterministische Serialisierung)

Sortierte Schlüssel (`JSONSerialization.WritingOptions.sortedKeys`), explizite
`null`-Werte statt weggelassener Felder, keine locale-abhängige Formatierung.
Enthält u. a.: `identifier`, `contactType`, Namensbestandteile, `emails`,
`phones`, `postalAddresses` (je mit `label`+`value`), `organizationName`,
`jobTitle`, `departmentName`, `birthday` (`year`/`month`/`day` oder `null`),
`hasThumbnail`, `thumbnailBase64`/`thumbnailBytes`, `keySetVersion`.

**Bewusst außen vor:** Normalisierung, Hashing, Fach-/Risiko-/Auditlogik —
das bleibt Aufgabe des Kerns (ADR-0016 §4). Der Sidecar garantiert nur, dass
zwei aufeinanderfolgende `get`-Aufrufe byte-identische Serialisierungen
liefern (im Spike verifiziert, siehe Handoff-Bericht).

## Fehlerbehandlung, Backpressure, Lebenszyklus

- Nicht-JSON-Zeilen auf stdin werden mit `invalid_request` beantwortet, der
  Kanal bleibt danach funktionsfähig.
- Host startet Dual-Reader (stdout **und** stderr) **vor** dem ersten Write
  (Deadlock-Vermeidung, Präzedenz `#309` im Hauptprojekt).
- Graziöser Shutdown: `{"op":"shutdown"}` → Antwort → `exit(0)`. EOF auf
  stdin beendet den Prozess ebenfalls mit `exit(0)`.
- Nach `kill -9` liefert ein Neustart einen funktionsfähigen neuen Prozess;
  der alte hängt nicht nach.

## SPIKE-ONLY: `requestAuthorization` (keine produktive Protokollentscheidung)

**Belegter Plattformbefund (Live-Test 2026-07-27, macOS 12.7.6 Intel):** Eine
normale Store-Operation wie `containers` löst bei `authorizationStatus ==
notDetermined` **keinen** TCC-Dialog aus. Der Sidecar scheitert vorher an
seinem eigenen `requireAuth`-Gate und antwortet `tcc_denied`. Der Dialog
entsteht ausschließlich durch einen ausdrücklichen
`CNContactStore.requestAccess(for: .contacts)`-Aufruf.

Dafür existiert diese Operation. Sie ist eine **Spike-Erweiterung** und
**nicht** Bestandteil einer produktiven Protokollfestlegung.

**Env-Gate:** Die Operation ist standardmäßig deaktiviert. Sie ist nur
verfügbar, wenn der Sidecar-Prozess mit exakt `JARVIS_CONTACTS_SPIKE_TCC=1`
gestartet wurde. Andernfalls antwortet sie mit `operation_disabled` — **ohne**
jeden `requestAccess`-Aufruf.

| op | Params | Ergebnis |
|---|---|---|
| `requestAuthorization` | — | `{"granted":<bool>,"authorizationStatus":"<status>","promptAttempted":<bool>}` |

**Verhalten nach Ausgangsstatus:**

| Status vorher | Dialog | Antwort |
|---|---|---|
| `authorized` | nein | `granted:true`, `authorizationStatus:"authorized"`, `promptAttempted:false` |
| `denied` / `restricted` | nein, **kein erneuter Prompt** | `granted:false`, aktueller Status, `promptAttempted:false` |
| `notDetermined` | **genau einmal** `requestAccess` | `granted` aus der Completion, danach neu gelesener Status, `promptAttempted:true` |
| Fehler / Timeout (fest: 120 s) | — | typisierter Fehler, fail-closed, **keine** Store-Operation |

**Verbote (Vertragsbestandteil):** Die Operation liest keine Kontakte, keine
Container, keine Gruppen und keine Change History, führt kein CRUD aus,
bestätigt keinen Dialog automatisch, prompt bei `denied` nicht erneut, ändert
keine TCC-Daten und ruft kein `tccutil` auf.

**Handshake- und `caps`-Erweiterung:** beide melden zusätzlich
`requestAuthorizationSupported:true` und `requestAuthorizationEnabled:<bool>`
entsprechend dem Env-Gate. Alle übrigen Operationen und Felder bleiben
unverändert.

Der vorgesehene Aufrufweg ist ausschließlich `authorize.py`, das vor der
Anforderung eine wörtliche manuelle Bestätigung verlangt.

## Spike-Sicherheitsrail (nur Spike, nicht produktiv)

`create`/`update`/`delete` verweigern jede Operation, deren Ziel-Datensatz
nicht `givenName`, `familyName` oder `organizationName` mit dem Präfix
`ZZZ-JarvisTest-` trägt (`forbidden`). Diese Schranke ist ausschließlich für
den Spike gedacht — ein produktiver Adapter kennt kein Präfix-Rail, sondern
die reguläre Rechte-/Risikoprüfung des Kerns.
