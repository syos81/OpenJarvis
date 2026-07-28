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

### Plattformprofil (seit 2026-07-28)

`authorize.py` bezieht Architektur und Zertifikats-Leaf **nicht** aus dem
Python-Code, sondern aus einem lokalen, schreibgeschützten Profil des
Übergabepakets:

```
<HANDOFF>/tools/authorization-profile.json
```

Das Profil wird bei der administrativen Paketbereitstellung aus unabhängig
geprüften Build- und Signaturwerten erzeugt und **niemals aus dem zu prüfenden
Sidecar abgeleitet** — das wäre eine zirkuläre Identitätsprüfung. Der
Sidecar-SHA-256 steht bewusst nicht im Profil; dafür bleibt der eindeutige
Eintrag in `SHA256SUMS.txt` die einzige Quelle.

Im Live-Betrieb sind Profilpfad und Erwartungswerte **weder per CLI-Argument
noch per Umgebungsvariable** überschreibbar. Der Code ist auf arm64 und x86_64
identisch; nur das Profil unterscheidet sich lokal. `uname` dient ausschließlich
der Verifikation gegen den Profilwert, nie der Auswahl.

Vor dem Start werden Profil (Pfad, Symlinks, Eigentümer, Schreibrechte,
Manifest-Hash, Schema, Wertebereiche, rekonstruierte DR) und anschließend der
Sidecar gegen die Profilwerte geprüft; nach dem Start folgt ein TOCTOU-Recheck
über **Sidecar- und Profil-Hash**. Jede Abweichung ist fail-closed: kein
Sidecar-Start, kein `requestAuthorization`, Exitcode ungleich 0.
Details: `docs/testing/contacts-bridge-platform-authorization-profile-2026-07-28.md`.

## SPIKE-ONLY: `enumerateProbe` (gestuft, ausschließlich lesend)

Seit 2026-07-28. Grenzt die Absturzgrenze im enumerate-Pfad ein und **mutiert
niemals**.

| Params | Bedeutung |
|---|---|
| `{"stage":1}` | Minimum: `identifier`, `givenName`, `familyName` |
| `{"stage":2,"group":"<g>"}` | Minimum **plus genau eine** unkritische Gruppe |
| `{"stage":3,"group":"<g>"}` | Minimum **plus genau einen** Risikokandidaten |

Stufe-2-Gruppen: `names-extended`, `organization`, `contact-type`, `emails`,
`phones`, `postal`. Stufe-3-Gruppen: `image-available`, `thumbnail`,
`image-data`, `birthday`, `dates`, `relations`, `social-profiles`,
`instant-messages`, `note`.

Antwort: `{"count","complete":true,"probe":"<label>","keys":[…]}`. Die
Stream-Zeilen melden ausschließlich Feld-**Präsenz** (`{"keysPresent":[…]}`),
niemals Werte.

## SPIKE-ONLY: `isolationSummary` (ausschließlich lesend, PII-frei)

Seit 2026-07-28. Klassifiziert den Bestand, **ohne** Kontaktdaten preiszugeben,
und **mutiert niemals** (konstruiert keinen `CNSaveRequest`).

Die Klassifikation läuft bewusst **im Sidecar**: Sie benötigt Namensfelder für
den Präfixabgleich und Identifier für Me-Card-Vergleich und
Dublettenerkennung — beides darf die Prozessgrenze nie überschreiten.

Ergebnisfelder (abschließend): `authorizationStatus`, `containerCount`,
`containerTypes`, `totalContacts`, `prefixedTestContacts`, `foreignContacts`,
`meCardPresent` (`true`/`false`/`"unknown"`), `meCardIncludedInEnumerate`
(`true`/`false`/`"unknown"`), `duplicateIdentifiersDetected`, `mutationCount`
(immer `0`), `testPrefix`.

Die Me-Card wird über `unifiedMeContactWithKeysToFetch:error:` gelesen —
ausschließlich mit `CNContactIdentifierKey`. `nil` bedeutet „keine gesetzt";
jeder andere Fehler ergibt `"unknown"` statt einer Vermutung.

## Capability: Notizen nicht verfügbar

**Live bestätigt (2026-07-28):** In `stage3-note` steht `note` in `keys`, fehlt
aber in `keysPresent` — das Framework wirft **keine** Exception, liefert das
Feld aber nicht aus.

`CNContactNoteKey` erfordert das Entitlement
`com.apple.developer.contacts.notes`. Der Sidecar trägt keine Entitlements;
der Schlüssel ist daher **nicht** Teil des Standard-Fetch. Gemeldet wird das im
Handshake als `limits.notesSupported=false` mit
`notesUnavailableReason="missing-entitlement"` und in `caps` als
`notesSupported=false`. `note` wird **nicht** als leerer Wert ausgegeben.

## SPIKE-ONLY: Diagnose-Gate (stderr, keine Protokolländerung)

Aktiv ausschließlich bei exakt `JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1`. Ohne
diesen Wert erscheint **keine** zusätzliche Ausgabe und das Verhalten bleibt
unverändert. **stdout bleibt in jedem Fall reines JSON-Lines-Protokoll** — die
Stufen gehen ausschließlich nach `stderr` in der Form `[sidecar] stage=<name>`
bzw. `[sidecar] stage=<name> error=<code>`.

**Enumerate-Stufen (2026-07-28):** `enumerate.received` · `validated` ·
`auth_ok` · `container_resolved` · `keys_begin` · `key.<symbolischer_name>` je
Schlüssel · `keys_complete` · `request_constructed` · `fetch_begin` ·
`callback_entered` · `serialized` · `response_written` · `fetch_returned` ·
`completed` (bzw. `fetch_error`, `auth_failed`). Die Schlüsselstufe wird **vor**
dem jeweiligen Zugriff geschrieben; ausgegeben werden nur konstante symbolische
Namen, niemals Kontaktwerte oder Identifier.

Zweck ist die Eingrenzung des auf dem Intel-Mac beobachteten `create`-Timeouts
(siehe `docs/testing/contacts-bridge-create-timeout-diagnostics-2026-07-27.md`).

Stufen des `create`-Pfads: `create.received` · `create.auth_ok` ·
`create.validated` · `create.note_set_attempted` · `create.contact_constructed` ·
`create.container_resolved` · `create.save_begin` · `create.save_returned` ·
`create.response_written` · `create.failed error=<code>`.

Ausgegeben werden **ausschließlich konstante Stufennamen und typisierte
Fehlercodes** — niemals Namen, Identifier, E-Mail-Adressen, Telefonnummern,
Anschriften, Geburtstage, Organisationen oder ganze Payloads.

## Spike-Sicherheitsrail (nur Spike, nicht produktiv)

`create`/`update`/`delete` verweigern jede Operation, deren Ziel-Datensatz
nicht `givenName`, `familyName` oder `organizationName` mit dem Präfix
`ZZZ-JarvisTest-` trägt (`forbidden`). Diese Schranke ist ausschließlich für
den Spike gedacht — ein produktiver Adapter kennt kein Präfix-Rail, sondern
die reguläre Rechte-/Risikoprüfung des Kerns.
