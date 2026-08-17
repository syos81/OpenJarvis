# Calendar — die Termine sind nicht geloescht, sie sind ueberschrieben, 2026-08-17

**Art:** Befundrecord. Korrigiert Befund B aus
`calendar-sync-tombstone-befund-2026-08-16.md`. Keine Reparatur, keine Abnahme.
**Rechner:** Apple M2, macOS 26, arm64.
**Worktree:** `~/Jarvis-Next-Everyday-Readiness`,
Branch `feature/everyday-readiness-v1-2026-08-16`, Stand `29c08fab`.
**Ausloeser:** Auftrag, Befund B zu reparieren — „wer wieder gesehen wird, ist
nicht geloescht".

> Aggregierte Angaben. Keine Termininhalte.

---

## 1. Befund B ist widerlegt

Der Vorbefund nahm an, `upsert_seen` lasse einen einmal gesetzten Grabstein
liegen. Das ist nicht so. Die Wiederbelebung steht seit `8e6e2063` im Code und
laeuft bedingungslos: `is_tombstone = 0`, `deleted_at = NULL` und ein `DELETE`
in `event_tombstones` bei **jedem** Wiedersehen
(`src/personaljarvis/calendar/repositories.py`, beide Zweige).

Gemessen an vier Sonden gegen eine migrierte Datei-Datenbank:

| Szenario | Ergebnis |
|---|---|
| Grabstein, Wiedersehen im **gleichen** Fenster | aufgehoben |
| Grabstein, Wiedersehen im **groesseren** Fenster | aufgehoben |
| Grabstein, Provider liefert den Termin **nie wieder** | bleibt (richtig so) |
| zwei Vorkommen **einer Serie** in einem Fenster | **ein Vorkommen geht verloren** |

`test_ein_wiedergesehener_termin_verliert_seinen_tombstone` deckt die Regel
bereits ab und ist gruen. Es gibt an dieser Stelle nichts zu reparieren — und
folglich auch keinen Grabstein, den eine Reparatur zum Verschwinden braechte.

## 2. Was die Termine wirklich entfernt

EventKit liefert je **Vorkommen** einen Datensatz. Alle Vorkommen einer Serie
tragen dieselbe `eventIdentifier`; der Sidecar sortiert aufsteigend nach Beginn
(`native/calendar-bridge/src/sidecar.swift`). Die Providerbindung ist aber das
Tripel Konto/Kalender/Terminkennung **ohne** den Beginn
(`event_external_ids`, Primaerschluessel in Migration 0009).

Also faellt ein ganzes Jahr in eine Zeile: liegen zwei Vorkommen derselben
Serie im Fenster, schreibt das spaeter gelesene das frueher gelesene um. Das
fruehere Vorkommen verschwindet aus der Ansicht, und weil jeder weitere Lauf
dasselbe tut, kommt es nie zurueck. Kein Grabstein beteiligt, `tombstoned = 0`,
`deletions_derivable` beliebig.

Der Widerspruch steht bereits im Quelltext: `sync.py` begruendet `series_id`
damit, die Instanz sei „erst mit ihrem Beginn eindeutig" — und bindet sie dann
ohne ihren Beginn.

## 3. Beleg auf echten Daten

Lokaler Bestand M2, ein einziger Lauf am 2026-08-14, Fenster
2026-05-16 bis 2027-08-14:

| Groesse | Wert |
|---|---|
| `events_seen` | 210 |
| `events_created` | **209** |
| `events_tombstoned` | 0 |
| `events` mit `is_tombstone = 1` | **0** |
| Zeilen in `event_tombstones` | **0** |

Die Differenz 210 zu 209 ist die Kollision, im ersten Lauf, ohne jede
Loeschableitung.

Der Abo-Kalender fuehrt hier 46 Termine, davon **22 mit `series_id`** — der
Feiertagsfeed ist also in weiten Teilen seriell, die Kollision trifft ihn.
Seine Augustverteilung: 2026-08 = 1, 2027-08 = 1.

Damit erklaert die Kollision **beide** Rechner aus derselben Regel, allein
ueber das Fensterende:

| Fensterende | 2027-08-08 im Fenster | 2027-08-15 im Fenster | 2026-08 | 2027-08 |
|---|---|---|---|---|
| M2, 2027-08-14 | ja | nein | 1 | 1 |
| Intel, 2027-08-16 | ja | ja | **0** | **2** |

Der Intel-Befund („August 2026 leer, August 2027 traegt dieselben zwei
Feiertage ein Jahr spaeter") ist genau das, was diese Regel vorhersagt. Der
Juli gehoert nicht zum Loch: er ist in beiden Bestaenden leer, auch 2027.

## 4. Der Test

`test_zwei_vorkommen_einer_serie_verdraengen_einander_nicht` in
`tests/personal/calendar/test_sync_contract.py`: ein vollstaendiger Lauf ueber
ein Fenster mit zwei Vorkommen einer Jahresserie, danach die Monatsansicht
August 2026.

```
assert len(sichtbar) == 1
E  assert 0 == 1
```

Der Test faellt am Stand `29c08fab`. Er liegt im Arbeitsbaum und ist
**nicht committet**: er gehoert zu seiner Reparatur, nicht vor sie.

## 5. Was NICHT getan wurde

- Keine Reparatur. Die beauftragte Grabstein-Reparatur waere ein Nulleingriff
  gewesen und haette die Ursache verdeckt.
- Keine Grabsteine von Hand entfernt — es gibt in diesem Bestand keine.
- Keine Migration, keine Schemaaenderung, keine produktive Mutation.
- Der Bestand auf dem Intel-Rechner wurde nicht angefasst und ist von hier aus
  nicht messbar.

## 6. Naechste Schritte

1. Entscheidung ueber die Identitaet: die Providerbindung eines Termins ist das
   Vorkommen, nicht die Serie. Das aendert den Primaerschluessel von
   `event_external_ids`, die Fensterableitung und die Adressierung im
   Schreibpfad (B3) — ein eigener Block, kein kleiner Handgriff.
2. Befund A bleibt offen und unabhaengig: `"complete": true` ist im Sidecar
   fest verdrahtet, ein leerer Abo-Read meldet Vollstaendigkeit.
3. Die Regelfrage — darf ein Lesepfad ueberhaupt loeschen — liegt beim
   Eigentuemer und ist von diesem Befund nicht praejudiziert.
