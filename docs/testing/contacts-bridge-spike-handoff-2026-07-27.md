# Kontakte-Bridge-Spike G3a — Übergabebericht (2026-07-27)

**Zweck:** Kontrollierte Übergabe des laufenden Swift-Contacts-Bridge-Spikes
(ADR-0016) von diesem Mac auf ein zweites Gerät. Dieser Branch enthält
ausschließlich reproduzierbare Quell- und Werkzeugdateien — keine Binaries,
keine Zertifikate, keine Kontaktdaten, keine TCC-Daten.

**Ausgangscommit:** `4cb82e13b9ede4dd216222fe137a62a17f354678`
(Branch `jarvis/rebuild-v1`, Tag-Vorgänger `personal-jarvis-architecture-v3-2026-07-27`).
Dieser Handoff-Branch zweigt von genau diesem Commit ab; `jarvis/rebuild-v1`
selbst ist unverändert.

Referenz-Plan: `docs/personal-jarvis/17-deferred-decisions.md` (DEC-D01),
`docs/adr/ADR-0016-swift-contacts-bridge.md`.

---

## 1. Bisher bestandene Gates (Phase A, vollständig auf diesem Mac)

| Gate | Ergebnis |
|---|---|
| G0 Git-Gate + Worktree | Isolierter Worktree `<QUELL-MAC>/Jarvis-Next-Contacts-Spike` auf `4cb82e13`; Haupt-Worktree während des gesamten Spikes nachweislich unverändert |
| G1 Toolchain/Zertifikat/Testbenutzer | Swift 6.3.2, SDK 26.5 mit `Contacts.framework` bestätigt; Testbenutzer `jarvisspike` (uid 503, Standardbenutzer) angelegt; Zertifikat „Personal Jarvis Contacts Spike" (selbstsigniert, eigenständig von `de.kluender.jarvis`) erstellt und vertraut |
| **G2 P0-Reachability** | **BESTANDEN** (K1-Gate) |
| **G3 JSON-Lines-Protokoll** | **18/18 bestanden** |
| G4 Usage-String-Nachweis | Beide Diskriminator-Texte technisch belegt |
| G5 Signierung/Packaging | T3 (ad-hoc) und T4 (spike-signiert) gebaut und verglichen |
| G6 Artefakt-Export | nach `/Users/Shared/JarvisContactsSpike/` (dort verblieben, **nicht** Teil dieses Branches) |
| GH Manueller Haltepunkt | erreicht, Anweisungen ausgegeben |
| G7–G13 (Phase B: TCC-Matrix, CRUD, Felder, Change History, Unified Contacts, Bereinigung) | **nicht begonnen** — auf diesem Mac keine einzige Kontakte-Operation ausgeführt |

## 2. P0-Reachability-Ergebnis

Apple markiert `enumeratorForChangeHistoryFetchRequest:error:` **und**
`enumeratorForContactFetchRequest:` als `NS_SWIFT_UNAVAILABLE("")`
(`CNContactStore.h:147,165` im SDK). Der genehmigte minimale ObjC-Shim
(`JCChangeHistoryShim.h`/`.m`, reine Aufrufweiterleitung, keine Fachlogik)
macht beide Methoden aus Swift erreichbar:

- Shim-Symbole sind im Binary nachweisbar (`nm`), `CNFetchResult<...>`
  bridged korrekt (`.value` als Enumerator, `.currentHistoryToken` als `Data`).
- `CNChangeHistoryEventVisitor` ist aus Swift konformierbar (Swift-Namen
  `visit(_:)` je Event-Typ, `event.accept(visitor)` — nicht die ObjC-Namen).
- Build mit explizitem `-target arm64-apple-macos12.3` (nicht der
  Compiler-Default `26.0`); `otool -l` bestätigt `minos 12.3`.

**Ergebnis: K1 (Stopp-Kriterium „Shim reicht nicht") tritt nicht ein.**
Der Spike konnte fortgesetzt werden.

## 3. Protokolltest: 18/18

`driver.py --protocol-test` (kontaktfrei, kein Store-Zugriff) deckte ab:
Handshake, `ping`/`caps`, typisierte Fehler bei unbekannter Operation und bei
Nicht-JSON-Zeilen, Erholung des Kanals danach, `id`-Korrelation, saubere
`stdout` (kein Protokoll-Leck), grazioser Shutdown (`exit 0`), EOF-auf-stdin
beendet den Prozess, kein Hänger nach `kill -9`, erfolgreicher Neustart
danach, 50 aufeinanderfolgende Anfragen ohne Deadlock, `stderr` ohne
PII-Marker. **Alle 18 Prüfungen liefen bei `authorizationStatus=notDetermined`**
— kein TCC-Dialog wurde ausgelöst.

## 4. Bestätigte APP-/SIDECAR-Usage-Strings

Diskriminator-Technik (E6 des Spike-Plans): App und Sidecar tragen bewusst
unterschiedliche `NSContactsUsageDescription`-Texte, damit der spätere
Berechtigungsdialog verrät, welche Info.plist macOS liest.

- **App:** `frontend/src-tauri/Info.plist` → Text „… (APP)". Nachweis nach
  dem Build: `plutil -extract NSContactsUsageDescription raw
  Contents/Info.plist` der gepackten App zeigt exakt diesen Text.
- **Sidecar:** eigene `__TEXT,__info_plist`-Sektion, per Linker-Flag
  `-Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker <plist>`
  eingebettet, Text „… (SIDECAR)". Nachweis: `otool -P
  Contents/MacOS/jarvis-contacts` zeigt diesen Text — **auch nach dem
  Signieren durch den Tauri-Bundler**, an beiden getesteten Signaturen
  (ad-hoc und spike-signiert).

Beide Nachweise liegen vor → der Diskriminator ist ein **gültiges
Testinstrument** (Kriterium aus E6 erfüllt). Nebenbefund: Der Sidecar erhält
aus seiner eingebetteten Plist eine **eigene** Designated Requirement mit
eigenem `CFBundleIdentifier` (`de.jarvis.contacts-spike.sidecar`), getrennt
von der App-Identität — relevant für die noch ausstehende
Attributionsfrage in Phase B.

## 5. Packaging-Befunde

- Repo-Default `signingIdentity: "-"` → **ad-hoc**. Verifiziert:
  `codesign -d -r-` liefert `cdhash H"…"` — reiner Hash, **ändert sich bei
  jedem Rebuild**.
- Mit dem Spike-Zertifikat signiert (`--config
  '{"bundle":{"macOS":{"signingIdentity":"Personal Jarvis Contacts Spike"}}}'`):
  `codesign -d -r-` liefert `identifier "…" and certificate leaf = H"…"` —
  **zertifikatsbasiert**, stabil über Rebuilds hinweg (statisch belegt;
  praktische TCC-Persistenz ist der erste Phase-B-Test).
- Der Sidecar wird beim gepackten Build automatisch signiert und **erbt**
  die App-Entitlements aus `frontend/src-tauri/Entitlements.plist`
  (app-sandbox `false`, JIT, unsigned-executable-memory,
  disable-library-validation, network client/server) — erwartetes
  Tauri-Bundler-Verhalten, im Produktivfall separat zu bewerten.
- Gesamtverifikation `codesign --verify --deep --strict` bestand für beide
  Konfigurationen (T3, T4).

## 6. `TAURI_CONFIG` funktioniert lokal nicht

Der erste Versuch, `externalBin` und `signingIdentity` per Umgebungsvariable
`TAURI_CONFIG` zu setzen (Muster aus `.github/workflows/desktop.yml:256`),
wurde von der lokalen Tauri-CLI **vollständig ignoriert** — der Sidecar fehlte
im Bundle, `createUpdaterArtifacts:false` griff nicht, der Build brach sogar
an einem fehlenden Updater-Signierschlüssel ab.

**Ursache:** `TAURI_CONFIG` ist eine Funktion der GitHub Action
`tauri-apps/tauri-action@v0`, nicht der Tauri-CLI selbst. Lokal (`tauri-cli
2.11.4`) ist ausschließlich die Kommandozeilenoption **`--config` bzw. `-c`**
wirksam (JSON-String, wird mit der Default-Konfiguration gemerged).

**Korrektes Kommando** (siehe Abschnitt 11) verwendet durchgehend `--config`.
Dieser Befund ist unabhängig vom Spike-Ergebnis selbst relevant für jeden
künftigen lokalen Tauri-Build mit Config-Override.

## 7. Übergebene Spike-Dateien (dieser Branch, vollständig)

Alle Pfade relativ zum Repository-Root.

```
scratch/contacts-spike/PROTOCOL.md               (neu, Protokollspezifikation)
scratch/contacts-spike/build.sh                  (Build der P0-Probe)
scratch/contacts-spike/build-sidecar.sh          (Build des vollen Sidecars + Info.plist-Sektion)
scratch/contacts-spike/driver.py                 (Host-Treiber, JSON-Lines, kontaktfreie Protokolltests)
scratch/contacts-spike/phase_b.py                (Phase-B-Ablauf: Preflight, CRUD, Change History, Unified, Cleanup)
scratch/contacts-spike/src/JCChangeHistoryShim.h (ObjC-Shim, Header)
scratch/contacts-spike/src/JCChangeHistoryShim.m (ObjC-Shim, Implementierung — reine Weiterleitung)
scratch/contacts-spike/src/main.swift            (P0-Reachability-Probe)
scratch/contacts-spike/src/sidecar.swift          (voller Kontakte-Sidecar)
docs/testing/contacts-bridge-spike-handoff-2026-07-27.md  (dieser Bericht)
```

Alle zehn Dateien sind reiner Text (Swift, Objective-C, Shell, Python,
Markdown). Keine davon enthält Zertifikate, Schlüssel, echte Kontaktdaten
oder TCC-Daten. Testdaten in `phase_b.py` sind synthetisch
(`ZZZ-JarvisTest-*`, E-Mail-Domain `@example.invalid`).

**Ausdrücklich nicht Teil dieser Übernahme:** die vier in Phase A temporär
im Spike-Worktree vorgenommenen Änderungen an bestehenden Tauri-Dateien
(`frontend/src-tauri/src/lib.rs`, `frontend/src-tauri/Info.plist`,
`frontend/src-tauri/binaries/jarvis-contacts-aarch64-apple-darwin`,
`frontend/tsconfig.tsbuildinfo`) — diese bleiben **unstaged** im
Spike-Worktree liegen und werden **nicht** committet (s. Abschnitt 9).

## 8. Ausdrücklich nicht übertragene Artefakte

| Kategorie | Beispiel | Grund |
|---|---|---|
| Kompilierte Binaries/Objektdateien | `scratch/contacts-spike/build/*` (`jarvis-contacts`, `jarvis-contacts-p0`, `JCChangeHistoryShim.o`) | nicht reproduzierbar-quellcodegleich zu übergeben; auf dem Zielgerät neu zu bauen |
| Gepackte App-Bundles | `OpenJarvis-T3-adhoc.app`, `OpenJarvis-T4-signed.app` | enthalten signierte Binaries, Bundle-Struktur; kein Text |
| Zertifikat und privater Schlüssel | „Personal Jarvis Contacts Spike" (Schlüsselbund) | darf laut Vorgabe nicht exportiert werden; **muss auf dem Zielgerät neu erstellt werden** |
| TCC-Daten | `~/Library/Application Support/com.apple.TCC/TCC.db`, `tccutil`-Zustand | Systemberechtigungsdaten, nicht portabel und nicht zu exportieren |
| Kontakt-Snapshots/Testdaten-Exporte | (keine erzeugt — Phase B lief nicht) | Phase B wurde auf diesem Mac nicht ausgeführt |
| Alles unter `/Users/Shared/JarvisContactsSpike/` | exportierte `.app`-Kopien, `ANWEISUNGEN.md`, Kopien von `driver.py`/`phase_b.py` | liegt außerhalb des Repositories, teils Binaries; **nicht ungeprüft übernommen** — die Quelldateien werden stattdessen frisch aus dem Worktree in diesen Branch übernommen |
| Temporäre Tauri-Integrationsänderungen (Phase A) | `lib.rs`-Diff, `Info.plist` (App-Seite), Sidecar-Binary in `binaries/`, `tsconfig.tsbuildinfo` | gehören zum Nachweis „Betrieb aus der App" auf *diesem* Mac, sind aber keine eigenständigen reproduzierbaren Spike-Quellen; bleiben unstaged, nicht Teil des Handoff-Commits |
| Testbenutzer `jarvisspike` | Systemkonto | kein Dateiartefakt, nicht exportierbar |

## 9. Noch offene Phase-B-Tests (auf diesem Mac: null durchgeführt)

- G7 TCC-Matrix (T2/T3/T4, inkl. Rebuild-Persistenz, `CFBundleVersion`-Bump,
  Verschieben der `.app`, Quarantäne-Probe)
- G8 CRUD (Create/Read/Update/Delete an `ZZZ-JarvisTest-`-Datensätzen)
- G9 Feldabdeckung (E-Mails, Telefone, Adressen, Geburtstag, Organisation,
  Thumbnail, Labels, Notizen-Sonderprüfung)
- G10 Change History (6 Mutationen, Echo-Unterdrückung, Token-Invalidierung,
  Voll-Diff-Fallback mindestens einmal ausgeführt)
- G11 Vereinheitlichte Kontakte (Schreibregel W1 vs. Hazard-Probe W2,
  Identifier-Stabilität)
- G12 Betrieb aus der gepackten App im Testbenutzer (Sidecar-Start via
  `current_exe()`, Handshake-Nachweis)
- G13 Bereinigung und PASS/FAIL-Gesamtentscheidung

## 10. Vollständige Start- und Buildbefehle für das MacBook

Arbeitsverzeichnis nach dem Auschecken dieses Branches auf dem Zielgerät.

```bash
# 1. Voraussetzungen prüfen (kein Xcode nötig, CLT genügt)
xcode-select -p
swiftc --version
xcrun --show-sdk-path
ls "$(xcrun --show-sdk-path)/System/Library/Frameworks/Contacts.framework"

# 2. P0-Reachability-Probe bauen und ausführen (kontaktfrei)
cd scratch/contacts-spike
chmod +x build.sh build-sidecar.sh
./build.sh
./build/jarvis-contacts-p0                 # ohne --run-fetch: kein Store-Zugriff

# 3. Vollen Sidecar bauen (inkl. eingebetteter Info.plist-Sektion)
./build-sidecar.sh
otool -P build/jarvis-contacts | grep -A1 NSContactsUsageDescription   # G4-Nachweis

# 4. Kontaktfreie Protokolltests
python3 driver.py --protocol-test              # Ziel: 18/18, authorizationStatus=notDetermined

# 5. Neues Spike-Zertifikat auf DIESEM Gerät erstellen (siehe Abschnitt 12)
#    danach:
codesign --force --options runtime --sign "<Zertifikatsname>" build/jarvis-contacts
codesign -d -r- build/jarvis-contacts          # muss "certificate leaf" zeigen, kein cdhash

# 6. Gepackte App bauen — WICHTIG: --config, NICHT TAURI_CONFIG (siehe Abschnitt 6)
cd ../../frontend
npm ci
# T3 (ad-hoc, Vergleichskonfiguration):
npx tauri build --bundles app --target aarch64-apple-darwin \
  --config '{"bundle":{"externalBin":["binaries/jarvis-contacts"],"createUpdaterArtifacts":false}}'
# T4 (spike-signiert, Primärkonfiguration):
npx tauri build --bundles app --target aarch64-apple-darwin \
  --config '{"bundle":{"externalBin":["binaries/jarvis-contacts"],"createUpdaterArtifacts":false,"macOS":{"signingIdentity":"<Zertifikatsname>"}}}'

# 7. Vor Schritt 6 muss der Sidecar an folgender Stelle liegen:
#    frontend/src-tauri/binaries/jarvis-contacts-aarch64-apple-darwin  (chmod +x)
#    und folgende temporäre Dateien müssen manuell neu angelegt werden
#    (siehe Abschnitt 8 — sie sind NICHT Teil dieses Branches):
#      - frontend/src-tauri/Info.plist  (App-Usage-String "(APP)")
#      - der env-gatete Block in frontend/src-tauri/src/lib.rs für G12
#        (Quelltext ist im Handoff-Bericht/Plan dokumentiert, nicht im Branch)

# 8. Vergleich der Designated Requirements (statischer Kernbeleg, reproduzierbar)
codesign -d -r- <T3.app>                              # erwartet: cdhash H"…"
codesign -d -r- <T4.app>                               # erwartet: identifier … certificate leaf H"…"
codesign -d -r- <T4.app>/Contents/MacOS/jarvis-contacts

# 9. Phase B — NUR in einem separaten macOS-Testbenutzer, NICHT im Hauptbenutzer:
python3 phase_b.py                    # bricht vor jedem Schreibvorgang ab,
                                       # falls fremde Kontakte gefunden werden
```

## 11. Neu zu erstellen auf dem MacBook

Aus Sicherheitsgründen wurden **nicht** übertragen und müssen dort neu
angelegt werden:

- **Separater macOS-Testbenutzer** (Standardrechte, kein Admin, keine
  iCloud-Kontaktsynchronisierung, leeres Adressbuch verifizieren).
- **Neues, dediziertes selbstsigniertes Codesigning-Zertifikat**
  ausschließlich für den Spike auf diesem Gerät (Schlüsselbundverwaltung →
  Zertifikatsassistent → „Selbstsigniertes Root-Zertifikat" → Typ
  „Codesignatur" → „Immer vertrauen"). Das auf diesem Mac erstellte
  Zertifikat „Personal Jarvis Contacts Spike" ist **gerätegebunden** und
  wurde nicht exportiert.
- **TCC-Freigaben** entstehen zwangsläufig neu bei der ersten Store-Anfrage
  auf dem Zielgerät; es gibt nichts zu übertragen oder zurückzusetzen.

## 12. Bereinigungs- und Sicherheitsregeln (gelten unverändert für das Zielgerät)

Aus dem ursprünglichen Spike-Plan, ohne Abschwächung:

- Store-Mutationen ausschließlich mit Präfix `ZZZ-JarvisTest-`; der Sidecar
  verweigert alles andere technisch (siehe `PROTOCOL.md`, Abschnitt
  „Spike-Sicherheitsrail").
- Echte Schreib-/Lösch-/Token-Reset-Tests **ausschließlich** im separaten
  Testbenutzer, niemals im Hauptbenutzer.
- Preflight bricht **vor jedem Schreibvorgang** ab, wenn fremde
  (nicht-`ZZZ-JarvisTest-`) Kontakte im Adressbuch gefunden werden.
- Bei Scheitern eines Kill-Kriteriums (K1–K9 des Spike-Plans): **Stopp,
  kein automatischer PyObjC-Wechsel**, erneute Freigabe einholen.
- Nach Abschluss von Phase B: alle Testkontakte löschen und Löschung über
  Zählstände verifizieren; `tccutil reset AddressBook` für die verwendeten
  Bundle-Identifier; Ergebnisse sichern, bevor `/Users/Shared/…`-Kopien
  entfernt werden.
- Kein Commit von Binaries, `.app`-Bundles, Zertifikaten, privaten
  Schlüsseln, TCC-Daten oder personenbezogenen Logs — auch auf dem
  Zielgerät nicht.

## 13. Aktueller PASS-/FAIL-Stand

| Kriterium | Stand |
|---|---|
| P0 Reachability | **PASS** |
| Protokoll (JSON-Lines, Backpressure, Restart, Shutdown) | **PASS** (18/18) |
| Usage-String-Diskriminator gültig | **PASS** (beide Texte technisch nachgewiesen) |
| Packaging (Build, Signierung, Bundle-Struktur) | **PASS** für T3 und T4 |
| TCC-Stabilität (Kernkriterium) | **NOCH NICHT GEPRÜFT** — statischer Beleg (Designated Requirement) liegt vor, die praktische Persistenz über Rebuilds/Neustarts ist der erste Phase-B-Test auf dem Zielgerät |
| Lesen/Schreiben/Löschen (CRUD) | **NOCH NICHT GEPRÜFT** |
| Feldabdeckung | **NOCH NICHT GEPRÜFT** |
| Change History / Fallback-Diff | **NOCH NICHT GEPRÜFT** (Reachability ja, Laufzeitverhalten nein) |
| Vereinheitlichte Kontakte | **NOCH NICHT GEPRÜFT** |
| Betrieb aus der gepackten App | Statisch vorbereitet (Sidecar korrekt gebündelt und signiert); **Laufzeitnachweis noch nicht erbracht** |

**Gesamturteil: Spike läuft, kein Kill-Kriterium ausgelöst, kein PASS/FAIL
für den Gesamt-Spike möglich, bevor Phase B abgeschlossen ist.**

## 14. Bestätigung

**Es ist noch kein Kontakte-Produktcode entstanden.** Alle übergebenen
Dateien sind Spike-Artefakte (temporär, ADR-0016 als Grundlage) — kein
`ContactsAdapter`-Vertrag, kein Domänenmodell, keine Datenbank, keine API,
keine Modul-UI, kein CommandBus wurden berührt. Der Hauptbranch
`jarvis/rebuild-v1` blieb während des gesamten Spikes unverändert (Nachweis:
`git status`/`git diff` im Haupt-Worktree leer, HEAD durchgehend
`4cb82e13`).
