# Kontakte-Bridge-Spike — TCC-Autorisierungs-Gate (Intel x86_64, 2026-07-27)

**Zweck:** Dokumentation des im ersten Phase-B-Lauf nachgewiesenen
TCC-Autorisierungsfehlers, seiner bestätigten Ursache und der daraus
abgeleiteten Korrektur (SPIKE-ONLY-Operation `requestAuthorization`,
gehärteter Helper `authorize.py`, korrigierter `phase_b.py`-Preflight).

**Ausgangscommit:** `53a36ee6b133e05c09cc744d2f92eca6fb38d911`
(Branch `spike/contacts-bridge-g3a-handoff-2026-07-27`).

Referenzen: `docs/adr/ADR-0016-swift-contacts-bridge.md`,
`docs/adr/ADR-0018-dual-architecture-macos-support.md`,
`docs/testing/contacts-bridge-intel-t3-t4-evidence-2026-07-27.md`,
`scratch/contacts-spike/PROTOCOL.md`.

> **Spike-Evidenz, keine Kontakte-Modulabnahme** (15 §7 Regel 4; 19 §7).

---

## 1. Beobachteter erster Phase-B-Abbruch

Live-Lauf im separaten Testbenutzer `jarvisspike` (macOS 12.7.6, Intel
x86_64), Arbeitsverzeichnis `<INTEL-MAC>/Shared/JarvisContactsSpike/tools`:

| Beobachtung | Ergebnis |
|---|---|
| Kontakte.app im Testbenutzer | **0 Kontakte** |
| Read-only `caps` vorab | erfolgreich |
| `authorizationStatus` vor dem Lauf | `notDetermined` |
| Aufruf | `python3 tools/phase_b.py` (ohne Optionen) |
| Erste Store-Operation im Preflight | `containers` |
| **macOS-TCC-Dialog** | **erschien nicht** |
| Sidecar-Antwort | `tcc_denied` — „Kontakte-Autorisierung ist notDetermined" |
| Skriptverhalten | fail-closed abgebrochen |
| Kontaktzugriff | **keiner** — nichts gelesen, erstellt, verändert oder gelöscht |
| `authorizationStatus` nach dem Lauf | unverändert `notDetermined` |

## 2. Bestätigte Ursache

Die Analyse des Codes bestätigt, dass das beobachtete Verhalten exakt der
Implementierung entspricht — **kein Bedienfehler**:

| # | Befund | Fundstelle (Stand `53a36ee`) |
|---|---|---|
| 1 | `phase_b.py` nahm an, der erste Store-Zugriff löse den Dialog aus, und rief `containers` **vor** jeder Statusprüfung auf | `phase_b.py:55-58` |
| 2 | Der Sidecar besaß **keinerlei** `requestAccess`-Aufruf | `src/sidecar.swift` — 0 Treffer |
| 3 | `caps` meldete ausschließlich den aktuellen Status, forderte nichts an | `src/sidecar.swift:419-422` |
| 4 | `requireAuth()` bricht bei allem außer `.authorized` mit `tcc_denied` ab; `opContainers` ruft es als **erste** Anweisung | `src/sidecar.swift:78-83`, `:159-160` |

**Schlussfolgerung:** Der `CNContactStore` wird bei `notDetermined` nie
erreicht — macOS erhält daher nie Gelegenheit, den Berechtigungsdialog
anzuzeigen. Die vorherige Annahme, eine gewöhnliche Store-Operation löse den
Dialog aus, ist auf diesem System **widerlegt**. Der Dialog entsteht
ausschließlich durch einen ausdrücklichen
`CNContactStore.requestAccess(for: .contacts)`-Aufruf.

## 3. Neue SPIKE-ONLY-Operation `requestAuthorization`

Ergänzt in `src/sidecar.swift`. **Keine produktive Protokollentscheidung** —
der spätere `ContactsAdapter`-Vertrag wird davon nicht präjudiziert.

### 3.1 Env-Gate

Standardmäßig **deaktiviert**. Verfügbar nur, wenn der Sidecar-Prozess mit
exakt `JARVIS_CONTACTS_SPIKE_TCC=1` gestartet wurde. Andernfalls antwortet die
Operation mit dem neuen typisierten Fehlercode `operation_disabled` — **ohne**
jeden `requestAccess`-Aufruf.

Handshake und `caps` melden zusätzlich `requestAuthorizationSupported:true`
sowie `requestAuthorizationEnabled:<bool>` entsprechend dem Gate. Alle
bestehenden Operationen und Felder bleiben unverändert.

### 3.2 Semantik je Autorisierungsstatus

| Status vorher | Dialog | Antwort |
|---|---|---|
| `authorized` | nein, kein Store-Read | `granted:true`, `authorizationStatus:"authorized"`, `promptAttempted:false` |
| `denied` / `restricted` | nein, **kein erneuter Prompt** | `granted:false`, aktueller Status, `promptAttempted:false` |
| `notDetermined` | **genau ein** `requestAccess` | `granted` aus der Completion, danach neu gelesener Status, `promptAttempted:true` |
| Fehler / Timeout (fest 120 s, `DispatchSemaphore`) | — | typisierter Fehler, fail-closed, **keine** Store-Operation |

**Verbote als Vertragsbestandteil:** liest keine Kontakte, Container, Gruppen
oder Change History, führt kein CRUD aus, bestätigt keinen Dialog automatisch,
promptet bei `denied` nicht erneut, ändert keine TCC-Daten, ruft kein
`tccutil` auf.

## 4. `authorize.py` — manuelle Bestätigung und gehärtete Identitätsprüfung

Einziger vorgesehener Weg, den ersten TCC-Dialog auszulösen. Verwendet
ausschließlich die Python-Standardbibliothek und macOS-Systemwerkzeuge.

### 4.1 Manuelle Bestätigung

Vor der Anforderung erscheint ein deutlicher Haltepunkt. Zum Fortfahren ist
die Zeile `AUTHORIZE CONTACTS SPIKE` **wörtlich** einzugeben; jede andere
Eingabe bricht ab, **ohne** eine Autorisierung anzufordern. Der Haltepunkt
nennt ausdrücklich den einzig zulässigen Dialogtext
(`Spike-Test: Zugriff auf Kontakte (SIDECAR)`) und weist an, bei `… (APP)`,
abweichendem Text oder ausbleibendem Dialog zu stoppen.

### 4.2 Gehärtete exakte Binary-Identitätsprüfung (fail-closed)

| Stufe | Prüfung |
|---|---|
| **A — Pfad & Manifest** | fester Pfad `<HANDOFF>/tools/jarvis-contacts`; kein Symlink (auch nicht im Pfadverlauf); reguläre Datei; SHA-256 **exakt** gleich dem Eintrag in `SHA256SUMS.txt`; fehlender oder mehrdeutiger Eintrag ⇒ Abbruch; Manifest wird nicht verändert |
| **B — Codesigning** | `codesign --verify --strict --verbose=4`; **exakter** DR-Vollvergleich nach Normalisierung (keine Teilstring-Heuristik auf „certificate leaf" oder den Identifier); Hardened Runtime gesetzt; Ad-hoc unzulässig; `Authority` = `Personal Jarvis Contacts Spike`; **keine** Entitlements |
| **C — Eingebettete Identität** | `CFBundleIdentifier` = `de.jarvis.contacts-spike.sidecar`; `NSContactsUsageDescription` = `Spike-Test: Zugriff auf Kontakte (SIDECAR)` |
| **D — Native Plattform** | Mach-O `x86_64`; `LC_BUILD_VERSION minos 12.3`; kein arm64-only-Binary; **kein** Universal-Binary in diesem Intel-Abnahmelauf |

Erwartete Designated Requirement (Vollvergleich):

```
identifier "de.jarvis.contacts-spike.sidecar" and certificate leaf = H"f378c267e1c065e3dbfc07acb7b922c10651255c"
```

### 4.3 TOCTOU-Schutz

Der Sidecar wird **unmittelbar** nach Abschluss aller Identitätsprüfungen
gestartet. Direkt nach dem Start und **vor** jeder Anforderung werden Pfad,
Symlink-Status, Dateityp und SHA-256 erneut geprüft; bei Abweichung wird der
Kindprozess sofort sauber beendet und fail-closed abgebrochen. Es wird
**keine** Kopie in ein beschreibbares temporäres Verzeichnis verwendet;
gestartet wird ausschließlich der geprüfte Pfad im Übergabepaket. ACLs und
Eigentumsverhältnisse des Pakets werden nicht verändert.

### 4.4 Gesendete Operationen

Ausschließlich `caps`, `requestAuthorization` und `shutdown`. **Keine**
Kontaktoperation: kein `containers`, `enumerate`, `changes`, `token`, `get`,
`getUnified`, `create`, `update`, `updateViaUnified`, `delete`.

Exitcode 0 **nur** bei `granted:true` **und** `authorizationStatus:authorized`
(3 bei `denied`/`restricted`, 4 bei nicht erteilter Autorisierung, 2 bei
Prüfungs- oder Identitätsfehlern, 1 bei fehlender Bestätigung).

## 5. Korrigierter `phase_b.py`-Preflight

| Status | Verhalten | Exit |
|---|---|---|
| `notDetermined` | Abbruch **vor** jeder Store-Operation, verweist auf `authorize.py` | 4 |
| `denied` / `restricted` | Abbruch, **keine** Store-Operation, kein Re-Prompt | 5 |
| sonstige | Abbruch | 6 |
| `authorized` | erst jetzt `containers` und die bestehende Isolationsprüfung | — |

Alle drei Abbruchpfade liegen nachweislich vor `sc.request("containers")`.
Keine Mutation ohne erfolgreichen `authorized`-Preflight. Die Fehlaussage
„der erste Store-Zugriff loest den TCC-Dialog aus" wurde entfernt.

## 6. Kontaktfreie Tests — 25/25

Die 18 bestehenden Protokolltests plus 7 neue Autorisierungs-Gate-Tests:

| Test | Ergebnis |
|---|---|
| `caps-requestauth-supported` | PASS |
| `caps-requestauth-disabled-by-default` | PASS (`enabled=False`) |
| `requestauth-gated-off` | PASS (`operation_disabled`) |
| `requestauth-gated-off-status-unchanged` | PASS (`notDetermined` → `notDetermined`) |
| `gate-on-handshake-enabled` | PASS |
| `gate-on-caps-enabled` | PASS |
| `gate-on-no-prompt-triggered` | PASS (Status unverändert) |

Mit gesetztem Env-Gate wurde ausschließlich `caps` abgefragt —
`requestAuthorization` wurde **nicht** gesendet. Bestanden vor **und** nach
der Signierung des Sidecars.

## 7. Negative Helper-Tests — 11/11

Isoliert gegen manipulierte Kopien in einem temporären Verzeichnis; der
Sidecar wurde dabei **nie** gestartet, das Übergabepaket **nicht** verändert
und **kein** TCC-Dialog ausgelöst.

| # | Fall | Ergebnis |
|---|---|---|
| 01 | falscher Benutzer | Abbruch vor jedem Sidecar-Start (`exit=2`) |
| 02 | fehlender Manifest-Eintrag | Abbruch |
| 02b | mehrdeutiger Manifest-Eintrag | Abbruch |
| 03 | falscher SHA-256 | Abbruch |
| 03b | Symlink statt regulärer Datei | Abbruch |
| 04 | Ad-hoc-Signatur / falsche DR | Abbruch (DR-Vollvergleich) |
| 05 | falscher Identifier (gültig signiert) | Abbruch (DR-Vollvergleich) |
| 06 | falscher Usage-String | Abbruch |
| 08 | Binary mit Entitlements | Abbruch |
| 09 | falsche Architektur (arm64) | Abbruch |
| 10 | gültiges Binary | alle Vorprüfungen grün, `requestAuthorization` **nicht** gesendet |

*Anmerkung zur Testmethodik:* Die Testfälle arbeiten mit aufgelösten
Pfaden, weil `/var/folders` auf macOS selbst ein Symlink auf
`/private/var/folders` ist — die Symlink-Prüfung greift sonst korrekt bereits
dort und verdeckt den jeweils beabsichtigten Fall.

## 8. Signatur nach dem Rebuild

| Merkmal | Wert |
|---|---|
| Architektur / Mindestversion | `x86_64`, `minos 12.3` |
| Identifier | `de.jarvis.contacts-spike.sidecar` (unverändert) |
| SIDECAR-Usage-String | unverändert |
| Signaturflags | `0x10000(runtime)` — Hardened Runtime, kein Ad-hoc |
| Authority | `Personal Jarvis Contacts Spike` |
| Entitlements | **keine** |

**Designated Requirement vor und nach dem Rebuild wortgleich:**

```
identifier "de.jarvis.contacts-spike.sidecar" and certificate leaf = H"f378c267e1c065e3dbfc07acb7b922c10651255c"
```

**Der `cdhash` darf sich ändern** und hat sich geändert:
`4df95d09063cbbbc52ef81b611c4f36426e6279d` → `2ada76e0f93ee04b674a4438f3b49bc4c5312372`.

**Nebenbefund zur Reproduzierbarkeit:** Der **unsignierte** Swift-Build ist
byte-deterministisch (zwei aufeinanderfolgende Builds ergaben identische
SHA-256). `codesign` erzeugt dagegen bei jedem Lauf abweichende
CMS-Signaturbytes, sodass die Datei-SHA-256 variiert, während `cdhash` und
Designated Requirement identisch bleiben. Für die Manifest-Prüfung in
`authorize.py` ist das unerheblich, weil sie die konkret ausgelieferte Datei
gegen den zugehörigen Manifest-Eintrag bindet.

**Betriebshinweis (reproduzierbar belegt):** Wird eine bereits ausgeführte,
signierte Binärdatei **in-place** überschrieben, behält der Kernel die zuvor
zu diesem Pfad zwischengespeicherte Code-Signatur; der nächste Start scheitert
dann mit `Killed: 9` (Exitcode 137), obwohl `codesign --verify` die Datei als
gültig meldet. Die Ersetzung muss über einen **neuen Inode** erfolgen
(Kopie auf Temp-Namen, danach `mv -f`).

## 9. Offener Stand

- **`requestAuthorization` wurde noch nicht live ausgeführt.** In keinem Lauf
  dieses Arbeitsschritts wurde die Operation mit gesetztem Env-Gate gesendet.
- **Es erschien zu keinem Zeitpunkt ein TCC-Dialog**; `authorizationStatus`
  ist durchgehend und final `notDetermined`.
- **Echte TCC-Persistenz** (Rebuild, Versions-Bump, Verschieben, Quarantäne)
  und **Kontakte-Live-Tests** (CRUD, Feldabdeckung, Change History,
  Fallback-Diff, Unified Contacts) bleiben **offen** und sind Gegenstand von
  Phase B im isolierten Testbenutzer.
- Die **Attributionsfrage** — ob der Dialog dem App- oder dem
  Sidecar-Usage-String zugeordnet wird — ist unentschieden. Der
  Diskriminator ist funktionsfähig; `authorize.py` startet den Sidecar als
  eigenständigen Prozess, weshalb der SIDECAR-Text erwartet wird. Das
  Ergebnis ist zu protokollieren, nicht vorwegzunehmen.

## 10. Sicherheitsaussagen

Dieses Dokument und die zugehörigen Quelldateien enthalten **keine** privaten
Schlüssel, keine Schlüsselbund- oder TCC-Daten, keine Kontaktdaten und keine
personenbezogenen Inhalte. Das Codesigning-Zertifikat
„Personal Jarvis Contacts Spike" verbleibt ausschließlich im lokalen
Schlüsselbund des Hauptbenutzers und wurde weder exportiert noch verändert.
Lokale Benutzerpfade sind mit `<INTEL-MAC>` neutralisiert.
