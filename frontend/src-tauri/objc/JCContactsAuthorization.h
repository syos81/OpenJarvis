// Schmale C-ABI für die Kontakte-Berechtigung.
//
// Warum ein Shim und nicht rohe Nachrichtenübermittlung aus Rust: die
// Korrektheit einer `msg_send!`-Kette lässt sich nicht am Quelltext beweisen —
// Rückgabetyp, BOOL-Darstellung, Blocksignatur, Retain-Semantik und
// Objektlebensdauer sind alle implizit. Hier übernimmt der Objective-C-Compiler
// diese Prüfung: er kennt die echten SDK-Header, prüft die Blocksignatur gegen
// die Deklaration und verwaltet die Lebensdauer per ARC.
//
// Der Shim darf ausschließlich den Status lesen und die Berechtigung
// anfordern. Er ruft keinen Kontakt ab und enthält keine Schreiboperation.

#ifndef JC_CONTACTS_AUTHORIZATION_H
#define JC_CONTACTS_AUTHORIZATION_H

#include <stdint.h>

#define JC_DOMAIN_CAPACITY 128
#define JC_BUNDLE_CAPACITY 256

/// PII-arme Laufzeitdiagnostik eines Autorisierungsversuchs.
///
/// Enthält ausschließlich Zustände, Zahlen und zwei Kennungen. Ausdrücklich
/// **nicht** enthalten: Pfade, `localizedDescription`, `userInfo`, Kontaktdaten.
typedef struct {
    /// CNAuthorizationStatus vor dem Aufruf (0 notDetermined … 3 authorized).
    int64_t status_before;
    /// CNAuthorizationStatus unmittelbar nach der Entscheidung.
    int64_t status_after;
    /// Verwendeter CNEntityType — aus dem Header, nicht geraten.
    int64_t entity_type;
    /// Wurde der Completion-Handler ausgeführt? 0 = Zeitüberlauf.
    int32_t callback_ran;
    /// Wie oft er ausgeführt wurde. Muss 0 oder 1 sein, nie mehr.
    int32_t callback_count;
    /// Ergebnis des Handlers.
    int32_t granted;
    /// Lag ein NSError vor?
    int32_t has_error;
    /// Numerischer Fehlercode. Nur gültig bei `has_error`.
    int64_t error_code;
    /// Lief der Systemaufruf auf dem Main Thread?
    int32_t called_on_main_thread;
    /// War die App zum Zeitpunkt des Aufrufs aktiv (im Vordergrund)?
    int32_t app_active;
    /// Trägt das Hauptbundle NSContactsUsageDescription?
    int32_t has_usage_description;
    /// Fehlerdomain, abgeschnitten. Leer, wenn kein Fehler vorlag.
    char error_domain[JC_DOMAIN_CAPACITY];
    /// Bundle-Identifier des Hauptbundles — die TCC-Identität dieses Prozesses.
    char bundle_identifier[JC_BUNDLE_CAPACITY];
} JCContactsAuthDiagnostics;

/// Liest CNAuthorizationStatus. Zeigt keinen Dialog, liest keinen Kontakt.
int64_t jc_contacts_authorization_status(void);

/// Füllt ausschließlich die Umgebungsangaben — ohne jeden Store-Aufruf.
void jc_contacts_environment(JCContactsAuthDiagnostics *out);

/// Fordert die Berechtigung an; **genau einmal**.
///
/// Muss von einem Hintergrundthread gerufen werden. Der Systemaufruf wird
/// intern auf die Main Queue gelegt — AppKit verlangt das, und ein Dialog aus
/// einem Nebenthread erscheint nicht zuverlässig. Gewartet wird auf dem
/// aufrufenden Thread, damit der Main Thread den Dialog zeichnen kann.
///
/// Der Rückgabewert ist 1, wenn der Handler binnen `timeout_seconds` lief.
int32_t jc_contacts_request_access(JCContactsAuthDiagnostics *out,
                                   double timeout_seconds);

#endif /* JC_CONTACTS_AUTHORIZATION_H */
