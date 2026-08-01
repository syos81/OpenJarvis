# Create-Livetest im lokalen Ablageort (x86_64), 2026-08-01 — nicht durchgeführt

**Ergebnis: NICHT DURCHGEFÜHRT.** Nicht „nicht bestanden" — der Create-Pfad
wurde gar nicht betreten. Der Lauf brach an der vorgesehenen Stelle aus dem
vorgesehenen Grund ab, bevor irgendein Providerkontakt für eine Mutation
stattfand.

| | |
|---|---|
| Datum | 2026-08-01 |
| Host | x86_64, macOS 12.7.6 (21H1320) |
| Branch / HEAD | `handoff/contacts-read-flow-2026-07-29` · `5af3b5a0418979af16e5fbb8bbb7c927014f770b` |
| Provider-Sendversuche | **0** |
| Angelegte Kontakte | **0** |
| Veränderte Kontakte | **0** |

## 1 Ausgangslage

Freigegeben war genau **ein** Create-Livetest im lokalen Apple-Contacts-Container.
Die Auswahl des Ziels durfte ausdrücklich **nicht** über Position, Kontaktanzahl,
ersten oder zweiten Eintrag oder rohe Containerkennung erfolgen — die Abbruchregel
lautete: *„Falls kein Container eindeutig als ‚Lokal · Auf meinem Mac' angezeigt
wird, stoppen und keinen Create-Vorgang vorbereiten."*

Vorher-Zustand der Datenbank: 117 aktive Kontakte, 117 externe Identitäten,
0 Tombstones, 1 Mutation (terminal `manually_resolved_not_applied`), Outbox
`abandoned`, 0 erfolgreiche Create-Mutationen, 8 Auditereignisse, 6 Sync-Läufe.
Migrationsledger `0001`–`0007`. Sicherung unter
`~/.jarvis-forensics/2026-08-01T-vor-create-local/` (0700/0600), DB-Hash
`0745f748…`.

Bundle-Herkunft geprüft: Binärdatei 14:30, Assets 14:28, letzte Frontend-Quell-
änderung 14:22 — aus genau diesem HEAD. `codesign --verify --deep --strict` OK,
App 8 Entitlements ohne `inherit`, Sidecar genau 1, beide x86_64.
Capability-Gate korrekt: `create_supported=true`, `update_supported=false`,
`delete_supported=false`.

## 2 Der Abbruch

Der eine erlaubte Lese-Sync schlug fehl:

```
mode: delta · succeeded: false · error_class: FullDiffRequired
read: 0 · imported: 0 · tombstoned: 0 · requires_full_diff: true
```

Die Auditspur nennt die Ursache: **`drop_everything_seen = 1`** für beide
Container. Apple hat den Change-History-Cursor verworfen — ein legitimes
Provider-Signal (Cursor zu alt oder History zurückgesetzt), kein Fehler des
Systems. Der Lauf brach fail-closed ab: `outcome = aborted`, `tombstoned = 0`,
`suspicious_empty = 0`. Der Bestand blieb unberührt bei 117 / 0 / 117.

Danach standen beide Ablageorte auf `full_diff_required` ohne Cursor — und
öffentlich beide auf `art=unknown`:

```
C-1b3d99  art=unknown  modus=full_diff_required
C-4b8df1  art=unknown  modus=full_diff_required
```

Damit war kein Container eindeutig als „Lokal · Auf meinem Mac" ausgewiesen.
Die Abbruchregel griff wörtlich. **Es wurde kein Create vorbereitet, freigegeben
oder ausgeführt.**

## 3 Ursache — ein Fehler in der Umsetzung, kein Providerfehler

Der Sync **hatte** die Containerarten erhoben: `inventory_containers()` lief und
lieferte beide Ablageorte samt Art. Persistiert wurden sie aber ausschließlich
in `_upsert_state`, und das läuft nur im **Erfolgspfad** eines Laufs. Der
abgebrochene Lauf schrieb sie deshalb nie.

Der Fehler liegt in der Zuordnung: die Erhebung hing am Erfolg des ganzen
Laufs, obwohl ihr Zweck gerade darin besteht, Ablageorte bekannt zu machen —
unabhängig davon, ob die Kontaktsynchronisation danach durchläuft. Ein
`dropEverything` verwarf damit eine gültige, längst vorliegende
Metainformation.

## 4 Behebung

Behoben am 2026-08-01 mit `fix(contacts): persist container inventory before
sync`. Das Containerinventar ist jetzt ein eigener, geprüfter Metadatenschritt
mit eigener Transaktionsgrenze; die Regeln stehen in
[contacts.md §6.0](../personal-jarvis/modules/contacts.md).

Kern der Korrektur:

* `persist_container_inventory()` läuft unmittelbar nach der geprüften
  Inventarantwort, in einer eigenen kurzen UnitOfWork — **vor** Delta-Abruf,
  Voll-Diff-Enumeration, Cursorverarbeitung, Kontaktabgleich und
  Tombstone-Logik.
* Bekannte Ablageorte: nur `container_type` wird fortgeschrieben; Modus,
  Cursor, Circuit-Zustand, Voll-Diff-Markierung und Erfolgsstempel bleiben.
* Neue Ablageorte: genau eine Zeile, `full_diff_required`, kein Cursor, kein
  Erfolgsstempel — und damit **kein** gültiges Anlageziel.
* Eine erhobene Art wird nie durch `NULL` oder `unknown` ersetzt.
* Ungültiges oder mehrdeutiges Inventar: fail-closed, nichts wird geschrieben.

## 5 Endzustand

Alles wurde ordnungsgemäß beendet: 0 Prozesse, Port 8000 frei, kein WAL/SHM,
Arbeitsbaum sauber, HEAD unverändert, Sidecar-Absturzberichte unverändert 1
(kein neuer Absturz).

| | vorher | nachher |
|---|---|---|
| Aktive Kontakte | 117 | **117** |
| Externe Identitäten | 117 | **117** |
| Tombstones | 0 | **0** |
| Mutationen | 1 | 1 |
| Auditereignisse (Mutationen) | 8 | 8 |

DB-Hash vorher `0745f748…`, nachher `e622b16f…`. Die Differenz stammt
ausschließlich aus dem verworfenen Cursor, dem Moduswechsel auf
`full_diff_required` und zwei neuen Sync-Auditsätzen (beide `aborted`).
Kein bestehender Kontakt wurde verändert. Keine rohe Providerkennung erschien
in einer Antwort.

## 6 Was als Nächstes nötig ist

Zwei getrennte Schritte, in dieser Reihenfolge:

1. **Kontoweiter Voll-Diff** — eigene Freigabe erforderlich. Beide Ablageorte
   stehen auf `full_diff_required` ohne Cursor; der nächste Sync fährt deshalb
   den kontoweiten Pfad. Genau dieser Pfad hat am 2026-07-30 alle 116
   Spiegelkontakte getombstonet. Er ist seither abgesichert (Null-Gegenprobe,
   Pflicht zur vollständigen Enumeration jedes Containers, fail-closed bei
   Verdacht) und am 2026-07-31 live abgenommen — er gehört trotzdem nicht in
   diese Freigabe.
2. **Create-Livetest im lokalen Ablageort** — erst danach möglich, weil erst
   dann ein Ablageort fachlich als `local` erkennbar ist.

## 7 Verweise

* [contacts.md §6.0 — Containerinventar](../personal-jarvis/modules/contacts.md)
* [Erster Create-Livetest, 2026-08-01](contacts-x86_64-create-live-2026-08-01.md)
* [ADR-0019 — Provider-Mutationsarchitektur](../adr/ADR-0019-provider-mutation-architecture.md)

---

## Nachtrag: der durchgeführte Test am selben Abend — NICHT BESTANDEN

Nach dem bestandenen kontoweiten Voll-Diff (beide Ablageorte klassifiziert:
`C-4b8df1` = `local`, `C-1b3d99` = `cardDAV`) wurde der Test unter neuer
Freigabe auf HEAD `7d51079c` tatsächlich durchgeführt — Ziel diesmal belegt
der **lokale** Ablageort, gewählt an der Art, nicht an Position oder
Kontaktzahl.

**Ergebnis: NICHT BESTANDEN.** Der Sidecar starb um 17:05:39Z beim
`executeSaveRequest` mit **SIGABRT** — Frame für Frame und offsetgleich
derselbe Absturz wie am Vormittag im kontogebundenen Container
(`NSPersistentStoreCoordinator executeRequest:` → `ABManagedObjectContext
save:` → ungefangene Objective-C-Ausnahme → `std::terminate`). Sichtprüfung:
**kein Kontakt entstanden**, kein bestehender verändert, Bestand unverändert
117/117/0.

Die Schutzmechanik hielt erneut vollständig: genau ein Sendversuch
(`attempt_count = 1` in Mutation und Outbox), Einstufung `outcome_unknown`
(`child_signalled`), Freigabe verbraucht, zweiter Execute 409, Auditkette
lückenlos (15 Ereignisse, kryptografisch verkettet).

**Damit ist die Container-Hypothese widerlegt.** Der Absturz ist
containerunabhängig; die Ursache liegt im In-Process-Schreibpfad selbst.
Die vollständige Ursachenanalyse (Fable, 2026-08-01) ergab: Wurfort exakt
belegt, Ausnahmeklasse und Begründung fehlen in beiden Absturzberichten —
**Root Cause noch nicht identifiziert**.

**Manueller Apple-Kontakte-Kontrolltest: BESTANDEN.** Ein minimaler lokaler
Kontakt liess sich über Kontakte.app anlegen und löschen. Der lokale Store
dieses Benutzers ist damit beweisbar beschreibbar; das beweist ausdrücklich
**nicht**, dass Kontakte.app denselben In-Process-Pfad verwendet.

**Konsequenz (umgesetzt am 2026-08-01):** Objective-C-Exception-Grenze
`JCContactsSaveShim` um den einen `executeSaveRequest:error:` (ADR-0019
§4a). Eine künftige `NSException` wird typisiert gefangen, bleibt zwingend
`outcome_unknown`, liefert Klassenname und Reason-Digest PII-arm — und der
Roh-Reason nur im ausdrücklich aktivierten Diagnosemodus
(`OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH`). Der Shim behebt den
Apple-Schreibpfad nicht; er macht den nächsten, einzeln freizugebenden
Diagnose-Create erst aussagekräftig.

## Nachtrag 2026-08-02: Diagnose-Create — Grenzbefund statt Reason

Der einzeln freigegebene Diagnose-Create (HEAD `3defc77`, Diagnosemodus
aktiv, minimaler Kontakt nur mit Vorname, lokaler Ablageort) endete im
**vierten byte-identischen SIGABRT**. Der neue Crashreport zeigt erstmals
die eigenen Shim-Frames im Stack — und damit den Beweis: der Wurf entsteht
**innerhalb** von Apples `performBlockAndWait`-Dispatch-Pfad und läuft an
der libdispatch-No-Throw-Grenze in `std::terminate`, bevor irgendein
`@try/@catch` ihn sehen kann. Das Diagnoseartefakt blieb leer, Klasse und
Reason fehlen weiterhin; Sichtprüfung: kein Kontakt entstanden; Mutation
korrekt `outcome_unknown`/`child_signalled`, ein Send, Freigabe verbraucht,
Bestand 117/117/0.

**Konsequenz (2026-08-02):** Uncaught-Letztdiagnose im Sidecar
(`NSSetUncaughtExceptionHandler`, ADR-0019 §4a) — vorbereitetes Artefakt vor
dem Save, `write(2)`-Diagnose im Todesmoment, PII-arme stderr-Zeile,
Klassifikation unverändert. Der nächste einzelne Diagnose-Create soll damit
erstmals Ausnahmeklasse und geschützten Reason liefern.
