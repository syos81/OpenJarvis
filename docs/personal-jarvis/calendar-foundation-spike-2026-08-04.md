---
Status: Spike-Ergebnis (untersuchend, nicht normativ)
Zugehörige DEC-Einträge: DEC-048 (Freigabe und Grenze dieses Spikes), DEC-042, DEC-030
Zugehörige ADRs: ADR-0002, ADR-0012, ADR-0016, ADR-0018, ADR-0019, ADR-0020
Evidenz: docs/testing/calendar-read-probe-x86_64-2026-08-04.md
---

# Kalender — Fundament-Spike (Intel, 2026-08-04)

## §1 Was das hier ist, und was es nicht ist

Eine Untersuchung. Sie beantwortet die Fragen, die man beantwortet haben muss,
**bevor** man ein Kalendermodul baut — und sie baut es nicht.

**Nicht Gegenstand:** produktiver Code, Migrationen, Routen, UI-Flächen,
Termine erstellen, ändern oder löschen. Der Spike hat genau einen Zugriff auf
echte Daten gemacht, und der war lesend.

**Und er startet das Modul nicht.** 16 §4.1 sagt „kein anderes Fachmodul
beginnt parallel", und das bleibt so: Das Kontaktmodul ist auf ARM64 nicht
abgenommen (15 §8.1). Dieses Dokument ist Vorarbeit, kein Startschuss
(DEC-048).

## §2 Bestandsaufnahme — was es schon gibt

**An Kalender-Bausteinen im Personal-Teil: nichts.** Kein EventKit, kein
`EKEvent`, kein `EKCalendar` — im gesamten Repository kein einziger Treffer in
Python, Rust, Swift, Objective-C oder TypeScript. Das Kalendermodul beginnt
auf leerem Grund.

**Was daneben existiert und später kollidieren wird:**

| Ort | Was es ist | Bedeutung fürs Modul |
|---|---|---|
| `src/openjarvis/connectors/gcalendar.py` (563 Zeilen) | Upstream-Konnektor: Google Calendar über die REST-API v3, OAuth-Tokens lokal, schreibt `Document`-Objekte in den durchsuchbaren Index | **Zweiter Datenpfad.** Exakt dieselbe Altlast wie `apple_contacts.py` beim Kontaktmodul (modules/contacts.md §13.2, §16 Nr. 7). Ein Modul, das eine einzige Datenwahrheit zusichert, ist nicht fertig, solange daneben ein zweiter Weg in einen Index offen steht — die Entscheidung (deaktivieren, entfernen, umleiten) gehört in den Modulplan, nicht in diesen Spike. |
| `src/openjarvis/skills/data/calendar-prep.toml`, `agents/morning_digest.py`, `tools/digest_collect.py` | Upstream-Verbraucher von Kalenderdaten | Sie lesen heute aus dem Konnektor. Wer den Konnektor abschaltet, nimmt ihnen die Quelle — das ist Teil derselben Entscheidung. |
| 16 §2 | Kanonische Entitäten sind bereits benannt: `calendars`, `events`, `event_attendees`, `event_external_ids`, Tombstones | Der Entwurf in §7 füllt diese Namen aus, statt neue zu erfinden. |

**Vorhandenes Fundament, das das Modul erbt:** Basis-DB mit Migrations-Ledger,
Outboxes, Audit, Approvals, Egress-Guard, CredentialStore, Backup-Kern — und
die gesamte Mutations-Architektur aus ADR-0019/0020, die beim Kontaktmodul
teuer erarbeitet wurde und für Kalender gilt, ohne noch einmal erfunden zu
werden.

## §3 TCC, Signierung, Entitlements — der harte Befund

Belegt am 2026-08-04, [Bericht](../testing/calendar-read-probe-x86_64-2026-08-04.md):

1. **Ohne Entitlement gibt es keinen Dialog, sondern eine stille Ablehnung.**
   Unter Hardened Runtime verlangt macOS
   `com.apple.security.personal-information.calendars`, bevor tccd überhaupt
   fragt. Ein `NSCalendarsUsageDescription` allein genügt nicht — die App wirkt
   dann von außen wie vom Nutzer abgelehnt. Das kostet Stunden, wenn man es
   nicht weiß.
2. **Die Jarvis-App hat dieses Entitlement heute nicht.** Sie trägt das
   Kontakt-Pendant (`…personal-information.addressbook`); der Kalendereintrag
   in `frontend/src-tauri/Entitlements.plist` fehlt. **Das ist die erste
   konkrete Änderung des künftigen Moduls** — hier bewusst nicht vorgenommen,
   weil dieser Spike keinen Produktcode anfasst.
3. **Aus der Shell gestartet ist die Berechtigung wertlos.** Dort ist der
   verantwortliche Prozess das Terminal; die Probe meldete `notDetermined` und
   tccd nannte als Verantwortlichen den Elternprozess. Ein Lesebeweis „aus dem
   Terminal heraus" hätte über Jarvis nichts ausgesagt und dem Terminal eine
   breite, dauerhafte Kalenderberechtigung eingetragen.
4. **Ein Zertifikat reicht, ein Apple-Developer-Programm ist nicht nötig.** Das
   vorhandene selbstsignierte „Personal Jarvis Contacts Spike" trägt auch den
   Kalenderzugriff; die DR bleibt zertifikatsgebunden.

## §4 Wo das Lesen wohnt

Die entscheidende Messung: Das signierte Bündel startete das **nackte,
unsignierte** CLI-Binary daneben — ohne eigenes Bündel, ohne eigenes
Entitlement, ohne eigene TCC-Kennung. Es las alle 11 Kalender.

**TCC urteilt über den verantwortlichen Prozess, nicht über die Kennung des
Kindes.** Damit sind alle drei Orte technisch möglich, und die Wahl fällt aus
Gründen, nicht aus Zwang:

| Ort | dafür | dagegen |
|---|---|---|
| **App-Prozess** (EventKit direkt in Tauri) | eine Grenze weniger, kein Protokoll, kein Prozessstart je Lauf | Ein Absturz in Apples Lesepfad nimmt die GUI mit. Das Kontaktmodul hat genau das erlebt — vier byte-identische SIGABRT und eine Ausnahme, die kein `@try/@catch` erreicht. |
| **Sidecar** (langlebiger Leseprozess, von der App gestartet) | Absturz kostet einen Neustart statt der Sitzung; großer Lesevorgang blockiert nichts; identisch zur Kontakte-Leseroute, also ein Betriebsmodell statt zwei | ein Protokoll und ein Lebenszyklus mehr |
| **Einmal-Helfer je Vorgang** | maximale Isolation | für regelmäßiges Lesen zu teuer; die Isolation kauft beim Lesen wenig, weil nichts verloren gehen kann |

**Empfehlung: Sidecar für Lesen und Sync.** Sie ist keine Vorliebe, sondern die
Lehre aus dem Kontaktmodul: Ein nativer Aufruf, der sterben kann, gehört nicht
dorthin, wo Sterben teuer ist. Für spätere Schreibvorgänge bleibt der
opferbare Einmal-Helfer nach ADR-0020 die naheliegende Form — **entschieden
wird das erst mit dem Schreibauftrag**, nicht hier.

Zwei Auflagen, unabhängig vom Ort:

* Der Sidecar muss **im Bündel** liegen und mitsigniert sein. Dass ein
  unsigniertes Kind auf Intel läuft, ist ein Befund über Intel — auf Apple
  Silicon ist mindestens eine Ad-hoc-Signatur Pflicht, und Library Validation
  unter Hardened Runtime verlangt ohnehin dieselbe Kette.
* Der Elternprozess muss das Entitlement tragen (§3 Nr. 2). Das Kind braucht
  keins.

## §5 Was EventKit nicht kann — und was daraus folgt

Der teuerste Unterschied zu Kontakten:

**Es gibt keine Änderungshistorie.** `CNChangeHistoryFetchRequest` hat kein
Gegenstück. EventKit bietet nur `EKEventStoreChangedNotification` — ein
grobes „irgendetwas hat sich geändert", ohne Was, ohne Wo, ohne Cursor, ohne
Reihenfolge. Damit ist die Kernmechanik des Kontakt-Syncs (Token, Delta,
Echo-Unterdrückung über den Transaktionsautor) für Kalender **nicht
verfügbar**.

**Es gibt kein „alle Termine".** Gelesen wird immer über ein Zeitfenster
(`predicateForEvents(withStart:end:calendars:)`). Ein Kalender hat keinen
Anfang und kein Ende; das Modul muss ein Fenster wählen und dazu stehen.

**Löschungen sind nicht beobachtbar.** Ein Termin, der im nächsten Lauf fehlt,
kann gelöscht, verschoben oder aus dem Fenster gefallen sein. Diese drei Fälle
sind ohne weitere Information ununterscheidbar.

Daraus folgt der Sync-Vertrag in §8 — nicht aus Geschmack, sondern zwangsläufig.

## §6 Identität: welche Kennung was taugt

| Kennung | Was sie ist | Taugt als Schlüssel? |
|---|---|---|
| `EKCalendar.calendarIdentifier` | lokale Kalender-ID | **Ja, pro Installation.** Überlebt kein Löschen/Neuanlegen des Kontos. |
| `EKEvent.eventIdentifier` | Termin-ID; bei Serien die der **Serie**, nicht der Instanz | **Nein allein.** Serieninstanz = Kennung + Startzeitpunkt der Instanz. |
| `EKCalendarItem.calendarItemIdentifier` | lokal eindeutig je Datensatz | **Ja lokal**, aber nicht über Geräte hinweg. |
| `EKEvent.calendarItemExternalIdentifier` | die CalDAV-UID | **Nein.** Ein und dieselbe UID erscheint mehrfach — bei Einladungen liegt derselbe Termin in mehreren Kalendern. Korrelationshinweis, kein Primärschlüssel. |

Im Fenster vom 2026-08-04 gab es **null** Kollisionen und **null** fehlende
Kennungen. Das ist ein Befund über 16 Termine ohne einen einzigen Teilnehmer —
und ausdrücklich **keine** Zusage über Bestände mit Einladungen. Der Entwurf
geht deshalb vom Kollisionsfall aus, nicht vom Messwert.

**Modell:** lokaler Primärschlüssel ist eine eigene UUIDv7. Die Providerbindung
liegt in `event_external_ids` als Tripel *(provider_account, calendar_id,
provider_event_id)* mit Eindeutigkeit über das Tripel. Die CalDAV-UID kommt in
eine eigene, **ausdrücklich nicht eindeutige** Spalte — sie beantwortet „ist
das derselbe Termin wie der in deinem Kalender?", nicht „welcher Datensatz ist
das?".

## §7 Kanonisches Datenmodell (Entwurf)

Füllt die in 16 §2 bereits benannten Entitäten aus.

**`calendars`** — `id` (UUIDv7) · `workspace_id` · `provider_account_id` ·
`display_name` · `calendar_type` (`local`/`calDAV`/`exchange`/`subscription`/
`birthday`) · `source_ref` (maskiert nach außen) · `color` · `is_writable` ·
`is_subscribed` · `is_immutable` · `supports_events` · `sync_enabled` ·
Sync-/Herkunftsfelder · Tombstone.

`is_writable` ist **Provider-Wahrheit, nicht Politik**: Geburtstags- und
Abonnementkalender melden `false`, und das Modul darf das nie überstimmen. Der
Geburtstagskalender ist zusätzlich eine Projektion des Kontaktmoduls — er wird
gelesen und niemals geschrieben; wer einen Geburtstag ändern will, ändert den
Kontakt.

**`events`** — `id` · `calendar_id` · `title` · `notes` · `location` · `url` ·
`starts_at_utc` · `ends_at_utc` · `time_zone` (IANA, **nullable**) ·
`is_all_day` · `status` (`confirmed`/`tentative`/`cancelled`/`none`) ·
`availability` · `recurrence_rule_raw` · `recurrence_end` ·
`series_id` (nullable) · `is_detached` · `occurrence_start_utc` (nur bei
abgelösten Instanzen) · `has_alarms` · `alarms_raw` · `created_at` ·
`last_modified_at` · `field_digest` · Sync-/Herkunftsfelder · Tombstone.

Drei Regeln, die keine Detailfragen sind:

1. **Die Wiederholungsregel wird roh gespeichert, Instanzen sind abgeleitet.**
   Materialisierte Instanzen sind Cache und nie Wahrheit (16 §2 sagt das
   bereits). 9 von 16 Terminen im Fenster waren Serien — das ist der Normalfall,
   nicht der Sonderfall.
2. **`time_zone` darf NULL sein und bedeutet dann „schwebend".** Ganztägige und
   schwebende Termine haben keine Zone; sie nach UTC zu normalisieren
   verschiebt sie beim nächsten Ortswechsel. 12 der 16 Termine im Fenster
   hatten keine Zone.
3. **`is_all_day` ist kein Zeitraum von 00:00 bis 24:00.** Ganztägig ist eine
   eigene Art von Termin, kein besonders langer.

**`event_attendees`** — `event_id` · `contact_id` (**nullable**) ·
`raw_email` · `display_name` · `role` · `participant_status` · `is_organizer`.
Die Zuordnung zu einem Kontakt ist ein späterer, eigener Schritt und darf nie
über Namensähnlichkeit laufen — dieselbe Regel wie beim Kontakt-Abgleich.
Im gemessenen Fenster gab es null Teilnehmer; die Spalte ist damit **nicht
belegt**, nur entworfen.

**`event_external_ids`** — `event_id` · `provider_account_id` ·
`provider_calendar_id` · `provider_event_id` · `external_uid` (nicht
eindeutig) · `first_seen_at` · `last_seen_at`. Eindeutigkeit über
*(provider_account_id, provider_calendar_id, provider_event_id)*.

## §8 Sync-, Delta- und Recovery-Vertrag

Folgt zwangsläufig aus §5.

1. **Fensterbasierter Voll-Diff je Kalender** ist der Normalbetrieb, nicht der
   Notfall. Vorschlag: −90 Tage bis +365 Tage, konfigurierbar. Jeder Lauf nennt
   sein Fenster; ein Bericht ohne Fensterangabe ist wertlos.
2. **`EKEventStoreChangedNotification` ist ein Auslöser, niemals ein Delta.**
   Sie sagt „schau nach", nicht „das hat sich geändert". Wer sie als Delta
   behandelt, verliert Änderungen.
3. **Änderungserkennung über einen Felddigest je Termin**, nicht über
   `lastModifiedDate`. Der Zeitstempel kommt vom Server und ist bei CalDAV
   nicht verlässlich; der Digest ist lokal und ehrlich.
4. **Die Transaktionsgrenze ist der Kalender, nicht der Lauf.** Ein
   abgebrochener Lauf hinterlässt vollständig verarbeitete Kalender und
   unberührte — nie halb verarbeitete. Dieselbe Lehre wie beim
   Containerinventar der Kontakte (modules/contacts.md §6.0): Was belegt ist,
   darf ein Abbruch nicht verwerfen.
5. **Ein Tombstone entsteht nur unter drei Bedingungen zugleich:** der Kalender
   wurde in diesem Lauf **vollständig** gelesen, das Fenster war **unverändert**,
   und der Termin lag im Fenster. Sonst gilt „nicht gesehen" als *unbekannt* —
   ein verschobener Termin ist kein gelöschter.
6. **Fensterwechsel ist ein eigener Vorgang.** Wird das Fenster vergrößert,
   ist der erste Lauf danach ein Import ohne Löschableitung. Wird es
   verkleinert, entstehen **keine** Tombstones für das, was herausfällt.
7. **Recovery:** ein unterbrochener Lauf wird nie fortgesetzt, sondern
   wiederholt — es gibt keinen Cursor, an dem man ansetzen könnte. Der
   Wiederholungslauf ist billig, weil der Digest unveränderte Termine sofort
   erkennt.
8. **Echo-Unterdrückung** (später, mit dem Schreiben): Der Transaktionsautor
   ist bei EventKit nicht verfügbar. Eigene Änderungen müssen deshalb über den
   erwarteten Digest wiedererkannt werden — nicht über die Herkunft. Das ist
   schwächer als bei Kontakten und muss so dokumentiert werden.

## §9 Providerabstraktion

Providerneutral nach ADR-0002 — die Capability-Verträge gehören dem Fachbereich,
nicht dem Adapter. Vorgesehene Adapter: **AppleEventKit** (erster),
**CalDAV**, **ICS-Feed** (nur lesend), **Google Calendar** (die OAuth-Kette
existiert bereits).

Der Fähigkeitssatz wird **je Kalender** erhoben, nicht je Konto — im gemessenen
Bestand liegen schreibbare, abonnierte und unveränderliche Kalender
nebeneinander in derselben Installation:

```
CalendarCapabilitySet {
  can_read, can_create_events, can_update_events, can_delete_events,
  supports_recurrence, supports_attendees, supports_alarms,
  supports_free_busy, supports_time_zones,
  window_required,            // EventKit: ja. CalDAV: ja. Google: nein.
  change_feed,                // "none" | "notification" | "delta_token"
}
```

`change_feed` ist das Feld, an dem sich die Adapter am stärksten
unterscheiden: EventKit meldet `notification`, Google kann echte Delta-Token.
Der Sync-Kern muss beides bedienen, ohne den schwächeren Fall zum Standard für
alle zu machen — und ohne dem stärkeren seine Stärke zu nehmen.
**Fail-closed:** eine nicht erhobene Fähigkeit gilt als nicht vorhanden.

## §10 Feldumfang v1

Geschlossen und versioniert, nach dem Vorbild des Kontakt-Feldvertrags.

**Lesen v1:** Titel · Notiz · Ort · URL · Beginn · Ende · Zeitzone ·
ganztägig · Status · Verfügbarkeit · Wiederholungsregel (roh) · Wecker (roh) ·
Teilnehmer (Rohadresse, Anzeigename, Rolle, Zusagestatus, Organisator) ·
Erstellt/Geändert · Kalenderzugehörigkeit.

**Nicht in v1:** Anhänge · Konferenz-/Videodaten · Reisezeit · Vorschläge ·
Verfügbarkeitsabfragen über Personen · wiederkehrende Ausnahmen als eigene
bearbeitbare Objekte · Erinnerungen (`EKReminder` ist ein eigenes Modul,
16 §1) · Geburtstagskalender als Schreibziel.

**Schreiben:** in v1 **gar nicht**. Kein Feld ist als schreibbar zugesagt. Der
Schreibvertrag entsteht mit dem Schreibauftrag und erbt ADR-0019/0020
unverändert: getrennte Freigabe und Ausführung, genau ein Sendversuch,
`outcome_unknown` führt nur in den Abgleich, Löschen ist R2.

## §11 UI-Grundstruktur

Erbt die Konventionen, die im Kontaktmodul entstanden sind — und die
Korrektur, die dort gerade nötig war:

* **Drei Spalten** wie bei Kontakten: Kalenderliste · Terminliste · Detail.
* **Fenster sichtbar machen.** Die Oberfläche zeigt, welchen Zeitraum sie
  kennt. Ein Kalender, der so tut, als kenne er alles, lügt (§5).
* **Nicht schreibbare Kalender sind sichtbar nicht schreibbar** — keine
  Bearbeitungsfläche, die erst beim Speichern nein sagt. Für den
  Geburtstagskalender führt der Weg sichtbar zum Kontakt.
* **Kein Dauerreiter für Freigaben.** Eine Freigabe gehört an den Vorgang, den
  sie betrifft, im Moment der Entscheidung; „Vorgänge" erscheint nur, wenn
  etwas läuft, klemmt oder ungeklärt ist; die vollständige Historie liegt unter
  „Diagnose" (modules/contacts.md §15.2).
* **Serien werden als Serien gezeigt.** Wer eine Instanz anfasst, sieht, dass
  sie zu einer Serie gehört, bevor er etwas ändert.

## §12 Was offen bleibt

1. **ARM64 vollständig.** Keine Zeile dieses Spikes gilt für Apple Silicon
   (DEC-042). Insbesondere ist der Befund „unsigniertes Kind erbt den Zugriff"
   ein Intel-Befund; auf arm64 ist eine Signatur ohnehin Pflicht.
2. **Große Bestände.** 11 Kalender, 16 Termine. Laufzeit, Speicher und
   Fensterwahl bei tausenden Terminen sind ungemessen.
3. **Teilnehmer.** Null im gemessenen Fenster. Das Teilnehmermodell in §7 ist
   entworfen, nicht belegt.
4. **TCC-Persistenzmatrix** (Rebuild, Versions-Bump, Verschieben, Quarantäne).
5. **Der zweite Datenpfad** `gcalendar.py` — Entscheidung gehört in den
   Modulplan (§2).
6. **Risikoklassen** der Kalenderoperationen (10) und die Egress-Einstufung
   (12) sind nicht festgelegt. Termine tragen Orte, Teilnehmer und Notizen;
   die Einstufung dürfte nicht milder ausfallen als bei Kontakten.
7. **Der Modulstart selbst.** Er ist an den Abschluss des Kontaktmoduls
   gebunden (16 §4.1) und wird von diesem Dokument nicht vorweggenommen.

## §13 Was in diesem Spike verboten war — und eingehalten wurde

Kein Termin erstellt, geändert oder gelöscht. Kein Schreibaufruf im Code — ein
Test prüft die Quelle, ein zweiter das Binary. Kein produktiver Kalender-Code,
keine Migration, keine Route, keine UI-Fläche. Keine Änderung an
`Entitlements.plist` der Jarvis-App, obwohl §3 Nr. 2 sie als nötig ausweist.
Keine ARM64-Aussage. Keine Inhalte in Berichten oder Commits.
