# Contacts — Write/Lifecycle-Reparatur, x86_64 Native Closure, 2026-08-16

**Lane:** Risk Lane (Signing/Packaging, nativer Plattformnachweis).
**Basis:** `b5ddf3b4c4a9d7ca9ceddc35c12fdacd4728ca86` — derselbe finale
Reparaturstand, der auf arm64 abgenommen wurde.
**Worktree:** `~/Jarvis-Next-Contacts-Repair-Intel`,
Branch `verify/contacts-repair-x86_64-2026-08-13`.
**Regelquelle:** `docs/governance/openjarvis-dauerregeln.md` bei
`3ca01ebcd3b39ace937e135f8588d85fa311224b`.

> Aggregierte Angaben. Keine Kontaktwerte, keine Providerkennungen im Klartext.

**Rechner.** Intel Core i7-6920HQ, macOS 12.7.6 (21H1320), x86_64 nativ
(`hw.optional.arm64` abwesend, kein Rosetta), Benutzer `lukasklunder`,
Xcode 14.2 (14C18), SDK MacOSX 13.1, gemeinsames git-dir
`/Users/lukasklunder/Jarvis-Next/.git`. Der eingefrorene Worktree
`~/Jarvis-Next` steht unverändert auf `1f03bfa4` und wurde nicht angefasst.

---

## 1. Was hier bewiesen wurde — und was nicht

Dies ist **keine** zweite Contacts-Abnahme. Bewiesen wird nur, was nach der
bestandenen arm64-Abnahme durch Architektur, Packaging oder den gemeinsamen
Reparaturcode Intel-spezifisch offen war.

Die Diffklassifizierung `ff240978` → `b5ddf3b4` (45 Dateien) ergibt für die
beiden riskanten Punkte:

| Frage | Befund |
|---|---|
| G — ist die OwnerDecision-/Approval-/Execute-Semantik gemeinsamer, plattformneutraler Code? | **Ja.** `src/personaljarvis/base/approvals.py` enthält null Architektur- oder Plattformbezüge (`x86_64`, `arm64`, `sys.platform`, `uname`, `machine()`); dasselbe gilt für alle geänderten Python-Dateien der Mutations-, Query- und Lifecycle-Schicht. |
| H — was am Packaging ist architekturspezifisch? | Genau die Parametrisierung: `build-product.sh` leitet aus `uname -m` das Triple ab; daran hängen Targetordner, externalBin-Slotname und die Architekturprüfung des Wächters (`_TRIPLE_ARCH`). Die Reihenfolge Sidecar → Helfer → Bundle → Reseal → Torwächter → DMG ist architekturunabhängig. |

## 2. Der einzige echte Intel-Befund

Der kanonische Produktbuild **scheiterte** im ersten Lauf, fail-closed, ohne
DMG:

```
FAIL openjarvis-desktop/entitlements   … gemessen '(leer)'
FAIL contacts-write-helper/entitlements … gemessen '(leer)'
FAIL jarvis-contacts/entitlements       … gemessen '(leer)'
FAIL jarvis-calendar/entitlements       … gemessen '(leer)'
VERTRAGSBRUCH: 4 von 33 Nachweisen fehlgeschlagen.
```

Die Rechte waren vorhanden — das Reseal-Protokoll unmittelbar davor wies für
Helfer und beide Sidecars je genau eines aus. Blind war der **Leser**:

`codesign -d --entitlements - --xml` hängt unter macOS 12.7.6 ein `\x00`
hinter `</plist>`. Expat lehnt das als „not well-formed" ab, und
`entitlement_keys()` fing jeden Lesefehler mit `except Exception: return
frozenset()` ab. Ein unlesbarer Rechteblob wurde damit zur Aussage „dieses
Binary trägt kein Recht". Unter macOS 13+ tritt das NUL-Byte nicht auf; auf
dem M2 lief derselbe Code deshalb grün.

**Fehlrichtung.** Der Wächter meldete FAIL, nicht PASS — für die vier Specs
dieses Bundles ist der Sollvorrat nicht leer, der stille Leerwert fiel also
fail-closed aus. Kein falsches Grün. Aber: für einen Vertrag, der eine leere
Rechtemenge *erwartet*, wäre daraus stilles Grün geworden — der
Empty-/No-op-Fall aus Dauerregeln §9.

**Reparatur** (Dauerregeln §18 — mechanisch festgestellter Blocker im
laufenden Funktionsweg, keine neue Toolingarchitektur):

* `entitlement_keys_from_blob()` schneidet an `</plist>` ab, statt auf ein
  wohlgeformtes Ende zu hoffen — eigene Funktion, weil hier die
  Plattformunterschiede sitzen und sie ohne gebautes Bundle prüfbar sein muss.
* Ein vorhandener, aber unlesbarer Blob wirft `EntitlementsUnreadable` und
  wird in `verify_binary()` zu einem FAIL-Befund `unlesbar (…)`. Er wird nie
  mehr gegen eine Menge verglichen, die nie erhoben wurde.
* Gar kein Blob bleibt die leere Menge: ohne `--entitlements` signiert heisst
  weiterhin „kein Recht", und `test_leeres_entitlement_set_wird_erkannt`
  bleibt gültig.

**Nachweise** (§12: Reproduktion ohne Reparatur, plus Gegenprobe) —
`tests/personal/contacts/test_bundle_contract.py`:

| Nachweis | Test |
|---|---|
| Blob mit NUL-Byte wird gelesen (fällt gegen den alten Stand) | `test_der_rechteblob_wird_auch_mit_nul_byte_gelesen` |
| Ohne NUL dieselbe Antwort | `test_ohne_nul_byte_liest_er_dasselbe` |
| Gar kein Blob bleibt die leere Menge | `test_gar_kein_blob_bleibt_die_leere_menge` |
| Unlesbarer Blob ist **nicht** die leere Menge | `test_ein_unlesbarer_blob_ist_nicht_die_leere_menge` |
| Und kommt als Vertragsbruch an | `test_der_unlesbare_vorrat_wird_zum_vertragsbruch` |

Diese fünf brauchen kein gebautes Bundle. Das bisherige Modul-`pytestmark`
wurde dafür in einen Marker `_braucht_bundle` je Test aufgelöst; die
bundleabhängigen Proben verhalten sich unverändert.

## 3. Deterministische A–J-Nachweise, nativ x86_64

`uv run pytest` über die für A–J relevanten Dateien:
**221 passed, 0 skipped, 0 failed** (25,3 s) —
`test_write_lifecycle_repair`, `test_owner_grant`, `test_capability_bridge`,
`test_mutation_pipeline`, `test_container_inventory`,
`test_pipeline_hardening`, `test_bundle_contract`.

Frontend (`vitest`): **124 passed** über 8 Dateien — `ownerGrant`,
`schreibsperre`, `seitenleiste`, `zielangabe`, `offene-vorgaenge`,
`kanalSemantik`, `ContactsPage`, `components`.

Stichprobenhaft gegen den Quelltext geprüft statt über Testnamen geglaubt:

* **G.** `OwnerDecision.__init__` wirft ohne das modulinterne `_SIEGEL`; das
  Siegel ist ein `object()` ohne Namen und Wert. `owner_decision()` weist
  leere und maschinelle Ursprünge ab. Der AST-Wächter
  `test_owner_decision_wird_nur_am_freigabeweg_aufgerufen` behauptet
  **Mengengleichheit** gegen genau `{contacts/api/routes.py,
  calendar/mutations/service.py}` — ein leerer Scan kann daran nicht bestehen,
  und Contacts und Calendar hängen nachweislich an derselben Grenze.
  `test_keine_selbstfreigabe_irgendwo_in_der_oberflaeche` prüft ebenso eine
  Menge über den ganzen `frontend/src`-Baum, nicht eine Datei.
* **B.** `effective_state()` ist die eine Stelle, die aus Zustand plus Zeit den
  wirksamen Zustand macht, und schreibt nichts fort; Anzeige und `consume()`
  lesen dieselbe Funktion.
* **I.** `test_kein_selbstgrant_aus_dem_kern` übt die Lesepfade dreimal aus
  und prüft danach, dass keine Freigabedatei entstanden ist.
  `test_eine_nach_dem_start_erteilte_freigabe_wirkt_ohne_neustart` und sein
  Gegenstück erzeugen beziehungsweise entfernen die Datei zur Laufzeit und
  beobachten den Umschlag.

## 4. Produktbuild, Artefakt und Installer

Kanonisch über `frontend/src-tauri/scripts/build-product.sh`, nativ
x86_64-apple-darwin. Der alte manuelle Ablauf wurde nicht als Produktnachweis
verwendet. Ergebnis: `PRODUKTBUILD OK`.

| Prüfung | Ergebnis |
|---|---|
| Vertrag an der finalen App | **33 von 33 Nachweisen** |
| Vertrag an der App **aus dem DMG** | **33 von 33 Nachweisen** |
| Negativproben | **14 passed**, darunter adhoc, falscher Identifier, falsches Entitlement-Set, leeres Entitlement-Set, fremdes echtes Zertifikatsblatt, fehlendes Binary |
| Original nach den Negativproben | unverändert (`test_das_original_ist_nach_den_negativproben_unveraendert`) |

Alle vier Mach-O: Architektur `x86_64`, Hardened Runtime `runtime`,
zertifikatsgebundene Signatur, DR mit eigenem Identifier und demselben Blatt
`34a4521ba80e5c701bf097897c794b6a5a716f14`; `bundle/einheitliches-blatt`
= genau eins. Mindestplattform 12.3 an allen vier (`LC_BUILD_VERSION minos`).
Spike-Treffer gegen `Personal Jarvis Contacts Spike`
(`F378C267…`): **0**.

Schreibhelfer: Identifier `de.kluender.jarvis.contacts-write-helper`,
Entitlements **genau eins**,
`com.apple.security.personal-information.addressbook`. Abwesend: App-Sandbox,
JIT, unsigned executable memory, disable library validation, Network Client,
Network Server, Calendar, Dateirechte.

`codesign --deep` wurde nicht als Nachweis für Identifier, Rechte,
Capability-Vertrag oder Blatt verwendet; jede dieser Eigenschaften ist einzeln
erhoben.

**Artefaktidentität.**

```
LC_UUID A1B6FA15-F1BE-35CC-B768-55C1681AD99D  an allen vier Stationen
   996 656 B  target/x86_64-apple-darwin/release/contacts-write-helper
   996 656 B  binaries/contacts-write-helper-x86_64-apple-darwin
 1 024 176 B  Jarvis.app/Contents/MacOS/contacts-write-helper
 1 024 176 B  Jarvis.app aus Jarvis_1.0.1_x64.dmg
```

Byteidentisch, wo Signierung die Bytes nicht verändert: Target und
externalBin-Slot teilen SHA-256 `81b61dd4…`; die gepackte App und die App aus
dem DMG teilen SHA-256 `584e8977…`. Der Größenunterschied Target → gepackt ist
die eingebettete Signatur. Der vorgelagerte `cargo build` wird **nicht** als
das gepackte Artefakt behauptet — `tauri build` baut den Bin selbst neu; die
Kette schloss in Runde 2 des Angleichschritts.

## 5. Oberfläche auf Intel

Gestartet wurde exakt der finale Produkt-Build
(`…/bundle/macos/Jarvis.app`), Mach-O `x86_64`, nativ.

| Prüfung | Ergebnis |
|---|---|
| App startet | ja, Prozess aus genau diesem Bundle |
| Backend erreichbar | ja |
| Reale Kontakte lesbar | ja — Read über `/v1/personal/contacts` liefert Datensätze des echten Bestands |
| Schreibzustand ohne Freigabe | `read_supported: true`, `create/update/delete_supported: false`, `mutations_available: false` |
| Self-Grant durch Start oder Read | **keiner** — nach App-Start und Read existiert keine `contacts-write-release.json` |

Für die Sichtprüfung wurde **keine** Freigabedatei erzeugt.

Neues Contacts-Design, Seitenleisten-Toggle und die Verständlichkeit des
gesperrten Schreibzustands sind Eigentümer-Sichtprüfung (Dauerregeln §13).

## 6. Kein Intel-Livetest — und warum

`INTEL_CONTACTS_LIVE_WRITE_REQUIRED` = **NO**.

Mechanische Grundlage: der Diff des **nativen Contacts-Providerpfads**
zwischen der Intel-Evidenz `5bb3061bcfec5c33294aef5dcd5d21a173b08c81`
(x86_64 Write-Helper-Revalidierung, 2026-08-12) und `b5ddf3b4` über
`frontend/src-tauri/objc`, `frontend/src-tauri/src`,
`frontend/src-tauri/native`, `frontend/src-tauri/binaries`, `Cargo.toml`,
`tauri.conf.json`, alle `*.entitlements`, `Entitlements.plist`,
`contacts/bridge`, `contacts/infrastructure` ist **leer**.

Daraus:

* Die frühere native Intel-Evidenz trägt den Contacts-Providerpfad — er ist
  nicht bloss ähnlich, sondern unverändert.
* Die neue gemeinsame Approval-/Lifecycle-Semantik ist plattformneutral (§1),
  live auf arm64 bewiesen (2026-08-13) und hier nativ x86_64 deterministisch
  belegt (§3).
* Der einzige native Intel-Befund (§2) liegt im **Prüfwerkzeug**, nicht im
  Provider- oder Writepfad, und zeigt keinen abweichenden Ausführungsweg.

Es wurde deshalb **keine** produktive Contacts-Mutation ausgeführt: kein
CREATE, kein UPDATE, kein DELETE. Der cardDAV-Bestand blieb unberührt.

## 7. Ergebnis

| Aussage | Stand |
|---|---|
| `CONTACTS WRITE/LIFECYCLE REPAIR – x86_64` | **PASS** |
| `CONTACTS WRITE/LIFECYCLE REPAIR – NATIVE BOTH ARCHITECTURES` | **COMPLETE** |
| `INTEL_CONTACTS_LIVE_WRITE_REQUIRED` | `NO` |
| `integration_report_update` | **geschlossen** — §10 im Integrationsbericht nachgetragen |
| `AUTOMATIC_COMMIT_WATCHERS` | **verdrahtet** — siehe §8 |
| `test_dec_052_ist_registriert` | vorbestehend, out of scope — siehe §9 |
| Pushstatus | `pushed_by_owner` — `verify/contacts-repair-x86_64-2026-08-13` bei `042eafc` am 2026-08-16 vom Eigentümer nach `origin` gepusht |

`NATIVE BOTH ARCHITECTURES = COMPLETE` heisst: die nativen Contacts-Pfade sind
auf beiden unterstützten Architekturen abgeschlossen. Es heisst **nicht**,
dass Contacts ohne jeden gemeinsamen Produktrest fertig ist. Bekannte
architekturunabhängige Restpunkte bleiben separat offen, insbesondere die
TCC-Persistenzmatrix und der nicht durchgeführte Zehn-Szenen-Pixelabgleich
(Integrationsbericht §5 und §7).

## 8. Automatische Wächter

Es gab bereits einen kleinen kanonischen Anschlussweg: `.pre-commit-config.yaml`
mit den beiden ruff-Hooks; `pre-commit` liegt im `dev`-Extra. Keine neue
Testplattform, kein neuer Gate-Name, keine neue Phase.

Ergänzt wurde **ein** `local`-Hook mit bereits vorhandenen Tests, ausgewählt
nach gemessener Laufzeit:

| Test | Umfang | Laufzeit | Deckt |
|---|---|---|---|
| `test_owner_grant` | 23 | 2,2 s | kein Self-Grant, erlaubte `owner_decision()`-Aufrufstellen, Execute erzeugt keine Freigabe |
| `test_write_lifecycle_repair` | 30 | 3,7 s | Approval-, Expiry- und Consume-Grundinvarianten, Zielangabe, Vorwert |
| `test_bundle_contract` | 14 | 2,8 s | Packaging-Vertrag, vier Negativproben, Leerscan-Schutz des Rechtevorrats |

`test_capability_bridge` (21 Tests, 23,9 s) bleibt bewusst draussen — zu
langsam für jeden Commit. Ebenso draussen: vollständige Suiten,
Zwei-Rechner-Abnahmen, Livetests, TCC, native Vollbuilds. Der vollständige
Packaging-Vertrag läuft weiterhin in `build-product.sh`.

**Wirkung beobachtet, nicht behauptet.** Über `pre-commit run` läuft der Hook
in 14,5 s und meldet `Passed`. Mit einer eingeschleusten `owner_decision()`-
Aufrufstelle in `contacts/application/queries.py` meldet er `Failed` und nennt
die Datei. Der Arbeitsbaum wurde danach wiederhergestellt.

Die Aktivierung (`pre-commit install`) schreibt in das **gemeinsame**
git-dir und wirkt damit auf alle Worktrees. Sie bleibt Eigentümerhandlung und
wurde nicht ausgeführt.

## 9. Nicht angefasst

| Gegenstand | Stand |
|---|---|
| `test_dec_052_ist_registriert` | Vorbestehend rot: das Register nennt „48 akzeptierte Entscheidungen", gezählt werden 62. Testdatei und Register sind zwischen `ff240978` und `b5ddf3b4` unverändert; der Fehler ist architekturunabhängig und nicht durch diesen Block verursacht. Auftragsgemäss nicht repariert. |
| M2-Testkontakt „Reparatur Attrappe" | `M2_CLEANUP_PENDING` — nicht vom Intel aus verändert |
| M2-Backup `20260813T130720Z` | `M2_CLEANUP_PENDING` — auf diesem Rechner nicht vorhanden, nicht automatisch gelöscht |
| Calendar | in diesem Teil nicht berührt |
| `~/Jarvis-Next` | unverändert auf `1f03bfa4` |

## 10. Ausdrückliche Bestätigungen

- Keine produktive Mutation: kein Contacts- und kein Calendar-CREATE/UPDATE/DELETE.
- Keine Schreibfreigabe erzeugt; keine existierte vor oder nach diesem Block.
- Keine neue Fachfunktion, kein neuer Produktumfang.
- Keine Historienumschreibung, kein Wechsel auf den alten Integrationszweig.
- Claude Code hat nicht gepusht.
