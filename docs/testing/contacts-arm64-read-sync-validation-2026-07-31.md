# Kontakte — ARM64-Abnahme des produktiven Lese- und Sync-Pfads (2026-07-31)

**Gegenstand:** Erste produktive Live-Abnahme des Kontakte-Moduls auf Apple
Silicon: Initialimport, Auditspur, Delta-Läufe und Cursorfortsetzung über einen
echten Anwendungsneustart.

**Betrifft Produktivcode** (nicht mehr den Spike aus ADR-0016). Referenzen:
`docs/adr/ADR-0016-swift-contacts-bridge.md`, `docs/adr/ADR-0018-dual-architecture-macos-support.md`,
`docs/personal-jarvis/modules/contacts.md`.

> Alle Zahlen sind aggregiert. Dieses Dokument enthält **keine** Kontaktdaten,
> keine Namen, keine Provider-Identifier, keine Cursor oder Token, keine
> Zertifikatsangaben und keine privaten Pfade. Containerkennungen erscheinen
> ausschliesslich als maskierte Referenz (`C-…`, nicht zurückrechenbar).

---

## 1. Host und Codeobjekte

| Merkmal | Wert |
|---|---|
| Architektur | Apple Silicon M2 Pro, **arm64** (nativ, kein Rosetta) |
| Anwendung | produktive `Jarvis.app`, aus dem Arbeitsbaum gebaut und signiert |
| App-Identifier | `de.kluender.jarvis` |
| Sidecar-Identifier | `de.kluender.jarvis.contacts-bridge` |
| Beide Binaries | `arm64`, Mindestversion `12.3` |
| Hardened Runtime | bei App **und** Sidecar gesetzt |
| Designated Requirement | zertifikatsgebunden bei beiden; kein `cdhash` |
| Signaturprüfung | `codesign --verify --strict --deep` erfolgreich |

**Entitlements — geprüft am gebauten Bundle:**

| | App | Sidecar |
|---|---|---|
| `personal-information.addressbook` | ja | ja |
| `app-sandbox` | `false` | nicht vorhanden |
| `inherit` | nicht vorhanden | nicht vorhanden |
| JIT, unsignierter Speicher, abgeschaltete Library-Validation | vorhanden | **nicht** vorhanden |
| Netz, Dateiauswahl | vorhanden | **nicht** vorhanden |
| **Anzahl Einträge** | 8 | **genau 1** |

Der Sidecar trägt seinen eigenen, minimalen Vertrag
(`ContactsSidecar.entitlements`); das Reseal-Skript signiert ihn damit, statt
die App-Entitlements zu erben. Die eingebettete `NSContactsUsageDescription`
überlebt das Reseal nachweislich.

## 2. Initialer produktiver Lauf

Vom Benutzer über die Oberfläche ausgelöst, nicht automatisch.

| Grösse | Wert |
|---|---|
| Modus | `full_diff_account` |
| Container | 2 |
| Enumeration je Container | `C-63caab`: 114 gemeldet / 114 erhalten · `C-4b8df1`: 1 / 1 |
| Vollständigkeit und Zählung | beide `complete`, beide konsistent, 0 Duplikate |
| Importiert | **115** |
| Tombstones | **0** |
| `suspicious_empty` | 0 |
| Cursor vorher / nachher | vorhanden / vorhanden |
| Ausgang | `committed` |
| Dauer | 383 ms |
| Auditspur | vollständig, aus Migration 0005 |

Damit ist auf arm64 aus der **gepackten** Anwendung live belegt:
TCC-Autorisierung unter dem neuen Entitlement-Modell, Containerabfrage,
vollständiger Enumerationspfad über beide Container, kontoweite Löschbasis,
Cursorführung und die Auditspur.

## 3. Delta- und Neustart-Test

| Grösse | Wert |
|---|---|
| Benutzer-Syncs | 2 |
| Delta-Läufe je Benutzer-Sync | 2 — einer je Container |
| Delta-Audit-Runs insgesamt | **4** |
| Ausgang | alle `committed` |
| Change-Ereignisse je Lauf | **0** |
| Cursor vorher / nachher | in allen vier Läufen vorhanden / vorhanden |
| Importiert, geändert, tombstoned | je 0 |
| Unerwartete Voll-Diffs | **keine** — `full_diff_required` blieb überall 0 |
| Zwischen den Syncs | **echter Neustart** von Anwendung und Backend |
| Cursorfortsetzung nach Neustart | erfolgreich; beide Container blieben im Modus `delta` |
| Veralteter `serve.lock` | produktiv ersetzt (tote PID durch die laufende überschrieben) |
| Aktive Kontakte danach | **115** |
| Tombstones danach | **0** |
| Recovery-Läufe | **0** |
| Autonomer Sync | **keiner** — jeder Lauf war ausdrücklich ausgelöst |

**Der wichtigste Einzelbefund:** Ein Delta-Lauf mit **null** Ereignissen
erscheint als `committed` in der Spur. Vor der Auditerweiterung war genau
dieser Fall unsichtbar — der Lauf hatte den Cursor fortgeschrieben, ohne eine
Spur zu hinterlassen.

**Ein Lauf, eine Spur.** Jeder Delta-Lauf trägt eine eigene `run_id`; ein
Benutzer-Sync über zwei Container erzeugt zwei Läufe, keine verschachtelten
Doppel-Runs. Delta-Läufe schreiben erwartungsgemäss **keine**
Container-Enumerationszeilen: ein Delta zählt nicht auf.

**Datenschutz der Spur — am Livebestand geprüft:** keine Container-Kennung im
Klartext, kein `@`, kein Tokenfragment, kein Pfad. Der Cursor erscheint
ausschliesslich als Wahrheitswert („vorhanden ja/nein"), nie als Wert.

## 4. Automatisiert getestet, **nicht** live provoziert

Die folgenden Pfade sind durch kontaktfreie Regressionstests gegen temporäre
Datenbanken und eine Attrappe abgedeckt. Sie sind auf diesem Gerät **nicht**
live eingetreten, weil sich das Adressbuch während der Abnahme nicht geändert
hat und kein Fehlerfall künstlich herbeigeführt wurde:

| Pfad | erwartetes Verhalten |
|---|---|
| `add`-Ereignis | aggregiert erfasst, `imported` erhöht, `committed` |
| `update`-Ereignis | aggregiert erfasst, `updated` erhöht, `committed` |
| **Provider-`DELETE`-Ereignis** | Tombstone und Auditzeile in **derselben** Transaktion, `tombstoned` aggregiert ausgewiesen |
| `dropEverything` | `aborted`, `full_diff_required`, `drop_everything_seen` |
| ungültiger Cursor | `aborted`, Fehlerklasse `CursorRejected` |
| fehlender Container | `aborted`, Kennung `container_missing` |
| Bridge-Timeout | `aborted`, Kennung `process:request_timeout` |
| `suspicious_empty_enumeration` | fail-closed, **kein** Tombstone |
| `transient_empty_snapshot` | Lauf verworfen, **kein** Tombstone |

Die Null-Gegenprobe war im Livebetrieb nicht auslösbar: beide Container hatten
`previous_count = 0`, die Bedingung „zuvor gefüllt" trat nie ein.

## 5. Abnahmeaussage

**Der ARM64-Lese- und Sync-Pfad einschliesslich Auditierung und Neustart gilt
als produktiv abgenommen.**

Ein künstlich herbeigeführter Provider-`DELETE`-Livetest wird **nicht** zur
Voraussetzung dieses Abschlusses gemacht. Begründung: Der Pfad ist
automatisiert abgedeckt, und ein Livetest verlangte eine Mutation an echten
Kontaktdaten — ein Eingriff, dessen Risiko den Erkenntnisgewinn gegenüber dem
Test nicht aufwiegt. Die Aussage gilt ausdrücklich **nur** für arm64.

## 6. Zum Vorfall vom 2026-07-30 — Stand der Ursachenklärung

Auf dem Intel-Gerät setzte ein Voll-Diff 116 Kontakte lokal auf gelöscht,
nachdem eine Enumeration `count=0, complete=true` gemeldet hatte. Bei Apple
war nichts verändert; die Provider-Identifier waren unversehrt.

Was **belegt** ist: die Enumeration meldete null Datensätze bei gesetztem
Vollständigkeitsmarker, und der damalige Code leitete daraus eine Löschmenge
ab. Der Schutz dagegen — kontoweite Löschbasis, einmalige Null-Gegenprobe,
`suspicious_empty` — ist implementiert und getestet.

Was **Hypothese bleibt**: warum der Provider in diesem Moment null Datensätze
meldete. Die Vermutung eines kurzzeitig leeren Stores im Zusammenhang mit
einem `dropEverything` ist plausibel, aber **nicht belegt** — weder durch
Apple-Dokumentation noch durch eine Reproduktion. Sie wird hier ausdrücklich
als offene Hypothese geführt und **nicht** als Ursache behauptet. Eine
Apple-interne Ursache wird in diesem Bericht an keiner Stelle als Tatsache
dargestellt.

## 7. Weiterhin offen

Siehe `docs/personal-jarvis/modules/contacts.md` §15. Kurz:

1. Intel-x86_64: Recovery der 116 lokal tombstoneten Spiegelkontakte.
2. Intel: Delta- und Neustartprüfung **nach** dem Recovery.
3. Provider-Mutationen (Anlegen, Bearbeiten, Löschen) mit Vorschau, Freigabe
   und ausdrücklicher Ausführung.
4. Alter OpenJarvis-Apple-Contacts-Connector: deaktivieren, entfernen oder auf
   die kanonische Personal-Jarvis-Datenbank umleiten.
5. Finaler Cross-Architecture-Abschluss.
6. Übernahme auf `jarvis/rebuild-v1`.
