# Kontakte — ARM64-Abschlusslauf auf dem Mac mini M2 Pro (2026-08-12)

**Gegenstand:** Die offene arm64-Spalte der produktiven Kontakte-Abnahme
(15 §8.1) und die M2-Abnahmecheckliste
([contacts-native-update-delete-intel-2026-08-04.md](../personal-jarvis/contacts-native-update-delete-intel-2026-08-04.md)
§17). Der Intel-Zweig wurde nicht neu aufgerollt.

> Alle Zahlen sind aggregiert. Dieses Dokument enthält **keine** Kontaktdaten,
> keine Namen echter Personen, keine Provider-Identifier im Klartext, keine
> Cursor und keine privaten Pfade. Der einzige genannte Datensatz ist der
> synthetische Testkontakt dieses Laufs.

---

## 1. Host und Artefakte

| Merkmal | Wert |
|---|---|
| Rechner | Mac14,12 — Mac mini M2 Pro |
| Architektur | `arm64` nativ; `sysctl.proc_translated = 0`, kein Rosetta |
| macOS | 26.2 (25C56) |
| Toolchain | Swift 6.3.2, Target `arm64-apple-macosx26.0`, SDK 26.5 (Command Line Tools) |
| Zertifikat | „de.kluender.jarvis", Blatt `b1038059…` |
| Basis | `d50318d9`, Worktree `feature/contacts-arm64-native-closure-2026-08-12` |

Alle vier Mach-O des Bundles sind `arm64` mit `minos 12.3` und Hardened
Runtime; `codesign --verify --deep --strict` ist grün. Designated Requirements,
jeweils zertifikatsgebunden auf dasselbe Blatt:

| Binary | Identifier | Entitlements |
|---|---|---|
| App | `de.kluender.jarvis` | 8 (unverändert) |
| Contacts-Sidecar | `de.kluender.jarvis.contacts-bridge` | genau 1 (Addressbook) |
| Calendar-Sidecar | `de.kluender.jarvis.calendar-bridge` | genau 1 (Kalender) |
| Write-Helper | `de.kluender.jarvis.contacts-write-helper` | genau 1 (Addressbook) |

## 2. Drei Defekte, die erst auf arm64 sichtbar wurden

**Der Write-Helper war nie gesiegelt.** `tauri build` signierte ihn mit den
Entitlements der App: neun Einträge, darunter JIT, unsignierter Speicher,
abgeschaltete Library-Validation, beide Netzrechte und Kalenderzugriff — für
einen Prozess, der eine Order von stdin liest, höchstens ein `CNSaveRequest`
ausführt und einen Bericht auf stdout schreibt. Sein Identifier lautete
`contacts-write-helper`. ADR-0026 bindet ihn auf einen eigenen Identifier und
**ein** Entitlement. Ursache: `reseal-contacts-sidecar.sh` erfasste beide
Sidecars, nicht aber den Helfer.

**Zwei Pflichtscans liefen auf arm64 leer.** `test_write_helper_bundle.py`
hatte `x86_64-apple-darwin` fest im Bundle-Pfad — auf dieser Architektur
übersprang damit die gesamte Signatur-, Entitlement- und TCC-Kette des
Helfers, achtzehn Prüfungen. Die Schwesterdatei `test_packaging_app.py` warnt
in ihrem eigenen Kommentar genau davor und leitet den Pfad aus dem
Host-Triple ab. Der Shim-Harness-Test wiederum suchte in `build`,
`build-x86_64` und `build-arm64`, nie in `build-<triple>` — der Form, die die
Paketierung tatsächlich verwendet — und übersprang, während `build.sh` den
Harness unmittelbar zuvor gebaut und ausgeführt hatte.

Wirkung, gleicher Befehl vor und nach der Korrektur: **56 Skips / 1164 grün →
9 Skips / 1211 grün**. Die neun verbliebenen sind x86_64- und
Cross-Build-Zeilen, die zur anderen Architektur gehören.

**Ein vierter Defekt, den erst der Livelauf sichtbar machte.** Die
Sicherheitszusage „ohne Kanalfähigkeit kein Claim"
(`test_app_execution_channel.py`) prüfte nichts. Ihr gesperrter Kanal entstand
aus `app_channel_capabilities()` **ohne** Pfadargument; der Aufruf fällt auf
`default_release_path()` zurück und liest damit die echte Freigabedatei des
ausführenden Rechners. Solange dort keine gültige Freigabe lag, war der Test
grün — geprüft hatte er den Zustand des Entwicklerrechners, nicht einen
gesperrten Kanal. Sobald für den Abnahmelauf eine gültige Schreibfreigabe
existierte, prüfte er unversehens einen **offenen** Kanal und schlug fehl.
Der gesperrte Fall bekommt jetzt einen Pfad, der nicht existieren kann, und
ist damit unabhängig vom Rechnerzustand. Das Produktverhalten war korrekt:
die Sperre in `AppExecutionService.claim` greift, sie wurde nur nie geprüft.

## 3. Live-CRUD gegen einen echten Provider

Ein einziger synthetischer Testkontakt, ausschliesslich im **lokalen**
Container `_local:ABAccount` — damit verliess er dieses Gerät nicht. Der
cardDAV-Container mit 114 echten Kontakten war zu keinem Zeitpunkt Ziel eines
Vorgangs. Schreibfreigabe: `contacts-write-v1`, 60 Minuten, vom Eigentümer
selbst erzeugt.

| Schritt | Nachweis |
|---|---|
| CREATE | `succeeded`, ein Versuch; Readback deckungsgleich mit dem freigegebenen Entwurf; Ziel im richtigen Container; echte `…:ABPerson`-Identität |
| UPDATE | nur `organization_name` geändert; Namen und `contact_type` unangetastet; beide E-Mails wert- **und** positionsgleich; Provider-Identität unverändert |
| DELETE | `confirm_delete` erzwungen; Tombstone mit Grund `deleted_by_own_mutation`; External Identity erhalten; 116 → 115 aktive Kontakte; extern in Apple Kontakte vom Eigentümer als abwesend sichtgeprüft |

Jeder der drei Vorgänge trägt `attempt_count = 1`; es gab keinen zweiten
Send. Der Delta-Lauf nach dem Delete meldete **0 Ereignisse** ohne
geforderten Voll-Diff — die Echo-Unterdrückung greift, der Provider hat den
Datensatz nicht wiederhergestellt.

Die Absicherung liegt im schreibenden Prozess selbst
(`objc/JCContactsCreate.m`): unmittelbarer Read über den Identifier, nie über
einen Namen, danach vollständiger Vergleich des projizierten Ist-Zustands
gegen den freigegebenen Vorzustand; bei jeder Abweichung `RevisionConflict`
**vor** jedem Save. Der Fingerprint ist damit der ganze Vorzustand, nicht
bloss eine Revisionsnummer.

## 4. Backup und Recovery

Vor dem Lauf und erneut unmittelbar vor dem Delete erzeugt
(`scripts/contacts-backup.py`): Kopie über die SQLite-Backup-API,
`PRAGMA integrity_check` **auf der Kopie**, Aggregatvergleich Quelle gegen
Kopie, Datei 0600 im Ordner 0700 ausserhalb des Repositorys.
`restore_path_verified: true` in beiden Läufen.

Der verschlüsselte Backup-Kern aus AV-23 / 13 §1 existiert weiterhin nicht.
Das ist eine architekturunabhängige Produktlücke und **keine** arm64-Lücke;
sie öffnet diese Zeile nicht erneut.

## 5. Lifecycle

| Prüfung | Ergebnis |
|---|---|
| Geordnetes Beenden | 2 s, 0 Restprozesse, Port frei |
| GUI-Absturz (SIGKILL) | Backend über den Watchdog nach 4 s beendet, 0 Restprozesse, Port frei |
| Neustart | Backend nach 6 s gesund; alle drei Vorgänge unverändert `succeeded`, je ein Versuch |

Nicht erbracht: ein Absturz **während** eines laufenden `CNSaveRequest`.
`executing → outcome_unknown` bleibt auf arm64 unbelegt, ebenso
`recover_interrupted()` — es existierte kein unterbrochener Vorgang, die
Erholung lief leer und zählt nach §9 nicht.

## 6. Zwei Bedienfallen, architekturunabhängig

**Die Fähigkeiten sind ein Startschnappschuss.** `module.capabilities`
(`lifecycle.py:128`) wird beim Modulstart einmal berechnet und danach
zurückgegeben, während `/app-channel` frisch liest. Erscheint die
Schreibfreigabe erst nach dem Start — und sie ist eine ablaufende Datei, die
genau dann entsteht, wenn man sie braucht — meldet `/capabilities` weiterhin
`mutations_available: false`, obwohl der Kanal längst offen ist. Erst ein
Neustart löst das auf.

**Ein freigegebener Vorgang ist unsichtbar, bis er ausgeführt wird.**
`AUFMERKSAMKEIT` (`ContactsStatusSurface.tsx:782`) kennt `executing`,
`provider_applied_pending_reconcile`, `outcome_unknown`,
`reconcile_required`, `manual_decision_required`, `failed` und
`failed_before_send`; `wartetAufFreigabe` kennt `awaiting_approval`. Der
Zustand `approved` steht in keiner der beiden Mengen. Der Reiter „Vorgänge"
erscheint deshalb nicht von allein, und der Vorgang ist nur über den Umweg
„Diagnose → Vorgang öffnen" ausführbar — obwohl die Diagnose sich selbst
ausdrücklich als „technischer Nachweis, kein Arbeitsbereich" beschriftet. Der
Entwurf setzt voraus, dass Freigabe und Ausführung ein ununterbrochener
Dialog sind; wird er unterbrochen, strandet der Vorgang bis zum Ablauf
seiner Freigabe.

Beides ist nicht sicherheitskritisch — ohne Ausführung wird nichts
geschrieben, und die Freigabe verfällt von selbst. Beides trifft x86_64
gleichermassen.

## 7. Stand

Belegt: Build und Signierung, Write-Helper im Bundle mit kontaktfreier Suite,
Lesen und Containerinventar, Delta-Pfad, Create, Update, Delete, Lifecycle
und Watchdog, Backup und Recovery.

Offen: Voll-Diff-Fallback, At-most-once unter Absturz, Erholung eines
unterbrochenen Vorgangs, vollständige TCC-Persistenzmatrix, vereinheitlichte
Datensätze (in diesem Bestand nicht auslösbar), Backup-Kern,
Apple-Kontakte-Pixelabgleich.

Die Einzelbegründungen stehen in 15 §8.1.
