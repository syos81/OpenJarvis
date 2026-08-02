// Schmale C-ABI für den App-Prozess-Save-Spike.
//
// Zweck: beweisen oder widerlegen, dass EIN minimaler CNSaveRequest im
// Prozess von Jarvis.app speichern kann, während derselbe Request im nackten
// CLI-Sidecar auf macOS 12.7.6 deterministisch an einem
// NSPersistentStoreCoordinator OHNE angehängte Stores stirbt (fünf Livetests,
// Reason digest-verifiziert; Same-Stack-These durch den Preflight-Livetest
// widerlegt). Der App-Prozess ist der einzige Prozess dieses Systems, der
// nachweislich bereits produktiv mit Contacts.framework spricht
// (JCContactsAuthorization) und dessen Identität der TCC-Grant gehört.
//
// Dies ist ein SPIKE, keine Produktionsintegration: fester Payload, feste
// Zielwahl (genau ein Container der Art `local`), genau ein Save, kein Retry,
// keine Backend- oder Datenbankbeteiligung. ADR-0019 bleibt normativ.
//
// Der Shim darf: Status lesen, Container inventarisieren, einen
// Diagnose-Fetch ausführen, genau einen Kontakt bauen und speichern, den
// einen geschriebenen Kontakt zurücklesen. Er darf nicht: Berechtigungen
// anfordern, wiederholen, fremde Kontakte lesen oder verändern, Felder oder
// Container von außen entgegennehmen.

#ifndef JC_CONTACTS_APP_SAVE_SPIKE_H
#define JC_CONTACTS_APP_SAVE_SPIKE_H

#include <stdint.h>

#define JC_SPIKE_DOMAIN_CAPACITY 128
#define JC_SPIKE_NAME_CAPACITY 65
#define JC_SPIKE_DIGEST_CAPACITY 65
#define JC_SPIKE_TYPE_CAPACITY 16

/// Geschlossene Ergebnismenge des nativen Spikes. `disabled` entscheidet der
/// Rust-Layer (Environment-Gate) — der Shim wird dann gar nicht erst gerufen.
/// `app_crashed` kann naturgemäß keine Antwort sein und wird extern aus
/// Crashreport und Diagnoseartefakt klassifiziert.
typedef enum {
    JCAppSaveSpikeOutcomeNotAuthorized = 1,
    JCAppSaveSpikeOutcomeLocalContainerNotFound = 2,
    JCAppSaveSpikeOutcomeLocalContainerAmbiguous = 3,
    JCAppSaveSpikeOutcomeReadPreflightFailed = 4,
    JCAppSaveSpikeOutcomeApplied = 5,
    JCAppSaveSpikeOutcomeSaveError = 6,
    JCAppSaveSpikeOutcomeCaughtException = 7,
} JCAppSaveSpikeOutcome;

/// PII-armes Ergebnis. Ausdrücklich NICHT enthalten: rohe Provider- oder
/// Containerkennungen (nur ein SHA-256-Digest der neuen Kennung), Reason-Text
/// (nur Digest; der Rohtext existiert ausschließlich im per
/// OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH aktivierten, exklusiven
/// 0600-Artefakt), Kontaktwerte, Pfade.
typedef struct {
    int32_t outcome;                       // JCAppSaveSpikeOutcome
    int32_t save_attempts;                 // 0 oder 1 — nie mehr
    int32_t provider_identifier_present;
    int32_t readback_succeeded;
    int32_t given_name_matched;
    int32_t reason_present;
    int32_t diagnostics_artifact_written;
    int64_t error_code;                    // numerischer NSError-Code
    char error_domain[JC_SPIKE_DOMAIN_CAPACITY];
    char exception_name[JC_SPIKE_NAME_CAPACITY];
    char reason_digest[JC_SPIKE_DIGEST_CAPACITY];
    char provider_identifier_digest[JC_SPIKE_DIGEST_CAPACITY];
    char container_type[JC_SPIKE_TYPE_CAPACITY];   // "local" bei applied
} JCAppSaveSpikeResult;

/// Führt den Spike gegen den ECHTEN CNContactStore aus — genau einmal je
/// Aufruf; die Einmaligkeit je Prozess erzwingt der Rust-Layer. Installiert
/// beim ersten Aufruf die Uncaught-Letztdiagnose (ein bereits registrierter
/// fremder Handler bleibt erhalten und wird weitergerufen).
void jc_app_save_spike_run(JCAppSaveSpikeResult *out);

/// SHA-256-Hexdigest des festen kanonischen Spike-Payloads
/// (`contactType=person`, `givenName=ZZZ-JarvisTest-AppSave`). Eine Wahrheit,
/// im Shim — Rust bindet Vorschau und Ausführung daran.
void jc_app_save_spike_payload_digest(char out[JC_SPIKE_DIGEST_CAPACITY]);

/// Kontaktfreier Testeinstieg: führt exakt denselben Ablauf mit eingebauten
/// Fake-Operationen aus — kein CNContactStore, kein Store-Zugriff. Die
/// Szenarien decken die Fälle C–I der Testmatrix ab.
typedef enum {
    JCSpikeScenarioNotAuthorized = 1,
    JCSpikeScenarioNoLocalContainer = 2,
    JCSpikeScenarioTwoLocalContainers = 3,
    JCSpikeScenarioFetchFails = 4,
    JCSpikeScenarioSaveSucceeds = 5,
    JCSpikeScenarioSaveNSError = 6,
    JCSpikeScenarioSaveThrows = 7,
    JCSpikeScenarioReadbackMissing = 8,
} JCSpikeScenario;

void jc_app_save_spike_run_scenario(int32_t scenario,
                                    JCAppSaveSpikeResult *out);

#endif /* JC_CONTACTS_APP_SAVE_SPIKE_H */
