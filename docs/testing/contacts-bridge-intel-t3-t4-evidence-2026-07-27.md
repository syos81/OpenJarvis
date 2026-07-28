# Kontakte-Bridge-Spike — Intel-x86_64-T3-/T4-Evidenz (2026-07-27)

**Zweck:** Kontaktfreie Reproduktion und Dokumentation der T3-/T4-Packaging-
und Signierungsprüfung des Swift-Contacts-Sidecars (ADR-0016) auf der
verpflichtenden Produktionsarchitektur **macOS Intel x86_64** (ADR-0018,
DEC-042). Dieses Dokument ist **Spike-Evidenz, keine Kontakte-Modulabnahme**
(15 §7 Regel 4; 19 §7).

**Ausgangscommit:** `d96f9a147986e19a439752ea9201277bac690fef`
(Branch `spike/contacts-bridge-g3a-handoff-2026-07-27`).

Referenzen: `docs/adr/ADR-0016-swift-contacts-bridge.md`,
`docs/adr/ADR-0018-dual-architecture-macos-support.md`,
`docs/personal-jarvis/15-testing-and-quality-gates.md` §7,
`docs/personal-jarvis/19-definition-of-done.md`,
`docs/personal-jarvis/decisions-register.md` (DEC-042).

---

## 1. Status

| Kriterium | Status |
|---|---|
| Intel x86_64 — T3 (ad-hoc) | **bestanden** |
| Intel x86_64 — T4 (zertifikatssigniert, Hardened Runtime) | **bestanden** |
| Echte TCC-Persistenz (Rebuild, Versions-Bump, Verschieben, Quarantäne) | **weiterhin offen** |
| Echte Kontakte-Live-Tests (CRUD, Change History, Unified Contacts) | **weiterhin offen** |

Dieses Dokument belegt **Signatur- und DR-Stabilität sowie einen kontaktfreien
Sidecar-Handshake aus beiden gepackten Apps** — keine TCC-Persistenz und keine
Kontaktoperation. Phase B (echte TCC-Freigabe, CRUD, Change History, Unified
Contacts) ist nicht Gegenstand dieses Dokuments und beginnt erst nach
separater Freigabe und Anlage des isolierten Testbenutzers `jarvisspike`.

## 2. Plattform und Toolchain

| Merkmal | Wert |
|---|---|
| macOS | 12.7.6 (Build 21H1320) |
| Architektur | Intel x86_64 |
| Xcode | 14.2 |
| SDK | macOS 13.1 |
| Swift | 5.7.2 (swiftlang-5.7.2.135.5, clang-1400.0.29.51) |
| Node.js | 24.18.0 |
| npm | 11.16.0 |
| Rust / Cargo | 1.97.0 |
| Python | 3.9.6 — **ausschließlich für den isolierten, kontaktfreien `driver.py`-Protokolltest**; keine produktive Toolchain-Abnahme. **Python exakt 3.12 bleibt für den späteren Kontakte-MASTER verpflichtend** (AV-29, 15 §6). |

## 3. Reproduzierbare Dependency-Schritte

```bash
cd <INTEL-MAC>/Jarvis-Next-Contacts-Spike/frontend
npm ci

cd <INTEL-MAC>/Jarvis-Next-Contacts-Spike/frontend/src-tauri
cargo fetch --locked
```

| Lockfile | SHA-256 vor der Installation | SHA-256 nach der Installation |
|---|---|---|
| `frontend/package-lock.json` | `5f378d9869f563cb1af1df636a345ff865e8f33886046a7d198c0b776704e2c9` | **identisch** |
| `frontend/src-tauri/Cargo.lock` | `376a0b9d00ac43a1c3264870d2209be7e1b18617a81d78f08117e958081d21f4` | **identisch** |

`npm ci` installierte 885 Pakete (886 auditiert). **npm-Auditbefund — nur
berichtet, nicht behoben:** 29 Schwachstellen (2 low, 16 moderate, 11 high);
5 Pakete mit nicht ausdrücklich freigegebenen Install-Skripten
(`core-js`, `esbuild`, `fsevents`, `msw`, `protobufjs`) — der Build lief
davon unbeeinflusst durch. Keine Dependency-Version wurde geändert; kein
`npm update`, kein `cargo update`.

## 4. Build- und Packaging-Befehle (neutrale Pfade)

```bash
# 1. Nativer Intel-Sidecar
cd <INTEL-MAC>/Jarvis-Next-Contacts-Spike/scratch/contacts-spike
TARGET=x86_64-apple-macos12.3 ./build-sidecar.sh
cp build/jarvis-contacts \
   ../../frontend/src-tauri/binaries/jarvis-contacts-x86_64-apple-darwin
chmod +x ../../frontend/src-tauri/binaries/jarvis-contacts-x86_64-apple-darwin

# 2. Gepackte App bauen — ausschließlich --config, NICHT TAURI_CONFIG
cd <INTEL-MAC>/Jarvis-Next-Contacts-Spike/frontend
npx tauri build --bundles app --target x86_64-apple-darwin \
  --config <INTEL-MAC>/Jarvis-Next-Contacts-Spike/scratch/contacts-spike/tauri-spike.conf.json

# 3. T3 (ad-hoc) — erhaltene Kopie des Bundler-Ergebnisses
ditto \
  <INTEL-MAC>/Jarvis-Next-Contacts-Spike/frontend/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/OpenJarvis.app \
  <INTEL-MAC>/Jarvis-Next-Contacts-Spike/scratch/contacts-spike/build/OpenJarvis-T3-adhoc.app

# 4. T4 (Zertifikat) — separate Kopie, von innen nach außen signiert
ditto \
  <INTEL-MAC>/Jarvis-Next-Contacts-Spike/frontend/src-tauri/target/x86_64-apple-darwin/release/bundle/macos/OpenJarvis.app \
  <INTEL-MAC>/Jarvis-Next-Contacts-Spike/scratch/contacts-spike/build/OpenJarvis-T4-signed.app

codesign --force --options runtime --sign "Personal Jarvis Contacts Spike" \
  --identifier de.jarvis.contacts-spike.sidecar \
  OpenJarvis-T4-signed.app/Contents/MacOS/jarvis-contacts

codesign --force --options runtime --sign "Personal Jarvis Contacts Spike" \
  --entitlements <INTEL-MAC>/Jarvis-Next-Contacts-Spike/frontend/src-tauri/Entitlements.plist \
  --identifier com.openjarvis.desktop \
  OpenJarvis-T4-signed.app
```

Der Rust-Release-Build (593 Crates, erstmalig kompiliert) benötigte auf
diesem Intel-Gerät **5 Minuten 26 Sekunden**.

## 5. T3-Befunde (ad-hoc)

| Komponente | Architektur | Mindestversion |
|---|---|---|
| `Contents/MacOS/openjarvis-desktop` | x86_64 | `minos 12.3` |
| `Contents/MacOS/jarvis-contacts` | x86_64 | `minos 12.3` |

- Signaturflags: `flags=0x10002(adhoc,runtime)` (App und Sidecar) —
  **Ad-hoc, zugleich mit Hardened-Runtime-Flag durch den Tauri-Bundler.**
- `codesign --verify --deep --strict --verbose=4`: `valid on disk`,
  `satisfies its Designated Requirement`.
- App-CDHash: `6d4ef47e51e4bcc9f107a0abe7e78d73c9f041fb`
- Sidecar-CDHash: `cd576ec20f874a37925e0f30ca323c8ca501a085`

**Designated Requirements (Wortlaut):**

```
App:     designated => cdhash H"6d4ef47e51e4bcc9f107a0abe7e78d73c9f041fb"
Sidecar: designated => cdhash H"cd576ec20f874a37925e0f30ca323c8ca501a085"
```

Keine `certificate leaf`-Bindung — wie für ein Ad-hoc-Artefakt erwartet.

`spctl -a -vvv -t exec OpenJarvis-T3-adhoc.app` → **`rejected`**. Das ist das
**erwartete Ergebnis** eines lokal gebauten, nicht notarisierten Spike-
Artefakts ohne Apple-Entwicklerzertifikat und ist kein Befund gegen die
Reproduktion.

## 6. T4-Befunde (zertifikatssigniert, Hardened Runtime)

| Komponente | Architektur | Mindestversion |
|---|---|---|
| `Contents/MacOS/openjarvis-desktop` | x86_64 | `minos 12.3` |
| `Contents/MacOS/jarvis-contacts` | x86_64 | `minos 12.3` |

- Signaturflags: `flags=0x10000(runtime)` (App und Sidecar) — Hardened
  Runtime **ohne** `adhoc`.
- `Authority=Personal Jarvis Contacts Spike` (App und Sidecar).
- `codesign --verify --deep --strict --verbose=4`: `valid on disk`,
  `satisfies its Designated Requirement`.
- App-CDHash: `81ea8b4a2343abea7abd9e5a30ec863607944156`
- Sidecar-CDHash: `4df95d09063cbbbc52ef81b611c4f36426e6279d`

**Designated Requirements (Wortlaut):**

```
App:     designated => identifier "com.openjarvis.desktop" and certificate leaf = H"f378c267e1c065e3dbfc07acb7b922c10651255c"
Sidecar: designated => identifier "de.jarvis.contacts-spike.sidecar" and certificate leaf = H"f378c267e1c065e3dbfc07acb7b922c10651255c"
```

Identifier- **und** certificate-leaf-Bindung an das dedizierte Spike-
Zertifikat, wie für T4 verbindlich gefordert.

**Entitlements:**

- App: unverändertes Projekt-Set aus `Entitlements.plist` (7 Schlüssel:
  `app-sandbox=false`, `network.client`, `network.server`,
  `files.user-selected.read-write`, `cs.allow-jit`,
  `cs.allow-unsigned-executable-memory`, `cs.disable-library-validation`).
- **Sidecar: keine Entitlements** (bewusst ohne Entitlements signiert —
  siehe Abschnitt 13).

## 7. Zertifikat (ohne privaten Schlüssel oder Exportdaten)

| Feld | Wert |
|---|---|
| Common Name | `Personal Jarvis Contacts Spike` |
| SHA-256-Fingerprint | `42:4A:30:1C:47:1C:39:58:A9:8A:3A:D1:9F:3F:EA:9C:D2:B5:AC:19:B3:D9:75:9B:79:82:E6:1E:25:63:FB:03` |
| SHA-1-Fingerprint (= certificate-leaf-Wert in den obigen DRs) | `F378C267E1C065E3DBFC07ACB7B922C10651255C` |
| Seriennummer | `01` |
| Gültig von | 2026-07-27 18:09:36 GMT |
| Gültig bis | 2027-07-27 18:09:36 GMT |
| Extended Key Usage | `Code Signing` (critical) |

Kein Produktivzertifikat verwendet (`de.kluender.jarvis`,
`de.kluender.jarvis.credential-helper` blieben unangetastet). Kein privater
Schlüssel, kein Export, keine Übertragung.

## 8. Usage-Descriptions

| Komponente | Text | Nachweis |
|---|---|---|
| App | `Spike-Test: Zugriff auf Kontakte (APP)` | `plutil -extract NSContactsUsageDescription raw Contents/Info.plist` — identisch in T3 und T4 |
| Sidecar | `Spike-Test: Zugriff auf Kontakte (SIDECAR)` | `otool -P Contents/MacOS/jarvis-contacts` — identisch in T3 und T4, **auch nach dem Neusignieren mit Zertifikat und Hardened Runtime** |

Der Diskriminator (E6 des Spike-Plans) bleibt in beiden Bundles intakt.

## 9. G12-Harness (`frontend/src-tauri/src/lib.rs`, temporär, nicht committet)

Vollständiger Patch: `spikes/contacts-bridge-g3a/g12-lib-rs.patch`
(rein additiv, 187 eingefügte Zeilen, 0 Löschungen, reproduzierbar
anwendbar auf `d96f9a1`).

- **Env-Gate:** aktiv ausschließlich bei `JARVIS_CONTACTS_SPIKE_G12=1`;
  ohne die Variable und bei jedem anderen Wert (getestet: `0`) **0**
  G12-Ausgabezeilen — reguläres Startverhalten unverändert.
- **`current_exe()`-Auflösung:** ermittelt das `Contents/MacOS`-Verzeichnis
  der gepackten App und darin den Sidecar `jarvis-contacts`.
- **Handshake:** verwendet ausschließlich die in `PROTOCOL.md`/`driver.py`
  bereits festgelegten Operationen — die unaufgefordert gesendete
  `ready`-Zeile, danach `caps`, `ping`, `shutdown` (Requestformat exakt
  `{"id":<n>,"op":"<name>","params":{}}`).
- **Fester Timeout:** 15 Sekunden je Lesevorgang (`recv_timeout`);
  bei Überschreitung oder jedem Protokollfehler **fail-closed**-Abbruch
  mit Exitcode 2.
- **Zuverlässige Child-Beendigung:** Polling-Schleife bis zur Deadline,
  danach `kill()` + `wait()`, um verwaiste Prozesse auszuschließen.
- **Keine Kontaktoperation:** kein `requestAccess`, kein Öffnen des
  `CNContactStore`, keine `containers`-, `enumerate`-, `changes`-,
  `token`-, `get`-, `create`-, `update`- oder `delete`-Operation, keine
  erfundene Protokolloperation, keine Kontakt-Fachlogik.
- Ausgaben sind ausschließlich technisch und PII-frei (`G12: …`-Präfix).

## 10. Handshake-Ergebnis (T3 und T4, identisch)

```
G12: ready=yes protocol=1 keySetVersion=1 caps=13
G12: authorizationStatus=notDetermined
G12: caps=ok protocol=1 authorizationStatus=notDetermined linkUnlinkSupported=false
G12: ping=ok
G12: shutdown=ok
G12: sidecar-exit=0
G12: RESULT=PASS (kontaktfrei: ready, caps, ping, shutdown)
```

Prozess-Exitcode in beiden Fällen: `0`.

## 11. `authorizationStatus`

| Zeitpunkt | Wert |
|---|---|
| vor Sidecar-Build / Protokolltest | `notDetermined` |
| nach Protokolltest (18/18) | `notDetermined` |
| vor T3-Start | `notDetermined` |
| nach T3-Start | `notDetermined` |
| vor T4-Start | `notDetermined` |
| nach T4-Start | `notDetermined` |

**Zu keinem Zeitpunkt erschien ein TCC-Dialog.**

## 12. Stabilitätsprobe (DR-Verhalten bei Rebuild)

Ein neu gebauter Sidecar (anderer Binärinhalt) ergab:

- **ad-hoc signiert:** `designated => cdhash H"e42b9a0c2aa90aa675756270f2c7ef41add6412e"`
  — **abweichend** von der T3-Bundle-DR (`cd576ec2…`). Die Ad-hoc-DR ist an
  den konkreten `cdhash` gebunden und ändert sich mit dem Binärinhalt bzw.
  den Signierparametern.
- **mit dem Spike-Zertifikat signiert:** `designated => identifier "de.jarvis.contacts-spike.sidecar" and certificate leaf = H"f378c267e1c065e3dbfc07acb7b922c10651255c"`
  — **wortgleich** mit der im T4-Bundle signierten Sidecar-DR.

**Das belegt ausschließlich statische Signatur- und DR-Stabilität bei
Rebuild.** Es ist **keine** Aussage über reale TCC-Persistenz — diese
erfordert eine tatsächlich erteilte Berechtigung und ist Gegenstand von
Phase B (G7, TCC-Matrix) im isolierten Testbenutzer.

## 13. T3-Entitlement-Befund und Empfehlung für den Produktpfad

Der Tauri-Bundler signierte den T3-Sidecar automatisch mit dem **vollen
App-Entitlement-Set** (u. a. `cs.allow-unsigned-executable-memory`,
`cs.disable-library-validation`) — erwartetes Bundler-Verhalten, im
Handoff bereits als Nebenbefund vermerkt. Für T4 wurde der Sidecar
**bewusst ohne Entitlements** signiert, da er keines der App-Entitlements
fachlich benötigt; das ändert die Designated Requirement nicht.

**Spätere Packaging-Anforderung (keine Änderung an DEC-D17, keine
Auslieferungsentscheidung):** Der Contacts-Sidecar sollte im späteren
Produktpfad **keine** App-Entitlements erhalten, sofern nicht für einen
einzelnen Schlüssel ein belegter fachlicher Bedarf nachgewiesen wird. Dies
ist eine Packaging-Empfehlung, keine Festlegung des Auslieferungsformats
(DEC-D17 bleibt unverändert offen).

## 14. Artefakte (nicht versioniert, nicht übertragen)

Alle Pfade relativ zum Spike-Worktree; **keines dieser Artefakte ist Teil
dieses Commits oder eines künftigen Transfers:**

| Relativer Pfad | Typ |
|---|---|
| `scratch/contacts-spike/build/OpenJarvis-T3-adhoc.app` | gepacktes App-Bundle, ad-hoc signiert |
| `scratch/contacts-spike/build/OpenJarvis-T4-signed.app` | gepacktes App-Bundle, zertifikatssigniert |
| `scratch/contacts-spike/build/jarvis-contacts`, `jarvis-contacts-p0`, `JCChangeHistoryShim.o`, `sidecar-Info.plist` | Sidecar-/P0-Binaries, Objektdatei, generierte Plist |
| `frontend/src-tauri/target/` | Rust-Build-Cache |
| `frontend/node_modules/` | npm-Abhängigkeiten (885 Pakete) |
| `frontend/dist/` | Vite-Build-Ausgabe |
| `frontend/src-tauri/binaries/jarvis-contacts-x86_64-apple-darwin` | Sidecar-Kopie im erwarteten Tauri-externalBin-Namen |

Das dedizierte Codesigning-Zertifikat „Personal Jarvis Contacts Spike"
verbleibt ausschließlich im lokalen Schlüsselbund dieses Geräts und wird
nicht exportiert.

## 15. Sicherheitsbestätigungen

- **Kein Kontakt gelesen, erstellt, verändert oder gelöscht.** Keine
  Container-, Gruppen- oder Change-History-Abfrage.
- **Kein TCC-Dialog ausgelöst oder bestätigt.**
- **Kein Testbenutzer erstellt.**
- **Kein Produktivzertifikat verwendet.**
- **Keine Lockfile-Änderung** (SHA-256 vor/nach identisch, siehe Abschnitt 3).
- **Keine Binaries, `.app`-Bundles oder Schlüssel in diesem oder einem
  künftigen Commit** — dieses Dokument sowie die begleitenden Textdateien
  (`g12-lib-rs.patch`, `app-Info.plist`, `tauri-spike.conf.json`) sind reiner
  Text ohne Binärdaten, Zertifikate oder personenbezogene Inhalte.
