// Produktiver Kalender-Create im App-Prozess (Block B3, Position P1).
//
// **Warum hier und nicht im Sidecar.** Der Lese-Sidecar
// (native/calendar-bridge/) bleibt reiner Leser; der eine EventKit-Save lebt
// im Prozess von OpenJarvis.app, dem der TCC-Grant gehört — dieselbe
// Grenzziehung, die sich beim Kontakte-Schreibpfad (JCContactsCreate.m)
// als tragfähig belegt hat.
//
// **Was dieser Shim ist — und was nicht.** Drei schmale C-ABI-Funktionen um
// EventKit: Kalender auflösen, genau einen Save absetzen, über die gemeldete
// Kennung frisch zurücklesen. Er trifft keine Entscheidung über Freigaben,
// Wiederholungen oder Zustände — das tut der Rust-Ablauf in
// calendar_write.rs, und vor ihm der Kern.
//
// **Was er nie tut.** Berechtigungen anfordern, wiederholen, fremde Events
// lesen oder verändern, mehr als einen Save absetzen, einen Kalender selbst
// aussuchen.

#ifndef JC_CALENDAR_WRITE_H
#define JC_CALENDAR_WRITE_H

#include <stdint.h>

#define JC_CALENDAR_IDENTIFIER_CAPACITY 512
#define JC_CALENDAR_ERROR_CAPACITY 512
#define JC_CALENDAR_READBACK_CAPACITY 8192

/// Autorisierungslage dieses Prozesses für Kalenderzugriff.
/// 1 = autorisiert, 0 = alles andere (nie ein Prompt aus diesem Shim).
int32_t jc_calendar_write_authorized(void);

/// Löst einen Kalender über `calendarWithIdentifier:` auf.
/// 1 = vorhanden, 0 = nicht auffindbar.
int32_t jc_calendar_write_calendar_exists(const char *calendar_identifier);

/// Ergebnis des Speicherversuchs. Die Trennlinie ist die Sicherheitsaussage:
/// alles < Saved ist beweisbar **vor** dem Save gescheitert.
typedef enum {
    JCCalendarSaveFailedBeforeSave = 1,
    JCCalendarSaveSaved            = 2,
    JCCalendarSaveFailedInSave     = 3,
} JCCalendarSaveOutcome;

/// Baut aus einer bereits digest-geprüften Feldmenge genau ein `EKEvent`
/// und setzt genau einen `saveEvent:span:error:` (span thisEvent) ab.
/// `fields_json`: {"title","starts_at_utc","ends_at_utc","is_all_day",
/// "location","notes","time_zone"} — Daten als `YYYY-MM-DDTHH:MM:SSZ`;
/// `time_zone` ist ein IANA-Name (wird als `event.timeZone` gesetzt;
/// unbekannt ⇒ Fehler vor dem Save) oder `null` (schwebend, timeZone nil).
int32_t jc_calendar_write_save(const char *fields_json,
                               const char *calendar_identifier,
                               char *out_identifier, int32_t identifier_capacity,
                               char *out_error, int32_t error_capacity);

/// Liest ein Event über `eventWithIdentifier:` aus einem **frischen**
/// `EKEventStore` zurück — nie das gecachte Objekt des Saves.
/// 1 = gelesen (`out_json` gefüllt), 0 = nicht lesbar.
int32_t jc_calendar_write_read_event(const char *event_identifier,
                                     char *out_json, int32_t json_capacity);

/// B3 P2 (Delta-Update): setzt AUSSCHLIESSLICH die in `changes_json`
/// enthaltenen Schlüssel auf dem bestehenden Event und setzt genau einen
/// `saveEvent:span:error:` (span thisEvent) ab. Das Wörterbuch selbst ist
/// der Marker, welche Felder gesetzt werden: ein fehlender Schlüssel bleibt
/// unangetastet, `null` ist der fachliche Wert (Titel/Ort/Notiz löschen,
/// Zone schwebend). Es wird NIE ein Event aus dem Jarvis-Modell
/// rekonstruiert — geladen wird das bestehende über `eventWithIdentifier:`.
int32_t jc_calendar_write_update(const char *changes_json,
                                 const char *event_identifier,
                                 char *out_identifier, int32_t identifier_capacity,
                                 char *out_error, int32_t error_capacity);

/// B3 P2: liest die Fingerprint-Feldmenge eines Events aus einem
/// **frischen** `EKEventStore` — die sieben Vertragsfelder plus
/// `provider_calendar_id` und `event_identifier`. Exakt die Feldmenge, die
/// Rust (`fingerprint_of`) und Python (`preimage_fingerprint_of`) binden.
/// 1 = gelesen (`out_json` gefüllt), 0 = nicht lesbar.
int32_t jc_calendar_write_read_fingerprint_fields(const char *event_identifier,
                                                  char *out_json,
                                                  int32_t json_capacity);

/// B3 P3: die READ-ONLY Delete-Safety-Probe — rohe, PII-arme Fakten über
/// die am nativen Event tatsächlich belegten Eigenschaften AUSSERHALB des
/// wiederherstellbaren B3-Vertrags (Serienregeln, Teilnehmer, Organisator,
/// Wecker, URL, Geo-Ort, Geburtstagsbindung, Verfügbarkeit, Status).
/// KEINE Inhalte: nur Wahrheitswerte und Zähler. Führt NIE eine Mutation
/// aus; die Bewertung (eligible, Flags, Digest) rechnet Rust.
/// 1 = gelesen (`out_json` gefüllt), 0 = nicht lesbar.
int32_t jc_calendar_write_delete_probe(const char *event_identifier,
                                       char *out_json, int32_t json_capacity);

/// B3 P3: löscht GENAU EIN Event über `removeEvent:span:error:`
/// (span thisEvent, sofortiger Commit). Kein Fallback, kein zweiter
/// Versuch. Die Trennlinie ist dieselbe wie beim Save: alles < Saved ist
/// beweisbar VOR der Übergabe gescheitert.
int32_t jc_calendar_write_delete(const char *event_identifier,
                                 char *out_error, int32_t error_capacity);

#endif
