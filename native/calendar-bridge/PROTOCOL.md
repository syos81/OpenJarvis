# Kalender-Bridge — produktiver JSON-Lines-Vertrag (v1, nur Lesen)

Transport, Hülle, Streaming, Lebenszyklus und Fehlerklassen sind **identisch**
zur Kontakte-Bridge (`native/contacts-bridge/PROTOCOL.md`) und werden von
denselben Primitiven bedient (`personaljarvis/base/sidecar`). Hier steht nur,
was am Kalender anders ist.

## Hülle

```json
{"protocolVersion":1,"requestId":<int>,"operation":"<name>","payload":{}}
{"protocolVersion":1,"requestId":<int>,"ok":true,"result":{}}
{"protocolVersion":1,"requestId":<int>,"ok":false,
 "error":{"code":"<geschlossene Menge>","message":"<Text>","retryable":<bool>}}
```

Streaming (nur `events`): Zwischenzeilen `{"stream":"item","item":{…}}`,
abgeschlossen durch die Erfolgsantwort mit `complete:true`. **Eine ohne
`complete:true` beendete Lesung ist ungültig und darf nie als Löschmenge
interpretiert werden** — das ist beim Kalender schärfer als bei den Kontakten,
weil es hier keinen Cursor gibt, an dem man ansetzen könnte.

`stdout` ist ausschließlich Protokollkanal; jede Diagnose geht nach `stderr`
mit dem Marker `[calendar-bridge]` und **nie** mit Fachdaten (kein Titel, kein
Ort, keine Notiz, keine Teilnehmerin, keine Uhrzeit, kein Identifier).

## Handshake

```json
{"type":"ready","protocolVersion":1,
 "bundleIdentifier":"de.kluender.jarvis.calendar-bridge",
 "keySetVersion":1,"authorizationStatus":"<status>",
 "operations":[…],"capabilities":{…}}
```

## Autorisierungsstatus (geschlossen)

`not_determined` · `restricted` · `denied` · `full_access` · `write_only` ·
`unknown`

Ermittelt über den **Rohwert**, nicht über Enum-Fälle: `.fullAccess` existiert
im macOS-13.1-SDK nicht, teilt sich mit `.authorized` aber ohnehin den Wert 3;
neu ist allein `.writeOnly` (4). Der alte Jarvis-Kalender scheiterte genau
hier — sein `@unknown default` meldete jeden neuen Wert als `unknown`, worauf
das authorized-Gate trotz erteiltem Vollzugriff schloss.

**Lesen verlangt `full_access`.** `write_only` genügt ausdrücklich nicht und
wird nie als Leseberechtigung gewertet.

## Capabilities

| Feld | Wert | Begründung |
|---|---|---|
| `canRead` | `true` | — |
| `canCreateEvents` / `canUpdateEvents` / `canDeleteEvents` | `false` | v1 schreibt nicht; kein Feld ist als schreibbar zugesagt |
| `supportsRecurrence` | `true` | Regel wird **roh** geliefert; Instanzen sind abgeleitet |
| `supportsAttendees` | `true` | Rohadresse, Anzeigename, Rolle, Antwortstatus, Organisator |
| `supportsAlarms` | `true` | absolut **oder** relativer Versatz, unverändert |
| `supportsFreeBusy` | `false` | keine Verfügbarkeitsabfrage über Personen in v1 |
| `supportsTimeZones` | `true` | `timeZone` darf **null** sein (schwebend) |
| `windowRequired` | `true` | EventKit kennt kein „alle Termine" |
| `changeFeed` | `"notification"` | `EKEventStoreChangedNotification` ist ein **Auslöser**, nie ein Delta |
| `mutationsImplemented` | `false` | — |

## Operationen

| Operation | Payload | Ergebnis (Auszug) | Store-Zugriff |
|---|---|---|---|
| `ping` | — | `{"pong":true}` | nein |
| `caps` | — | Handshake-Felder | nein |
| `authorizationStatus` | — | `{"authorizationStatus"}` | nein |
| `requestAuthorization` | `{"request":true}` | `{"granted","authorizationStatus","promptAttempted"}` | Dialog |
| `calendars` | — | `{"calendars":[…],"count","keySetVersion"}` | ja |
| `events` | `{"startUtc","endUtc","calendarIdentifiers"?}` | streamt DTOs, dann `{"count","complete":true,"windowStartUtc","windowEndUtc","calendarIdentifiers"}` | ja |
| `createEvent`/`updateEvent`/`deleteEvent` | — | `not_implemented` | **nein** |
| `shutdown` | — | `{"bye":true}` → `exit(0)` | nein |

`requestAuthorization` erfolgt **ausschließlich** auf ausdrückliche
Nutzeraktion (`payload.request === true`). Es gibt kein Env-Gate und keinen
impliziten Weg; ein Start des Sidecars fordert **nie** Berechtigungen an. Ist
der Status bereits entschieden, meldet die Antwort ehrlich
`promptAttempted:false`, statt einen Versuch zu behaupten, den macOS gar nicht
mehr zulässt.

`events` wiederholt sein Fenster in der Antwort. Ein Bericht ohne Fensterangabe
wäre wertlos: ohne ihn ist „nicht gesehen" nicht von „gelöscht" zu
unterscheiden. Ein unbekannter Kalender in `calendarIdentifiers` ist
fail-closed `not_found` — ein stillschweigend kleineres Ergebnis sähe aus wie
ein vollständiges.

## Ereignis-DTO

`providerIdentifier` · `calendarItemIdentifier` · `externalUid` ·
`calendarIdentifier` · `title` · `notes` · `location` · `url` ·
`startsAtUtc` · `endsAtUtc` · `timeZone` (**nullable**) · `isAllDay` ·
`status` · `availability` · `hasRecurrenceRules` · `recurrenceRuleCount` ·
`recurrenceRule` (roh, strukturiert) · `isDetached` · `occurrenceStartUtc` ·
`hasAlarms` · `alarms` · `hasAttendees` · `attendees` · `createdAtUtc` ·
`lastModifiedAtUtc`

Drei Eigenschaften, die keine Detailfragen sind:

* **`externalUid` ist nicht eindeutig.** Bei Einladungen liegt derselbe Termin
  in mehreren Kalendern. Korrelationshinweis, nie Primärschlüssel.
* **`timeZone` darf `null` sein** und bedeutet dann „schwebend". Ganztägige und
  schwebende Termine nach UTC zu normalisieren verschiebt sie beim nächsten
  Ortswechsel.
* **`recurrenceRule` ist roh.** Materialisierte Instanzen sind Cache und nie
  Wahrheit. EventKit gibt keinen RFC-5545-Text heraus, deshalb werden die
  Bestandteile strukturiert übernommen — nichts wird gedeutet.

Bewusst **außen vor** (bleibt im Kern, ADR-0016 Punkt 4): Normalisierung,
Felddigest, Anzeigenamen-Bildung, Zuordnung von Teilnehmern zu Kontakten,
Konflikt-, Risiko- und Auditlogik.

## Fehlercodes (geschlossen)

`tcc_denied` · `not_found` · `invalid_request` · `forbidden` ·
`provider_error` · `unsupported` · `internal` · `not_implemented` ·
`protocol_mismatch`

## Schreibfreiheit

v1 enthält **keinen** EventKit-Schreibaufruf. Das wird zweifach geprüft: ein
Test liest die Quelle, und `build.sh` sucht im **gebauten Binary** nach
Schreibselektoren und bricht ab, wenn einer auftaucht. Ein Versprechen, das nur
im Quelltext steht, ist keines.

## Berechtigung und Signierung

Das Entitlement `com.apple.security.personal-information.calendars` trägt der
**Elternprozess** (die App). Unter Hardened Runtime fragt tccd sonst gar nicht
erst — die Ablehnung ist von außen nicht von einem Nein des Nutzers zu
unterscheiden (belegt: `docs/testing/calendar-read-probe-x86_64-2026-08-04.md`).
Der Sidecar trägt trotzdem seinen eigenen, minimalen Vertrag
(`CalendarSidecar.entitlements`) und wird nach dem Bündeln neu versiegelt.
