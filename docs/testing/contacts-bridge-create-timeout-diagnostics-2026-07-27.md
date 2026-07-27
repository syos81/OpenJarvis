# Kontakte-Bridge-Spike — `create`-Timeout: Diagnose und Härtung (2026-07-27)

**Zweck:** Analyse des ersten Phase-B-`create`-Timeouts auf dem Intel-Arbeits-Mac
und Implementierung der Maßnahmen, die einen blinden Wiederholungsversuch
verhindern: typisierte Treiberfehler, `mutation_outcome_unknown`, ein
SPIKE-ONLY-Diagnose-Gate im Sidecar und ein gestufter CRUD-Feldtestplan.

**Ausgangscommit:** `da1107dc9fef820fb499376147969235177e657c`
**Branch:** `spike/contacts-create-timeout-diagnostics-2026-07-27`

> **Spike-Evidenz, keine Kontakte-Modulabnahme** (15 §7 Regel 4; 19 §7).

---

## 1. Beobachteter Live-Befund (Intel-Arbeits-Mac)

| Schritt | Ergebnis |
|---|---|
| Testbenutzer | `jarvisspike` |
| Kontakte.app **vor** dem Test | **0 Kontakte** |
| Explizite Autorisierung (`authorize.py`) | `granted:true`, `authorizationStatus:authorized` |
| Preflight | bestanden — lokaler Container „On My Mac"; gesamt 0, Testdatensätze 0, fremde 0 |
| Erster `create` in G8/G9 | **`queue.Empty` in `driver.py request()`** |
| Skriptende | Traceback |
| Danach: Sidecar-Prozess | keiner aktiv |
| Danach: `phase-b-results.json` | nicht vorhanden |
| Kontakte.app **nach** dem Test | **weiterhin 0 Kontakte** |

**Es wurde keine Mutation nachgewiesen.** Die genaue technische Ursache des
Timeouts ist damit **nicht** bestimmt — 0 Kontakte danach belegen, dass kein
sichtbarer Datensatz entstand, schließen aber einen abgebrochenen Schreibvorgang
nicht mit letzter Sicherheit aus.

## 2. Ursachenanalyse

### 2.1 Bestätigte Ursachen (im Code belegt)

Diese Defekte erklären **die Fehlerform** (nacktes `queue.Empty`, fehlende
Diagnose) vollständig und unabhängig von der Timeout-Ursache:

| # | Defekt | Fundstelle (Stand `da1107d`) |
|---|---|---|
| **B1** | `request()` ließ `queue.Empty` ungefangen nach außen — exakt der beobachtete Traceback | `driver.py` `request()` |
| **B2** | `request()` prüfte **nie**, ob der Kindprozess noch lebt. Stirbt der Sidecar, endet der stdout-Reader still; nichts landet mehr in der Queue und der Aufruf wartet bis zum Timeout **ohne jede Anzeige** | `driver.py` `request()` |
| **B3** | Antworten mit fremder `id` wurden **still verworfen** (`continue` ohne Festhalten) | `driver.py` `request()` |
| **B4** | Die absolute Deadline wurde nicht erzwungen: `max(0.1, deadline - time.time())` ließ jede Iteration ≥ 0,1 s warten; ein Strom fremder Nachrichten konnte den Timeout beliebig verlängern | `driver.py` `request()` |
| **B5** | Das mitgeschriebene `stderr` wurde im Fehlerfall **nicht ausgegeben** — die wertvollste Diagnose ging verloren | `driver.py` |
| **B6** | Kein Child-Cleanup im Fehlerfall | `driver.py` |
| **B7** | `phase_b.py` behandelte einen Mutationsabbruch nicht; der Ausgang blieb unbenannt und undokumentiert | `phase_b.py` `gate_crud_fields()` |

### 2.2 Plausible Ursachen des Timeouts (nicht bewiesen)

| Prio | Hypothese | Begründung | Status |
|---|---|---|---|
| **P1** | **`note` ohne Entitlement.** Der erste Payload setzte `note`. `CNContactNoteKey` erfordert seit macOS 11 `com.apple.developer.contacts.notes`; der Spike-Sidecar trägt **bewusst keine** Entitlements. Löst das Framework dabei eine **Objective-C-Exception** aus, ist sie in Swift **nicht** über `catch let e as NSError` fangbar → Prozessabbruch → stdout-EOF → `queue.Empty` beim Treiber. Das passt exakt zum Symptom „keine Antwort, kein Prozess mehr". | **plausibel, unbelegt** |
| **P2** | **Blockierender `store.execute()`-Aufruf.** Die Hauptschleife des Sidecars läuft ohne laufende Run-Loop. Benötigt der Contacts-XPC-Pfad Main-Run-Loop-Bedienung, kann `execute()` dauerhaft blockieren. Der Prozess bliebe dann am Leben — B2 hätte das bisher nicht sichtbar gemacht. | **plausibel, unbelegt** |
| **P3** | **Andere ObjC-Exception im Feldaufbau** (z. B. ungültiges Label, `CNMutablePostalAddress`, `DateComponents`) mit demselben Abbruchmuster wie P1. | **plausibel, unbelegt** |

### 2.3 Noch unbelegte Hypothesen

- Container-Auflösung (`toContainerWithIdentifier:`) als Blocker.
- Sandbox-/Hardened-Runtime-Wechselwirkung beim Schreibpfad.
- Zeitweiliges Hängen des Contacts-Daemons im frisch angelegten Testbenutzer.

**Keine dieser Hypothesen wird als bewiesen dargestellt.** Die neue
Instrumentierung ist gerade darauf ausgelegt, zwischen P1/P3 (Prozess tot →
`child_exited`) und P2 (Prozess lebt → `request_timeout`) beim nächsten
Intel-Lauf **eindeutig** zu unterscheiden.

## 3. Neue Treiber-Fehlersemantik

Ein Request endet nie wieder als nacktes `queue.Empty`. Jeder Ausgang ist eine
`DriverError` mit Fehlerklasse und PII-freien Feldern:

`request_id` · `operation` · `elapsed_seconds` · `child_exit_code` ·
`child_alive` · `stdout_eof` · `stderr_eof` · `wrong_response_ids` ·
`diag_stages` · begrenztes, gefiltertes `stderr_tail` · `detail`

| Fehlerklasse | Bedeutung |
|---|---|
| `request_timeout` | Deadline abgelaufen, Kind lebt noch |
| `child_exited` | Kindprozess beendet (Exitcode erfasst) |
| `stdout_eof` | stdout geschlossen, Kind läuft noch |
| `protocol_error` | nicht parsebare Zeile auf stdout |
| `response_id_mismatch` | zu viele fremde Antwort-IDs |
| `mutation_outcome_unknown` | Abbruch **während** `create`/`update`/`updateViaUnified`/`delete` |

Bei jedem Abbruch: **kein automatischer Retry**, Kindprozess wird zuverlässig
beendet (`terminate` → `kill`), `stderr` nur begrenzt (max. 20 Zeilen à 200
Zeichen) und gefiltert gespeichert, **keine Payload** in der Ausgabe.

## 4. `mutation_outcome_unknown`

Bricht `request_timeout`, `child_exited` oder `stdout_eof` **während einer
mutierenden Operation** ab, wird die Fehlerklasse zu
`mutation_outcome_unknown` angehoben; die ursprüngliche Klasse bleibt als
`underlying_class` erhalten.

**Das bedeutet ausdrücklich WEDER fehlgeschlagen NOCH erfolgreich.**

`phase_b.py` stoppt daraufhin sofort: keine weitere Mutation, kein Retry,
**kein automatisches Cleanup**, eigener Exitcode `7`, und eine klare Anweisung
zur **rein visuellen** Prüfung in Kontakte.app (Anzahl ablesen, auf
`ZZZ-JarvisTest-` prüfen, nichts ändern, Befund melden).

### PII-freie Fehlerdatei

Geschrieben nach `<HOME-MAC>/Shared/JarvisContactsSpike/results/phase-b-outcome-unknown.json`.
Der Pfad ist über `JARVIS_CONTACTS_SPIKE_RESULTS_DIR` umleitbar, damit das
Schreiben **ohne** den echten Übergabepfad testbar ist. Die Datei enthält
ausschließlich die oben genannten technischen Felder plus
`authorization_status_before_mutation` — **niemals eine Kontakt-Payload.**

## 5. SPIKE-ONLY-Diagnose-Gate im Sidecar

Aktiv nur bei exakt `JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1`; ohne diesen Wert
erscheint **keine** Zusatzausgabe und das Verhalten bleibt unverändert.
stdout bleibt reines JSON-Lines-Protokoll; Stufen gehen ausschließlich nach
stderr.

Erlaubte Stufen: `create.received` · `create.validated` · `create.auth_ok` ·
`create.container_resolved` · `create.contact_constructed` ·
`create.save_begin` · `create.save_returned` · `create.response_written`;
zusätzlich `create.note_set_attempted` und `create.failed error=<code>`.

Ausgegeben werden **ausschließlich konstante Stufennamen** — niemals Namen,
Identifier, E-Mail-Adressen, Telefonnummern, Anschriften, Geburtstage,
Organisationen oder Payloads.

**Diagnostischer Nutzen:** Bleibt der nächste Lauf nach `create.save_begin`
ohne `create.save_returned` stehen, ist der Blocker eindeutig `store.execute()`
(P2). Fehlt bereits `create.contact_constructed`, liegt er im Feldaufbau (P3).
Erscheint `create.note_set_attempted` als letzte Stufe, ist P1 bestätigt.

## 6. Gestufter CRUD-Feldtestplan

Die vollständige Feldabdeckung bleibt **Pflicht**; verbessert wird nur die
Fehlerisolation.

### 6.1 Feldmatrix des bisherigen ersten `create`

| Feld | JSON-Typ | Swift-Zuweisung | SDK 13.1 | Mögliche Fehlerquelle | Für Minimal-`create` nötig | Später per `update` testbar |
|---|---|---|---|---|---|---|
| `givenName` | String | `c.givenName` | ab 10.11 | — | **ja** | — |
| `familyName` | String | `c.familyName` | ab 10.11 | — | **ja** | — |
| `organizationName` | String | `c.organizationName` | ab 10.11 | gering | nein | ja |
| `jobTitle` | String | `c.jobTitle` | ab 10.11 | gering | nein | ja |
| `departmentName` | String | `c.departmentName` | ab 10.11 | gering | nein | ja |
| `emails` | Array\<Obj\> | `CNLabeledValue<NSString>` | ab 10.11 | Label-Konstanten, Bridging | nein | ja |
| `phones` | Array\<Obj\> | `CNLabeledValue<CNPhoneNumber>` | ab 10.11 | Label-Konstanten | nein | ja |
| `postalAddresses` | Array\<Obj\> | `CNMutablePostalAddress` | ab 10.11 | viele Teilfelder | nein | ja |
| `birthday` | Obj\<Int\> | `DateComponents` | ab 10.11 | Bridging `[String: Int]`, Kalenderlogik | nein | ja |
| **`note`** | String | `c.note` | ab 10.11 | **Entitlement `com.apple.developer.contacts.notes` fehlt — höchstes Risiko (P1)** | **nein** | ja, isoliert |
| `thumbnail` | — | *(nicht gesetzt)* | ab 10.11 | noch nicht abgedeckt | nein | ja, isoliert |
| `containerIdentifier` | String | `req.add(_:toContainerWithIdentifier:)` | ab 10.11 | Container-Auflösung | optional | — |

### 6.2 Neuer Ablauf

**Stufe 1 — minimaler `create`:** ausschließlich `givenName`/`familyName` mit
Präfix `ZZZ-JarvisTest-` (plus optional `containerIdentifier`). Danach
Read-back und Determinismusprobe.

**Stufe 2 — unkritische Feldgruppen, je ein `update` mit eigener Prüfung:**
`organizationName` · `jobTitle` · `departmentName` · `nickname`.

**Stufe 3 — riskante Felder, je einzeln:** `birthday` · `emails` (inkl.
Label-Roundtrip) · `phones` · `postalAddresses` · **`note` zuletzt und
isoliert**.

Damit schlägt ein Fehler künftig **einer konkreten Feldgruppe** zu, statt den
gesamten ersten `create` unbrauchbar zu machen.

## 7. Kontaktfreie Testergebnisse

Alle Tests liefen **ohne** Contacts-Operation, ohne TCC-Dialog und ohne
Zugriff auf echte Kontakte. `authorizationStatus` blieb durchgehend
`notDetermined`.

**Treiber-Fehlermodi gegen Fake-Sidecars — 24/24**

| Fall | Ergebnis |
|---|---|
| normale Antwort | PASS |
| Sidecar antwortet nie → `request_timeout` | PASS |
| Sidecar beendet sich vor Antwort → `child_exited` (Exitcode 3 erfasst) | PASS |
| stdout-EOF vor Antwort → `stdout_eof` | PASS |
| stderr begrenzt (20 Zeilen) und PII redigiert | PASS |
| falsche Request-ID → `response_id_mismatch`, IDs festgehalten | PASS |
| ungültige JSON-Antwort → `protocol_error` | PASS |
| Mutationstimeout → `mutation_outcome_unknown` (+ `underlying_class`) | PASS |
| **kein Mutation-Retry** — genau **1** `create` erreichte den Sidecar | PASS |
| kein automatisches Cleanup, eigener Exitcode 7 | PASS |
| Fehlerdatei: nur erlaubte Felder, keine Payload/PII | PASS |
| gestufter Payload beginnt minimal, `note` zuletzt und isoliert | PASS |

**Diagnose-Gate am echten Sidecar — 7/7**

| Fall | Ergebnis |
|---|---|
| Gate aus → keine Zusatzdiagnose, Verhalten unverändert | PASS |
| Gate an → nur erlaubte Stufen (`create.received`, `create.failed`) | PASS |
| keine unerlaubten Stufen | PASS |
| `save_begin` nicht erreicht (Spike-Rail griff vorher — kein Store-Zugriff) | PASS |
| keine PII-Marker in den Diagnosen | PASS |

**Bestehende Protokolltests — 25/25**, sowohl vor als auch nach der
Signierung.

## 8. Build-Ergebnisse

> **Maschinenhinweis:** Dieser Arbeitsschritt lief nicht auf einem
> Apple-Silicon-Gerät, sondern auf demselben **Intel-Mac** (x86_64,
> macOS 12.7.6), auf dem der Live-Befund entstand. Die Architekturrollen sind
> daher vertauscht: `x86_64` ist hier der **native**, `arm64` der
> **Cross-Build**.

| Ziel | Ergebnis |
|---|---|
| `arm64-apple-macos12.3` | Build erfolgreich, `arm64`, `minos 12.3`, externalBin-Name `jarvis-contacts-aarch64-apple-darwin`. **Nicht ausgeführt** — arm64 ist auf Intel nicht lauffähig (Rosetta übersetzt ausschließlich x86_64 → arm64). **Keine Laufzeitaussage, keine arm64-Abnahme.** |
| `x86_64-apple-macos12.3` | Build erfolgreich, `x86_64`, `minos 12.3`; **nativ ausgeführt**, 25/25 Protokolltests bestanden |

**Signierung** (lokale Identität `Personal Jarvis Contacts Spike` vorhanden):
angewandt auf den **nativen x86_64**-Build — Hardened Runtime
(`flags=0x10000(runtime)`), **keine** Entitlements, Identifier unverändert
`de.jarvis.contacts-spike.sidecar`, `cdhash 8d519223…`:

```
designated => identifier "de.jarvis.contacts-spike.sidecar" and certificate leaf = H"f378c267e1c065e3dbfc07acb7b922c10651255c"
```

Da dieser Rechner **derselbe** ist wie der Intel-Arbeits-Mac, ist es auch
dasselbe Zertifikat. **Es wird dennoch keine Intel-Abnahme behauptet** — die
Signierung diente ausschließlich der Verifikation, dass die geänderten Quellen
signierbar bleiben und die DR unverändert bleibt.

## 9. Offener Stand

- **Auf diesem Mac wurde keine einzige echte Contacts-Operation ausgeführt.**
  Kein `phase_b.py`, kein `authorize.py`, kein `requestAuthorization`, kein
  `containers`/`enumerate`/`changes`/`token`, kein `create`/`update`/`delete`,
  keine App gestartet, kein TCC-Dialog, kein `tccutil`, keine TCC-Daten
  gelesen oder verändert.
- **Die Ursache des `create`-Timeouts bleibt unbestimmt.** Bestätigt sind nur
  die Treiber- und Diagnosedefekte (§2.1); P1–P3 sind Hypothesen.
- **Der Intel-Live-Retest steht aus.** Er ist mit gesetztem
  `JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1` durchzuführen, damit die Stufenfolge
  die Hypothesen unterscheidet. Ein blinder Wiederholungsversuch ohne
  Diagnose-Gate ist ausdrücklich nicht vorgesehen.
- **Echte TCC-Persistenz und die Kontakte-Live-Tests** (CRUD, Feldabdeckung,
  Change History, Fallback-Diff, Unified Contacts) bleiben offen.

## 10. Sicherheitsaussagen

Dieses Dokument und die zugehörigen Quelldateien enthalten **keine** privaten
Schlüssel, keine Schlüsselbund- oder TCC-Daten, keine Kontaktdaten und keine
personenbezogenen Inhalte. Lokale Benutzerpfade sind mit `<HOME-MAC>`
neutralisiert.
