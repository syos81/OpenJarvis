# B3 Abschluss cross-platform — feststellend (2026-08-11)

**Rein feststellend.** Dieses Dokument ändert keine Regel, keinen
Gatevertrag, kein Schema, keine Entscheidung und keinen Produktcode. Es
schreibt keinen historischen Record um und verkleinert kein
Erfolgskriterium. Es schliesst den Geltungsbereich, den
`docs/governance/b3-abschluss-x86_64-2026-08-10.md` ausdrücklich offen
gelassen hat: die arm64-Gegenprüfung.

Der x86_64-Abschluss bleibt unverändert bestehen. Dieses Dokument tritt
neben ihn, nicht an seine Stelle.

Alle Commit-Kennungen sind vollständige, mechanisch bestätigte OIDs
(`git cat-file -t` = `commit`, Länge 40, aus HEAD erreichbar). Kurzformen
wurden nie ergänzt und nie geraten. Die im Verlauf genannten Kennungen
`492e23d7` und `6a1a8e52` sind **Mutations-IDs, keine Commits** — sie
lösen auf kein Objekt auf und erscheinen hier nicht als OID.

## §1 Korrigierte Repositorysicht des M2

Die vorangegangene arm64-Gegenprüfung lief gegen einen um vier Commits
veralteten Klon. Der Klon wurde per engem `git fetch origin` und
ausschliesslich per Fast-Forward auf den Remotestand gebracht; kein
Mergecommit, kein Rebase, kein Reset, kein Cherry-pick, keine
Force-Aktion.

| Grösse | Wert |
|---|---|
| Worktree | `spike/calendar-foundation-intel-2026-08-04` |
| HEAD vorher | `1b9f3f1df6763cf06df3146625121aeec8a4ab4a` |
| HEAD nachher | `6be2b7e8c0a9ae3ac6d9bafa2ed22dfe30067516` |
| Verhältnis | vorher strikter Vorfahr, 4 Commits hinter, 0 voraus |
| Erzeugte Mergecommits | 0 |

**Drei Aussagen der vorangegangenen Gegenprüfung stammten aus dem
veralteten Stand und werden hiermit zurückgezogen:**

| Zurückgezogene Aussage | Tatsächlicher Stand ab `6be2b7e8` |
|---|---|
| „`origin_continuity` existiert im Repository nicht" | Existiert als tragender Vertragsbegriff: `src/personaljarvis/calendar/mutations/contracts.py:603` (`assess_restorability`), `.../service.py:265` (`origin_continuity_of`), Pflichtfeld `origin_continuity_proven` in `tools/gates/runners/b3_checks.py:60` |
| „`config/gates/history/b3-live-record.json` fehlt" | Vorhanden; `functional_commit` = `66e7e0f71ec28a60e444fff7bd88de7c061cffa0`, drei Stufen `create`/`update`/`delete`, alle `executed`, Delete mit `readback_status = absent_confirmed` |
| „`platform-live` ist `blocked` mit `live_record_missing`" | `platform-live` = `fail` (`pl-b3-live`), aufgezeichnet gegen `f62ad9c76b16a8b9e1dbab2059e45c79c171747c`; der `fail` ist die beabsichtigte Wirkung des finalen Vertrags |

Ebenfalls überholt: der damalige Commitplanstand. Der Plan steht heute
bei 16 von 16 Positionen.

**Nicht zurückgezogen** werden die SDK-Rohbefunde der Gegenprüfung. Sie
wurden gegen das Dateisystem erhoben, nicht gegen den Repositorystand,
und sind vom Fast-Forward unberührt. Die SDK-Erkundung wurde deshalb
nicht wiederholt.

## §2 Finaler arm64-Befund

| Merkmal | Wert | Beleg |
|---|---|---|
| SDK | `macosx26.5` | `SDKSettings.plist`: `CanonicalName = macosx26.5`, `Version = 26.5` |
| SDK-Pfad | `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk` | `xcrun --show-sdk-path` |
| Toolchain | clang 21.0.0 (`arm64-apple-darwin25.2.0`), Swift 6.3.2 | `clang --version`, `swiftc --version` |
| Host | arm64, macOS 26.2 (25C56) | `uname -m`, `sw_vers` |
| `attachment_observability` | **`unavailable`** | siehe öffentlicher API-Befund |

### §2.1 Öffentlicher API-Befund

Im öffentlichen EventKit-Vertrag des real vorhandenen SDK gibt es

- **keine Attachment-Property**,
- **keine Attachment-Methode**,
- **kein Attachment-Flag**,
- **keinen Attachment-Zähler**,
- **keine Attachment-Collection**,
- **keine geeignete availability-gebundene API**.

Geprüft wurden alle 17 ObjC-Header, `EventKit.apinotes`, das
`EventKit.swiftmodule`-Overlay, die SDK-weite Deklarationssuche über alle
Framework-Header sowie die Symboltabelle. Der einzige Treffer auf
`attach` in den Headern ist Fliesstext in der Klassenbeschreibung von
`EKParticipant.h:31`. Die `has*`-Familie auf `EKCalendarItem` umfasst
`hasAlarms`, `hasRecurrenceRules`, `hasAttendees` und `hasNotes`; ein
`hasAttachments` ist darin nicht enthalten. `EventKitUI` existiert in
diesem SDK nicht; `CalendarStore` trägt ebenfalls keinen Treffer und ist
seit 10.8 deprecated.

Folge: die **Abwesenheit** von Anhängen an einem konkreten `EKEvent` ist
nicht positiv feststellbar. Aus fehlender Sichtbarkeit folgt keine
Abwesenheit.

### §2.2 SPI-Befund

> Interne/SPI-Symbole für Attachment-Zustände sind im Framework
> vorhanden, jedoch im geprüften öffentlichen EventKit-Vertrag nicht
> exponiert.

Das ist eine Feststellung über den geprüften Stand. Sie enthält **keine**
Aussage über eine Herstellerabsicht und **keine** Prognose über künftiges
Verhalten.

### §2.3 Identifier je tatsächlich geprüftem Typ

| Identifier | Fundstelle | Availability | stability | uniqueness |
|---|---|---|---|---|
| `eventIdentifier` | `EKEvent.h:61` | Klasse `NS_CLASS_AVAILABLE(10_8, 4_0)` | `changeable` | `insufficient_contract` |
| `calendarItemIdentifier` | `EKCalendarItem.h:43` | `NS_AVAILABLE(10_8, 6_0)` | `changeable` | `insufficient_contract` |
| `calendarItemExternalIdentifier` | `EKCalendarItem.h:70` | `NS_AVAILABLE(10_8, 6_0)` | `changeable` | `reuse_possible` |
| `calendarIdentifier` (EKCalendar) | `EKCalendar.h:66` | `NS_AVAILABLE(10_8, 5_0)` | `changeable` | `insufficient_contract` |
| `sourceIdentifier` (EKSource) | `EKSource.h:19` | Klasse `NS_CLASS_AVAILABLE(10_8, 5_0)` | `insufficient_contract` | `insufficient_contract` |
| `UUID` | `EKCalendarItem.h:22` | `NS_DEPRECATED(NA, NA, 5_0, 6_0)` — auf macOS nie verfügbar | — | — |

Tragende Vertragsaussagen aus dem SDK selbst: der Wechsel des Kalenders
eines Events ändert `eventIdentifier` wahrscheinlich, und auch eine
Sync-Operation kann ihn ändern; `calendarItemIdentifier` und
`calendarIdentifier` sind ausdrücklich nicht sync-fest, ein Full-Sync
verliert sie; `calendarItemExternalIdentifier` reicht für lokale Kalender
auf `calendarItemIdentifier` durch, kann in vier benannten Fällen als
Duplikat in derselben Datenbank vorkommen und trägt für alle Vorkommen
einer Wiederholungsserie denselben Wert.

Kein verfügbarer Provider-Identifier trägt damit zugleich Stabilität und
Wiederverwendungsausschluss.

### §2.4 Ergebnis der Gegenprüfung

`M2_RESULT_B` — bestätigt. Beide Bedingungen für `M2_RESULT_A` scheitern
mechanisch und unabhängig voneinander:

1. Attachment-Abwesenheit ist im öffentlichen Vertrag nicht positiv
   feststellbar.
2. Der Herkunftsvertrag ist nicht positiv beweisbar, weil beide
   Identitätsträger des Löschpfads dokumentiert änderbar sind.

Damit ist die offene Frage des x86_64-Abschlusses beantwortet:
**`M2_RESULT_B` ist nicht x86_64-spezifisch, sondern gilt auf beiden
produktiven Zielplattformen.** Die Verzweigung `m2_open_branches` ist zu
Zweig B aufgelöst; `m2_outcome` ist nicht länger `not_decided`.

## §3 Cross-Platform-Matrix

Erzeugt ausschliesslich aus `docs/governance/b3-abschluss-x86_64-2026-08-10.md`
samt dessen wirksamer Evidenz (`config/gates/history/b3-p3a-correction.json`,
Abschnitt `sdk_findings`) und aus der abgeschlossenen arm64-Gegenprüfung.

| Merkmal | x86_64 / `MacOSX13.1.sdk` | arm64 / `macosx26.5` |
|---|---|---|
| `attachment_observability` | `unavailable` | `unavailable` |
| `identifier_contract` | `insufficient` | `insufficient` |
| `generic_delete` | `blocked` | `blocked` |
| `event_identifier` | stability `changeable`, uniqueness `insufficient_contract` | stability `changeable`, uniqueness `insufficient_contract` |
| `calendar_item_identifier` | stability `changeable`, uniqueness `insufficient_contract` | stability `changeable`, uniqueness `insufficient_contract` |
| `calendar_item_external_identifier` | stability `changeable`, uniqueness `reuse_possible` | stability `changeable`, uniqueness `reuse_possible` |
| Herkunft der Aussage | `b3-p3a-correction.json` → `sdk_findings` | Gegenprüfung gegen das real vorhandene SDK |

Die beiden Spalten stimmen in allen drei Kernmerkmalen überein. Der
Befund ist damit kein Artefakt einer einzelnen SDK-Generation.

## §4 Produktaussage — maschinenlesbar

Bewusst hier und nicht unter `config/`: die Abdeckungswurzeln der
Loader-Bindung sind `config` und `tools/guard`; eine neue Datei dort
verlangte eine Loader-Deklaration und damit eine Vertragsänderung, die
dieser feststellende Abschluss ausdrücklich nicht vornimmt.

```json
{
  "kind": "b3_cross_platform_closing",
  "schema_version": 1,
  "recorded_at_utc": "2026-08-11T07:45:40Z",
  "branch": "spike/calendar-foundation-intel-2026-08-04",
  "scope": "both_productive_release_targets",
  "commits": {
    "x86_64_closing": "6be2b7e8c0a9ae3ac6d9bafa2ed22dfe30067516",
    "final_delete_contract": "51f2ff6e977705f9b2bd02f23aca151060f61f88",
    "p3a_status_correction": "f62ad9c76b16a8b9e1dbab2059e45c79c171747c",
    "p3a_live_record": "742709fc148286a1b563f36d5449688ea25468bf",
    "p3a_bundle_build": "66e7e0f71ec28a60e444fff7bd88de7c061cffa0"
  },

  "calendar_create": "supported_on_proven_x86_64_scope",
  "calendar_update": "supported_on_proven_x86_64_scope",

  "x86_64_generic_delete": "blocked",
  "arm64_generic_delete": "blocked",
  "delete_block_reason": [
    "attachment_absence_unprovable_via_public_eventkit",
    "origin_identity_contract_insufficient"
  ],

  "arm64_sdk": "macosx26.5",
  "arm64_attachment_observability": "unavailable",
  "arm64_spi_note":
    "internal_spi_symbols_present_but_not_exposed_in_reviewed_public_contract",
  "m2_result": "M2_RESULT_B",
  "m2_result_scope": "holds_on_both_release_targets",

  "historical_delete_executed": true,
  "historical_delete_scope": "controlled_b3_self_created_event",
  "final_contract_would_allow_same_delete": false,

  "pre_execute_measurement_persistence": "deferred_until_executable_delete",
  "must_exist_before_first_future_live_delete": true,

  "cleanup": "deferred",
  "b3_success_criterion_changed": false,

  "b3_status": "completed_blocked",
  "next_functional_step": "contacts_m2_arm64_acceptance"
}
```

## §5 module-final — tatsächlicher Befund

`module-final` wurde auf dem M2 **nicht gefahren**. Der Grund ist
mechanisch und wird hier belegt statt umschrieben.

Der Auftrag erlaubte den Lauf unter der Bedingung, dass der Gatevertrag
für diesen mechanischen Produktblocker einen `blocked`-Ausgang trägt.
Diese Bedingung ist **nicht erfüllt**:

1. `tools/gates/runners/b3_checks.py`, `mode_live`: fehlende oder
   unerfüllte strukturierte Delete-Pflichtfelder erzeugen Einträge in
   `failures`, und der Abschluss lautet
   `_report.PASSED if not failures else _report.FAILED`. Der
   Produktblocker ist damit vertraglich ein **`fail`**.
2. `BLOCKED` ist in demselben Runner ausschliesslich für fehlende
   Voraussetzungen reserviert: `live_record_missing`,
   `backup_proof_missing`, `stage_pending`, `stages_incomplete`,
   `supersession_missing`.
3. `tools/gates/engine.py`, `_internal_phase_results`: eine als `fail`
   gespeicherte Pflichtphase führt zu `status = FAIL`,
   `reason = previous_phase_failed`. Nur eine als `blocked` gespeicherte
   Vorphase ergibt `previous_phase_blocked`. Die aufgezeichnete Vorphase
   `platform-live` ist ein `fail`.

Ein Lauf auf diesem Rechner hätte zusätzlich aus zwei umgebungsbedingten
Gründen abgebrochen, die mit dem Produktblocker nichts zu tun haben:
`~/.openjarvis/personal/backups/calendar/latest.json` existiert hier
nicht (`backup_proof_missing`), und `.gate-runtime/results/` existiert
hier nicht (`phase_result_missing`). Das Blockmanifest bindet zudem
`platform_requirements.architectures = ["x86_64"]`.

Ein so erzeugtes `blocked` trüge mechanisch gebundene Gründe — aber die
**falschen**. Es als Beleg für den Produktblocker zu führen, wäre genau
die Bindung, die DEC-067 — Der Bericht ist Folge der Definition, nie ihre
Schwester (`docs/governance/decisions/DEC-067-bericht-als-folge.md`)
untersagt. Der Lauf unterblieb deshalb.

**Festzuhalten ist damit:**

| Grösse | Wert |
|---|---|
| `module_final_run_on_m2` | `not_performed` |
| `module_final_recorded_status` | `nicht gefahren` (x86_64-Abschluss §5) |
| `module_final_contract_value_for_this_blocker` | `fail`, nicht `blocked` |
| `module_final_disposition` | `blocked` im Sinne von: das ursprüngliche Erfolgskriterium verlangt weiterhin einen sicheren DELETE |

Die Wörter sind auseinanderzuhalten: der x86_64-Abschluss führt
`"module_final": "blocked"` als **Lagebezeichnung**, nicht als
Rückgabewert eines Gatelaufs. Ein Gatelauf hat `module-final` bis heute
nicht ermittelt.

Das Gate hat zu keinem Zeitpunkt `pass` gemeldet. Es wurde nichts durch
Berichtstext kompensiert, und es wurde kein Unterblock zur
Gate-Härtung eröffnet.

## §6 B3-Status

```
B3 status = completed_blocked
```

**Nicht** `completed_pass`. Bedeutung, ausgeschrieben:

- Die Arbeit an B3 wird beendet.
- Das ursprüngliche Erfolgskriterium — Create **und** Update **und**
  sicherer Delete — blieb unverändert erhalten und wurde nicht
  nachträglich verkleinert.
- Sein DELETE-Teil ist auf **beiden** produktiven Zielplattformen
  mechanisch blockiert.
- Innerhalb des aktuellen öffentlichen EventKit-Vertrags existiert
  **keine** sichere weitere B3-Implementierung. Weitere Arbeit an einem
  Löschpfad würde entweder private API, Reflection oder einen
  unbewiesenen Herkunftsvertrag voraussetzen; keines davon ist zulässig.

```
next functional step = contacts_m2_arm64_acceptance
```

## §7 Aufgeschobene Pflicht — unverändert

```
pre_execute_measurement_persistence      = deferred_until_executable_delete
must_exist_before_first_future_live_delete = true
```

Wegen `M2_RESULT_B` entsteht daraus **keine** Plumbing-Arbeit: kein Feld,
kein Schema, keine Persistenzschicht, keine Vorbereitung. Sobald
irgendeine Plattform wieder einen ausführbaren DELETE-Vertrag erreicht,
ist diese Persistierung zwingende Voraussetzung **vor** dem ersten realen
Delete auf dieser Plattform.

## §8 Cleanup

```
cleanup = deferred
```

Unverändert aus `config/gates/history/b3-p3a-correction.json`: im
Zielkalender lebt nach der Löschung genau ein Termin, ein anderer
geeigneter Kontrolltermin existiert nicht, und es wurde und wird kein
Termin nur als Kontrollobjekt erzeugt. Der verbliebene Termin bleibt
stehen.

## §9 OID-Integrität

Jede in §1 und §4 als Commit bezeichnete Kennung wurde geprüft: Länge 40,
`git cat-file -t` ergibt `commit`, Objekt aus HEAD erreichbar. Neun von
neun bestanden. `492e23d7` und `6a1a8e52` lösen auf kein Objekt auf und
sind entsprechend nicht als OID geführt.

## §10 Offener Punkt für den Eigentümer

`config/gates/history/b3-commit-plan.json` steht bei 16 von 16
Positionen (`max_commits: 16`, `plan_change.actual: 16`). Der Commit
dieses Dokuments wäre Position 17 und verlangte einen neunten
`plan_change` mit eigenem `decided_by`. Ein solcher Eintrag ist eine
Eigentümerhandlung; er wurde deshalb **nicht** von mir angelegt. Kein
B3-Gate bindet diese Datei — der `commit-plan`-Check in
`tools/gates/runners/history_checks.py` ist auf `b0a-4-commit-plan.json`
festgelegt und nur im Block `b0a-4-guard` verdrahtet. Es entsteht dadurch
kein Gatefehler, wohl aber eine Lücke in der Plandisziplin. Die
Entscheidung darüber liegt bei Lukas.

## §11 Ausdrückliche Bestätigungen

- Keine Live-Mutation, kein Cleanup, kein neuer Kontrolltermin, kein
  App-Start, keine TCC-Berührung.
- Kein `module-final`-Lauf; kein Gatelauf überhaupt.
- Kein Produktcode, keine Regel, kein Gatevertrag, kein Schema, keine
  Entscheidung in diesem Commit.
- Kein historischer Record umgeschrieben; der x86_64-Abschluss bleibt
  unverändert bestehen.
- Kein Merge, kein Rebase, kein Reset, kein Cherry-pick, keine
  Force-Aktion; das Repository wurde ausschliesslich per Fast-Forward
  bewegt.
- Pushstatus: `not_performed_owner_action`.
