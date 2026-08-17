// Interaktive Eigentümerauthentisierung — die einzige Stelle im App-Prozess,
// die mit LocalAuthentication spricht.
//
// Übersetzt mit -fobjc-arc, aus denselben Gründen wie `JCContactsAuthorization`:
//
//   * Die Signatur des Reply-Blocks wird gegen den SDK-Header geprüft.
//   * BOOL ist der echte BOOL des Systems.
//   * `LAPolicyDeviceOwnerAuthentication` kommt aus dem Header, nicht aus
//     einer Zahl im Code.
//   * ARC hält Block und Zustandsbox am Leben, bis der Handler gelaufen ist —
//     auch dann, wenn der wartende Thread längst einen Zeitüberlauf gemeldet
//     hat.
//
// Was diese Datei nicht enthält: eine eigene Kennworteingabe, ein eigenes
// Geheimnis, eine Speicherung des Ergebnisses. Sie fragt das System und gibt
// ein Ja oder Nein zurück.

#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <LocalAuthentication/LocalAuthentication.h>
#import <dispatch/dispatch.h>

#include "JCOwnerAuth.h"

/// Zustand eines laufenden Versuchs — als Objekt, damit ARC die Lebensdauer
/// trägt und ein spät eintreffender Reply nicht in freigegebenen Speicher
/// schreibt.
@interface JCOwnerAuthBox : NSObject
@property(nonatomic, strong) dispatch_semaphore_t sem;
@property(atomic, assign) int32_t callbackCount;
@property(atomic, assign) BOOL succeeded;
@property(atomic, assign) BOOL hasError;
@property(atomic, assign) NSInteger errorCode;
@property(atomic, copy) NSString *errorDomain;
@end

@implementation JCOwnerAuthBox
@end

static void jc_auth_copy_string(char *ziel, size_t kapazitaet, NSString *quelle) {
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

static void jc_auth_reset(JCOwnerAuthResult *out) {
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
}

int32_t jc_owner_auth_available(JCOwnerAuthResult *out) {
    @autoreleasepool {
        jc_auth_reset(out);
        LAContext *kontext = [[LAContext alloc] init];
        NSError *fehler = nil;
        BOOL moeglich = [kontext canEvaluatePolicy:LAPolicyDeviceOwnerAuthentication
                                             error:&fehler];
        if (out != NULL) {
            out->can_evaluate = moeglich ? 1 : 0;
            out->biometry_type = (int64_t)kontext.biometryType;
            if (fehler != nil) {
                out->has_error = 1;
                out->error_code = (int64_t)fehler.code;
                jc_auth_copy_string(out->error_domain, JC_AUTH_DOMAIN_CAPACITY,
                                    fehler.domain);
            }
        }
        return moeglich ? 1 : 0;
    }
}

int32_t jc_owner_auth_require(JCOwnerAuthResult *out, const char *reason_utf8,
                              double timeout_seconds) {
    @autoreleasepool {
        jc_auth_reset(out);

        NSString *grund = nil;
        if (reason_utf8 != NULL) {
            grund = [NSString stringWithUTF8String:reason_utf8];
        }
        if (grund.length == 0) {
            // Ohne Begründung zeigt das System einen leeren Dialog. Ein
            // Dialog, der nicht sagt, wofür er steht, ist keine informierte
            // Zustimmung — also gibt es hier keinen.
            return 0;
        }

        LAContext *kontext = [[LAContext alloc] init];
        NSError *vorpruefung = nil;
        if (![kontext canEvaluatePolicy:LAPolicyDeviceOwnerAuthentication
                                  error:&vorpruefung]) {
            if (out != NULL) {
                out->can_evaluate = 0;
                out->biometry_type = (int64_t)kontext.biometryType;
                if (vorpruefung != nil) {
                    out->has_error = 1;
                    out->error_code = (int64_t)vorpruefung.code;
                    jc_auth_copy_string(out->error_domain,
                                        JC_AUTH_DOMAIN_CAPACITY,
                                        vorpruefung.domain);
                }
            }
            return 0;
        }

        JCOwnerAuthBox *box = [[JCOwnerAuthBox alloc] init];
        box.sem = dispatch_semaphore_create(0);

        // Der Dialog gehört dem Main Thread. Gewartet wird hier, damit der
        // Main Thread frei bleibt, ihn zu zeichnen.
        dispatch_async(dispatch_get_main_queue(), ^{
            [kontext evaluatePolicy:LAPolicyDeviceOwnerAuthentication
                    localizedReason:grund
                              reply:^(BOOL erfolg, NSError *_Nullable fehler) {
                                box.callbackCount += 1;
                                box.succeeded = erfolg;
                                if (fehler != nil) {
                                    box.hasError = YES;
                                    box.errorCode = fehler.code;
                                    box.errorDomain = fehler.domain;
                                }
                                dispatch_semaphore_signal(box.sem);
                              }];
        });

        dispatch_time_t frist = dispatch_time(
            DISPATCH_TIME_NOW, (int64_t)(timeout_seconds * NSEC_PER_SEC));
        long abgelaufen = dispatch_semaphore_wait(box.sem, frist);

        if (out != NULL) {
            out->can_evaluate = 1;
            out->biometry_type = (int64_t)kontext.biometryType;
            out->callback_ran = (abgelaufen == 0) ? 1 : 0;
            out->callback_count = box.callbackCount;
            out->succeeded = (abgelaufen == 0 && box.succeeded) ? 1 : 0;
            out->has_error = box.hasError ? 1 : 0;
            out->error_code = (int64_t)box.errorCode;
            jc_auth_copy_string(out->error_domain, JC_AUTH_DOMAIN_CAPACITY,
                                box.errorDomain);
        }

        // Zeitüberlauf, Abbruch, Fehler: alles ist 0. Nur ein gelaufener
        // Handler mit Erfolg ist ein Ja.
        return (abgelaufen == 0 && box.succeeded) ? 1 : 0;
    }
}
