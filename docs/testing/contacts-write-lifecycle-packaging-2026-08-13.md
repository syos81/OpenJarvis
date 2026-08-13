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
