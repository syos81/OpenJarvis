//  JCCalendarWrite.m — produktiver Kalender-Create im App-Prozess (B3 P1).
//
//  Bewusst schmaler als JCContactsCreate.m: Der Ablauf (Validierung,
//  Berichtsbau, Fake-Betrieb) liegt vollständig in Rust
//  (src/calendar_write.rs); hier stehen nur die drei Operationen, die
//  EventKit wirklich brauchen. Jede Funktion baut ihren eigenen
//  `EKEventStore` — Kennungen sind datenbankweit gültig, und der Read-back
//  soll gerade NICHT das gecachte Event des Save-Stores wiedersehen.

#import "JCCalendarWrite.h"

#import <EventKit/EventKit.h>
#import <Foundation/Foundation.h>
#import <string.h>

// ── Hilfen ──────────────────────────────────────────────────────────────────

static void JCCalCopy(char *dst, int32_t cap, NSString *_Nullable src) {
    if (dst == NULL || cap <= 0) { return; }
    dst[0] = '\0';
    if (src == nil) { return; }
    const char *utf8 = src.UTF8String;
    if (utf8 == NULL) { return; }
    strlcpy(dst, utf8, (size_t)cap);
}

/// Ein Formatter je Aufruf, fest auf UTC: `2026-08-09T12:00:00Z`.
/// NSISO8601DateFormatter statt NSDateFormatter, weil er das eine
/// Vertragsformat ohne Locale-Fallstricke liest und schreibt.
static NSISO8601DateFormatter *JCCalFormatter(void) {
    NSISO8601DateFormatter *f = [[NSISO8601DateFormatter alloc] init];
    f.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    f.formatOptions = NSISO8601DateFormatWithInternetDateTime;
    return f;
}

static NSString *_Nullable JCCalString(const char *_Nullable c) {
    if (c == NULL) { return nil; }
    return [NSString stringWithUTF8String:c];
}

/// Ein Feld, das im JSON `null` sein darf: `NSNull` wird zu `nil`.
static NSString *_Nullable JCCalOptionalString(NSDictionary *dict, NSString *key) {
    id wert = dict[key];
    if (![wert isKindOfClass:[NSString class]]) { return nil; }
    return (NSString *)wert;
}

// ── Operationen ─────────────────────────────────────────────────────────────

int32_t jc_calendar_write_authorized(void) {
    // SDK 13.x: `Authorized` (Rohwert 3) ist der volle Zugriff; das
    // macOS-14-Enum `FullAccess` trägt denselben Rohwert. Kein Prompt hier —
    // die Autorisierung besorgt der bestehende Leseweg.
    EKAuthorizationStatus status =
        [EKEventStore authorizationStatusForEntityType:EKEntityTypeEvent];
    return status == EKAuthorizationStatusAuthorized ? 1 : 0;
}

int32_t jc_calendar_write_calendar_exists(const char *calendar_identifier) {
    NSString *ident = JCCalString(calendar_identifier);
    if (ident.length == 0) { return 0; }
    EKEventStore *store = [[EKEventStore alloc] init];
    return [store calendarWithIdentifier:ident] != nil ? 1 : 0;
}

int32_t jc_calendar_write_save(const char *fields_json,
                               const char *calendar_identifier,
                               char *out_identifier, int32_t identifier_capacity,
                               char *out_error, int32_t error_capacity) {
    if (out_identifier != NULL && identifier_capacity > 0) { out_identifier[0] = '\0'; }
    if (out_error != NULL && error_capacity > 0) { out_error[0] = '\0'; }

    NSString *json = JCCalString(fields_json);
    NSString *calIdent = JCCalString(calendar_identifier);
    if (json.length == 0 || calIdent.length == 0) {
        JCCalCopy(out_error, error_capacity, @"empty_input");
        return JCCalendarSaveFailedBeforeSave;
    }
    NSError *parseError = nil;
    id parsed = [NSJSONSerialization
        JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding]
                   options:0
                     error:&parseError];
    if (![parsed isKindOfClass:[NSDictionary class]]) {
        JCCalCopy(out_error, error_capacity, @"fields_not_an_object");
        return JCCalendarSaveFailedBeforeSave;
    }
    NSDictionary *felder = (NSDictionary *)parsed;

    NSISO8601DateFormatter *formatter = JCCalFormatter();
    NSString *startText = JCCalOptionalString(felder, @"starts_at_utc");
    NSString *endeText = JCCalOptionalString(felder, @"ends_at_utc");
    NSDate *start = startText != nil ? [formatter dateFromString:startText] : nil;
    NSDate *ende = endeText != nil ? [formatter dateFromString:endeText] : nil;
    if (start == nil || ende == nil) {
        JCCalCopy(out_error, error_capacity, @"unparseable_dates");
        return JCCalendarSaveFailedBeforeSave;
    }

    // Zeitzonenanker (B3-P1-Korrektur): ein IANA-Name wird TATSÄCHLICH als
    // `event.timeZone` gesetzt — die UTC-Zone des Formatters allein verankert
    // nichts am Event. Ein Name, den die Zonendatenbank nicht kennt, fällt
    // beweisbar VOR dem Save; `null` heisst bewusst schwebend (timeZone nil).
    NSString *zonenName = JCCalOptionalString(felder, @"time_zone");
    NSTimeZone *zone = nil;
    if (zonenName != nil) {
        zone = [NSTimeZone timeZoneWithName:zonenName];
        if (zone == nil) {
            JCCalCopy(out_error, error_capacity, @"unknown_time_zone");
            return JCCalendarSaveFailedBeforeSave;
        }
    }

    EKEventStore *store = [[EKEventStore alloc] init];
    EKCalendar *kalender = [store calendarWithIdentifier:calIdent];
    if (kalender == nil) {
        JCCalCopy(out_error, error_capacity, @"calendar_vanished_before_save");
        return JCCalendarSaveFailedBeforeSave;
    }

    EKEvent *event = [EKEvent eventWithEventStore:store];
    event.calendar = kalender;
    event.title = JCCalOptionalString(felder, @"title");
    event.startDate = start;
    event.endDate = ende;
    event.allDay = [felder[@"is_all_day"] isKindOfClass:[NSNumber class]]
                       ? [felder[@"is_all_day"] boolValue]
                       : NO;
    event.location = JCCalOptionalString(felder, @"location");
    event.notes = JCCalOptionalString(felder, @"notes");
    if (zone != nil) {
        event.timeZone = zone;
    }

    NSError *saveError = nil;
    BOOL gespeichert = NO;
    @try {
        // Genau EIN Save, span thisEvent, sofortiger Commit. Wirft EventKit
        // hier, ist der Save uebergeben worden — der Ausgang ist ungewiss,
        // nie ein zweiter Versuch.
        gespeichert = [store saveEvent:event span:EKSpanThisEvent commit:YES
                                 error:&saveError];
    } @catch (NSException *ausnahme) {
        JCCalCopy(out_error, error_capacity,
                  [NSString stringWithFormat:@"exception:%@", ausnahme.name]);
        return JCCalendarSaveFailedInSave;
    }
    if (!gespeichert) {
        NSString *beschreibung = saveError != nil
            ? [NSString stringWithFormat:@"%@:%ld", saveError.domain,
                                         (long)saveError.code]
            : @"save_returned_no";
        JCCalCopy(out_error, error_capacity, beschreibung);
        return JCCalendarSaveFailedInSave;
    }
    NSString *kennung = event.eventIdentifier;
    if (kennung.length == 0) {
        // Gespeichert, aber ohne Kennung nicht adressierbar: der Rust-Ablauf
        // macht daraus `unknown`, nie `applied`.
        JCCalCopy(out_error, error_capacity, @"identifier_missing_after_save");
        return JCCalendarSaveFailedInSave;
    }
    JCCalCopy(out_identifier, identifier_capacity, kennung);
    return JCCalendarSaveSaved;
}

int32_t jc_calendar_write_read_event(const char *event_identifier,
                                     char *out_json, int32_t json_capacity) {
    if (out_json != NULL && json_capacity > 0) { out_json[0] = '\0'; }
    NSString *ident = JCCalString(event_identifier);
    if (ident.length == 0) { return 0; }

    // Frischer Store: der Beleg soll aus der Datenbank kommen, nicht aus dem
    // Objektcache des Save-Stores.
    EKEventStore *store = [[EKEventStore alloc] init];
    EKEvent *event = [store eventWithIdentifier:ident];
    if (event == nil) { return 0; }

    NSISO8601DateFormatter *formatter = JCCalFormatter();
    NSDictionary *dict = @{
        @"title": event.title ?: [NSNull null],
        @"starts_at_utc": event.startDate != nil
            ? [formatter stringFromDate:event.startDate] : [NSNull null],
        @"ends_at_utc": event.endDate != nil
            ? [formatter stringFromDate:event.endDate] : [NSNull null],
        @"is_all_day": @(event.allDay),
        @"location": event.location ?: [NSNull null],
        @"notes": event.notes ?: [NSNull null],
        // Der Anker des GELESENEN Events: nil = schwebend, nie eine Vorgabe.
        @"time_zone": event.timeZone.name ?: [NSNull null],
        @"provider_calendar_id": event.calendar.calendarIdentifier ?: [NSNull null],
    };
    NSError *jsonError = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:dict options:0
                                                     error:&jsonError];
    if (data == nil) { return 0; }
    NSString *json = [[NSString alloc] initWithData:data
                                           encoding:NSUTF8StringEncoding];
    if (json == nil) { return 0; }
    JCCalCopy(out_json, json_capacity, json);
    return 1;
}
