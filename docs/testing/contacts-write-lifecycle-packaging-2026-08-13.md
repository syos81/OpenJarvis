# Contacts — Write-Lifecycle und Packaging-Reparatur, 2026-08-13

**Lane:** Risk Lane (Signing/Packaging, TCC, potenzielle Live-Mutation).
**Basis:** `ff2409780aa385145122a3a83a7d35b262d6e8db` — mechanisch bestätigt als
HEAD von `integration/openjarvis-product-v1-2026-08-12`, Arbeitsbaum sauber,
Upstream `origin/integration/openjarvis-product-v1-2026-08-12`.
**Worktree:** `~/Jarvis-Next-Contacts-Repair`,
Branch `fix/contacts-write-lifecycle-packaging-2026-08-13`.
**Regelquelle:** `docs/governance/openjarvis-dauerregeln.md` bei
`3ca01ebcd3b39ace937e135f8588d85fa311224b` (Repository
`~/Jarvis-Next-Calendar-Spike`).

> Aggregierte Angaben. Keine Kontaktwerte, keine Providerkennungen im Klartext,
> keine privaten Pfade.

---

## 1. Herkunft der Punkte — und zwei Abweichungen zur Auftragsannahme

Der Auftrag spricht von „bekannten Contacts-Produktdefekten A bis H". Der
Integrationsbericht führt in
[§8](openjarvis-product-integration-v1-2026-08-12.md) **A bis G** — sieben
Punkte. Ein Punkt `H` existiert dort nicht.

`H` ist der Packaging-Befund aus dem M2-arm64-Lauf gegen denselben Commit
(§10-Arbeit vom 2026-08-13). Er ist real und gemessen, stammt aber aus der
Buildprüfung, nicht aus §8. Er wird hier unter der vom Eigentümer vergebenen
Kennung `H` geführt; erfunden ist daran nichts, verschoben ist nur die
Herkunftsangabe.

Zweitens: **§10 ist noch nicht in den Integrationsbericht geschrieben.** Die
Messungen liegen vor (Build, Tests, App-Start, Read, Entitlements), die Zeile
`M2 arm64 INTEGRATED BUILD` in §9 steht weiterhin auf `offen`. Sachlich ist die
Vorbedingung erfüllt — kein Merge-Regressionsblocker, Testzahlen identisch zum
Intel-Befund aus §6 —, dokumentarisch ist sie offen. Das Nachtragen gehört auf
den Integrationsbranch und ist nicht Teil dieses Blocks.

## 2. Arbeitsmatrix

Spalte „Befund" ist gegen den Code auf `ff240978` belegt, nicht aus dem
Auftragstext übernommen.

### A — Freigabevorschau nennt den Zielcontainer nicht sichtbar

*§8 wörtlich:* „Die Freigabevorschau nennt den Zielcontainer nicht sichtbar.
**Produktanforderung:** vor künftigen Writes muss der Eigentümer mindestens
Zielcontainer/-typ und eindeutige Kennung sehen."

| | |
|---|---|
| Befund | `_build_preview` setzt `container_identifier` nur für `create` (aus dem Command). Für `update` und `delete` steht dort fest `None`. Container**typ** und Anzeigename fehlen in allen drei Fällen; `MutationPreview` hat keine Felder dafür. |
| Dateien | `application/mutation_service.py` (`_build_preview`, `_reuse`), `application/models.py` (`MutationPreview`), `api/schemas.py`, `api/routes.py`, `status/ContactsStatusSurface.tsx`, `components.tsx` |
| Schicht | Produktcode + API-Schema + UI |
| Safety | Hoch — die informierte Eigentümerfreigabe ist ohne Zielort unvollständig |
| Architektur | architekturunabhängig |
| Nebenwirkung | `MutationPreview.digest` deckt `container`; zusätzliche Felder ändern den Digest. Betrifft nur in Flight befindliche Freigaben. |

### B — Abgelaufene Freigabe zeigt weiterhin `granted`

*§8 wörtlich:* „Eine abgelaufene Freigabe zeigt weiterhin `granted`, bis ein
Zugriff sie auswertet."

| | |
|---|---|
| Befund | `Approval.is_expired()` existiert und `ApprovalStore.consume()` fail-closed korrekt. Die Lesewege (`get`, `find_for_subject`, `ContactsApprovalService.pending`, `queries.list_approvals`) geben den **gespeicherten** `state` zurück; ein abgelaufener Grant bleibt dort `granted`, bis `consume` ihn umschreibt. |
| Dateien | `base/approvals.py`, `contacts/application/approvals.py`, `contacts/application/queries.py`, `api/schemas.py`, `status/ContactsStatusSurface.tsx` |
| Schicht | Produktcode + API-Semantik + UI |
| Safety | Mittel-hoch — die Anzeige verspricht eine Handlungsfähigkeit, die Execute korrekt verweigert |
| Architektur | architekturunabhängig |
| Leitplanke | Anzeige aus derselben Zeitlogik ableiten, die Execute schützt — keine UI-seitige Zweitwahrheit |

### C — `approved`, nicht ausgeführt: nicht erkennbar

*§8 wörtlich:* „`approved`, aber nicht ausgeführte Vorgänge sind in der
Oberfläche nicht deutlich genug als offen und ausführbar erkennbar."

| | |
|---|---|
| Befund | Schärfer als „nicht deutlich genug": Die Freigabeliste filtert auf `state === 'awaiting_approval'`. Die Vorgangsliste filtert über `AUFMERKSAMKEIT`, und diese Menge enthält `approved` **nicht**. Ein freigegebener, nicht ausgeführter Vorgang erscheint damit in keiner Liste. Die Detailansicht mit „Freigegeben — noch nicht ausgeführt" und dem Knopf „Jetzt ausführen" existiert, ist aber ohne bekannte `mutation_id` nicht erreichbar. |
| Dateien | `status/ContactsStatusSurface.tsx` (`AUFMERKSAMKEIT`, `wartetAufFreigabe`, `zeigeVorgaenge`) |
| Schicht | UI |
| Safety | Hoch — ein scharfgestellter Vorgang ist unsichtbar |
| Architektur | architekturunabhängig |

### D — Mehrere offene Vorbereitungen nebeneinander

*§8 wörtlich:* „Mehrere offene Vorbereitungen können nebeneinander bestehen,
ohne dass das erkennbar wäre."

| | |
|---|---|
| Befund | `prepare` dedupliziert ausschließlich über `_find_by_idempotency(provider_account_id, idempotency_key)`. Zwei Vorbereitungen derselben fachlichen Aktion mit verschiedenen Idempotenzschlüsseln erzeugen zwei offene Mutationen mit je eigener Freigabe — still. |
| Dateien | `application/mutation_service.py` (`prepare`, `_find_by_idempotency`), `application/queries.py`, API + UI |
| Schicht | Produktcode + UI |
| Safety | Hoch — zwei gültige Freigaben auf dasselbe Ziel |
| Architektur | architekturunabhängig |

### E — Detailroute liefert nach DELETE den Tombstone mit HTTP 200

*§8 wörtlich:* „Die Contacts-Detailroute liefert nach DELETE den Tombstone
weiter mit HTTP 200." Status dort: `UNRESOLVED_API_SEMANTICS`.

| | |
|---|---|
| Vertragsbefund | `docs/personal-jarvis/modules/contacts.md` Zeile 263: `GET /v1/personal/contacts/{id}` → „Kontakt inkl. `field_availability`", Fehlerfall `NotFound`. Das Antwortschema `ContactDetailOut` ist `_Strict` und führt **weder** `deleted_at` **noch** `is_tombstone`. Die Route kann einen Tombstone nicht einmal ausdrücken. |
| Entscheidung | **Variante B** des Auftrags: Die Route verspricht ausschließlich aktive Kontakte → Produktdefekt. |
| Befund | `queries.get_contact` filtert `is_tombstone` nicht; `SqliteContactRepository.get` liest ohne Tombstone-Klausel, während die Listenwege `AND is_tombstone = 0` führen. |
| Dateien | `application/queries.py`, `repositories/sqlite.py`, `api/routes.py`, `api/schemas.py` |
| Schicht | API-Semantik + Produktcode |
| Safety | Mittel — positive Abwesenheitskontrollen nach DELETE dürfen diese Route nicht als Beleg verwenden |
| Architektur | architekturunabhängig |

### F — `"previous": null` im Änderungssatz des UPDATE

*§8 wörtlich:* „Im Änderungssatz des UPDATE steht `"previous": null`, obwohl
ein Vorwert existierte."

| | |
|---|---|
| Befund | Ursache mechanisch bestimmt: `queries.mutation_changes` liest `payload_json["fields"]` — für `update` sind das die **kanonischen** Schlüssel aus `canonical_patch` (`organizationName`) — und schlägt sie in einer Zeile der Tabelle `contacts` nach, deren Spalten **API-Namen** tragen (`organization_name`). `vorher.get("organizationName")` ist damit strukturell immer `None`. Zweiter Pfad: ist `target_contact_id` NULL (lokal unbekanntes Ziel), bleibt `vorher` leer. Die Vorschau bei `prepare` ist **nicht** betroffen: `_build_preview` vergleicht API-Namen gegen API-Spalten. |
| Dateien | `application/queries.py` (`mutation_changes`), `application/field_contract.py` (`SCALAR_FIELDS`, `LIST_FIELDS`) |
| Schicht | Produktcode |
| Safety | Mittel — der zurückgelesene Änderungssatz behauptet „kein Vorwert" |
| Architektur | architekturunabhängig |

### G — Command-Bar-Kontaktzweig ruft den Server-Execute

*§8 wörtlich:* „Der Kontaktzweig der Command Bar
(`frontend/src/core/writeAdapter.ts`) ruft `POST /mutations/{id}/execute` statt
des bewiesenen App-Prozess-Kanals (claim → Tauri-`invoke` → settle). Live nie
ausgeübt. Durch diese Integration steht die Command Bar erstmals auch auf
arm64." Status dort: unbelegte Beobachtung, keine Defektbehauptung.

| | |
|---|---|
| Befund | Bestätigt: `fuehreAus` verzweigt bei `kanal === 'kontakte'` auf `approveMutation` + `executeMutation`; der Kalenderzweig darunter nutzt `gibFrei → beanspruche → fuehreNativAus → schliesseAb`. |
| Zusatzbefund | In derselben Funktion steht `await approveMutation(vorbereitet.mutationId, ENTSCHEIDER)` mit `const ENTSCHEIDER = 'lukas'` (Zeile 37). Die Freigabe wird also **programmatisch im Ausführungsschritt** erteilt. `ApprovalStore.grant` weist nur `llm_assisted`/`automation`/`system` ab; der Literalstring passiert. Das berührt unmittelbar die Auftragsvorgaben zu C („keine automatische Ausführung allein durch Approval") und zu I („kein Self-Grant"). Es ist kein neuer Buchstabe, sondern ein Befund an G. |
| Dateien | `frontend/src/core/writeAdapter.ts` |
| Schicht | UI/Adapter |
| Architektur | architekturunabhängig; die Command Bar steht durch die Integration erstmals auch auf arm64 |

### H — Packaging ist nicht fail-closed *(Herkunft: §10-Lauf, nicht §8)*

| | |
|---|---|
| Befund | Gemessen auf arm64 am Integrationsstand, unmittelbar nach `tauri build --target aarch64-apple-darwin`, **vor** Reseal: `Signature=adhoc`, `Identifier=contacts-write-helper-5555494487957ca5…`, **9** Entitlements (der volle App-Satz inkl. JIT, unsigniertem Speicher, abgeschalteter Library-Validation, beider Netzrechte, Kalender). Erst `reseal-contacts-sidecar.sh` stellt Identifier, ein Entitlement und die zertifikatsgebundene Signatur her. |
| Dateien | `frontend/src-tauri/scripts/reseal-contacts-sidecar.sh`, `frontend/src-tauri/tauri.conf.json`, Buildeinstiegspunkte, `tests/personal/contacts/test_write_helper_bundle.py` |
| Schicht | Packaging |
| Safety | Hoch — ein scheinbar fertiges Paket kann einen vertragswidrigen Schreibhelfer enthalten |
| Architektur | plattformspezifisch; verlangt nach §14 eine eigene Prüfung je natives Releaseziel |

### I — Write-Authorization-Bootstrap-UX *(Auftragspunkt, read-only bestätigt)*

| | |
|---|---|
| Befund 1 | Bestätigt: `/capabilities` liefert `module.capabilities`, und `self._capabilities` wird **einmal** in `check_bridge()` gesetzt und danach nur noch zurückgegeben. `derive_capabilities(..., database_path=…)` wertet die Freigabedatei genau zu diesem Zeitpunkt aus. Eine nach App-Start erzeugte oder abgelaufene Freigabe ist bis zum Neustart unsichtbar. `/app-channel` liest dagegen frisch — zwei Wahrheiten über denselben Sachverhalt. |
| Befund 2 | Live gemessen am 2026-08-13: `channel_mode: disabled`, `provider_write_enabled: false`, `create/update/delete_supported: false`, `mutations_available: false`. `kannAusfuehren()` in der UI hängt an genau diesen Flags. |
| Dateien | `contacts/lifecycle.py`, `contacts/domain/capabilities.py`, `contacts/api/routes.py`, `application/write_release.py`, `status/ContactsStatusSurface.tsx` |
| Schicht | Produktcode + API-Semantik + UI |
| Grenze | Die Erteilung bleibt Eigentümerhandlung. Kein Self-Grant durch Modell, Backend, Kanal oder Routine. |
| Architektur | architekturunabhängig |

### J — Linke Seitenleiste nicht ausblendbar *(Auftragspunkt, funktionale UI-Lücke)*

| | |
|---|---|
| Befund | `ContactsWorkspace` ist ein festes dreispaltiges Grid; die Sidebarbreite ist über `PaneDivider` **veränderbar**, aber es gibt keinen Weg auf Null und keinen Toggle. |
| Dateien | `workspace/ContactsWorkspace.tsx`, `workspace/ContactsToolbar.tsx`, `sidebar/ContactsSidebar.tsx`, `tokens.css` |
| Schicht | UI |
| Grenze | Kein Pixelabgleich, keine Designrunde; die abgenommene Oberfläche bleibt sonst unangetastet |
| Architektur | architekturunabhängig |

## 3. Ausdrücklich nicht in diesem Block

Active Context · Memory · Spaces · neue Calendar-Funktionen · Calendar DELETE ·
Felder außerhalb Feldvertrag v1 (Pronomen, Klingelton, Nachrichtenton,
Benutzername) · Pixelmessung und Zehn-Szenen-Abgleich · erneute vollständige
Contacts-Gates · erneute vollständige CRUD-Abnahme beider Architekturen ·
`test_dec_052_ist_registriert` (vorbestehend).

## 4. Bekannte Blocker zu Blockbeginn

| Gegenstand | Stand |
|---|---|
| Intel-x86_64-Revalidierung | Dieser Rechner ist ein Mac mini M2; installiert ist ausschließlich das Rust-Target `aarch64-apple-darwin`. Rosetta ersetzt nach Dauerregeln §14 keinen nativen Plattformnachweis. Verlangt den Intel-Rechner. |
| Live-Risk-Test | Setzt eine gültige Schreibfreigabe voraus. Deren Erzeugung ist Eigentümerhandlung (Dauerregeln §4, DEC-069). |
| §10 im Integrationsbericht | Nicht nachgetragen; gehört auf den Integrationsbranch. |

---

## 5. Ergebnis je Punkt

| # | Punkt | Ergebnis | Beleg |
|---|---|---|---|
| A | Zielcontainer in der Freigabevorschau | **PASS** | Vorschau trägt Kennung **und** Art für alle drei Operationen; Digest deckt beides; Angabe steht im Freigabe-Board **vor** den Entscheidungsknöpfen; `tests/personal/contacts/test_write_lifecycle_repair.py::TestZielablageortInDerVorschau`, `frontend/…/zielangabe.test.tsx` |
| B | Abgelaufene Freigabe | **PASS** | `effective_state()` als eine Stelle; Anzeige und `consume()`-Sperre teilen die Zeitlogik; Lesen schreibt nicht fort; `TestAblaufBeimLesen` |
| C | `approved` sichtbar und ausführbar | **PASS** | `OFFEN` neben `AUFMERKSAMKEIT`; Karte nennt Frist, Ausführung und Verwerfen; kein Auto-Execute; `frontend/…/offene-vorgaenge.test.tsx` |
| D | Mehrfachvorbereitung | **PASS** | `MutationAlreadyPending` nennt den bestehenden Vorgang; kein zweiter Datensatz, keine zweite Freigabe; `create` bleibt frei; `TestMehrfachvorbereitung` |
| E | Tombstone-Detailroute | **PASS** — Variante B | Vertrag nennt `NotFound`, `ContactDetailOut` ist `_Strict` ohne `deleted_at`/`is_tombstone`; Tombstone gefiltert, Historie über `include_tombstones`; `TestTombstoneDetailroute` |
| F | `"previous": null` | **PASS** | Ursache: kanonische Payload-Schlüssel gegen DB-Spaltennamen; jetzt aus `expectedPrevious`; `TestVorwertImAenderungssatz` |
| G | Command-Bar-Kontaktzweig / Self-Grant | **PASS** | Eigentümerentscheidung liegt vor: G ist Safety-Blocker vor dem Live-Test und wurde repariert. Siehe §8. |
| H | Packaging fail-closed | **PASS** | Kanonischer Build erzwingt den Helfervertrag; App und DMG je 33/33; vier Negativproben greifen; `tests/personal/contacts/test_bundle_contract.py` |
| I | Write-Bootstrap-UX und Capability-Lifecycle | **PASS** | Schreibrechte frisch statt Startschnappschuss; gesperrte Aktion bleibt sichtbar und führt in eine Erklärung; kein Self-Grant; `test_capability_bridge.py`, `frontend/…/schreibsperre.test.tsx` |
| J | Seitenleiste ausblendbar | **PASS** | Toggle an macOS-üblicher Stelle; Leiste und Trenner bleiben im Grid-Fluss, nur unsichtbar; Eigentümer-Sichtprüfung nach der Korrektur bestanden; `frontend/…/seitenleiste.test.tsx` |

## 6. Nicht erbracht — und warum

| Gegenstand | Stand | Grund |
|---|---|---|
| Intel-x86_64-Revalidierung | **BLOCKED** | Dieser Rechner ist ein Mac mini M2; installiert ist nur `aarch64-apple-darwin`. Dauerregeln §14: Rosetta ersetzt keinen nativen Plattformnachweis. H ändert plattformspezifische Pfade und verlangt die Prüfung dort. |
| Live-Risk-Test | **BLOCKED** | Setzt eine gültige Schreibfreigabe voraus; ihre Erzeugung ist Eigentümerhandlung (Dauerregeln §4, DEC-069). Der Lauf soll gerade den neuen Weg ausüben — Grant zunächst nicht vorhanden, UI zeigt gesperrt, Eigentümer aktiviert, UI erkennt ohne Neustart. |
| `test_dec_052_ist_registriert` | vorbestehend | Nicht angefasst (Auftragsvorgabe). Liest ausschliesslich `decisions-register.md`. |
| Pixelabgleich | out of scope | Ausdrücklich ausgeschlossen. |

## 7. Ausdrückliche Bestätigungen

- Keine produktive Mutation: kein Contacts- und kein Calendar-CREATE/UPDATE/DELETE.
- cardDAV-Container unberührt; kein Livelauf gegen einen echten Provider.
- Keine neue Fachfunktion ausserhalb A–J.
- Feldvertrag bleibt v1: keine Pronomen, kein Klingelton, kein Nachrichtenton,
  kein Benutzername.
- `~/Jarvis-Next-Contacts-ARM64` unverändert bei `b9675dbf`.
- Pushstatus: `not_performed_owner_action`.

---

## 8. G — die Freigabe ist keine Zeichenkette mehr

*Nachtrag nach der Eigentümerentscheidung vom 2026-08-13: G ist ein
Safety-Blocker vor dem Live-Risk-Test und wird in diesem Block repariert.*

**Der Defekt hatte zwei Hälften, und beide waren nötig.**

`ApprovalStore.grant()` prüfte eine **Denylist**: `llm_assisted`,
`automation` und `system` raus, alles andere rein. Der Literal `'lukas'`
genügte damit für eine Eigentümerfreigabe. Und `writeAdapter.fuehreAus()`
setzte genau diesen Literal — `const ENTSCHEIDER = 'lukas'` — programmatisch
**im Ausführungsschritt** ein. Der Execute-Pfad erteilte sich also die
Freigabe, die er im selben Atemzug verbrauchte; die Trennung von Vorbereiten
und Ausführen war damit aufgehoben.

**Warum keine Allowlist.** `actor == 'lukas'` wäre dieselbe Lücke mit
umgekehrtem Vorzeichen: weiterhin von beliebigem Produktcode vortäuschbar.
Die Grenze darf nicht an einem Wert hängen, den der Aufrufer wählt.

**Die geschlossene Repräsentation.** `grant()` verlangt kein
`decision_actor: str` mehr, sondern ein `OwnerDecision`. Das Objekt entsteht
ausschliesslich in `owner_decision()` — ein Konstruktor ohne das
Modulsiegel wirft. Der Parametername wechselte bewusst mit: Aufrufer, die
bisher einen String übergaben, scheitern jetzt laut statt still
weiterzulaufen. 173 Testaufrufe fielen dabei auf, was der Punkt war.

**Wo `owner_decision()` aufgerufen werden darf**, hält ein Statiktest über den
AST fest: genau zwei Stellen, `contacts/api/routes.py` und
`calendar/mutations/service.py`, beide der interaktive Entscheidungsweg. Ohne
diese Enge wäre die Repräsentation folgenlos — wer sie überall aufrufen darf,
hat wieder den freien String, nur mit mehr Zeichen.

**Der Kalenderzweig ist mitgezogen.** Eine Sicherheitsgrenze im geteilten
Freigabekern, die nur für ein Modul gilt, ist keine. Das ist Anpassung eines
Aufrufers, keine neue Calendar-Funktion.

**Was das ist und was nicht.** Eine geschlossene Repräsentation mit
maschineller Wirkung, kein kryptographischer Nachweis, dass ein Mensch
geklickt hat. Wer Produktcode ändern darf, darf auch `owner_decision()`
aufrufen. Der Unterschied: dafür gibt es jetzt genau eine benannte,
auffindbare und statisch geprüfte Stelle statt jeder beliebigen Zeichenkette.
Dieselbe Semantik wie im Guard-Vertrauensmodell —
`requires_interactive_owner_authentication`, nicht `technically_impossible`.

**Der Ausführungsschritt** liest den Zustand jetzt frisch und führt nur aus,
was `state == 'approved'` **und** `approval_state == 'granted'` trägt. Beide
Bedingungen zusammen decken die vier Sperrfälle: wartend, abgelaufen (der
wirksame Zustand aus B), verbraucht, abgeschlossen.

### Deterministische Nachweise

| Nachweis | Test |
|---|---|
| Execute auf `awaiting_approval` erzeugt keine Freigabe | `test_execute_auf_wartendem_vorgang_erzeugt_keine_freigabe` |
| Execute auf `awaiting_approval` mutiert nicht (Provider ungerufen, `attempt_count` 0) | `test_execute_auf_wartendem_vorgang_mutiert_nicht` |
| Kein selbst gewählter Name erzeugt eine Freigabe | `test_ein_selbst_gewaehlter_name_erzeugt_keine_freigabe`, `test_auch_direkt_am_store_nicht` |
| Maschinenquelle wird abgewiesen | `test_maschinelle_ursprünge_werden_abgewiesen` |
| Ausdrückliche Handlung erzeugt genau den gebundenen Grant | `test_die_ausdrueckliche_handlung_erzeugt_genau_den_gebundenen_grant` |
| Bindung an Mutation-ID, Nutzlast und Vorschau | `test_die_bindung_gilt_an_genau_dieser_vorbereitung` |
| Danach separates Execute nötig | `test_nach_der_freigabe_ist_execute_ein_eigener_schritt` |
| Abgelaufen trägt kein Execute | `test_eine_abgelaufene_freigabe_traegt_kein_execute` |
| Kein zweites Execute | `test_ein_zweites_execute_findet_nicht_statt` |
| Lesen schreibt keinen Freigabezustand fort | `test_der_abgelaufene_grant_liest_sich_ohne_mutation_als_expired` |
| `owner_decision()` nur am Freigabeweg | `test_owner_decision_wird_nur_am_freigabeweg_aufgerufen` |
| Execute-Pfad kennt `grant` nicht | `test_der_ausfuehrungspfad_ruft_keine_freigabe` |
| Command Bar gibt nicht mehr selbst frei (Verhalten) | `frontend/src/core/ownerGrant.test.ts`, 5 Tests |

Die Frontendtests laufen gegen den **echten** Adapter, nicht gegen einen
Stubport: Die vorhandene Core-Suite arbeitet mit einem Zählport und hätte
diese Änderung nicht bemerkt. Ihr Mock stellt `approveMutation`
ausdrücklich bereit — der alte Adapter soll alles bekommen, was er zum
Freigeben braucht, und trotzdem auffallen. Gegen den alten Stand fallen alle
fünf.

## 9. Sachstatus

| Aussage | Stand |
|---|---|
| `M2 arm64 INTEGRATED BUILD` | `PASS_EVIDENCE_COMPLETE` |
| `integration_report_update` | `PENDING` — Nachtrag auf dem Integrationszweig nach diesem Block, keine Historienumschreibung |
| `CONTACTS REPAIR x86_64 NATIVE CLOSURE` | `PENDING` — eigener Nachweisblock auf dem Intel-Rechner, derselbe finale Commit, nativ |
| M2-Live-Risk-Test | **PASS** — A, B, CREATE, UPDATE, DELETE; siehe §10 |
| `CONTACTS WRITE/LIFECYCLE REPAIR – arm64` | **PASS** |

---

## 10. M2-Live-Risk-Test, 2026-08-13

Gefahren am gebauten Paket des Reparaturstands, mit einer vom Eigentümer im
Lauf erteilten Schreibfreigabe (`contacts-write-v1`, zwei Stunden, alle drei
Operationen). Ein einziger synthetischer Kontakt, ausschliesslich im lokalen
Ablageort `C-4b8df1`. Der cardDAV-Container `C-63caab` war zu keinem Zeitpunkt
Ziel eines Vorgangs.

### Die Trennung, in Zeitstempeln

Das ist der Kernbeleg, und er braucht keine Erklärung:

| Operation | vorbereitet | freigegeben | ausgeführt | Versuche |
|---|---|---|---|---|
| `create` (**alter Stand**) | 13:25:45 | 13:25:45 | 13:25:46 | 1 |
| `create` | 13:42:50 | 13:46:35 | 13:47:55 | 1 |
| `update` | 13:49:46 | 13:51:00 | 13:51:12 | 1 |
| `delete` | 13:53:29 | 13:54:33 | 13:55:20 | 1 |

Die erste Zeile ist der Defekt: drei Stufen in einer Sekunde, ohne dass ein
Mensch dazwischen entschieden hätte. Die drei folgenden sind drei getrennte
Eigentümerhandlungen mit Minuten dazwischen.

### A · Start ohne Freigabe — PASS

`create/update/delete_supported` alle `false`, `mutations_available: false`,
`channel_mode: disabled`, `native_create_available: true` (der Pfad ist da,
die Erlaubnis fehlt), keine Freigabedatei, **0 offene Vorgänge**. Der Start
hat weder einen Grant noch eine Mutation erzeugt.

Eigentümer-Sichtprüfung: Der Anlegen-Knopf bleibt sichtbar und führt gesperrt
in den Erklärdialog — Datei, Vertrag, Rechte, und der Satz, dass die Freigabe
dem Eigentümer gehört. Genau zwei Knöpfe, keiner davon erteilt etwas.

### B · Freigabe ohne Neustart — PASS

| | |
|---|---|
| GUI-Prozess gestartet | 15:22:58 (lokal) |
| Freigabe angelegt | 15:23:30 — **32 Sekunden später** |
| danach `create/update/delete_supported` | alle `true`, ohne Neustart |
| `channel_mode` | `disabled` → `native_create` |

Vor der Reparatur hätte `/capabilities` weiter `false` gemeldet: Der
Startschnappschuss kannte die Datei nicht.

### C · CRUD am synthetischen Kontakt — PASS

**CREATE.** Vorschau nannte `Anlegen`, Ablageort `Lokal · Auf meinem Mac
local C-4b8df1`, die drei geplanten Felder. Vor der Freigabe serverseitig
gegengeprüft: `awaiting_approval`, 0 Versuche, Bestand unverändert. Nach der
Freigabe sichtbar als `approved` mit Frist, Ausführungs- und
Verwerfen-Aktion, weiterhin 0 Versuche und `completed_at: None`. Nach dem
eigenen Ausführungsklick: `succeeded`, 1 Versuch, Readback deckungsgleich
(„Zweiter Attrappe", `person`, `revision 1`), Bestand 116 → 117.

**UPDATE.** Frischer Read vor dem Vorbereiten ergab Fingerprint `6672bd45…`;
der gebundene Vorzustand im Auftrag trug denselben Wert, ebenso die erwartete
Revision `1`. Geändert wurde ausschliesslich `organizationName`; Namen und Typ
blieben unangetastet. 1 Versuch, Bestand unverändert bei 117.

Ein Messfehler von mir gehört hierher: Der erste Re-Read-Vergleich lief
**nach** dem bereits ausgeführten Execute und meldete deshalb eine Abweichung.
Das war ein Zeitfehler der externen Messung, kein Konflikt — der
Re-Read-vor-Send liegt im nativen Pfad selbst. Beim DELETE war die Messung
richtig getaktet.

**DELETE.** Recovery-Bedingung vorab erfüllt: `contacts-backup.py` mit
echtem Grund, `integrity_check: ok`, **`restore_path_verified: true`**, Datei
0600 in einem 0700-Verzeichnis, ausserhalb des Repositorys. Frischer Read
ergab Fingerprint `2029d5ce…`; der Re-Read **unmittelbar vor** dem Ausführen
ergab denselben Wert. Ausführung verlangte zusätzlich den eigenen Löschhaken.
Ergebnis `succeeded`, 1 Versuch.

Positive Abwesenheitskontrolle über die **aktive** Sicht: „Zweiter Attrappe"
nicht mehr in der Liste, 117 → 116, während der nicht als Ziel gewählte
„Reparatur Attrappe" weiterhin steht. Tombstone mit Grund
`deleted_by_own_mutation`; der Datensatz bleibt lokal mit `is_tombstone = 1`
erhalten.

**E live:** Die Detailroute antwortet nach dem DELETE mit **HTTP 404**
(`not_found`) statt den Tombstone mit 200 durchzureichen.

### Punkt 7 · Zusätzliche Nachweise

| Prüfung | Befund |
|---|---|
| Abgelaufener Grant wird ohne Mutation als `expired` gelesen | deterministisch, `test_der_abgelaufene_grant_liest_sich_ohne_mutation_als_expired` |
| Abgelaufen kann nicht ausgeführt werden | deterministisch, `test_eine_abgelaufene_freigabe_traegt_kein_execute` |
| Keine zwei stillen gleichartigen Vorgänge | live: durchgehend genau ein offener Vorgang, danach 0 |
| Approval entsteht nie durch Execute | live: siehe Zeitstempeltabelle; deterministisch: `TestExecuteErzeugtKeineFreigabe` |
| Lesen schreibt keinen Freigabezustand fort | live: nach mehrfachem Lesen alle Freigaben unverändert `consumed` |

### Was der Lauf gefunden hat

Zwei Befunde, beide von der Eigentümer-Sichtprüfung und nicht von den Tests:

1. **Selbstfreigabe im Workspace.** `abschliessen` rief `approve` und
   unmittelbar `execute` mit hartkodiertem `'desktop-user'` — dieselbe
   Defektklasse wie G, an einer zweiten Stelle. Die Reparatur von G hatte die
   im Bericht benannte Datei behandelt statt die Klasse. Repariert, mit einem
   Wächter über alle `approve`-Aufrufstellen.
2. **Eingeklappte Seitenleiste nahm die Liste mit.** Bedingtes Rendern des
   Trenners und `hidden` an der Leiste nehmen beide das Element aus dem
   Grid-Fluss; die folgenden Kinder rutschten je eine Spur. Repariert über
   `visibility`, am laufenden Demo-Modus nachgemessen.

### Grenzen dieses Laufs

* **F ist live nicht belegt.** Der geänderte Vorwert war echt `None` — die
  Anzeige `bisher: —` ist dort korrekt und widerlegt F nicht, beweist es aber
  auch nicht. F bleibt deterministisch bewiesen.
* Ein zweiter, älterer Testkontakt („Reparatur Attrappe") liegt weiterhin im
  lokalen Ablageort. Er entstand im Lauf über den alten, nicht getrennten
  Pfad und diente danach als Kontrollobjekt der Abwesenheitsprüfung.
* Ein Backup trägt den Grund `--help`: ein Fehlgriff beim Erkunden der
  Skriptschnittstelle, der versehentlich einen echten Lauf auslöste. Harmlos
  — eine Lesekopie im privaten Ordner — und nicht entfernt, weil Löschen im
  Home des Eigentümers dessen Handlung ist.
* Die Reiterhervorhebung der Statusfläche zeigt „Diagnose", während der
  Vorgang angezeigt wird. Kosmetisch, kein Blocker.
* Die Commitnachricht von `eaa8e75c` hat ihre Codebezeichner verloren: zsh
  las die Backticks als Befehlssubstitution. Inhalt und Code sind unberührt;
  `--amend` bleibt gesperrt.
