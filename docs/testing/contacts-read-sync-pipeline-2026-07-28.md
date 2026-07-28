# Kontakte Gate B — produktive Lese-Sync-Pipeline (2026-07-28)

**Gegenstand:** Initialimport, Cursorführung, Delta-Sync und Voll-Diff des
produktiven Kontakte-Moduls (Plan §6, ADR-0016, ADR-0018).

**Host:** Intel MacBook Air · macOS 12.7.6 (21H1320) · x86_64
**Branch:** `jarvis/rebuild-v1`
**Basis:** `483863041db4b5cf3f0207c62bf09bf1039b8766`

> **Dieser Auftrag war kontaktfrei.** Es wurde **kein** Sidecar gestartet,
> **kein** Kontakte-Store gelesen, **keine** Autorisierung angefordert und
> **kein** Kontakt angelegt, geändert oder gelöscht. Alle unten genannten
> Prüfungen laufen gegen eine Attrappe und erfundene Daten.

---

## 1. Herkunft der Angaben — was ich selbst geprüft habe und was nicht

Dieser Abschnitt steht bewusst vor allen Zahlen.

| Angabe | Herkunft | Von mir verifiziert |
|---|---|---|
| Testergebnisse, Codeverhalten, Gates unten | eigener Lauf auf diesem Host | **ja** |
| Struktur der Live-Antworten (§4) | Bericht der vorangegangenen Sitzung | **nein** |
| Inhalte der Live-Ergebnisdateien | — | **nein, nicht lesbar** |

**Die vier Ergebnisdateien der Intel-Live-Abnahme konnten nicht gelesen
werden.** Das Verzeichnis gehört dem Testbenutzer:

```
drwx------  6 jarvisspike  staff  /Users/Shared/PersonalJarvisContactsLive/results
```

Diese Sitzung läuft als `lukasklunder` (uid 501). Die Rechte wurden
**ausdrücklich nicht** geändert: das Live-Paket steht unter Änderungsverbot,
und die Zugriffsbeschränkung ist genau die Schutzwirkung, die dort gewollt ist.
Damit ist die Zahlenlage aus der Live-Abnahme in diesem Dokument **zugeschrieben,
nicht nachgeprüft** — und die Testfixtures übernehmen daraus ausschliesslich die
*Form* der Antworten, nie einen Inhalt.

Wer die Zahlen selbst belegen will, muss die Dateien als `jarvisspike` lesen und
das Ergebnis hier eintragen. Bis dahin bleibt §4 eine Zuschreibung.

## 2. Was implementiert wurde

Gekapselte Schicht unter `src/personaljarvis/contacts/sync/`:

| Datei | Verantwortung |
|---|---|
| `mapper.py` | `BridgeContact` → kanonische Domäne, Anzeigename, Feldzustände, Zusammenführung mit dem Bestand |
| `service.py` | Containerinventar, Initialimport, Delta, Voll-Diff, Tombstones, Cursorpersistenz, Laufergebnis |
| `state.py` | Cursorzustände, Laufarten, PII-freies `SyncRunResult` |
| `errors.py` | typisierte Fehler- und Wiederanlaufzustände |
| `echo.py` | Grundlage der Echo-Unterdrückung |

**Keine additive Migration nötig.** Das Schema aus Migration 0002/0003 trägt
bereits `contacts_sync_state` (Cursor, Schlüsselsatzversion, Modus,
Circuit-Zustand), `contact_external_ids`, `contacts_tombstones`,
`contact_field_availability` und `contacts_mutations`. Es wurde nichts
hinzugefügt, was schon da war.

Zusätzlich erweitert: `bridge/models.py`. Der Sidecar liefert seit jeher
Namenszusätze, URLs, soziale Profile, Sofortnachrichten, Beziehungen und
weitere Daten — das Python-DTO verwarf sie stillschweigend. Sie werden jetzt
übernommen. Der native Vertrag blieb dabei unverändert.

## 3. Entscheidungen, die dabei fielen

**Cursor zuerst, dann Enumeration.** Eine Änderung zwischen beiden Schritten
wird dadurch beim nächsten Delta erneut gemeldet und noch einmal angewandt.
Andersherum ginge sie verloren. Doppelt anwenden ist folgenlos, verlieren nicht.

**Kein stiller Voll-Diff.** Wird der Delta-Pfad untragfähig (`dropEverything`,
abgelehnter Cursor, Schlüsselsatzwechsel, unbekannter Ereignistyp), endet der
Lauf, der Modus `full_diff_required` wird persistiert und der Cursor verworfen.
Der Voll-Diff ist der **nächste ausdrückliche** Aufruf. Eine verdeckte
Eskalation im selben Aufruf würde einen teuren Vollabgleich unsichtbar machen.

**Löschungen nur aus einer vollständigen Enumeration.** Ohne `complete=true`
und ohne übereinstimmende Zählung wird der Lauf verworfen — kein Teilbestand,
kein Tombstone, kein neuer Cursor. Eine abgebrochene Enumeration sieht einer
geleerten Adressliste zum Verwechseln ähnlich.

**`unavailable_by_capability` ist nie leer.** Kann der Provider ein Feld nicht
liefern, behält der Bestand seinen Wert. Nur `absent` — der Provider hat
geliefert, das Feld ist leer — darf leeren. Beide Richtungen sind getestet.

**Ereigniszuordnung.** Die Änderungshistorie ist speicherweit, der Cursor je
Container. Bei genau einem Container ist jedes Ereignis eindeutig; bei mehreren
entscheidet die Containerangabe des Ereignisses, sonst die lokale Zuordnung.
Bleibt sie offen, wird nicht geraten — der Lauf verlangt den Voll-Diff.

**Miniaturbilder (Plan §10):** werden in Gate B **nicht** gespeichert. Es
existiert kein Blobspeicher, und ein S2-Rohbild gehört nicht in die kanonische
Tabelle. Geführt werden `image_available` und der Feldzustand `thumbnail`;
`thumbnail_blob_ref` bleibt `None`. Der Blob wird bereits im DTO verworfen,
damit er nicht unbemerkt in Repräsentationen und Diagnosen weiterreist.

**Me-Karte:** bleibt schreibgeschützt. Ein Aktualisierungsereignis auf sie
zählt als „unverändert"; nur Zuordnung und Feldzustände werden nachgeführt.

**Tombstone = Ereignisbeleg, nicht Zustandsflag.** Taucht ein Datensatz beim
Provider wieder auf, wird er neu importiert und der Beleg der früheren Löschung
bleibt bestehen.

**Kein Lauf ohne Aufruf.** Der Dienst startet keinen Sidecar, autorisiert nie
und kennt weder Timer noch Hintergrundlauf. `ContactsModule.sync_service()`
*stellt bereit* und *läuft nicht* — beides ist getestet.

## 4. Form der Live-Abnahme (zugeschrieben, siehe §1)

Aus der vorangegangenen Sitzung berichtet:

| Beobachtung | Wert |
|---|---|
| Container | genau einer, Typ `local` |
| Enumeration | `complete=true`, `count=1` |
| Basislauf der Historie | ein `add`, ein `dropEverything` |
| zweiter Lauf | null Ereignisse |

Übernommen wurde daraus ausschliesslich die Struktur — als Testfall
`test_form_der_live_abnahme_laeuft_durch`, mit frei erfundenen Namen,
Identifiern und Token. Der Testfall belegt insbesondere, dass der
Initialimport die Basisereignisse verwirft und nur den Cursor nimmt.

## 5. Prüfstand

| Gate | Ergebnis |
|---|---|
| `pytest tests/personal/contacts/test_sync.py` | **38 bestanden, 0 fehlgeschlagen** |
| Sidecar gestartet | nein |
| Store-Operation ausgeführt | nein |
| TCC-Dialog ausgelöst | nein |
| Live-Paket verändert | nein |
| Altes Spike-Paket verändert | nein |

Die vollständige Verifikationskette ist in §6 des Berichts zu dieser Sitzung
protokolliert.

## 6. Was ausdrücklich offen bleibt

* **§1 dieses Dokuments:** die Live-Zahlen sind nicht selbst verifiziert.
* **Mutationen** (`create`/`update`/`delete`) bleiben `not_implemented`; sie
  entstehen in Gate C über den CommandBus, nie über den Bridge-Client.
* **DEC-D17** (Auslieferungsformat) wird von dieser Arbeit nicht berührt.
* **E.164-Normalform** der Telefonnummern bleibt offen: sie verlangt eine
  Regionsannahme, die hier nicht geraten wird.
* **Auflösung von Beziehungen** auf konkrete Kontakte bleibt offen; der
  Rohname bleibt erhalten, `to_contact_id` bleibt `None`.
* **Persistenz der Audit-Ereignisse:** sie liegen im `SyncRunResult`; eine
  Audit-Tabelle existiert im Kontakte-Schema noch nicht.
