# Calendar — x86_64 auf dem aktuellen Produktstand, 2026-08-16

**Lane:** Risk Lane (produktiver Kalender-Schreibpfad, nativer Plattformnachweis).
**CURRENT_PRODUCT_BASE:** `042eafceb797e616368d700c843489784b1364d2`
— mechanisch als HEAD von `verify/contacts-repair-x86_64-2026-08-13` nach der
Contacts-x86_64-Closure bestimmt, vom Eigentümer gepusht.
**Historischer Evidence-Anchor:** `22887d229e9a614961af8931b767d2f23966672d`
(Intel-Write-Enablement, Livelauf vom 2026-08-11).
**Worktree:** `~/Jarvis-Next-Calendar-Intel-Closure`,
Branch `verify/calendar-x86_64-current`.
**Regelquelle:** `docs/governance/openjarvis-dauerregeln.md` bei
`3ca01ebcd3b39ace937e135f8588d85fa311224b`.
**Rechner:** Intel i7-6920HQ, macOS 12.7.6, x86_64 nativ, Benutzer
`lukasklunder`. `~/Jarvis-Next` unverändert auf `1f03bfa4`.

> Aggregierte Angaben. Keine Termininhalte, keine Kalendernamen, keine
> Providerkennungen im Klartext.

---

## 1. Der write-relevante Diff — vollständig, nicht nach Dateinamen

Verglichen wurde `22887d` gegen `CURRENT_PRODUCT_BASE` über die **gesamte
transitiv write-relevante Kette**, nicht nur über Dateien mit `calendar` im
Namen: `src/personaljarvis/calendar/**`, `base/approvals.py`,
`frontend/src-tauri/src/**`, `frontend/src-tauri/objc/**`, `Cargo.toml`,
`tauri.conf.json`, alle `*.entitlements`, `frontend/src-tauri/scripts/**`,
`frontend/src/personal/calendar/**`, `frontend/src/core/**`.

Sechs Dateien haben sich geändert:

| Datei | Klasse | Semantik |
|---|---|---|
| `scripts/build-product.sh` (neu) | nur Packaging | Bauorchestrierung, kein Schreibverhalten |
| `scripts/reseal-contacts-sidecar.sh` | nur Packaging | Siegelung |
| `core/ownerGrant.test.ts` (neu) | nur Tests | — |
| `base/approvals.py` | gemeinsamer Approval-Kern | **strenger** (§2) |
| `calendar/mutations/service.py` | Calendar-Produktsemantik | **strenger** — eine Aufrufstelle (§2) |
| `core/writeAdapter.ts` | Command-Bar-Wiring | Änderung **vollständig im Kontaktzweig**; der Kalenderzweig ist bytegleich |

**Unverändert** — und das ist der Kern der Aussage:
`calendar/api.py`, `calendar/mutations/contracts.py`, `calendar/bridge/**`,
`calendar/domain.py`, `calendar/lifecycle.py`, `calendar/repositories.py`,
`frontend/src-tauri/src/calendar_write.rs`, `objc/JCCalendarWrite.{h,m}`,
das **gesamte** `frontend/src/personal/calendar/**`, `core/writePort.ts`,
`core/writeResolver.ts`, `core/commandRouter.ts`, Entitlements,
`tauri.conf.json`, `Cargo.toml`.

Der native EventKit-Pfad, Fingerprint, Claim, Re-Read, Complete/Audit und das
Calendar-Produktwiring sind also nicht bloss ähnlich, sondern **byteidentisch**
zum Stand des historischen Livelaufs.

## 2. Warum die geänderte gemeinsame Infrastruktur äquivalent ist

`ApprovalStore.grant()` verlangte bis 2026-08-13 einen `decision_actor: str`
und prüfte eine Denylist. Heute verlangt es eine gesiegelte `OwnerDecision`;
ein String wirft. `owner_decision()` weist zusätzlich leere und maschinelle
Ursprünge weiter ab. Das ist eine **Obermenge** der alten Prüfung — strenger,
nie schwächer.

`Approval.effective_state()` ist rein additiv: ein Leser rechnet die Zeit ein.
`consume()` ist zwischen `22887d` und `CURRENT_PRODUCT_BASE` **bytegleich**
(76 Zeilen beidseitig, `diff` leer) — die Fail-closed-Sperre des
Ausführungswegs hat sich nicht verändert.

`calendar/mutations/service.py` ändert genau eine Zeile im Freigabeschritt:
`grant(decision_actor=…)` → `grant(decision=owner_decision(…))`. Anpassung
eines Aufrufers an die strengere Grenze, keine neue Calendar-Funktion.

Daraus: **`CALENDAR_WRITE_RELEVANT_DIFF = NULL_EQUIVALENT`** — nach der Regel
„technisch umgebaut, aber mechanisch eindeutig dieselbe beziehungsweise
strengere Semantik und deterministisch geprüft".

## 3. Deterministische Nachweise, nativ x86_64

| Ebene | Ergebnis |
|---|---|
| `tests/personal/calendar` | **142 passed** |
| `cargo test --target x86_64-apple-darwin --lib calendar_write` | **62 passed, 0 failed** |
| `vitest` über `personal/calendar` und `core` | **215 passed** (9 Dateien) |

Nicht über Testnamen geglaubt, sondern gegen die Behauptung geprüft:

**Freigabe und Claim.**
`test_ohne_freigabe_kein_claim` (ohne Freigabe kein Auftrag),
`test_claim_konsumiert_freigabe_genau_einmal`,
`test_falsches_claim_token_ist_konflikt`,
`test_ohne_backup_nachweis_kein_claim` (DEC-069 Absatz 2),
`test_manipulierter_payload_nach_freigabe_faellt` (Bindung an genau diese
Vorbereitung), `test_cancel_mutiert_nicht`.

**Bindung an die Mutation-ID.** `core/writeResolver.ts` weist eine Freigabe
zurück, deren ID nicht zur offenen Vorbereitung gehört, und verbraucht die
offene Vorbereitung **vor** der Ausführung — auch ein Fehlschlag lässt keine
zweite Ausführung derselben Freigabe zu.

**Fingerprint und Re-Read** — der Kern von CALENDAR 4, im nativen Pfad:
`ein_update_ohne_expected_fingerprint_faellt`,
`ein_zwischen_freigabe_und_execute_geaendertes_feld_ist_revision_conflict`,
`eine_zwischen_freigabe_und_execute_geaenderte_eligibility_blockt`,
`ein_fehler_im_save_ist_ungewiss_nicht_not_sent`.
`calendar_write.rs` liest das Event **vor** der Mutation aus einem frischen
Store, bildet den vollständigen stabilen Fingerprint und endet bei Abweichung
als `not_sent / revision_conflict` — vor jeder Übergabe an den Provider, ohne
stilles Retry.

## 4. Read Safe Scope

Gestartet wurde der finale x86_64-Produkt-Build aus Teil 1 (dasselbe
`CURRENT_PRODUCT_BASE`, §6).

| Prüfung | Ergebnis |
|---|---|
| EventKit-Bridge | `bridge_available: true`, `authorization_status: full_access`, `can_read: true` |
| Schreibfähigkeiten ohne Freigabe | `can_create_events`, `can_update_events`, `can_delete_events` je `false` |
| Echter Provider-Read (Sync, ±7 Tage) | `outcome: completed`, **11 von 11 Kalendern vollständig**, 1 Termin gesehen, created 0, updated 0, tombstoned 0 |
| Gespeicherter Bestand | 11 Kalender (9 beschreibbar; Quellen calDAV, subscribed, birthdays) |
| Termine heutiges UTC-Fenster | 0 |
| Gegenprobe ±45 Tage | **13 Termine** — der Lesepfad ist nicht leer |

Die Null im Tagesfenster ist die Lage, nicht ein ausgefallener Lesepfad; die
Gegenprobe belegt das. Keine Providermutation.

## 5. Command Bar / Produktweg

| Prüfung | Ergebnis |
|---|---|
| Calendar Read erreichbar | ja (`termine`) |
| CREATE-Weg | `termin_anlegen` vorhanden |
| UPDATE-Weg | `termin_aendern` vorhanden |
| Calendar DELETE | **nicht angeboten** — kein `termin_loeschen` im Router, kein `bereiteLoeschenVor` im Core |
| `foreign_event_delete` | kommt im Produktcode nicht vor |
| Prepare mutiert nicht | ja — die Vorbereitung liefert Vorschau und `Zum Ausführen: freigabe <mutationId>` |

## 6. Build und Packaging — übernommen, nicht wiederholt

Teil 1 hat `CURRENT_PRODUCT_BASE` nativ x86_64 über `build-product.sh` gebaut:
App **33 von 33**, App aus dem DMG **33 von 33**, Artefaktkette über eine
LC_UUID. Übertragbar, weil mechanisch geprüft:

* Von den drei Teil-1-Commits berührt nur `bd9097d` überhaupt eine
  Buildeingabe (`tools/packaging/bundle_contract.py`, der Torwächter in
  Schritt 7). Dessen reparierte Fassung war während des Laufs nachweislich
  aktiv — der Lauf meldete `VERTRAG ERFUELLT: 33 Nachweise`, was die
  unreparierte Fassung nicht erzeugt (sie meldete 4 Fehlschläge).
* `4ac08b5` und `042eafc` berühren ausschliesslich `.pre-commit-config.yaml`
  und `docs/**` — keine Buildeingaben.
* Calendar hat in diesem Block **keine** Datei geändert.

Kein zweiter Build. Keine neue Packaging-Zeremonie.

## 7. Der Blocker: die Freigabegrenze ist für Calendar nicht maschinell erzwungen

Dies ist der einzige nicht grüne Punkt — und er ist **vorbestehend**, nicht
neu: `frontend/src/personal/calendar/**` und der Kalenderzweig von
`writeAdapter.ts` sind seit `22887d` unverändert. Der historische Intel-Lauf
vom 2026-08-11 lief über genau diesen Pfad.

**Was tatsächlich gilt.** Es gibt je Mutation eine ausdrückliche
Eigentümerhandlung: in der Command Bar das getrennte Kommando
`freigabe <mutationId>`, an die konkrete Vorbereitung gebunden; im
Terminformular genau ein Freigabeknopf, nachdem die Vorschau das
serverseitige Delta alt → neu gezeigt hat. DEC-069 Absatz 1 —
Einzelfreigabe je Mutation, an Operation und Payload-Digest gebunden — ist
damit auf der Interaktionsebene erfüllt.

**Was nicht gilt.** Drei Punkte der geforderten Prüfung sind nicht erfüllt:

| Geforderte Prüfung | Befund |
|---|---|
| Execute erzeugt kein Approval | **nicht erfüllt.** `gibFrei()` — `POST /mutations/{id}/approve` — steht *innerhalb* des Ausführungsschritts: `writeAdapter.ts:427`, `TerminFormular.tsx:321`, `TerminLoeschen.tsx:171`, jeweils unmittelbar vor `beanspruche` → nativer Execute → `schliesseAb`. |
| Approval / Execute getrennt | auf der Interaktionsebene ja, **maschinell nein** — beides liegt in derselben Client-Funktion. |
| Calendar-Pfad vom Struktur-/AST-Wächter umfasst | **nicht erfüllt.** `test_keine_selbstfreigabe_irgendwo_in_der_oberflaeche` sucht `.approve(` und `approveMutation(` und behauptet eine Dateimenge aus **drei Kontaktdateien**. `gibFrei(` ist für ihn unsichtbar. |

Dazu: `mutationsApi.ts:125` trägt `const ENTSCHEIDER = 'lukas'` und schickt
ihn als `decision_actor`. Das ist genau das Konstrukt, das die G-Reparatur am
2026-08-13 aus `writeAdapter.ts` entfernt hat, mit der Begründung „ein vom
Produktcode gewählter String ist keine Eigentümerhandlung". Auf dem
Calendar-Pfad steht es unverändert.

**Die Asymmetrie in einem Satz.** Serverseitig sind beide Approve-Routen
gleich — sie nehmen den Actor-String entgegen und bauen die `OwnerDecision`.
Contacts hat seit dem 2026-08-13 zusätzlich eine maschinelle Client-Grenze:
`fuehreAus` liest den Zustand frisch und führt nur aus, was bereits
`state == 'approved'` **und** `approval_state == 'granted'` trägt; die Freigabe
entsteht getrennt an einem Klick, und ein Statiktest hält die Aufrufstellen
fest. Calendar hat diese Grenze nicht.

**Warum ein Livetest das nicht heilt.** Ein produktiver Schreiblauf würde
genau diesen Pfad ausüben und über die fehlende maschinelle Trennung nichts
aussagen. Der Punkt ist deterministisch festgestellt und deterministisch zu
reparieren.

Nicht repariert in diesem Block: die Reparatur ändert den Calendar-UI-Fluss
und gehört damit in einen eigenen Risk-Lane-Block — dieselbe Klasse und
derselbe Umfang wie die G-Reparatur bei Contacts.

## 8. Livewrite-Entscheidung

`CALENDAR_X86_64_LIVE_WRITE_REQUIRED` = **NO**.

Begründung: `CALENDAR_WRITE_RELEVANT_DIFF = NULL_EQUIVALENT`; der native
Provider- und EventKit-Pfad ist byteidentisch zum Stand des historischen
Intel-Livelaufs vom 2026-08-11; Fingerprint-, Claim- und Re-Read-Semantik
sind nativ x86_64 deterministisch belegt; der offene Punkt aus §7 ist durch
einen Livelauf nicht beweisbar und durch ihn auch nicht zu entkräften.

Es wurde **kein** produktiver Kalender-Write ausgeführt: kein CREATE, kein
UPDATE, kein DELETE. Kein Testtermin erzeugt. Die historische native
x86_64-Provider-Evidenz wird carried forward.

## 9. Delete

`CALENDAR DELETE = COMPLETED_BLOCKED` — unverändert. `prepare_delete` und
`DeleteNotRestorable` wurden nicht umgangen und nicht angefasst.
`foreign_event_delete` bleibt
`unsupported_until_explicit_future_functional_scope`. Kein DELETE-Livetest,
kein Jarvis-Cleanup.

Der bekannte alte Cleanup-Rest — „Jarvis Schreibtest geändert", 11.08.,
23:00–23:30 — wurde **nicht** durch Jarvis gelöscht.

## 10. Oberfläche

Geprüft wurde ausschliesslich die Calendar-UI, die in `CURRENT_PRODUCT_BASE`
tatsächlich enthalten ist (`CalendarWorkspace`, `TerminFormular`,
`TerminLoeschen`, 90 Frontendtests grün). Es wurde kein konkurrierender
Intel-UI-Zweig begonnen und nichts nachgebaut.

## 11. Ergebnis

| Aussage | Stand |
|---|---|
| `CALENDAR x86_64 READ` | **PASS** |
| `CALENDAR x86_64 CREATE` | Provider-, Fingerprint- und Claim-Semantik `PASS_CURRENT_PRODUCT_STAND`; Freigabegrenze siehe §7 |
| `CALENDAR x86_64 UPDATE` | Provider-, Fingerprint- und Claim-Semantik `PASS_CURRENT_PRODUCT_STAND`; Freigabegrenze siehe §7 |
| `CALENDAR DELETE` | `COMPLETED_BLOCKED` |
| `CALENDAR_WRITE_RELEVANT_DIFF` | `NULL_EQUIVALENT` |
| `CALENDAR_X86_64_LIVE_WRITE_REQUIRED` | `NO` |
| `CALENDAR x86_64 CURRENT PRODUCT STAND` | ~~BLOCKED~~ → **COMPLETE**, siehe §13 |
| `CALENDAR arm64` | `UNKNOWN UNTIL FINAL REPORT` — im Repository existiert kein finaler arm64-Calendar-Abschlussbericht |
| `CALENDAR OVERALL` | `NOT_YET_CLAIMED_COMPLETE`, reason: `arm64 closure status not established from a final report` |
| `M2_GUARD_OWNER_SETUP` | `PENDING` nach DEC-068 |
| Pushstatus | `not_performed_owner_action` |

`BLOCKED` heisst hier nicht, dass der Kalender-Schreibpfad unbewiesen wäre.
Nativer Pfad, Fingerprintbindung, Claim-Einmaligkeit und Fail-closed-Verhalten
sind belegt. Blockiert ist die Aussage `CURRENT PRODUCT STAND = COMPLETE`,
weil die Trennung von Freigeben und Ausführen für Calendar nicht maschinell
erzwungen und vom Strukturwächter nicht erfasst ist.

## 12. Ausdrückliche Bestätigungen

- Keine produktive Kalendermutation: kein CREATE, kein UPDATE, kein DELETE.
- Kein Testtermin erzeugt, kein Termin gelöscht.
- Keine Schreibfreigabe erzeugt.
- Keine Datei ausserhalb dieses Records geändert.
- Keine neue Command-Bar-Architektur, keine neue Packaging-Zeremonie.
- Claude Code hat nicht gepusht.

---

## 13. Nachtrag: die Freigabegrenze ist repariert (2026-08-16, Risk Lane)

*Dieser Abschnitt hebt §7 und die Zeile `CURRENT PRODUCT STAND` in §11 auf.
Die Messungen der §1–§6 und §8–§10 bleiben unverändert gültig; sie betreffen
Diff, native Semantik, Read und Packaging und wurden von der Reparatur nicht
berührt.*

### Teil A — der Wächter zuerst

Der Befund aus §7 hatte zwei Hälften, und die zweite wog schwerer: Der
Strukturwächter, der Self-Grants finden sollte, war selbst namensbasiert. Er
suchte `.approve(` und `approveMutation(` und behauptete daraus eine
geschlossene Menge. `gibFrei(` sah er nicht.

Repariert in `tools/guards/approval_boundary.py`: Die Grenze wird am
**Endpunkt** erkannt (`/approve` im Pfad; `'approve'` in Argumentposition),
nicht am Bezeichner. Von dieser Saat schliesst die Analyse über den
Modulgraphen — Importe samt Umbenennung, lokale Wrapper, Bindung an
Objekteigenschaften und Aufrufe darüber.

Zwei Dinge mussten dafür stimmen, beide beim Bauen gemessen:

* **Ein Aufruf ist kein Behälter.** Für jedes Symbol zählt nur der eigene
  Rumpf, geschachtelte Definitionen werden abgezogen — samt ihrer Köpfe.
  Ohne den Kopf sah `async genehmige(v, e): Promise<void> {` im Rumpf der
  Portfabrik wie ein Aufruf aus und machte jede Fabrik zur Freigeberin.
* **Kommentare sind keine Aufrufe.** Zeichenketten bleiben stehen — dort
  steht die Saat —, Kommentare werden längentreu ausgeblendet.

Neun Proben auf Fixtures, dazu zwei Regressionsproben für blinde Flecken,
die erst beim Reparieren auffielen: eine mehrzeilige Signatur mit generischem
Rückgabetyp liess die Saat lautlos verschwinden, und ein Kommentar über die
Grenze galt als Aufruf. Beides hätte still zu einem leeren Scan geführt.

| Probe | Ergebnis |
|---|---|
| A3 Umbenennen der Grenzfunktion | erkannt — die Saat hängt am Endpunkt |
| A4 direkter Aufruf ausserhalb | FAIL, Callsite benannt |
| A5 Alias-Import | FAIL |
| A6 deutsch benannter Wrapper | FAIL, über zwei Ebenen verfolgt |
| A7 englisch benannter Wrapper | FAIL |
| A8 zusätzliche Callsite in unauffälliger Datei | FAIL, Datei benannt |
| A9 positive Kontrolle | grün — legitime Freigabe wird nicht blockiert |
| Behälter ist kein Freigeber | Portfabrik erreicht die Grenze nicht |

**Ehrliche Reichweite.** `coverage_limits()` nennt, was **nicht** bewiesen
ist: dynamisches `import()`, Aufrufe über berechnete Namen, über Closures
verlorene Bezeichner — und dass Eigenschaftszugriffe über den **Namen**
aufgelöst werden, nicht über den Typ des Objekts. Letzteres überschätzt
bewusst. Es wird keine vollständige semantische Geschlossenheit behauptet;
die Aussage ist „geschlossen über Import-, Aufruf- und Eigenschaftskanten,
soweit statisch auflösbar".

`WATCHER HOTFIX = PASS`.

### Teil B — die Calendar-Reparatur

| Stelle | vorher | jetzt |
|---|---|---|
| `mutationsApi.ts` | `const ENTSCHEIDER = 'lukas'`, vom Modul selbst eingesetzt | Entscheider ist Pflichtparameter von `gibFrei`/`bricheAb` |
| `writeAdapter.ts:427` | `await gibFrei(id)` im Ausführungsschritt | eigener Weg `genehmige()`; `fuehreAus` liest frisch und verlangt `approved` **und** `granted` |
| `writeResolver.ts` | Phasen `prepare` / `execute` | zusätzlich `approve`; der Schacht bleibt bei der Freigabe offen |
| `commandRouter.ts` | `freigabe <id>` führte aus | `freigabe <id>` gibt nur frei, `ausfuehren <id>` führt aus |
| `TerminFormular.tsx:321` | ein Klick: approve + claim + execute + settle | `freigeben()` und `ausfuehren()` getrennt, Zwischenzustand sichtbar |
| `TerminLoeschen.tsx:171` | dito | dito — Delete bleibt gesperrt |
| `calendar/mutations/service.py` | `get()` ohne Freigabezustand | `approval_state` als **wirksamer** Zustand |

**Der Entscheider** steht jetzt dort, wo der Mensch handelt: in beiden
Dialogen und in der Command Bar. Keine zweite calendar-eigene
Eigentümerrepräsentation — der Kern bleibt die gesiegelte `OwnerDecision`,
die Contacts und Calendar teilen.

### Nachweise

| Ebene | Ergebnis |
|---|---|
| `tests/personal` (Contacts + Calendar + Wächter) | **1362 passed, 94 skipped, 1 failed** |
| Frontend (`vitest`, gesamt) | **396 passed** (20 Dateien) |
| `tsc -b` | sauber |

Der eine Fehlschlag ist `test_dec_052_ist_registriert` — vorbestehend, liest
nur das Entscheidungsregister, architektur- und modulunabhängig.

**Die Invariante**, geschlossen und ohne eine Funktion beim Namen zu nennen
(`test_approval_boundary_produkt.py`):

* Die Menge der Dateien mit Freigabe-Aufrufstellen ist **genau** die
  Allowlist — neun Dateien, jede einzeln begründet.
* Kein Blattsymbol erreicht Freigabe **und** Ausführung. Erlaubt sind allein
  fünf Verteiler, die getrennte Phasen nebeneinander beherbergen.
* Die drei Stellen aus §7 erreichen die Freigabe nicht mehr.

Gegen den Stand vor der Reparatur fallen alle drei Aussagen.

**Wirkung im verdrahteten Weg beobachtet**, nicht nur im Testcode: Über
`pre-commit run` meldet der Hook `Passed`. Mit einem eingeschleusten deutsch
benannten Wrapper im Ausführungsschritt meldet er `Failed` und nennt
`core/writeAdapter.ts::fuehreAus`; mit einem Alias-Import in
`personal/calendar/raster.ts` meldet er `Failed` und nennt
`raster.ts:4 — nebenbei ruft stillerHelfer()`. Nach Rücknahme wieder
`Passed`, ohne Rückstände im Baum.

### Kein Livetest

`CALENDAR_LIVE_WRITE_REQUIRED_AFTER_G_REPAIR` = **NO**.

Mechanisch: Der Diff gegen den Evidence-Anchor `22887d` über
`calendar_write.rs`, `JCCalendarWrite.{h,m}`, `calendar/bridge`,
`calendar/domain.py`, `mutations/contracts.py`, `Cargo.toml`,
`tauri.conf.json` und alle Entitlements ist **leer**. Die einzige
Backendänderung liegt in `mutations/service.py`: die Freigabe-Aufrufstelle
und das zusätzliche Lesefeld `approval_state`. Claim, Settle,
Fingerprintbildung, Re-Read und Provider-Execute sind unberührt.

Die neue Approval-→-Claim-→-Execute-Verbindung ist deterministisch belegt
(142 Calendar-Tests, 62 native Rust-Tests, 396 Frontendtests). Es wurde
**keine** produktive Mutation ausgeführt: kein CREATE, kein UPDATE, kein
DELETE, kein Testtermin erzeugt.

### Status nach der Reparatur

| Aussage | Stand |
|---|---|
| `CALENDAR OWNER-APPROVAL BOUNDARY` | **PASS** |
| `CALENDAR x86_64 READ` | **PASS** |
| `CALENDAR x86_64 NATIVE CREATE PROVIDER EVIDENCE` | `CARRIED_FORWARD` |
| `CALENDAR x86_64 NATIVE UPDATE PROVIDER EVIDENCE` | `CARRIED_FORWARD` |
| `CALENDAR x86_64 CURRENT PRODUCT WRITE PATH` | **PASS** |
| `CALENDAR DELETE` | `COMPLETED_BLOCKED` |
| `CALENDAR x86_64 CURRENT PRODUCT STAND` | **COMPLETE** |
| `CALENDAR arm64` | `UNKNOWN UNTIL FINAL REPORT` |
| `CALENDAR OVERALL` | `NOT_YET_CLAIMED_COMPLETE` |
| `M2_GUARD_OWNER_SETUP` | `PENDING` nach DEC-068 |
| Pushstatus | `not_performed_owner_action` |

Der Produktcode dieser Reparatur ist **gemeinsam** für x86_64 und arm64.
Calendar arm64 ist damit nicht abgeschlossen: Es existiert weiterhin kein
finaler arm64-Abschlussbericht, und die Reparatur verlangt den Nachweis auf
dem M2 auf genau diesem Stand. `Calendar = COMPLETE` bleibt unzulässig.
