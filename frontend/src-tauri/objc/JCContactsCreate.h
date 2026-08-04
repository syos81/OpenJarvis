// Produktiver Create-Pfad im App-Prozess (ADR-0020 §8.1, Phase B).
//
// **Warum hier und nicht im Sidecar.** Fünf Livetests auf macOS 12.7.6
// haben gezeigt: derselbe minimale `CNSaveRequest` stirbt im nackten
// CLI-Sidecar deterministisch an einem `NSPersistentStoreCoordinator` ohne
// angehängte Stores, während er im Prozess von Jarvis.app speichert. Der
// App-Prozess ist der einzige Prozess dieses Systems, dem der TCC-Grant
// gehört und der nachweislich produktiv mit Contacts.framework spricht.
// Seit ADR-0020 hat der Sidecar deshalb gar keinen Schreibpfad mehr.
//
// **Was dieser Shim ist — und was nicht.** Er ist die schmale
// Objective-C-Grenze um genau einen Speichervorgang: Er nimmt eine bereits
// validierte, digest-gebundene Nutzlast und einen ausdrücklichen
// Zielcontainer entgegen, baut daraus genau einen `CNMutableContact`,
// führt genau einen `CNSaveRequest` aus und liest das Ergebnis über die
// **gemeldete Kennung** zurück. Er trifft keine Entscheidung: nicht über
// Freigaben, nicht über Zustände, nicht über Wiederholungen. Wer entscheidet,
// ist der Kern.
//
// Er ist ausdrücklich **kein** Spike: kein fester Payload, keine feste
// Zielwahl, keine Environment-Schalter, keine Testphrase, keine Nonce, keine
// eigene Zustandsmaschine, keine eigene Bundle-Kennung.
//
// **Was er nie tut.** Berechtigungen anfordern (nur lesen), wiederholen,
// fremde Kontakte lesen oder verändern, mehr als einen Save absetzen, einen
// Container selbst aussuchen, ein nicht freigegebenes Feld schreiben.

#ifndef JC_CONTACTS_CREATE_H
#define JC_CONTACTS_CREATE_H

#include <stdint.h>

#define JC_CREATE_DOMAIN_CAPACITY 128
#define JC_CREATE_NAME_CAPACITY 65
#define JC_CREATE_DIGEST_CAPACITY 65
#define JC_CREATE_IDENTIFIER_CAPACITY 512
#define JC_CREATE_READBACK_CAPACITY 32768

/// Geschlossene Ergebnismenge. Die Reihenfolge folgt dem Ablauf: alles vor
/// `Applied` ist beweisbar **vor** dem Save gescheitert, alles danach ist
/// mindestens übergeben worden.
typedef enum {
    JCContactsCreateOutcomeNotAuthorized      = 1,
    JCContactsCreateOutcomeContainerNotFound  = 2,
    JCContactsCreateOutcomeReadPreflightFailed = 3,
    JCContactsCreateOutcomeInvalidPayload     = 4,
    JCContactsCreateOutcomeApplied            = 5,
    JCContactsCreateOutcomeSaveError          = 6,
    JCContactsCreateOutcomeCaughtException    = 7,
    JCContactsCreateOutcomeIdentifierMissing  = 8,
    JCContactsCreateOutcomeReadbackFailed     = 9,
} JCContactsCreateOutcome;

/// PII-armes Ergebnis mit **einer** bewussten Ausnahme: `provider_identifier`
/// ist roh, weil das Backend ohne ihn keine External-ID anlegen und den
/// Kontakt nie wieder gezielt ansprechen könnte (ADR-0020 §5). Er reist
/// ausschliesslich im Settle-Rumpf; in Audit, Log und Oberfläche steht der
/// Digest. `readback_json` trägt die kanonische v1-Projektion des
/// **gelesenen** Zustands — der Kern bildet daraus seinen Digest, statt
/// einen Zustand zu erfinden.
typedef struct {
    int32_t outcome;                        // JCContactsCreateOutcome
    int32_t save_attempts;                  // 0 oder 1 — nie mehr
    int32_t add_request_count;              // 0 oder 1 — nie mehr
    int32_t provider_identifier_present;
    int32_t readback_succeeded;
    int32_t reason_present;
    int32_t diagnostics_artifact_written;
    int64_t error_code;                     // numerischer NSError-Code
    char error_domain[JC_CREATE_DOMAIN_CAPACITY];
    char exception_name[JC_CREATE_NAME_CAPACITY];
    char reason_digest[JC_CREATE_DIGEST_CAPACITY];
    char provider_identifier_digest[JC_CREATE_DIGEST_CAPACITY];
    char provider_identifier[JC_CREATE_IDENTIFIER_CAPACITY];
    char readback_json[JC_CREATE_READBACK_CAPACITY];
} JCContactsCreateResult;

/// Führt genau einen Create gegen den echten `CNContactStore` aus.
///
/// `payload_json` ist die kanonische v1-Nutzlast (dieselbe Form, die der
/// `payload_digest` deckt); `container_identifier` ist der ausdrückliche
/// Zielcontainer aus dem Auftrag — der Shim sucht sich keinen aus.
/// `transaction_author` trägt der Save, damit der Lese-Sync das eigene
/// Ereignis als Echo erkennt.
///
/// Die Einmaligkeit je Claim erzwingt der Rust-Layer; dieser Shim führt je
/// Aufruf genau einen Save aus und niemals eine Wiederholung.
void jc_contacts_create_run(const char *payload_json,
                            const char *container_identifier,
                            const char *transaction_author,
                            JCContactsCreateResult *out);

/// Kontaktfreier Testeinstieg: derselbe Ablauf mit eingebauten
/// Fake-Operationen — kein `CNContactStore`, kein Store-Zugriff, kein
/// TCC-Dialog. Der Ablauf ist **derselbe**; nur die Anbindung wechselt.
typedef enum {
    JCCreateScenarioNotAuthorized    = 1,
    JCCreateScenarioContainerMissing = 2,
    JCCreateScenarioFetchFails       = 3,
    JCCreateScenarioSaveSucceeds     = 4,
    JCCreateScenarioSaveNSError      = 5,
    JCCreateScenarioSaveThrows       = 6,
    JCCreateScenarioIdentifierMissing = 7,
    JCCreateScenarioReadbackMissing  = 8,
    JCCreateScenarioReadbackDiffers  = 9,
} JCCreateScenario;

void jc_contacts_create_run_scenario(int32_t scenario,
                                     const char *payload_json,
                                     JCContactsCreateResult *out);

#endif /* JC_CONTACTS_CREATE_H */
