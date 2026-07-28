# Kontakte-Bridge-Spike G3a — arm64: SIGABRT im enumerate-Pfad (2026-07-28)

**Gegenstand:** Diagnose eines Live-Abbruchs auf Apple Silicon. Betrifft
ausschließlich Spike-Code (ADR-0016), keinen Produktivcode.

**Quelle:** `<OFFICE-ARM64-MAC>` · **Branch:** `spike/contacts-create-timeout-diagnostics-2026-07-27`
**Basis:** `fc253ab7`

---

## 1. Bestätigte Live-Fakten (Testbenutzer `jarvisspike`)

Der TCC-Fluss auf arm64 war **erfolgreich** — das ist der erste vollständige
Nachweis für Spike-Ziel (a) auf dieser Plattform:

| Beobachtung | Wert |
|---|---|
| `authorize.py` | `granted: true`, `authorizationStatus: authorized`, `promptAttempted: true` |
| Sidecar-Start | erfolgreich, Protokoll 1 |
| `containers` | erfolgreich: `On My Mac`, `type=local`, `id=_local:ABAccount` |
| **erster `enumerate`** | **Abbruch** |

Abbruchdetails: `operation=enumerate`, `request_id=2`, `child_exit_code=-6`,
`child_alive=false`, `stdout_eof=true`, `stderr_eof=true`,
`elapsed≈0,013 s`. Python-Exitcode `-6` entspricht **SIGABRT**.

**Keine Mutation wurde erreicht** — kein `create`, `update` oder `delete`.
Der Abbruch lag im Preflight, vor jeder Schreiboperation.

## 2. Diagnoseverlust durch die bisherige stderr-Filterung

`stderr_tail` enthielt ausschließlich zwanzigmal
`[redigiert: nicht-technische stderr-Zeile]`.

Ursache: Die Allowlist `^\[sidecar\][^@]*$` ließ nur eigene Diagnosezeilen
durch. Ein SIGABRT durch eine nicht abgefangene Objective-C-Exception schreibt
aber einen mehrzeiligen Dump (`*** Terminating app due to uncaught exception …`,
Stack-Frames, `libc++abi: terminating …`, `Abort trap: 6`) — **keine** dieser
Zeilen beginnt mit `[sidecar]`. Der gesamte technische Befund wurde durch
identische Platzhalter ersetzt.

Dass überhaupt ~20 Zeilen vorlagen, ist zugleich ein Indiz: ein stiller Exit
hätte keine stderr-Ausgabe erzeugt. Ein mehrzeiliger Crash-Dump ist mit dem
beobachteten Muster vereinbar — bewiesen ist er dadurch nicht.

## 3. Ursachenmatrix

### A — Bestätigt

- Der Sidecar stirbt beim ersten `enumerate` mit **SIGABRT**.
- Die vorangehende Container-Abfrage war erfolgreich (Autorisierung wirkt).
- Es kam **keine** JSON-Antwort; der Kanal endete mit stdout- und stderr-EOF.
- `stderr` war durch die Filterung technisch unbrauchbar.
- **Keine Mutation** wurde erreicht.
- **Code-Defekt im enumerate-Pfad (statisch belegt):** `dto()` las
  `c.imageDataAvailable`, während `CNContactImageDataAvailableKey` **nicht** in
  `fetchKeys` stand. `imageDataAvailable` ist eine eigenständige Eigenschaft mit
  eigenem Schlüssel (`CNContact.h:83` bzw. `:158`). `CNContact.h:52` ist dazu
  eindeutig: *„Accessing a property that was not fetched will throw
  `CNContactPropertyNotFetchedExceptionName`."* Eine nicht abgefangene
  ObjC-Exception führt in Swift zu `abort()` — also exakt SIGABRT.
  Ein systematischer Abgleich aller `dto()`-Zugriffe gegen `fetchKeys` ergab
  **genau diesen einen** Treffer.

### B — Plausibel, nicht bewiesen

- Der unter A belegte Defekt ist die **wahrscheinlichste** Ursache des
  beobachteten SIGABRT: er passt zum Zeitpunkt (im Callback, ~13 ms), zum
  fehlenden JSON und zum mehrzeiligen stderr-Dump.
- **Offener Widerspruch:** Der Zugriff erfolgt nur, wenn der Enumerations-Callback
  mindestens einmal läuft, also **mindestens ein Kontakt existiert**. Berichtet
  wurden jedoch **0 Kontakte** vor und nach dem Lauf. Entweder existierte ein
  nicht sichtbarer Datensatz (z. B. eine „Meine Karte"), oder die Ursache liegt
  woanders. **Das ist durch den Probe-Lauf zu klären, nicht durch Annahme.**
- Ein entitlement-abhängiger Schlüssel als Auslöser ist für den Standard-Fetch
  **ausgeschlossen**: `CNContactNoteKey` war dort nie enthalten.

### C — Noch unbewiesen

- Contacts-Daemon-Zustand (`contactsd`), Datenbank-Migration des frisch
  angelegten Kontos.
- Thread-/Runloop-Problem im Enumerations-Callback.
- Container-Predicate (im Standardlauf gar nicht gesetzt).
- Serialisierung nach dem Callback (`JSONSerialization`) — sie ist bereits
  fehlertolerant und erzeugt kein `abort()`.

## 4. Vollständige Key-Matrix des Standard-Fetch

| Symbolischer Key | dto()-Nutzung | vorher angefordert | Entitlement | Exception-Risiko | Minimal-Enumerate |
|---|---|---|---|---|---|
| `identifier` | ja | ja (immer) | — | keins | **ja** |
| `givenName`, `familyName` | ja | ja | — | keins | **ja** |
| `middleName`, `namePrefix`, `nameSuffix`, `nickname` | ja | ja | — | keins | nein |
| `organizationName`, `jobTitle`, `departmentName` | ja | ja | — | keins | nein |
| `contactType` | ja | ja | — | keins | nein |
| `emailAddresses`, `phoneNumbers`, `postalAddresses` | ja | ja | — | keins | nein |
| `birthday` | ja | ja | — | gering | nein |
| `thumbnailImageData` | ja | ja | — | gering | nein |
| **`imageDataAvailable`** | **ja** | **NEIN** | — | **hoch — belegter Defekt** | nein |
| `imageData` | nein | nein | — | mittel (Größe) | nein |
| `dates`, `relations`, `socialProfiles`, `instantMessageAddresses` | nein | nein | — | offen | nein |
| **`note`** | nein | **nein** | **`com.apple.developer.contacts.notes`** | hoch | **nein** |

## 5. Umgesetzte Korrekturen

**Absturzursache behoben, doppelt abgesichert:**
1. `CNContactImageDataAvailableKey` wurde in `fetchKeys` aufgenommen.
2. `dto()` liest **jede** Eigenschaft nur noch über `ifFetched(…)`, das zuvor
   `CNContact.isKeyAvailable(_:)` prüft — genau der vom Header empfohlene Weg.
   Nicht geholte Felder werden als explizites `null` ausgegeben, **nie**
   stillschweigend als Leerwert. Damit kann ein nicht angeforderter Schlüssel
   strukturell keinen `abort()` mehr auslösen.

**Crash-Sanitisierung (`driver.py`):** Technische Information bleibt erhalten —
Exception-Klasse, Signalname, Framework, symbolische Funktionsnamen,
Stack-Frames, Assertion, `reason:`. Entfernt werden Benutzerpfade, E-Mails,
Telefonnummern, UUIDs, Kontakt-Identifier und Testkontaktnamen. Zeilen **ohne**
technischen Wert werden verworfen statt als Platzhalter mitgeführt und nur
gezählt ausgewiesen. Grenzen unverändert: höchstens 20 Zeilen à 200 Zeichen,
kein rohes stderr auf Platte, keine Payload im Bericht.
Ein Reihenfolgefehler wurde dabei behoben: Das Telefonmuster fraß UUID-Präfixe
an und ließ den Rest im Klartext stehen — UUID und Kontakt-ID werden jetzt
**vor** der Telefonnummer ersetzt.

Zusätzlich meldet der Fehlerbericht nun `child_signal` (z. B. `SIGABRT(6)`)
statt nur den numerischen Exitcode.

## 6. Enumerate-Diagnosestufen (nur mit `JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1`)

`enumerate.received` · `validated` · `auth_ok` · `container_resolved` ·
`keys_begin` · **`key.<symbolischer_name>` je Schlüssel** · `keys_complete` ·
`request_constructed` · `fetch_begin` · `callback_entered` · `serialized` ·
`response_written` · `fetch_returned` · `completed` (bzw. `fetch_error`,
`auth_failed`).

Jede Schlüsselstufe wird **vor** dem jeweiligen Zugriff geschrieben und
geflusht. Ausgegeben werden ausschließlich konstante symbolische Namen aus
`symbolicKeyName(_:)` — niemals Kontaktwerte oder Identifier. Ohne das Gate
erscheint **keine** zusätzliche Ausgabe; `stdout` bleibt in jedem Fall reines
JSON-Lines-Protokoll.

## 7. Gestufter, ausschließlich lesender Probe-Plan

Neue Operation `enumerateProbe` und Runner `tools/enumerate_probe.py`:

- **Stufe 1** — Minimum: `identifier`, `givenName`, `familyName`. Keine Note,
  keine Bilder, keine Birthday-/Dates-/Relations-/Social-/IM-Felder.
- **Stufe 2** — je eine unkritische Gruppe zusätzlich: `names-extended`,
  `organization`, `contact-type`, `emails`, `phones`, `postal`.
- **Stufe 3** — je ein Risikokandidat **einzeln**: `image-available`,
  `thumbnail`, `image-data`, `birthday`, `dates`, `relations`,
  `social-profiles`, `instant-messages`, `note`.

Eigenschaften: Der Runner kann **technisch keine Mutation senden**
(`ALLOWED_OPS = {caps, enumerateProbe, shutdown}`); jede Stufe läuft in einem
**frischen** Sidecar; bei Child-Abbruch endet der Lauf **sofort ohne Retry**;
die Antwort meldet nur Feld-**Präsenz** (`keysPresent`), nie Werte. Bericht:
`results/enumerate-probe.json`, PII-frei.

## 8. Notes-Capability — fail-closed

`CNContactNoteKey` erfordert das Entitlement
`com.apple.developer.contacts.notes`. Der Sidecar trägt **bewusst keine
Entitlements** (Nachweis: `codesign -d --entitlements -` liefert nichts).

Entscheidung: Der Note-Schlüssel bleibt **außerhalb** des Standard-Fetch. Die
Fähigkeit wird ausdrücklich als nicht verfügbar gemeldet — im Handshake unter
`limits.notesSupported=false` mit `notesUnavailableReason="missing-entitlement"`
und in `caps` als `notesSupported=false`. `note` wird **nicht** stillschweigend
als leerer Wert ausgegeben, und es wird **keine** Notes-Funktionalität
behauptet. Es wurde **kein** Entitlement hinzugefügt. Als isolierte Stufe-3-Probe
bleibt der Schlüssel prüfbar.

## 9. Kontaktfreie Testergebnisse

| Suite | Ergebnis |
|---|---|
| `test_enumerate_diagnostics.py` (neu) | **38/38** |
| `test_authorization_profiles.py` | **37/37** |
| `test_driver_failmodes.py` | **26/26** |
| Protokolltests (unsigniertes arm64-Binary) | **25/25** |
| Protokolltests (signiertes arm64-Binary) | **25/25** |

Abgedeckt sind u. a.: SIGABRT-Erkennung als Signal 6, Erhalt von
Exception-Klasse/Signal/Framework/Symbolen/`reason:` nach Sanitisierung,
Entfernung von Pfaden, E-Mails, Telefonnummern, UUIDs und Testkontaktnamen,
Zeilen- und Längengrenzen, Vollständigkeit und PII-Freiheit aller
Enumerate-Stufen, Minimal-Keyset ohne Note/Bilder/Sonderfelder, deterministischer
Gruppenaufbau, kein automatischer Read-Retry, technische Unmöglichkeit einer
Mutation im Probe-Modus sowie die unveränderte Sicherheit des Standardmodus.

Alle Tests laufen gegen Fake-Sidecars, Textfixturen und Quelltextanalyse.
`authorizationStatus` blieb im Bürobenutzer durchgehend `notDetermined` —
**keine Contacts-Operation, kein TCC-Dialog**.

## 10. Stand

Der Live-Retest steht **weiterhin aus**. Weder `phase_b.py` noch
`enumerate_probe.py` noch `authorize.py` wurden ausgeführt. Die
Kontakteberechtigung im Testbenutzer bleibt unverändert bestehen und wurde
nicht zurückgesetzt.

Nächster Schritt (nach Freigabe, im Testbenutzer):
`JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1 python3 tools/enumerate_probe.py`

Keine TCC-Datenbankinhalte und keine Kontaktdaten sind Teil dieser Änderung.
