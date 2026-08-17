// Schmale C-ABI für die interaktive Eigentümerauthentisierung.
//
// Derselbe Schnitt wie bei `JCContactsAuthorization`: Der Systemaufruf lebt in
// Objective-C, wo der Compiler Blocksignatur, BOOL-Darstellung und
// Enum-Werte gegen die echten SDK-Header prüft und ARC die Lebensdauer von
// Block und Zustandsbox trägt. Aus Rust wäre all das implizit geblieben.
//
// Verwendet wird `LAPolicyDeviceOwnerAuthentication` — die Systemfunktion
// „Geräteeigentümer authentisieren". Sie zeigt auf diesem Rechner Touch ID und
// fällt selbsttätig auf das Anmeldekennwort zurück. Ausdrücklich **keine**
// jarvis-eigene PIN und kein jarvis-eigenes Kennwort: Die Authentisierung
// bleibt beim Betriebssystem, und Jarvis sieht weder Fingerabdruck noch
// Kennwort, sondern ausschliesslich ein Ja oder Nein.
//
// Was dieser Shim nicht ist: ein Herkunftsnachweis. Er belegt, dass **dieser**
// Weg eine Eigentümerhandlung verlangt hat. Er sagt nichts darüber, was ein
// anderer Prozess unter derselben Benutzerkennung tun kann.

#ifndef JC_OWNER_AUTH_H
#define JC_OWNER_AUTH_H

#include <stdint.h>

#define JC_AUTH_DOMAIN_CAPACITY 128

/// PII-arme Laufzeitdiagnostik eines Authentisierungsversuchs.
///
/// Enthält ausschliesslich Zustände und Zahlen. Ausdrücklich **nicht**
/// enthalten: Benutzername, `localizedDescription`, `userInfo`, biometrische
/// Angaben jeder Art.
typedef struct {
    /// Konnte die Richtlinie überhaupt ausgewertet werden (Gerät gesperrt,
    /// keine Anmeldedaten hinterlegt, Richtlinie nicht verfügbar)?
    int32_t can_evaluate;
    /// Wurde der Reply-Block ausgeführt? 0 = Zeitüberlauf.
    int32_t callback_ran;
    /// Wie oft er ausgeführt wurde. Muss 0 oder 1 sein, nie mehr.
    int32_t callback_count;
    /// Ergebnis: 1 = der Eigentümer hat sich authentisiert.
    int32_t succeeded;
    /// Lag ein NSError vor?
    int32_t has_error;
    /// Numerischer Fehlercode. Nur gültig bei `has_error`.
    /// `-2` ist Abbruch durch den Benutzer, `-4` Abbruch durch das System.
    int64_t error_code;
    /// Welche Biometrie das Gerät führt (LABiometryType): 0 keine, 1 Touch ID,
    /// 2 Face ID. Reine Diagnostik — die Richtlinie erlaubt in jedem Fall
    /// auch das Kennwort.
    int64_t biometry_type;
    /// Fehlerdomain, abgeschnitten. Leer, wenn kein Fehler vorlag.
    char error_domain[JC_AUTH_DOMAIN_CAPACITY];
} JCOwnerAuthResult;

/// Fragt, ob die Richtlinie ausgewertet werden könnte. Zeigt keinen Dialog.
int32_t jc_owner_auth_available(JCOwnerAuthResult *out);

/// Verlangt die Authentisierung des Geräteeigentümers; **genau einmal**.
///
/// Muss von einem Hintergrundthread gerufen werden. Der Systemaufruf wird
/// intern auf die Main Queue gelegt — AppKit verlangt das, und ein Dialog aus
/// einem Nebenthread erscheint nicht zuverlässig. Gewartet wird auf dem
/// aufrufenden Thread, damit der Main Thread den Dialog zeichnen kann.
///
/// `reason_utf8` ist der Text, den das System im Dialog zeigt. Er wird nicht
/// protokolliert.
///
/// Der Rückgabewert ist 1, wenn der Eigentümer sich authentisiert hat — und
/// nur dann. Zeitüberlauf, Abbruch und Fehler sind alle 0: Es gibt keinen
/// Zweig, der im Zweifel öffnet.
int32_t jc_owner_auth_require(JCOwnerAuthResult *out, const char *reason_utf8,
                              double timeout_seconds);

#endif /* JC_OWNER_AUTH_H */
