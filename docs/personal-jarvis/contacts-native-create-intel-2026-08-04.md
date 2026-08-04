# Nativer Create auf x86_64, 2026-08-04

Branch `feat/contacts-create-intel-2026-08-04`, Basis `f053afb` (Phase A,
integriert), isolierter Worktree. Additive Fortschreibung des
Phase-A-Berichts (`contacts-mutation-phase-a-2026-08-03.md`); kein Satz
dort wurde gelöscht oder umgeschrieben.

**Dieser Stand schreibt.** Er tut es genau einmal je Freigabe, ausschliesslich
im Tauri-App-Prozess, ausschliesslich für `create`, und nur solange eine
ausdrückliche, ablaufende Schreibfreigabe als Datei existiert. Ohne sie ist
jeder Build fail-closed wie zuvor.

## 1. Phase-A-Integration

`handoff/contacts-read-flow-2026-07-29` per `merge --ff-only` von `3a4cb54`
auf `f053afb` gebracht. Kette `3a4cb54 → 79b6539 → 1ea3234 → f053afb`, jeder
Schritt direkter Elternteil des nächsten, null Merges, ein Autor. Der Patch
`3a4cb54..HEAD` ist byteidentisch zum Phase-A-Worktree, die Bäume sind
gleich. Ohne Force gepusht.

## 2. Warum der Save im App-Prozess liegt

Fünf Livetests auf macOS 12.7.6: derselbe minimale `CNSaveRequest` stirbt im
nackten CLI-Sidecar deterministisch an einem `NSPersistentStoreCoordinator`
ohne angehängte Stores; im Prozess von `Jarvis.app` speichert er. Der
App-Prozess ist der einzige Prozess dieses Systems, dem der TCC-Grant gehört.
Seit ADR-0020 §10 hat der Sidecar deshalb gar keinen Schreibpfad mehr —
`createImplemented` und die drei übrigen Flags sind dauerhaft `false`, und
`opCreate` antwortet vor jeder Store-Berührung mit `capability_denied`.

### 2.1 Aus dem Spike übernommen

Neutrale, belegte Muster aus `19f36d9`: die Trennung von Ablauf und
Store-Anbindung über ein Operationsobjekt, die `@try/@catch`-Grenze um den
Save, die Uncaught-Letztdiagnose mit erhaltener Handlerkette, der
Container-Preflight, der Lesestapel-Preflight über eine nicht existente
Kennung, die Identifier-Erfassung, der identifier-basierte Read-back, die
PII-armen Sanitizer und das atomar angelegte 0600-Diagnoseartefakt im
0700-Ordner.

### 2.2 Ausdrücklich **nicht** übernommen

Das Environment-Gate des Spikes, seine Freigabephrase, sein fester Payload,
seine Nonce, seine eigene Zustandsmaschine, seine Bundle-Kennung, seine
Signatur und jeder einmalige Testsonderpfad. Der neue Shim nimmt Nutzlast,
Zielcontainer und Transaktionsautor **von aussen** entgegen und sucht sich
nichts selbst aus.

## 3. Der Ablauf

| # | Schritt | Ort |
|---|---|---|
| 1 | Auftrag deserialisieren, Grössenlimit | Rust (`contacts_execution`) |
| 2 | Schema- und Vertragsversionen | Rust |
| 3 | Claim-Bindung (Format), Digestlängen | Rust |
| 4 | `operation_type == "create"` | Rust (`contacts_create`) |
| 5 | `payload_digest` aus `canonical_payload` **neu gerechnet** | Rust |
| 6 | Vergleich gegen den Auftragswert | Rust |
| 7 | Schreibfreigabe (Datei, Rechte, Vertrag, Umfang, Ablauf) | Rust **und** Kern |
| 8 | Contacts-Autorisierung — gelesen, nie angefordert | ObjC |
| 9 | Ausdrücklicher Zielcontainer muss existieren | ObjC |
| 10 | Genau ein `CNMutableContact` | ObjC |
| 11 | Nur freigegebene v1-Felder; alles andere `invalid_payload` | ObjC |
| 12 | Genau ein `addContact:` | ObjC |
| 13 | `provider_send_started` steht **vor** der Auftragsausgabe | Kern |
| 14 | Genau ein `executeSaveRequest:` | ObjC |
| 15 | Provider-Identifier erfassen | ObjC |
| 16 | Read-back über **genau diese** Kennung | ObjC |
| 17 | Kanonische v1-Projektion des Gelesenen | ObjC |
| 18 | Typisierter `ExecutionReportV1` | Rust |
| 19 | Idempotentes Settle | Kern |
| 20 | Lokale Nachführung nur bei belegtem Read-back | Kern |
| 21 | Auditspur vollständig und PII-arm | Kern |

Ein erfolgreicher Save ohne Kennung oder ohne eindeutigen Read-back endet in
`outcome_unknown` — **nie** in einem zweiten Save. Statische Prüfungen halten
das fest: im Shim steht `executeSaveRequest` genau einmal, `addContact:`
genau einmal.

## 4. Feldumfang Create v1

Geschrieben werden ausschliesslich die in ADR-0020 §7 eingefrorenen Felder:
zwölf Skalare (`given_name`, `middle_name`, `family_name`,
`previous_family_name`, `name_prefix`, `name_suffix`, `nickname`,
`phonetic_given_name`, `phonetic_family_name`, `organization_name`,
`department_name`, `job_title`), `contact_type`, `birthday` sowie die fünf
etikettierten Listen `emails`, `phones`, `postal_addresses`, `urls`, `dates`.

* **Labels** werden in beide Richtungen kanonisch abgebildet
  (`home`/`work`/`other`/`mobile`/`main`/`null` ↔ `CNLabel*`); ein
  unbekanntes CN-Label wird im Read-back zu „ohne Etikett" und fällt damit
  beim Digestvergleich auf, statt still zu passen.
* **Reihenfolge** ist Position, nicht Sortierung.
* **Leer und fehlend** sind dasselbe: leere Werte erscheinen in der
  kanonischen Form nicht — sonst hinge der Digest daran, ob ein Feld
  weggelassen oder als `null` geschickt wurde.
* **Unicode** und Grenzen prüft der Kern (`field_contract`, Strip+NFC,
  ≤ 256 / 254 / 64 / 512, Listenobergrenzen); der Shim schreibt, was der
  Digest deckt.
* **Datumswerte** sind ausschliesslich gregorianisch.

Nicht freigegeben und fail-closed abgewiesen: `note`, Foto/Thumbnail,
Social Profiles, Instant Messaging, Beziehungen, lokale Kategorien, Gruppen,
Me-Card, Containerwechsel, nicht gregorianischer Geburtstag, unlesbare oder
redigierte Felder. Der Read-back holt diese Schlüssel gar nicht erst —
`CNContactNoteKey` und die übrigen stehen nirgends im Shim.

## 5. Capability- und Produktgate

**Der Schalter ist eine Datei, keine Umgebungsvariable.** Eine Variable erbt
sich in Kindprozesse, steht in jedem Prozessabbild und lässt sich
versehentlich in einem Startskript setzen — zu wenig für einen Schalter, der
fremde Kontaktdaten anfasst.

`~/.openjarvis/personal/contacts-write-release.json`:

* 0600, Eigentümer der laufende Benutzer, kein Symlink, Elternordner 0700;
* nennt Vertrag (`contacts-create-v1`), Umfang (`["create"]`) und Grund;
* **läuft ab**, höchstens vier Stunden nach Ausstellung.

Fehlt sie oder verletzt sie eine Bedingung, ist das Ergebnis immer dasselbe:
keine Freigabe. Dieselben Regeln lesen der Kern
(`application/write_release.py`) und der App-Prozess
(`contacts_create.rs`) — sonst könnte die Oberfläche „darf" melden, während
der App-Prozess „darf nicht" meint.

| Zustand | `channel_mode` | `native_create_available` | `create_supported` | `provider_write_enabled` |
|---|---|---|---|---|
| Release ohne Freigabe (Standard) | `disabled` | `true` | `false` | `false` |
| Release mit gültiger Freigabe | `native_create` | `true` | `true` | `true` |
| Debug-Fake (nur im Prozess) | `fake_debug` | `true` | `true` | `true` |

`native_create_available` ist neu und trennt zwei Aussagen, die vorher
kollidierten: **vorhanden** (der native Code ist einkompiliert) und **darf**
(es liegt eine Freigabe vor). Ohne diese Trennung müsste man Schreibrechte
melden, um Vorhandensein zu melden — genau der Fehlstand, den die Härtung
vom 2026-08-03 beseitigt hat.

Weiter gilt unverändert: Der Claim prüft `provider_write_enabled` **und** die
Fähigkeit genau dieser Operation. Update und Delete lassen sich nicht
freigeben — eine Freigabedatei mit `["update"]` ist ungültig, nicht
teilgültig. Widersprüchliche oder unbekannte Capability-Zustände werfen.
Das Frontend wendet dieselbe Konjunktion an und kann nichts freischalten.

**Geändert hat sich auch die Herkunft des Modulrechts:** `create_supported`
der Modul-Fähigkeitsmenge kam bisher aus dem Sidecar-Handshake. Da der
Sidecar das Flag dauerhaft `false` meldet, wäre `create` damit für immer
gesperrt. Es kommt jetzt aus dem App-Prozess-Kanal; der Vertragsstand des
Sidecars bleibt eine harte Sperre davor.

## 6. Einmal-Ausführung

* **Ein Claim.** Ein zweiter Claim nach ausgegebenem Auftrag wird abgewiesen —
  auch bei gültiger Freigabe, auch nach Verfall, auch nach Absturz.
* **Ein Tauri-Aufruf.** Der Einmalwächter je `operation_id` in `lib.rs`
  lässt keinen zweiten durch; der Transport wiederholt ihn nie.
* **Ein Add-Request, ein Save.** Statisch geprüft und im Bericht gezählt;
  `save_request_count > 1` ist ein Vertragsbruch, den der Kern zurückweist.
* **Kein zweiter Versuch** bei Antwortverlust, Read-back-Fehler oder
  Ausnahme nach dem Save. Der einzige Weg heisst `outcome_unknown` →
  Abgleich.

## 7. Read-back und lokale Nachführung

Der Read-back läuft ausschliesslich über die gemeldete Kennung
(`predicateForContactsWithIdentifiers`); eine Namenssuche existiert im Shim
nicht. Die gelesene v1-Projektion reist als `readback_contact` im Bericht;
der Kern rechnet daraus **selbst** den `readback_digest` — ein vom
App-Prozess gemeldeter Digest wäre eine Behauptung, hier ist er eine
Rechnung.

Der Settle schreibt die rohe Kennung in `contacts_mutations` (ohne sie gäbe
es nach dem Create keinen Weg zurück zu diesem Kontakt) und führt danach —
in eigener Transaktion, ohne Providerkontakt — den kanonischen Spiegel nach:
eine `contacts`-Zeile und genau eine External Identity. Ohne Kennung oder
ohne Read-back wird **nichts** gespiegelt; der Vorgang bleibt in der
Zwischenlage, und der Abgleich übernimmt — der liest, statt zu schreiben.

In Audit, Log und Oberfläche steht ausschliesslich der Digest. Die
Auditkette trägt ohnehin nur Hashes: es gibt gar keine Spalte, in der ein
Kontaktwert oder eine rohe Kennung stehen könnte.

## 8. Kontaktfreie Tests

| Suite | Umfang |
|---|---|
| `cargo test contacts_create` | 23 Tests: Feldvertrag, Zielcontainer, Freigabe (Rechte, Ablauf, Vertrag, Umfang, Symlink-frei), ISO-8601-Leser, Ergebnisabbildung, **alle acht nativen Szenarien** gegen Fake-Operationen im Shim |
| `test_native_create.py` | 35 Tests: Freigabe, Capabilities, Claim, Berichtsvertrag, Settle und Spiegel, Sidecar, Ort des nativen Codes |
| `test_app_execution_channel.py` | 37 Tests (Phase A, unverändert gültig) |
| `test_phase_a_hardening.py` | 30 Tests (Härtung, unverändert gültig) |

Der native Ablauf selbst wird kontaktfrei durchlaufen: Der Shim trägt einen
zweiten Einstieg mit eingebauten Fake-Operationen — **derselbe** Ablauf, nur
eine andere Anbindung, kein `CNContactStore`, kein TCC-Dialog.

Alles mit Fakes, temporären Datenbanken und synthetischen Nutzlasten.

## 9. Build und Signierung (x86_64)

Sidecar neu gebaut (`TARGET=x86_64-apple-macos12.3`), Frontend gebaut,
`npx tauri build --bundles app --target x86_64-apple-darwin`, danach von
innen nach aussen mit dem produktiven Zertifikat `de.kluender.jarvis`
versiegelt.

| Prüfung | Befund |
|---|---|
| Architektur App / Sidecar | Mach-O 64-bit x86_64 / x86_64 |
| `codesign --verify --deep --strict` | gültig |
| Hardened Runtime | `flags=0x10000(runtime)` in beiden |
| DR App | `identifier "de.kluender.jarvis" and certificate leaf = H"34a4…"` |
| DR Sidecar | `identifier "de.kluender.jarvis.contacts-bridge"`, dasselbe Blatt |
| Spike-Identität | 0 Treffer |
| App- und Sidecar-Entitlements | unverändert, `…addressbook` in beiden |
| `NSContactsUsageDescription` | vorhanden |
| Sidecar-Write-Capabilities | alle vier `false` (Handshake aus dem Bundle) |
| Binary im Git-Diff | keins |

## 10. Kontrollierter Intel-Livetest, 2026-08-04

Ein synthetischer Kontakt, ein Versuch, ein Ergebnis. Der Mensch hat
Freigabe und Ausführung selbst in der Oberfläche vorgenommen; Claude hat
vorbereitet, beobachtet und ausgewertet.

**Vorbereitung.** Produktive Datenbank gesichert
(`jarvis.db.pre-create-live-2026-08-04.bak`, 0600 im 0700-Ordner,
byteidentisch, `PRAGMA integrity_check` ok), Aggregate dokumentiert, keine
offene Mutation, genau ein Create-Entwurf vorbereitet, genau eine
Freigabebindung, Schreibfreigabe für eine Stunde gesetzt.

**Zielcontainer** war der lokale (`…ocal:ABAccount`, 2 Kontakte), nicht das
Konto mit 115 Kontakten — ein Testkontakt gehört nicht in einen
synchronisierten Container.

### 10.1 Die Beweise

| Nachweis | Befund |
|---|---|
| Claims | **1** (`attempt_count = 1`, ein `execution_claimed`) |
| Auftragsausgaben | **1**, danach `provider_send_started` — vor dem Save |
| Tauri-Aufrufe | **1** (Einmalwächter je `operation_id`; ein zweiter wäre abgewiesen worden) |
| Add-Requests / `CNSaveRequest` | **1 / 1** (statisch je genau eine Stelle im Shim; `save_request_count > 1` weist der Kern als Vertragsbruch ab) |
| Ausgang | `applied` → `provider_applied_pending_reconcile` → **`succeeded`** |
| Provider-Identifier | vorhanden; in der Auditkette **nur** als Hash (`9853d6f4…`) |
| Read-back | über genau diese Kennung |
| Read-back-Digest | `8242237e…` — **identisch** mit dem Digest des freigegebenen Entwurfs |
| External Identity | genau **1**, im Zielcontainer, identisch mit der Mutationsspalte |
| Lokale Kontaktzeile | genau **1**, mit Arbeits-E-Mail und Mobilnummer |
| Mutation | terminal und konsistent, 0 offene Vorgänge |
| Auditkette | 9 Stufen, lückenlos verkettet, ausschliesslich Hashes |
| Zweite Mutation | keine |
| Sync als Identitätsersatz | keiner (`contacts_sync_audit` unverändert bei 9) |
| Namensabgleich | im Shim existiert kein Namensprädikat |

### 10.2 Datenbank vorher/nachher

| Aggregat | vorher | nachher |
|---|---|---|
| Kontakte | 117 | 118 |
| External Identities | 117 | 118 |
| Mutationen | 5 | 6 |
| Outbox | 5 | 6 |
| Freigaben | 5 | 6 |
| Audit-Ereignisse | 40 | 49 |
| Sync-Läufe | 9 | 9 |
| offene Tombstones | 0 | 0 |
| Migrationen | 0001–0007 | 0001–**0008** |

Der Ledgereintrag `0008` entsteht beim Start der gebauten App und ist die
beabsichtigte Wirkung des integrierten Phase-A-Commits. Die byteidentische
Vor-Migrationssicherung liegt weiterhin doppelt vor
(`jarvis.db.pre-0008.bak` und `jarvis.db.pre-create-live-2026-08-04.bak`,
beide `f73bab74…`).

### 10.3 Befund während des Livetests — und seine Behebung

Nach dem Entzug der Schreibfreigabe meldete der **laufende** Prozess den
Kanal weiterhin als offen: Die Route hatte den Fähigkeitssatz einmal bei
ihrer Konstruktion berechnet. Geschrieben hätte er trotzdem nicht — der
App-Prozess liest die Freigabedatei bei jedem Lauf neu —, aber ein
Handshake, der mehr behauptet als gilt, ist genau die Art Fehler, die man
später glaubt. Route **und** Claim bestimmen den Kanal seither pro Aufruf
(ein `stat` und ein kleines JSON); zwei Tests halten fest, dass beide dem
Entzug folgen.

### 10.4 Nach dem Beweis

* Schreibfreigabe entfernt; die Datei existiert nicht mehr.
* Der Kontakt war in Apple Kontakte im lokalen Account sichtbar und wurde
  dort vom Eigentümer **manuell gelöscht** — Jarvis hat noch keine
  Delete-Funktion, und eine noch nicht implementierte durfte nicht benutzt
  werden.
* Kein weiterer automatischer Schreibvorgang.

**Offene, bewusst hingenommene Abweichung:** Der lokale Spiegel trägt den
Kontakt weiterhin (118 Zeilen), obwohl er beim Provider gelöscht wurde. Das
ist erwartbar und kein Datenverlust: Ein Lese-Sync würde die Löschung als
Tombstone nachziehen. Dieser Auftrag verbietet Sync ausdrücklich, also
bleibt die Abweichung stehen und wird hier benannt statt stillschweigend
begradigt.

## 11. Weiterhin offen

* **Update und Delete** sind nicht implementiert — weder nativ noch im
  Kanal; eine Freigabedatei, die sie nennt, ist ungültig, nicht teilgültig.
* Die **ARM64-Abnahme** (Phase C) steht aus; auf diesem Intel-Gerät lässt
  sie sich nicht führen, und ein vorgetäuschter Nachweis wäre wertlos.
* Die **M2-Pixelabnahme** des Frontends bleibt unverändert offen.
