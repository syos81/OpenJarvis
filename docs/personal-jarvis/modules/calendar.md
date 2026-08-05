---
Status: normativ (Modulunterlage, in Arbeit)
Zugehörige ADRs: ADR-0002, ADR-0012, ADR-0016 (Sidecar-Muster), ADR-0018
Zugehörige DEC-Einträge: DEC-042, DEC-045, DEC-048
Baseline: [calendar-implementation-baseline-2026-08-04](../calendar-implementation-baseline-2026-08-04.md)
Evidenz: [calendar-read-probe-x86_64-2026-08-04](../../testing/calendar-read-probe-x86_64-2026-08-04.md)
---

# Kalender — Modul 2, Implementierungsstand

## §1 Was gebaut ist (Block 1, 2026-08-05)

Ein vertikaler Leseblock durch alle Schichten. **Freigegeben vom Eigentümer am
2026-08-05** als ausdrücklicher Vorgriff auf die noch offene M2-arm64-Abnahme
des Kontaktmoduls (16 §4.1); die Kontakte-Gates aus DEC-050 bleiben unberührt.

| Schicht | Ort | Zustand |
|---|---|---|
| Entitlement | `frontend/src-tauri/Entitlements.plist` | `…personal-information.calendars` ergänzt |
| Sidecar | `native/calendar-bridge/` | Swift, JSON-Lines, **nur lesend** |
| Signierung | `CalendarSidecar.entitlements`, `scripts/reseal-contacts-sidecar.sh` | eigener Vertrag, ein Eintrag |
| Bau | `native/calendar-bridge/build.sh`, `scripts/build-calendar-sidecar.sh` | je Architektur, `minos 12.3` |
| Protokoll | `native/calendar-bridge/PROTOCOL.md` | v1, geschlossene Fehlermenge |
| Bridge (Python) | `src/personaljarvis/calendar/bridge/` | DTOs, Client, Vertrag |
| Domäne | `src/personaljarvis/calendar/domain.py` | Felddigest, Fensterregeln |
| Schema | Migration `0009` | `calendars`, `events`, `event_attendees`, `event_external_ids`, Tombstones, Fenster- und Laufprotokoll |
| Sync | `src/personaljarvis/calendar/sync.py` | fensterbasierter Voll-Diff je Kalender |
| API | `src/personaljarvis/calendar/api.py` | `/v1/personal/calendar/*` |
| UI | `frontend/src/personal/calendar/` | drei Spalten, Jahr/Monat/Woche/Tag |

## §2 Gemeinsame Primitive statt zweiter Infrastruktur

Prozessführung, Binärauflösung, JSON-Lines-Hülle und Fehlerklassen sind aus
`contacts.bridge` nach `base/sidecar/` **gehoben** worden, als der Kalender
denselben Vertrag brauchte — nicht vorsorglich (AV-33). `contacts.bridge`
re-exportiert unverändert; die Typen sind identisch, nicht kopiert (ein
`except BridgeError` fängt in beiden Modulen dasselbe Objekt).

Der Kalender importiert **keinen** Kontakte-Code (Modulgrenze, Statiktest) und
teilt sich die `ConnectionFactory` des Bootstraps — zwei Factories auf
derselben Datei wären zwei Schreiber (07 §5).

## §3 Der Sync-Vertrag

Er folgt zwangsläufig daraus, was EventKit **nicht** kann: keine
Änderungshistorie, kein „alle Termine", keine beobachtbaren Löschungen.

1. **Fensterbasierter Voll-Diff je Kalender** ist der Normalbetrieb. Jeder Lauf
   nennt sein Fenster; das Laufprotokoll speichert es mit.
2. **`EKEventStoreChangedNotification` ist ein Auslöser, nie ein Delta.**
   Deshalb meldet die Fähigkeitsmenge `change_feed: "notification"`.
3. **Änderungserkennung über den Felddigest**, nicht über
   `lastModifiedDate` — der Zeitstempel kommt vom Server und ist bei CalDAV
   nicht verlässlich.
4. **Die Transaktionsgrenze ist der Kalender, nicht der Lauf.** Ein
   abgebrochener Lauf hinterlässt vollständig verarbeitete Kalender und
   unberührte, nie halb verarbeitete.
5. **Ein Tombstone entsteht nur unter drei Bedingungen zugleich:** der Kalender
   wurde vollständig gelesen, das Fenster war unverändert, und der Termin lag
   im Fenster. Sonst gilt „nicht gesehen" als *unbekannt*.
6. **Fensterwechsel ist ein eigener Vorgang** — Vergrössern ist ein Import ohne
   Löschableitung, Verkleinern erzeugt keine Tombstones.
7. **Ein unterbrochener Lauf wird wiederholt, nie fortgesetzt.** Es gibt keinen
   Cursor. Der Wiederholungslauf ist billig, weil der Digest unveränderte
   Termine sofort erkennt.

## §4 Was v1 ausdrücklich nicht tut

**Schreiben.** Kein Feld ist als schreibbar zugesagt. Das ist zweifach
abgesichert: ein Test liest die Sidecar-Quelle, und `build.sh` sucht im
**gebauten Binary** nach EventKit-Schreibselektoren und bricht bei einem Fund
ab. Ein Versprechen, das nur im Quelltext steht, ist keines.

Ebenfalls nicht enthalten: Erinnerungen (eigenes Modul, 16 §1), Zuordnung von
Teilnehmern zu Kontakten, Drag-and-drop, Kontextmenüs, Konferenzdaten,
Anhänge, Reisezeit, Verfügbarkeitsabfragen.

## §5 Berechtigung

Unter Hardened Runtime verlangt macOS `com.apple.security.personal-information.calendars`,
**bevor** tccd überhaupt fragt; ohne das Entitlement gibt es keine Ablehnung
durch den Menschen, sondern eine stille durch die Richtlinie. Das Entitlement
trägt der **Elternprozess**; TCC urteilt über den verantwortlichen Prozess,
nicht über die Kennung des Kindes.

Der Status wird über den **Rohwert** ermittelt, nicht über Enum-Fälle:
`.fullAccess` existiert im macOS-13.1-SDK nicht, teilt sich mit `.authorized`
aber den Wert 3; neu ist allein `.writeOnly` (4). Genau hier scheiterte der
alte Jarvis-Kalender auf macOS 14 — sein `@unknown default` meldete jeden neuen
Wert als `unknown`, worauf das authorized-Gate trotz erteiltem Vollzugriff
schloss. Die macOS-14-API wird zur Laufzeit über den Selektor gesucht, sodass
**ein** Quelltext auf beiden SDK-Ständen baut.

**`write_only` gilt nie als Leseberechtigung.**

## §6 Übernahme aus dem alten Jarvis

Nach Baseline §3 übernommen: die Rasterlogik samt ihrer Prüfungen
(`frontend/src/personal/calendar/raster.ts`, 37 Tests), die Gate-Reihenfolge,
die strikte Antwortvalidierung, die Ehrlichkeitsregeln der Oberfläche und die
Trennung von Beobachtung und Entscheidung.

Beim Parametrisieren der Zeitzone (B-7) kam ein **latenter Fehler** der
geerbten Rasterlogik zum Vorschein: `lokaleMitternachtUtc` addierte den
Tagesversatz mit falschem Vorzeichen und lag damit bei jeder Zone **westlich
von UTC** um zwei Tage daneben. Im alten Jarvis fiel das nie auf, weil dort
fest `Europe/Berlin` stand. Der Fehler ist behoben, ein Test hält ihn fest.

## §7 Prüfstand (2026-08-05, Intel x86_64, macOS 12.7.6)

| Gate | Ergebnis |
|---|---|
| `pytest tests/personal` | 1185 grün, 85 übersprungen, **1 rot** (vorbestehend, siehe §8) |
| Kalender-Suite | 50 grün (Sync-Vertrag 27, Grenzen 23) |
| `vitest run` (Frontend) | 216 grün, davon 65 Kalender |
| `tsc --noEmit` | grün |
| `ruff` (neuer Code) | grün |
| Sidecar-Bau | grün, `minos 12.3`, keine Schreibselektoren im Binary |
| Kalenderfreier Handshake gegen das echte Binary | grün (`ready`, `ping`, `caps`, `shutdown`) |

**Ohne Berechtigung verhält sich der Lauf fail-closed:** `outcome: failed`,
kein Datensatz geschrieben, kein Tombstone abgeleitet.

## §8 Offen — nichts davon gilt als bestanden

1. **Echter Lesedurchlauf aus der gepackten App** auf **beiden**
   Architekturen. Aus dem Terminal gestartet ist der verantwortliche Prozess
   das Terminal; ein Lesebeweis von dort sagte über Jarvis nichts aus und
   trüge dem Terminal eine breite, dauerhafte Kalenderberechtigung ein.
2. **ARM64 vollständig.** Keine Zeile dieses Blocks gilt für Apple Silicon
   (DEC-042). Insbesondere ist „unsigniertes Kind erbt den Zugriff" ein
   Intel-Befund.
3. **TCC-Persistenzmatrix** (Rebuild, Versions-Bump, Verschieben, Quarantäne).
4. **Grosse Bestände.** Laufzeit, Speicher und Fensterwahl bei tausenden
   Terminen sind ungemessen.
5. **Teilnehmer im Echtbetrieb.** Das Modell ist gebaut und getestet, im
   gemessenen Fenster gab es null Teilnehmer.
6. **Der Apple-Paritätsvertrag P-1…P-15** ist erst teilweise erfüllt und
   **nirgends visuell gegen die M2-Referenz verglichen**. Offen sind
   insbesondere Drag-and-drop mit Freigabe (P-7), Serienbearbeitung (P-9),
   Kontextmenüs (P-12) und der vollständige Barrierefreiheits-Audit (P-13).
7. **Schreiben** — eigener Auftrag, erbt ADR-0019/0020 unverändert.
8. **Der zweite Datenpfad `gcalendar.py`** ist unberührt; der Ablöseplan steht
   in Baseline §5.
9. **ADR-Nummernkollision 0019/0020** unverändert offen (Baseline §6).
10. **Vorbestehend rot:** `test_dec_045_ist_registriert` prüft eine Zählung im
    Entscheidungsregister („44 akzeptierte Entscheidungen") und schlägt auch
    ohne diesen Block fehl.
