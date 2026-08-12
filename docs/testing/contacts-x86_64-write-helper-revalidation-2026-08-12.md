# Contacts x86_64 — Revalidierung des Schreibhelfers, 2026-08-12

Dieser Lauf schließt **ein** nachträglich entdecktes Beweisloch im bereits
funktional bewiesenen Contacts-x86_64-Stand: Paketierung, Signierung,
Identifier und Entitlements des Schreibhelfers waren auf Intel nie am fertigen
Paket gemessen worden. Er ist **keine** Neuabnahme von Contacts x86_64; der
vorhandene funktionale Nachweis bleibt unberührt.

Rechner: Intel-Mac, `uname -m` = `x86_64` nativ (kein `sysctl.proc_translated`,
also keine Rosetta), macOS 12.7.6 (21H1320).

## 1. Ausgangslage und übernommene Fixes

Basis: `22887d229e9a614961af8931b767d2f23966672d` („feat(core): write contacts
and calendar from the command bar, approval-bound").

`22887d2` ist **nicht** Vorfahr der M2-Linie. Beide sitzen auf `d50318d9`;
`ac9d3bb8` hat `d50318d9` als Elternteil, `22887d2` ist `d50318d9` plus drei
Core-Command-Bar-Commits, die ausschließlich `frontend/src/**` berühren.

| Commit | Herkunft | Inhalt |
|---|---|---|
| `63000eb3` | Cherry-Pick von `ac9d3bb8` | Reseal erfasst den Helfer, eigene Entitlementdatei, entblindete Architekturtests |
| `e535b9a7` | kleinste isolierbare Änderung aus `18036803` | deterministischer Write-Grant-Sperrtest |
| `4d0ca75f` | Cherry-Pick von `1c4794c5` | `scripts/contacts-backup.py` als belegter Recovery-Weg |

Einziger Konflikt beim Cherry-Pick: `frontend/tsconfig.tsbuildinfo`, ein
generierter tsc-Inkrementalcache. Aufgelöst zugunsten des Basisstands
(byteidentisch zu `22887d2`) — der M2-Cache gehört zu einem anderen Quellbaum.

Der Ort des deterministischen Fixes wurde mechanisch bestimmt
(`git log -S app_channel_capabilities`, `git log -S release_path`), nicht aus
der Commitnummer geraten. Der Blob nach Anwendung ist byteidentisch mit dem
Ergebnis in `18036803`. Die M2-Abnahmeevidenz aus demselben Commit wurde
ausdrücklich **nicht** übernommen.

`scripts/contacts-backup.py` geht über den engen Auftragswortlaut hinaus. Grund:
Dauerregeln §3 verlangt vor destruktiven Tests einen vorab belegten
Recovery-Weg und schließt den bloßen Hinweis auf eine Backup-Funktion
ausdrücklich aus; der Basisstand hatte für Contacts kein solches Werkzeug.

## 2. Der Helfer als Artefakt

Buildpfad: `frontend/src-tauri/target/x86_64-apple-darwin/release/contacts-write-helper`

| Prüfung | Befund |
|---|---|
| Format | Mach-O 64-bit executable x86_64 |
| `lipo -info` | Non-fat, `x86_64` |
| `minos` | 12.3 |

**Artefaktidentität.** Ein vorgelagerter `cargo build --bin contacts-write-helper`
erzeugte ein *anderes* Binary (`LC_UUID 498C0B3D-…`) als das gepackte:
`tauri build` baut den Bin selbst neu (Feature `custom-protocol`). Der
externalBin-Slot wurde deshalb aus dem finalen Target-Artefakt nachgezogen und
neu gebaut, bis alle drei Stellen dieselbe signaturinvariante Identität tragen:

```
LC_UUID F7EF6A3D-C04C-36BB-9899-38CDBFC3E0A0
  target/x86_64-apple-darwin/release/contacts-write-helper        996 656 B
  binaries/contacts-write-helper-x86_64-apple-darwin              996 656 B
  …/bundle/macos/Jarvis.app/Contents/MacOS/contacts-write-helper 1 025 840 B
```

Der Größenunterschied ist die eingebettete Signatur. SHA-256 taugt hier nicht,
weil Reseal die Bytes legitim verändert.

## 3. Der Defekt, gemessen — und geschlossen

**Vorzustand nach `tauri build`, vor Reseal (auf Intel):**

| Merkmal | Befund |
|---|---|
| Signatur | `adhoc` |
| Identifier | `contacts-write-helper-55554944f7ef…` (generiert) |
| Entitlements | **null** Einträge |

Auf arm64 war derselbe Defekt anders sichtbar (App-Identifier, neun
Entitlements). Gemeinsam ist beiden: weder das produktive Blatt noch das von
ADR-0026 geforderte Addressbook-Recht.

**Nach `reseal-contacts-sidecar.sh` mit `APPLE_SIGNING_IDENTITY=de.kluender.jarvis`:**

| Prüfung | Befund |
|---|---|
| Identifier | `de.kluender.jarvis.contacts-write-helper` |
| Alter Identifier `contacts-write-helper` | nicht mehr Signing-Identität |
| Entitlements | **genau eins**: `com.apple.security.personal-information.addressbook` |
| Verbotene Rechte | JIT, unsigned executable memory, disabled library validation, network.client, network.server, calendars, app-sandbox, files.user-selected: alle abwesend |
| Hardened Runtime | `flags=0x10000(runtime)` |
| DR | `identifier "de.kluender.jarvis.contacts-write-helper" and certificate leaf = H"34a4521ba80e5c701bf097897c794b6a5a716f14"` |
| Bindung | zertifikatsgebunden, keine `cdhash`-Bindung |
| Blattgleichheit App/Helfer | identisch |
| Spike-Identität | 0 Treffer |

Maßgeblich ist ADR-0026: eigener Identifier, zertifikatsgebundene DR mit
demselben Blatt wie die App, Hardened Runtime, **ein** Entitlement
(Addressbook). Die App selbst trägt neun Schlüssel — der Helfer erbt sie nicht.

## 4. Wirkt der Reseal wirklich?

Vier Defektklassen wurden in Kopien des fertigen Pakets erzeugt und die
Testkette gegen jede gefahren:

| Szenario | Erkannt durch |
|---|---|
| Helfer ungesiegelt | 5 Fehlschläge (Identifier, DR, Runtime, Entitlements, Blatt) |
| falscher Identifier | 3 Fehlschläge, darunter äußeres Siegel `nested code is modified or invalid` |
| falsche Entitlements (voller App-Satz) | 1 Fehlschlag (Entitlementprüfung) |
| fremdes Blatt (Spike-Identität) | 3 Fehlschläge, darunter äußeres Siegel |
| unverändert | 17/17 grün |

**Befund, der festgehalten gehört:** Bei falschen Entitlements bleibt das Paket
unter macOS 12 `valid on disk`. Die äußere Signatur versiegelt verschachtelten
Code über dessen Designated Requirement; ein Helfer mit richtigem Identifier
und richtigem Blatt erfüllt es weiterhin. `codesign --deep` allein trägt diese
Behauptung also **nicht** — nur die dedizierte Entitlementprüfung fängt den
Fall. Beide zusammen decken alle vier Klassen ab, einzeln keine.

## 5. Die ehemals blinden Prüfungen

Alle Zahlen sind gemessen, nicht erwartet.

| Datei | Ergebnis |
|---|---|
| `test_write_helper_bundle.py` | 17 run, **0 skip** |
| `test_save_exception_shim.py` | 36 run, **0 skip** |
| `test_app_execution_channel.py` | 37 run, 0 skip |

Auf Intel war die Blindheit in `test_save_exception_shim.py`: die
Kandidatenliste kannte `build`, `build-x86_64` und `build-arm64`, die
Paketierung erzeugt aber `build-x86_64-apple-darwin`. Keiner der drei
Basiskandidaten existiert auf diesem Rechner — `test_der_native_harness_besteht`
und `test_build_sh_baut_und_startet_den_harness` übersprangen also lautlos,
obwohl `build.sh` den Harness unmittelbar zuvor gebaut hatte. Beide laufen
jetzt.

`test_write_helper_bundle.py` war auf Intel nicht architekturblind (der fest
verdrahtete Pfad war der richtige); dort lag das Loch darin, dass die Kette nie
gegen ein resealtes Paket lief.

**Deterministischer Grant-Test.** Der Sperrfall bekommt jetzt einen
ausdrücklich kontrollierten, nicht existierenden Releasepfad. Empirisch belegt:
37/37 **ohne** Freigabedatei auf dem Rechner und 37/37 **mit** gültiger echter
Freigabe. Der Zustand unter `~/.openjarvis` beeinflusst das Ergebnis nicht.

**Contacts-Regression gesamt:** 1211 passed, 9 skipped, 1 failed.
Die 9 Skips sind ausnahmslos arm64- und Cross-Build-Zeilen (andere
Architektur). Der Fehlschlag ist `test_dec_052_ist_registriert`; er liest
ausschließlich `docs/personal-jarvis/decisions-register.md`, das keiner der
drei Commits berührt — vorbestehend und außerhalb dieses Scopes.

## 6. Finales Intel-Paket

| Artefakt | Architektur | Identifier |
|---|---|---|
| `openjarvis-desktop` | x86_64 | `de.kluender.jarvis` |
| `contacts-write-helper` | x86_64 | `de.kluender.jarvis.contacts-write-helper` |
| `jarvis-contacts` | x86_64 | `de.kluender.jarvis.contacts-bridge` |
| `jarvis-calendar` | x86_64 | `de.kluender.jarvis.calendar-bridge` |

`codesign --verify --deep --strict`: `valid on disk`, `satisfies its Designated
Requirement`. Alle vier DR nennen dasselbe Blatt `34a4521b…`. Spike-Treffer: 0.
Geprüfte Mach-O im Bundle: 4, davon Write-Helper: 1.

Der `tauri build`-Exitcode war 1 — ausschließlich wegen des fehlenden
`TAURI_SIGNING_PRIVATE_KEY` für das Updater-Archiv, nach Fertigstellung des
`.app`. Kein Bezug zu Signatur, Helfer oder Bundle.

## 7. Produktiver CRUD-Nachweis

Ein synthetischer Kontakt, ausschließlich im lokalen Container `C-4b8df1`.
Kanal live: `channel_mode: native_create`, `provider_write_enabled: true`,
`architecture: x86_64`, TCC `authorized`.

**Abgebrochener erster Anlauf.** Zwei Create-Vorgänge (18:55:25Z, 19:05:17Z)
wurden vorbereitet und freigegeben, aber nie ausgeführt; die App wurde vom
Eigentümer beendet. Beleg, dass nichts gesendet wurde: beide Outbox-Zeilen
`state: pending`, `attempt_count: 0`, `claimed_at: NULL`,
`execution_order_issued_at: NULL`. Nach ADR-0026 steht `provider_send_started`
**vor** dem Verlassen des Backends; ein fehlender Auftrag schließt einen Send
aus. Kein `save_started`-Marker, kein Crashreport, Bestand unverändert.
Beide wurden anschließend ausdrücklich `expired`.

Ursache der Doppelung: „Freigeben" im Vorschaudialog **approved nur**; die
Ausführung ist ein getrennter Klick im Vorgänge-Panel. Das ist vertraglich
gewollt (ADR-0025 §1: ein Klick darf nicht beides bedeuten), war aber im Ablauf
nicht erkennbar.

**Der gültige Lauf.**

| Operation | Mutation | Beleg |
|---|---|---|
| CREATE | `f7710595` | `succeeded`, `container_ref C-4b8df1`, `attempt_count 1`, ein `execution_order_issued_at 20:26:30Z`, `execution_report_digest 44da1ee7…`, `settled_at 20:26:32Z`, Freigabe `consumed` |
| UPDATE | `44356130` | `succeeded`, `expected_revision "1"` = der vor der Änderung festgehaltene Fingerprint, `attempt_count 1`, `operation_id 3510d940…` |
| DELETE | `c6a91c7d` | `succeeded`, `expected_revision "1"`, `attempt_count 1`, `operation_id 83e59ab7…` |

Readback nach CREATE: OID `0172ff07-944a-4196-9084-53c77c5c2167`,
`container_refs: ['C-4b8df1']`, `revision 1`, `sync_state in_sync`.
Readback nach UPDATE: `family_name` trägt den Zielwert, Container unverändert.
Bestand: 119 → 120 → nach DELETE wieder 117 in der Listenroute.

**Recovery-Weg vor dem DELETE, ausgeübt statt behauptet.**
Zwei Sicherungen (`20260812T182221Z` vorab, `20260812T203058Z` unmittelbar vor
dem Löschen), jeweils `integrity_check: ok`, Aggregate Quelle = Kopie,
`restore_path_verified: true`, Datei 0600 im 0700-Ordner. Zusätzlich der
vollständige Vorzustand des Testobjekts, wiederherstellbar über exakt den
CREATE-Pfad, der in derselben Sitzung nachweislich funktioniert hat.

**Positive Nichtvorhandenheitskontrolle.** Eigentümer-Sichtprüfung in Apple
Kontakte, „Auf meinem Mac", Suche `ZZ-Reval`: **0 Treffer**. Das ist die von
ADR-0026 für Delete genannte externe Sichtprüfung. `POST /sync` wurde
ausdrücklich **nicht** gefahren. Der Kern akzeptiert `succeeded` ohnehin nur bei
`outcome == "applied"` **und** `readback_status ∈ {confirmed, absent_confirmed}`;
der Tombstone trägt `reason: deleted_by_own_mutation`.

**Fremde Daten.** In diesem Lauf war `C-1b3d99` (cardDAV, 115 Kontakte) zu
keinem Zeitpunkt Mutationsziel; alle drei heutigen Vorgänge nennen `C-4b8df1`.
Der einzige Mutationssatz mit `C-1b3d99` stammt vom 2026-08-01 und steht auf
`manually_resolved_not_applied` / `failed`. Kein bestehender Kontakt wurde
verändert.

Die Schreibfreigabe wurde nach dem Lauf vom Eigentümer gelöscht; der Kern liest
`None`.

## 8. Offene Punkte — nicht in PASS umetikettiert

Keiner davon wurde in diesem Block repariert.

| # | Punkt | Status |
|---|---|---|
| A | Die Freigabevorschau nennt den Zielcontainer nicht sichtbar. Das Ziel war nur am Mutationssatz prüfbar. | offen |
| B | Eine abgelaufene Freigabe zeigt weiterhin `approval_state: granted`, bis ein Zugriff sie auswertet. | offen |
| C | `approved`, aber nicht ausgeführte Vorgänge sind in der Oberfläche nicht deutlich genug als offen erkennbar. | offen |
| D | Mehrere offene Vorbereitungen können nebeneinander bestehen, ohne dass das erkennbar wäre. | offen |
| E | Die Contacts-Detailroute liefert nach DELETE den Tombstone weiter mit HTTP 200; ein OID-Abruf taugt damit nicht als Abwesenheitsprobe. | `UNRESOLVED_API_SEMANTICS` — kein Defekt behauptet, solange der API-Vertrag nicht geprüft ist |
| F | Im Änderungssatz des UPDATE steht `"previous": null`, obwohl ein Vorwert existierte. Die Bindung lief über `expected_revision` und hielt; die Vorschautreue ist schwächer als beschrieben. | offen |

## 9. Ergebnis

`CONTACTS x86_64 WRITE-HELPER REVALIDATION = PASS`

Helfer nativ x86_64, korrekter Identifier, exakt das eine erlaubte Entitlement,
App und Helfer mit derselben produktiven Leaf-Identität gesiegelt, Helfer
nachweislich vom Reseal erfasst, die vormals blinden Prüfungen laufen wirklich,
das final gepackte Bundle ist mechanisch geprüft, CREATE/UPDATE/DELETE mit genau
einem synthetischen lokalen Testkontakt erfolgreich, Re-Read und Fingerprint
tatsächlich ausgeübt, positive Nichtvorhandenheitskontrolle bestanden,
`C-1b3d99` unberührt.

Pushstatus: `not_performed_owner_action`.
