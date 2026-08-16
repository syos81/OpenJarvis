# Calendar — ein Lesevorgang hat Termine entfernt, 2026-08-16

**Art:** Befundrecord. Keine Reparatur, keine Abnahme.
**Rechner:** Intel i7-6920HQ, macOS 12.7.6, x86_64.
**Worktree:** `~/Jarvis-Next-Everyday-Readiness`,
Branch `feature/everyday-readiness-v1-2026-08-16`.
**Ausloeser:** Eigentuemerbefund — nach einmaligem „Aktualisieren" waren die
Feiertage aus der Monatsansicht verschwunden.

> Aggregierte Angaben. Keine Termininhalte ausser den beiden vom Eigentuemer
> selbst genannten Feiertagen.

---

## 1. Was gemessen wurde

Der lokale Bestand fuehrt 11 Kalender. „Deutsche Feiertage" (`subscription`,
Quelle `subscribed`) traegt **48 Termine** — mehr als jeder andere Kalender.
Verloren ist also nichts pauschal.

Ihre zeitliche Verteilung:

```
2026-05  4     2026-10  6     2027-02  5     2027-05  6
2026-06  1     2026-11  5     2027-03  7     2027-08  2
2026-07  0     2026-12  9     2027-04  1
2026-08  0     2027-01  1
2026-09  1
```

Der belegte Bereich **2026-05 bis 2027-08** entspricht genau dem Sync-Fenster
(90 Tage zurueck, 365 vor, ab 2026-08-16). **Innerhalb** dieses Fensters liegt
ein Loch: Juli und August 2026 sind leer, waehrend Juni und September belegt
sind. Der August **2027** traegt zwei Eintraege — dieselben Feiertage ein Jahr
spaeter.

Der Eigentuemer hatte vor dem Lauf einen Bildschirmabzug: am 8. August 2026
„Fried…", am 15. August „Mari…", beide aus diesem Kalender. Genau diese
Vorkommen fehlen.

## 2. Der Provider ist unberuehrt

Der Sync liest ausschliesslich. Der produktive Lese-Sidecar ist read-only mit
Mutationssymbol-Sperre im Build (B1, DEC-069 Absatz 5). Die Apple-Kalender des
Eigentuemers sind nicht betroffen; verloren gegangen ist ausschliesslich das
lokale Abbild.

## 3. Die Ableitung selbst ist abgesichert

`src/personaljarvis/calendar/sync.py` setzt Grabsteine nur unter einer
zusammengesetzten Bedingung und begrenzt sie auf Fenster und tatsaechlich
gesehene Kennungen:

```python
result.deletions_derivable = window_result.complete and window_unchanged
if result.deletions_derivable:
    result.tombstoned = events.tombstone_absent_in_window(
        …, window=window, seen_provider_ids=seen_ids, at=at)
```

Ein unvollstaendiger Lauf leitet also nichts ab. Daraus folgt: der damalige
Read muss den Kalender als **vollstaendig** gemeldet haben, **ohne** die
Juli-/Augustvorkommen zu liefern.

## 4. Befund A — Ursache der Loeschung: OFFEN

Nicht bewiesen. Naheliegender, aber unbelegter Verdacht: „Deutsche Feiertage"
ist ein **abonnierter** Kalender. Ein Provider-Read, der einen noch nicht
materialisierten Abo-Kalender leer oder teilweise zurueckgibt und dabei nicht
scheitert, ist von „dieser Kalender hat hier keine Termine" nicht zu
unterscheiden — und genau dann greift die Ableitung. Das ist der
Empty-/No-op-Fall aus Dauerregeln §9, eine Ebene tiefer als die vorhandene
Sicherung.

Zu messen: was der Sidecar-Read fuer einen Abo-Kalender liefert und als
`complete` meldet.

## 5. Befund B — ein Grabstein wird nie aufgehoben: BEWIESEN

Am 2026-08-16 gemessen, mit gesicherter Beweislage vorher:

| Groesse | Wert |
|---|---|
| `outcome` | `completed` |
| Termine gesehen (gesamt) | 60 |
| davon „Deutsche Feiertage" | **48** |
| `created` | **0** |
| `tombstoned` | 0 |
| `deletions_derivable` | **false** fuer alle 11 Kalender |
| August-Fenster danach | **0 Feiertage** |

Der Provider liefert die Termine. Der Lauf sieht sie. Er legt keinen einzigen
wieder an, und die Ansicht bleibt leer.

Damit ist belegt: **Ein einmal gesetzter Grabstein wird nicht aufgehoben, auch
wenn derselbe Termin beim Provider nachweislich weiter existiert.**
`upsert_seen` erkennt die Zeile wieder und laesst sie als „unveraendert"
liegen — samt Grabstein. Kein noch so haeufiges Aktualisieren bringt die
Eintraege zurueck.

Das ist der schwerere der beiden Befunde: Er macht einen einmaligen
Ableitungsfehler dauerhaft und fuer den Eigentuemer unbehebbar.

## 6. Was NICHT getan wurde

- Keine Reparatur. Dieser Record stellt fest, er behebt nicht.
- Keine produktive Mutation an Apple Kalender.
- Kein Calendar DELETE.
- Grabsteine wurden nicht von Hand entfernt: der Fehler soll durch seine
  Reparatur verschwinden, nicht durch einen Handgriff, der ihn verdeckt.

## 7. Beweislage

Vor dem Messlauf gesichert: eine vollstaendige Kopie der Personal-Datenbank
und ein JSON-Auszug aller 64 Termine des Fensters, beides im
Sitzungsverzeichnis ausserhalb der Anwendung. **Fluechtig** — dieser Record
ist die dauerhafte Fassung des Befundes.

## 8. Naechste Schritte

1. Befund B reparieren: wer wieder gesehen wird, ist nicht geloescht. Klein,
   deterministisch, mit einem Test, der ohne die Reparatur faellt.
2. Befund A messen: Verhalten des Sidecar-Reads bei abonnierten Kalendern.

Beides Risk Lane — ein Lesepfad, der Daten entfernt, gehoert eingezaeunt.
