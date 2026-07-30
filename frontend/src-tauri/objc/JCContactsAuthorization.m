// Kontakte-Berechtigung — die einzige Stelle im App-Prozess, die mit
// CNContactStore spricht.
//
// Übersetzt mit -fobjc-arc. Damit übernimmt der Compiler genau die Prüfungen,
// die bei roher Nachrichtenübermittlung aus Rust implizit geblieben wären:
//
//   * Die Blocksignatur wird gegen die Deklaration im SDK-Header geprüft.
//   * BOOL ist der echte BOOL des Systems, nicht eine nachgebaute Darstellung.
//   * `CNEntityTypeContacts` kommt aus dem Header, nicht aus einer Zahl im Code.
//   * ARC hält den Completion-Block und die Zustandsbox am Leben, bis der
//     Handler gelaufen ist — auch dann, wenn der wartende Thread längst einen
//     Zeitüberlauf gemeldet hat.
//
// Was diese Datei nicht enthält: Abrufen, Aufzählen oder Ändern von Kontakten.
// Kein CNSaveRequest, kein CNMutableContact, keine Container, kein Fetch.

#import <AppKit/AppKit.h>
#import <Contacts/Contacts.h>
#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>

#include "JCContactsAuthorization.h"

/// Zustand eines laufenden Versuchs.
///
/// Als Objective-C-Objekt, damit ARC die Lebensdauer trägt: der Completion-Block
/// hält eine starke Referenz. Nach einem Zeitüberlauf kehrt der wartende Thread
/// zurück, ohne dass der später eintreffende Handler in freigegebenen Speicher
/// schreibt — er schreibt in diese Box, die noch lebt.
@interface JCAuthBox : NSObject
@property(nonatomic, strong) dispatch_semaphore_t sem;
@property(atomic, assign) int32_t callbackCount;
@property(atomic, assign) BOOL granted;
@property(atomic, assign) NSInteger errorCode;
@property(atomic, assign) BOOL hasError;
@property(atomic, copy) NSString *errorDomain;
@property(atomic, assign) BOOL calledOnMainThread;
@property(atomic, assign) BOOL appActive;
@end

@implementation JCAuthBox
@end

static void jc_copy_string(char *ziel, size_t kapazitaet, NSString *quelle) {
    if (kapazitaet == 0) {
        return;
    }
    ziel[0] = '\0';
    if (quelle == nil) {
        return;
    }
    const char *utf8 = [quelle UTF8String];
    if (utf8 == NULL) {
        return;
    }
    strncpy(ziel, utf8, kapazitaet - 1);
    ziel[kapazitaet - 1] = '\0';
}

int64_t jc_contacts_authorization_status(void) {
    // Klassenmethode laut CNContactStore.h:74 — kein Store wird erzeugt.
    return (int64_t)[CNContactStore
        authorizationStatusForEntityType:CNEntityTypeContacts];
}

void jc_contacts_environment(JCContactsAuthDiagnostics *out) {
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
    out->entity_type = (int64_t)CNEntityTypeContacts;
    out->status_before = jc_contacts_authorization_status();
    out->status_after = out->status_before;

    NSBundle *haupt = [NSBundle mainBundle];
    jc_copy_string(out->bundle_identifier, JC_BUNDLE_CAPACITY,
                   [haupt bundleIdentifier]);
    out->has_usage_description =
        ([haupt objectForInfoDictionaryKey:@"NSContactsUsageDescription"] != nil)
            ? 1
            : 0;
}

int32_t jc_contacts_request_access(JCContactsAuthDiagnostics *out,
                                   double timeout_seconds) {
    if (out == NULL) {
        return 0;
    }
    jc_contacts_environment(out);

    JCAuthBox *box = [[JCAuthBox alloc] init];
    box.sem = dispatch_semaphore_create(0);

    // Der Systemaufruf gehört auf den Main Thread; das Warten unten läuft auf
    // dem aufrufenden Thread, damit der Main Thread frei bleibt.
    dispatch_async(dispatch_get_main_queue(), ^{
      box.calledOnMainThread = [NSThread isMainThread];
      // NSApplication darf nur vom Main Thread gelesen werden — hier ist es
      // der Main Thread.
      box.appActive = [[NSApplication sharedApplication] isActive];

      // Instanzmethode laut CNContactStore.h:86 — sie braucht einen Store.
      CNContactStore *store = [[CNContactStore alloc] init];
      [store requestAccessForEntityType:CNEntityTypeContacts
                      completionHandler:^(BOOL granted, NSError *error) {
                        // Laut Header „called on an arbitrary queue" — dieser
                        // Block macht deshalb nichts, was den Main Thread
                        // braucht.
                        box.callbackCount += 1;
                        box.granted = granted;
                        if (error != nil) {
                            box.hasError = YES;
                            box.errorCode = error.code;
                            // Nur die Domain. `localizedDescription` und
                            // `userInfo` können Pfade und private Angaben
                            // tragen und werden nicht gelesen.
                            box.errorDomain = error.domain;
                        }
                        dispatch_semaphore_signal(box.sem);
                      }];
    });

    dispatch_time_t frist = dispatch_time(
        DISPATCH_TIME_NOW, (int64_t)(timeout_seconds * NSEC_PER_SEC));
    long gewartet = dispatch_semaphore_wait(box.sem, frist);

    out->callback_ran = (gewartet == 0) ? 1 : 0;
    out->callback_count = box.callbackCount;
    out->granted = box.granted ? 1 : 0;
    out->has_error = box.hasError ? 1 : 0;
    out->error_code = (int64_t)box.errorCode;
    out->called_on_main_thread = box.calledOnMainThread ? 1 : 0;
    out->app_active = box.appActive ? 1 : 0;
    jc_copy_string(out->error_domain, JC_DOMAIN_CAPACITY, box.errorDomain);
    out->status_after = jc_contacts_authorization_status();

    return out->callback_ran;
}
