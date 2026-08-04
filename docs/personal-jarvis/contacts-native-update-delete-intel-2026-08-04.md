# Nativer Update und Delete auf x86_64, 2026-08-04

Branch `feat/contacts-update-delete-intel-2026-08-04`, Basis `9e08404`
(Create, integriert). Additive Fortschreibung von
`contacts-native-create-intel-2026-08-04.md`; kein Satz dort wurde gelöscht.
Hier steht **nur das Delta**.

## 1. Create-Integration

`handoff/contacts-read-flow-2026-07-29` per `merge --ff-only` von `f053afb`
auf **`9e08404`**. Direkter Elternteil, null Merges, ein Autor, Patch
byteidentisch zum Create-Worktree. Ohne Force gepusht.

## 2. DEC-D06 entschieden (DEC-046)

Für R2 genügt die zusätzliche In-App-Bestätigung; kein nativer
Systemdialog. Der Riegel vor der Delete-Implementierung (ADR-0019 §546,
ADR-0020 §8.3/§12) ist damit aufgelöst — additiv als Nachtrag, ohne einen
Satz oberhalb zu ändern. ADR-0014 bleibt unberührt: der ApprovalClient-
Vertrag wird **nicht** um einen Zweitdialog erweitert.

## 3. Der alte Create-Testkontakt ist bereinigt

Ein einziger normaler Lese-Sync, ausgelöst über die gepackte App (aus dem
Terminal meldet der Sidecar `notDetermined` — TCC ordnet den Zugriff dem
verantwortlichen Prozess zu, nicht dem Binary).

| Aggregat | vorher | nachher |
|---|---|---|
| Kontakte gesamt | 118 | 118 |
| **davon aktiv** | 118 | **117** |
| davon Tombstone | 0 | 1 |
| External Identities | 118 | 118 |
| Tombstone-Historie | 116 | 117 |

Zuordnung ausschliesslich über die Change-History-Kennung, kein
Provider-Write, keine Namenssuche. Zeilenweiser Vergleich gegen die
Vorher-Sicherung: **genau eine** Kontaktzeile geändert. Der Historieneintrag
trägt `provider_delete_event`; die External Identity bleibt als
Identitätsbeleg stehen.

Zwei Zahlen, die man falsch lesen könnte: `contacts_sync_audit` wächst um
**zwei** Zeilen, weil `live.py` je Container einen Lauf schreibt — ein
Request, zwei Container. Und „offene Tombstones" steht jetzt auf 1: die
Kennzahl zählt jede nicht-abgeglichene Zeile, also auch eine **korrekte**
Providerlöschung. Der Wiederherstellungsdienst rührt sie nicht an
(`RECOVERABLE_REASONS` enthält nur `absent_in_complete_enumeration`).

## 4. Der Vorher-Vergleich — das eigentliche Neue

Update und Delete ändern etwas, das schon existiert. Sie dürfen das nur,
wenn der Zustand noch der ist, den der Mensch freigegeben hat. Deshalb trägt
der Entwurf ab jetzt zwei zusätzliche Schlüssel, die bei `prepare` entstehen
und vom `payload_digest` gedeckt sind:

| Schlüssel | Inhalt |
|---|---|
| `expectedPrevious` | kanonische v1-Projektion des lokalen Zielzustands |
| `expectedFieldsDigest` | `readback_digest` genau dieser Projektion |

Der native Pfad bekommt `expectedPrevious` als JSON und vergleicht es
**strukturell** (`isEqualToDictionary:`) mit dem, was er unmittelbar vor dem
Save liest — kein Digest in Objective-C, keine zweite Kanonisierung, die
auseinanderlaufen könnte. Rust prüft zusätzlich, dass
`expectedFieldsDigest` zum mitgelieferten `expectedPrevious` passt; sonst
liesse sich der Vergleichsmassstab austauschen, ohne dass der Digest es
merkt. Weicht auch nur ein Feld ab: `not_sent / revision_conflict`, vor
jeder Übergabe.

`project_local_contact()` liefert diese Projektion. Sie ist gegen die
Wirklichkeit geprüft: für den Create-Testkontakt ergibt sie denselben Digest
`8242237e…`, den der native Read-back beim Livetest gemeldet hat.

## 5. Update

Ziel ausschliesslich über den Provider-Identifier. Nach dem Vergleich
`mutableCopy` des gelesenen Kontakts, dann **nur** die benannten Felder:

* ein fehlender Schlüssel lässt das Feld unangetastet;
* `null` (Skalar) und `[]` (Liste) löschen ausdrücklich;
* alles, was v1 nicht kennt — Notiz, Bild, Beziehungen —, trägt die Kopie
  unverändert weiter. Genau dafür gibt es sie.

Genau ein `updateContact:`, genau ein `CNSaveRequest`, Read-back über
dieselbe Kennung. Ein unbekanntes Feld oder ein Typwechsel endet als
`invalid_payload` vor dem Save.

## 6. Delete

Zusätzlich zu Ziel und Vergleich:

* **Me-Karte** ist nie ein Mutationsziel. Lässt sich die Me-Karte nicht
  ermitteln, gilt das als Nein — nicht als Ja.
* **Containerbindung** gegen die External-ID; ein fremder Container endet
  als `container_unavailable`.
* Genau ein `deleteContact:`, genau ein `CNSaveRequest`.
* Danach der **Abwesenheitsnachweis**: gezielter Fetch über die Kennung,
  lesbar **und** leer. „Nicht lesbar" ist kein Löschbeweis und endet als
  `outcome_unknown`.

Lokal danach: `is_tombstone = 1`, `deleted_at`, Historienzeile mit eigenem
Grund `deleted_by_own_mutation`. Die External Identity **bleibt** — sie ist
der Beleg, wovon der Grabstein spricht; wer sie löscht, kann eine spätere
Wiederkehr desselben Datensatzes nicht mehr erkennen.

## 7. Die zusätzliche Bestätigung (R2)

Der Claim für `delete` verlangt `confirm_delete: true` zusätzlich zur
vorausgegangenen Freigabe. Fehlt sie, antwortet die Route mit 409
`confirmation_required` — und **verbraucht keinen Versuch**: der Vorgang
bleibt `approved`, `attempt_count` bleibt 0. Ein `confirm_delete` bei einer
Nicht-Löschung ist ein Fehler, kein harmloser Zusatz.

In der Oberfläche ist es ein eigenes Kontrollkästchen mit dem Wort
„löschen" und dem Hinweis auf die Unumkehrbarkeit; der Ausführungsknopf
bleibt bis dahin gesperrt.

## 8. Capabilities

Der Standard eines Release-Builds ist unverändert: alles falsch. Die
Freigabedatei bindet **je Operation** — wer `update` freigibt, hat kein
`delete` freigegeben. Unverändert: 0600 im 0700-Ordner, kein Symlink,
Ablauf nach höchstens vier Stunden, keine Umgebungsvariable, nicht durch
Frontendangaben übersteuerbar. Die Modul-Fähigkeitsmenge leitet jetzt alle
drei Operationen aus demselben Kanal ab; der Sidecar meldet weiterhin alle
vier Schreibfähigkeiten `false`.

## 9. Kontaktfreie Tests

| Suite | Umfang |
|---|---|
| `test_native_update_delete.py` | 25 (Vorzustandsbindung, Freigabe je Operation, Löschbestätigung, Settle, Tombstone, statische Schranken) |
| `cargo test schreib_tests` | 21 (Fake-Operationen im Shim: Konflikt, Me-Karte, Container, ein Save, Patch- und Löschsemantik, Abwesenheit) |
| Frontend | 3 (Bestätigung sichtbar, Text, gesperrter Knopf) |

Alles mit Fakes, synthetischen Payloads und temporären Datenbanken.

## 10. Der Livetest hat die Architektur widerlegt — und korrigiert

### 10.1 Der Befund

Beim ersten Create der CRUD-Sequenz (13:34 Uhr) starb die gesamte App mit
SIGABRT — **im GUI-Prozess**, den ADR-0020 §10 gerade deshalb zum Save-Ort
erklärt hatte, weil der CLI-Sidecar dort deterministisch starb. Aus dem
Crashreport: Die CoreData-Ausnahme entsteht in
`NSPersistentStoreCoordinator executeRequest:` **innerhalb** von
`performBlockAndWait`, überquert die Dispatch-Grenze und endet in
`std::terminate` — sie ist von keinem `@try/@catch` erreichbar. Die
Grundannahme „im App-Prozess ist der Save sicher" ist damit widerlegt: er
ist dort nur *meistens* erfolgreich (der Vormittagslauf), aber im
Fehlerfall tödlich.

Der Eigentümer hat bei Apple nachgesehen: **kein** Kontakt entstanden — der
Save schlug atomar fehl. Der Vorgang wurde nach der Erholung als
`manually_resolved_not_applied` geschlossen (Evidenz
`manual_provider_inspection`, geschlossenes Vokabular; der Crashreport
`openjarvis-desktop-2026-08-04-133455.ips` ist hier referenziert, nicht in
der Auditspur). Auditkette lückenlos: `…provider_send_started →
outcome_unknown → mutation_outcome_manually_resolved`. Kein zweiter Send,
lokaler Bestand unverändert (117 aktiv).

### 10.2 Zweiter Befund: der Waise, der die Erholung aushebelte

Der Backendprozess (gestartet 13:32:54) **überlebte** den GUI-Absturz — die
Prozessgruppen-Kopplung greift nur beim geordneten Beenden. Der nächste
App-Start hängte sich an den Waisen, es gab keinen frischen Bootstrap, und
`recover_interrupted()` lief nie: der Vorgang stand nach dem „Neustart"
weiter auf `executing`. Nachgewiesen doppelt — an einer Kopie erholt der
Dienst korrekt, und nach SIGTERM an den Waisen plus echtem Neustart stand
der Vorgang auf `outcome_unknown / interrupted`.

**Abhilfe:** `openjarvis/server/parent_watchdog.py`. Die GUI reicht ihre
PID über `OPENJARVIS_GUI_PID` herein; der Server prüft alle zwei Sekunden
PID **und Startzeit** (PID-Wiederverwendung!) und beendet sich beim Tod des
Elternteils über den regulären SIGTERM-Pfad. `getppid()` hätte nicht
genügt: der direkte Elternteil ist `uv`, nicht die GUI. Acht Tests decken
normales Beenden, harten Absturz (SIGKILL), bereits tote GUI,
PID-Wiederverwendung und die Nicht-Fälle ab.

### 10.3 Die Korrektur: der opferbare Schreibhelfer

Wenn der Save grundsätzlich tödlich sein kann, muss er in einem Prozess
laufen, dessen Tod nichts kostet. Neu: `contacts-write-helper`, ein
eigenes, signiertes Binary im App-Bundle (Contents/MacOS, eigener
Identifier `de.kluender.jarvis.contacts-write-helper`, zertifikatsgebundene
DR mit demselben Blatt wie die App, Hardened Runtime, genau **ein**
Entitlement: Addressbook — keine der App-Lockerungen).

| Vertragspunkt | Umsetzung |
|---|---|
| Start | ausschliesslich durch die Tauri-App, `posix_spawn` — **kein** fork |
| Umfang | genau **eine** ExecutionOrder je Prozess, von stdin, größenbegrenzt |
| Torwächter | Freigabedatei, Digest, Feldvorrat, Vorzustand — **erneut** im Helfer; er vertraut der GUI nicht |
| Save | höchstens ein `CNSaveRequest` (geteilter Shim) |
| Bericht | genau einer, über stdout; nur parsbar **und** zur Order gehörig zählt |
| Tod | Marker fehlt → `not_sent / write_stack_unavailable` (beweisbar nichts übergeben); Marker da → `outcome_unknown / app_process_crash`. Nie ein zweiter Start |
| Hänger | nach 90 s wird der Helfer geopfert, nie die GUI |
| GUI-Fallback | **keiner** — ohne Helfer gibt es keinen Schreibweg; der widerlegte In-Prozess-Save ist aus dem Dispatch entfernt |

### 10.4 Diagnose je nativem Write

Der Shim schreibt unmittelbar vor der Übergabe einen `save_started`-Marker
(0600, `O_EXCL`, PII-frei: Phase und Operation). Die GUI stellt dem Helfer
zusätzlich `~/.openjarvis/personal/diagnostics` (0700) als Artefaktpfad —
bei einer gefangenen Ausnahme wie beim Uncaught-Handler entsteht dort das
0600-Artefakt mit Exceptionname und Grund (Rohgrund nur dort, öffentlich
nur der Digest). `diagnostic_artifact_present` im Bericht sagt, ob eines
entstand. Beim Absturz um 13:34 war der Diagnosepfad nicht gesetzt — genau
deshalb ist er jetzt fest verdrahtet.

### 10.5 Vertragskorrektur am Rand

Zwei Klassen aus dem Update/Delete-Pfad waren keine Vertragsklassen und
wären am Settle fail-closed gescheitert (der 0008-CHECK ist produktiv
angewandt und geschlossen): `me_card_protected` wird an der Berichtsgrenze
auf `capability_denied` abgebildet (die Schutzregel verweigert die
Operation), `unsupported_operation` auf `schema_mismatch`.

## 11. Helfer-Spike 2026-08-04 — die Isolation trägt, die Ursache liegt vor

Ein synthetischer Create über den Helfer, freigegeben und ausgeführt vom
Eigentümer. **Der Helfer starb, GUI und Backend nicht.** Genau dafür ist er
gebaut.

| Nachweis | Befund |
|---|---|
| GUI nach dem Absturz | läuft |
| Backend nach dem Absturz | läuft |
| Vorgang | `outcome_unknown / app_process_crash`, 1 Versuch, kein zweiter |
| Oberfläche | Abgleich-Angebot statt Absturzdialog |
| Marker | gesetzt → konservativ „möglicherweise gesendet" |
| Crashreport | eigener (`contacts-write-helper-2026-08-04-175233.ips`) |
| Kontakte | unverändert 117 |

### 11.1 Die Ursache, im Klartext

Das Diagnoseartefakt (0600, `diagnostics/`) nennt sie zum ersten Mal:

```
NSInternalInconsistencyException
This NSPersistentStoreCoordinator has no persistent stores (unknown).
It cannot perform a save operation.
```

Wortgleich mit den vier CLI-Sidecar-Abstürzen von 2026-08-02. Es ist
**kein** TCC- oder Signaturproblem: Der Helfer kam bis in den Save, seine
Kette trug. Das Problem ist ein anderes — und es korrigiert die Lesart von
ADR-0020 §10 ein zweites Mal:

> Nicht „App-Prozess sicher, Sidecar unsicher", sondern: **ein Prozess, der
> noch nie wirklich gelesen hat, kann nicht speichern.**

Damit fällt auch die letzte Unklarheit des Vormittags. Der Create in der GUI
gelang, weil dort vorher gelesen worden war (Autorisierung, Kontaktliste,
Sync) — die Stores hingen. Der SIGABRT um 13:34 traf einen frisch
gestarteten GUI-Prozess, in dem sofort geschrieben wurde. Der AppSave-Spike
gelang, weil er vor dem Save ein **volles Container-Inventar** zog.

### 11.2 Die Korrektur: echter Warmlauf statt Attrappen-Fetch

Der bisherige Lese-Preflight suchte eine erfundene Kennung
(`JC-CREATE-PROBE-<uuid>`). Ein solcher Fetch findet nichts — und rührt die
Stores offenbar nicht an. `JCCreateWarmUpStores` ersetzt ihn durch zwei
**echte**, read-only Lesevorgänge vor jedem Save:

1. das volle Container-Inventar (`containersMatchingPredicate:nil`),
2. eine echte Enumeration im Zielcontainer, abgebrochen nach dem ersten
   Datensatz (leeres Ergebnis zulässig, Aufzählfehler nicht).

Er gilt für alle drei Operationen: bei Create als Preflight, bei
Update/Delete im Zielabruf — schlägt er fehl, ist das Ziel „nicht lesbar",
und nicht lesbar heisst nicht schreibbar. Drei Statiktests halten fest,
dass es genau einen Warmlauf gibt, dass er vor jedem Save steht und dass die
Attrappen-Kennung verschwunden ist.

## 12. Zweiter Helfer-Spike — bestanden

Derselbe Helfer, dieselbe Signaturkette, dieselbe Nutzlast, nur mit
Warmlauf: **`succeeded`**.

| Nachweis | Befund |
|---|---|
| Vorgang | `succeeded`, 1 Versuch |
| Auditkette | 9 Stufen lückenlos, `provider_send_started` vor der Übergabe |
| Read-back-Digest | `390af260…` — **identisch** mit dem Digest des Entwurfs |
| External Identity | genau 1, lokaler Container, Kennung deckungsgleich |
| Lokale Zeile | 117 → 118 |
| Neue Diagnoseartefakte | keine |
| GUI / Backend | beide leben |

Damit ist die Ursachenkette geschlossen und erklärt **alle** bisherigen
Beobachtungen: den geglückten Vormittags-Create (GUI hatte gelesen), den
SIGABRT um 13:34 (frische GUI, sofort geschrieben), den geglückten
AppSave-Spike (zog vorher ein Container-Inventar), die vier
Sidecar-Abstürze (nackter Prozess) und den ersten Helfer-Spike (frischer
Prozess ohne echten Lesevorgang).

Der Vorgang des ersten Helfer-Spikes wurde nach Sichtprüfung des
Eigentümers als `manually_resolved_not_applied` geschlossen; 0 offene
Vorgänge.

## 13. Zwei Anzeigefehler, im Livetest aufgefallen

**Der Kanalhinweis log.** Er sagte „Provider-Schreiben deaktiviert",
während die Freigabe aktiv war — fest verdrahtet aus der Zeit, als der
Kanal konstant geschlossen war. Er folgt jetzt den Modul-Fähigkeiten
(über die Datenquelle, damit der Nullaufruf-Vertrag des Demo-Modus hält)
und nennt bei offener Freigabe die freigegebenen Operationen.

**Die Vorschau zeigte `emails: [object Object]`.** `String(wert)` scheitert
an den etikettierten Listen — ausgerechnet vor der Freigabe, wo der Mensch
prüfen soll, was er freigibt. `lesbar()` schreibt Etikett und Wert aus,
Anschriften als Komponentenkette in Vertragsreihenfolge, Datumswerte
normalisiert.

## 14. CRUD-Livetest — vollständig bestanden

Ein synthetischer Kontakt, drei Operationen, je genau eine Freigabe für
genau eine Operation. Der Eigentümer hat jede Freigabe und jede Ausführung
selbst in der App vorgenommen.

| Operation | Ergebnis | Versuche | Auditstufen |
|---|---|---|---|
| Create | `succeeded` | 1 | 9 |
| Update | `succeeded` | 1 | 9 |
| Delete | `succeeded` | 1 | 9 |

**Create.** Read-back-Digest `390af260…` identisch mit dem Digest des
freigegebenen Entwurfs; genau eine External Identity im lokalen Container;
117 → 118.

**Update.** Nachname und Organisation geändert, zweite E-Mail ergänzt.
Entscheidend sind die *nicht* genannten Felder: Vorname und Telefonnummer
blieben unangetastet — die Patch-Semantik trägt. Die E-Mails stehen in
**Positionsreihenfolge** (`work` vor `home`), wie eingegeben; vor der
Korrektur an §7 hätte der Vertrag sie alphabetisch umsortiert. Provider-
Identität unverändert.

**Delete.** Mit der zusätzlichen In-App-Bestätigung (R2, DEC-046).
Abwesenheitsnachweis durch den Helfer, danach lokal `is_tombstone = 1`,
`deleted_at`, Historienzeile mit eigenem Grund `deleted_by_own_mutation`,
External Identity **erhalten**. 118 → 117. Extern sichtgeprüft: der Kontakt
ist in Apple Kontakte unter „Auf meinem Mac" nicht mehr vorhanden.

Über alle drei: kein zweiter Sendeversuch, kein Namensabgleich, kein Sync
als Identitätsersatz, keine neuen Diagnoseartefakte, 0 offene Vorgänge.

### 14.1 Zwei Vertragsfehler, die der erste Update-Versuch aufdeckte

Der erste Update-Versuch endete als **`unsupported_field`, nichts
gesendet** — der Torwächter hat vor jeder Übergabe abgelehnt. Genau dafür
ist er da, und er hat zwei Fehler sichtbar gemacht:

1. **Der Patch trug API-Namen** (`family_name`) statt der kanonischen
   Schlüssel. Beim Create fällt das nie auf, weil der Entwurf dort durch
   den Feldvertrag läuft. Behoben mit `canonical_patch()` im Kern.
2. **Der Feldvertrag sortierte Listen** entgegen §7. Behoben in beiden
   Richtungen. Ein Test hatte die Sortierung sogar festgeschrieben („zwei
   Reihenfolgen ergeben denselben Digest") — er hat den Fehler nicht
   verhindert, sondern konserviert, und wurde auf die Vertragsaussage
   umgeschrieben.

### 14.2 Ein UI-Fehler, der Update unmöglich machte

Die Mehrwertfelder waren im API-Betrieb **hart gesperrt**
(`gesperrt={!demoModus}`) — ein Überbleibsel aus der Zeit vor dem
Update-Pfad. „E-Mail hinzufügen" tat nichts, und selbst bei Eingabe hätte
der Editor die Liste verworfen: er reichte ausschliesslich Skalarfelder an
`prepareUpdate` weiter. Die Sperre hängt jetzt an `update_supported`, der
Editor baut den vollständigen Patch (Skalare **und** ganze geänderte
Listen, v1-Listenersatz).

Auch hier zementierte ein Test den Fehlstand („kennzeichnet Mehrwertfelder
als noch nicht übertragbar"); er prüft jetzt das Gegenteil, plus einen
zweiten Fall: ohne `update_supported` gibt es gar keinen Editor.

## 15. Weiterhin offen

* **ARM64-Abnahme (Phase C)** — auf diesem Intel-Gerät nicht führbar.
* **M2-Pixelabnahme** des Frontends.
* `provider_write_enabled` bleibt standardmässig **falsch**; jeder Write
  verlangt eine ausdrückliche, ablaufende Freigabedatei je Operation.
