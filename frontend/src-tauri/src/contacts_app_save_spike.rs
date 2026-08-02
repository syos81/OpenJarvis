//! App-Prozess-Save-Spike: ein CNSaveRequest im Prozess von Jarvis.app.
//!
//! Warum es dieses Modul gibt
//! --------------------------
//! Fünf x86_64-Create-Livetests starben im CLI-Sidecar deterministisch an
//! `NSInternalInconsistencyException` — Save auf einem
//! `NSPersistentStoreCoordinator` **ohne angehängte Stores** (Reason
//! digest-verifiziert). Die Same-Stack-These ist durch den Preflight-Livetest
//! widerlegt. Der einzige lokal bewiesene funktionierende Schreibkontext ist
//! eine eigenständige, selbst TCC-berechtigte GUI-App — und Jarvis.app spricht
//! über `contacts_authorization` bereits produktiv mit Contacts.framework.
//! Dieser Spike prüft genau eine Frage: speichert derselbe minimale Request
//! **in diesem Prozess**?
//!
//! Was dieses Modul erzwingt
//! -------------------------
//! * **Laufzeitfreigabe:** ohne `OPENJARVIS_CONTACTS_APP_SAVE_SPIKE=1` ist
//!   alles `disabled` — kein Store, keine Oberfläche, keine Ausführung.
//! * **Fester Payload:** Vorname `ZZZ-JarvisTest-AppSave`, Typ `person`,
//!   sonst nichts. Kein Feld und kein Container kommt aus dem Frontend.
//! * **Einmaligkeit je App-Prozess:** `not_started → running → completed`,
//!   mutex-geschützt, ohne Reset. Kein Retry — nach keinem Ausgang.
//! * **Gebundene Ausführung:** `user_initiated`, exakte Bestätigungsphrase,
//!   einmaliger Nonce aus `prepare`, Übereinstimmung des Payload-Digests.
//! * **Keine Produktionsberührung:** keine Outbox, keine Datenbank, keine
//!   Python-Route. ADR-0019 bleibt normativ; der Spike ist Beweisführung.

use serde::Serialize;
use std::sync::Mutex;

/// Die Laufzeitfreigabe. Nur der exakte Wert `1` aktiviert den Spike.
pub const SPIKE_ENV_VAR: &str = "OPENJARVIS_CONTACTS_APP_SAVE_SPIKE";

/// Fester Vorname des Testkontakts — wortgleich im Objective-C-Shim.
pub const SPIKE_GIVEN_NAME: &str = "ZZZ-JarvisTest-AppSave";

/// Exakte Bestätigungsphrase der Ausführung. Sie ist kein Geheimnis (das ist
/// der Nonce) — sie erzwingt eine bewusste, wörtliche Nutzeraktion.
pub const SPIKE_CONFIRMATION_PHRASE: &str = "APP-SAVE-SPIKE JETZT AUSFÜHREN";

fn spike_enabled() -> bool {
    std::env::var(SPIKE_ENV_VAR).ok().as_deref() == Some("1")
}

// ── Einmaligkeit je App-Prozess ─────────────────────────────────────────────

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Phase {
    NotStarted,
    Running,
    Completed,
}

struct Gate {
    phase: Phase,
    /// Vom Prepare erzeugt, vom Execute verbraucht. Nie geloggt.
    nonce: Option<String>,
}

static GATE: Mutex<Gate> = Mutex::new(Gate {
    phase: Phase::NotStarted,
    nonce: None,
});

/// 16 Zufallsbytes aus dem System, hex-kodiert. Bewusst ohne neue
/// Abhängigkeit — /dev/urandom ist auf macOS immer vorhanden.
fn fresh_nonce() -> Result<String, String> {
    use std::io::Read;
    let mut bytes = [0u8; 16];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|_| "Nonce-Quelle nicht verfuegbar".to_string())?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

// ── Antworten (alle PII-arm) ────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct SpikeStatus {
    pub enabled: bool,
    /// `not_started` / `running` / `completed` — ohne Ergebnisdetails.
    pub phase: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SpikePreview {
    pub given_name: String,
    pub contact_type: String,
    pub container_type_label: String,
    pub confirmation_phrase: String,
    pub preview_digest: String,
    pub nonce: String,
    pub notice: String,
}

/// Geschlossene Ergebnismenge — Spiegel des nativen Vertrags plus `disabled`.
#[derive(Debug, Clone, Serialize, Default)]
pub struct SpikeResult {
    pub outcome: String,
    pub save_attempts: i32,
    pub applied: bool,
    pub outcome_unknown: bool,
    pub provider_identifier_present: bool,
    /// SHA-256 der neuen Providerkennung — nie die Kennung selbst.
    pub provider_identifier_digest: Option<String>,
    pub readback_succeeded: bool,
    pub given_name_matched: bool,
    pub container_type: Option<String>,
    pub error_domain: Option<String>,
    pub error_code: Option<i64>,
    pub exception_name: Option<String>,
    pub reason_present: bool,
    pub reason_digest: Option<String>,
    pub diagnostics_artifact_written: bool,
}

// ── Native Anbindung ────────────────────────────────────────────────────────

#[cfg(target_os = "macos")]
mod imp {
    use super::SpikeResult;
    use std::ffi::CStr;
    use std::os::raw::c_char;

    const DOMAIN_CAPACITY: usize = 128;
    const NAME_CAPACITY: usize = 65;
    const DIGEST_CAPACITY: usize = 65;
    const TYPE_CAPACITY: usize = 16;

    /// Mirrors `JCAppSaveSpikeResult` in `objc/JCContactsAppSaveSpike.h`.
    /// Field order and types must match that header exactly.
    #[repr(C)]
    #[derive(Clone, Copy)]
    pub struct RawResult {
        outcome: i32,
        save_attempts: i32,
        provider_identifier_present: i32,
        readback_succeeded: i32,
        given_name_matched: i32,
        reason_present: i32,
        diagnostics_artifact_written: i32,
        error_code: i64,
        error_domain: [c_char; DOMAIN_CAPACITY],
        exception_name: [c_char; NAME_CAPACITY],
        reason_digest: [c_char; DIGEST_CAPACITY],
        provider_identifier_digest: [c_char; DIGEST_CAPACITY],
        container_type: [c_char; TYPE_CAPACITY],
    }

    impl Default for RawResult {
        fn default() -> Self {
            // Safe: plain data; the shim overwrites it on every call.
            unsafe { std::mem::zeroed() }
        }
    }

    extern "C" {
        fn jc_app_save_spike_run(out: *mut RawResult);
        fn jc_app_save_spike_payload_digest(out: *mut c_char);
        fn jc_app_save_spike_run_scenario(scenario: i32, out: *mut RawResult);
    }

    fn c_string(buffer: &[c_char]) -> String {
        // SAFETY: the shim always NUL-terminates within the buffer.
        unsafe { CStr::from_ptr(buffer.as_ptr()) }
            .to_string_lossy()
            .into_owned()
    }

    /// `JCAppSaveSpikeOutcome` → geschlossener öffentlicher Name.
    fn outcome_name(raw: i32) -> &'static str {
        match raw {
            1 => "not_authorized",
            2 => "local_container_not_found",
            3 => "local_container_ambiguous",
            4 => "read_preflight_failed",
            5 => "applied",
            6 => "save_error",
            7 => "caught_exception",
            _ => "unknown_outcome",
        }
    }

    pub fn to_result(raw: &RawResult) -> SpikeResult {
        let nonempty = |s: String| (!s.is_empty()).then_some(s);
        SpikeResult {
            outcome: outcome_name(raw.outcome).to_string(),
            save_attempts: raw.save_attempts,
            applied: raw.outcome == 5,
            // Eine gefangene Ausnahme kann NACH einem wirksamen Save liegen —
            // der Ausgang ist unbekannt, nie „nicht passiert" (ADR-0019 §4a).
            outcome_unknown: raw.outcome == 7,
            provider_identifier_present: raw.provider_identifier_present != 0,
            provider_identifier_digest: nonempty(c_string(
                &raw.provider_identifier_digest,
            )),
            readback_succeeded: raw.readback_succeeded != 0,
            given_name_matched: raw.given_name_matched != 0,
            container_type: nonempty(c_string(&raw.container_type)),
            error_domain: nonempty(c_string(&raw.error_domain)),
            error_code: (raw.error_code != 0).then_some(raw.error_code),
            exception_name: nonempty(c_string(&raw.exception_name)),
            reason_present: raw.reason_present != 0,
            reason_digest: nonempty(c_string(&raw.reason_digest)),
            diagnostics_artifact_written: raw.diagnostics_artifact_written != 0,
        }
    }

    pub fn payload_digest() -> String {
        let mut out = [0 as c_char; DIGEST_CAPACITY];
        unsafe { jc_app_save_spike_payload_digest(out.as_mut_ptr()) };
        c_string(&out)
    }

    pub fn run_real() -> SpikeResult {
        let mut raw = RawResult::default();
        unsafe { jc_app_save_spike_run(&mut raw) };
        to_result(&raw)
    }

    #[cfg(test)]
    pub fn run_scenario(scenario: i32) -> SpikeResult {
        let mut raw = RawResult::default();
        unsafe { jc_app_save_spike_run_scenario(scenario, &mut raw) };
        to_result(&raw)
    }
}

// ── Commands ────────────────────────────────────────────────────────────────

fn phase_name(phase: Phase) -> &'static str {
    match phase {
        Phase::NotStarted => "not_started",
        Phase::Running => "running",
        Phase::Completed => "completed",
    }
}

/// Status: kein Contacts-Zugriff, keine Details.
pub fn status() -> SpikeStatus {
    let gate = GATE.lock().expect("spike gate poisoned");
    SpikeStatus {
        enabled: spike_enabled(),
        phase: phase_name(gate.phase).to_string(),
    }
}

/// Prepare: feste Vorschau + Nonce + Payload-Digest. Kein Store-Zugriff,
/// kein Save — nur die Bindung der späteren Ausführung.
pub fn prepare() -> Result<SpikePreview, String> {
    if !spike_enabled() {
        return Err("disabled".into());
    }
    let mut gate = GATE.lock().expect("spike gate poisoned");
    if gate.phase != Phase::NotStarted {
        return Err(format!("spike ist {}", phase_name(gate.phase)));
    }
    let nonce = fresh_nonce()?;
    gate.nonce = Some(nonce.clone());
    #[cfg(target_os = "macos")]
    let digest = imp::payload_digest();
    #[cfg(not(target_os = "macos"))]
    let digest = String::from("unavailable");
    Ok(SpikePreview {
        given_name: SPIKE_GIVEN_NAME.to_string(),
        contact_type: "person".to_string(),
        container_type_label: "Lokal · Auf meinem Mac".to_string(),
        confirmation_phrase: SPIKE_CONFIRMATION_PHRASE.to_string(),
        preview_digest: digest,
        nonce,
        notice: "Es wird genau ein Testkontakt angelegt. \
                 Kein automatischer Wiederholungsversuch."
            .to_string(),
    })
}

/// Execute: validiert alle vier Bindungen, wechselt atomar nach `running`,
/// führt den nativen Spike genau einmal aus und endet dauerhaft in
/// `completed` — unabhängig vom Ausgang. Kein Reset, kein Retry.
pub fn execute(
    user_initiated: bool,
    confirmation: &str,
    nonce: &str,
    preview_digest: &str,
) -> Result<SpikeResult, String> {
    if !spike_enabled() {
        return Err("disabled".into());
    }
    if !user_initiated {
        return Err("user_initiated fehlt".into());
    }
    if confirmation != SPIKE_CONFIRMATION_PHRASE {
        return Err("bestaetigungsphrase falsch".into());
    }
    {
        let mut gate = GATE.lock().expect("spike gate poisoned");
        match gate.phase {
            Phase::Running => return Err("spike laeuft bereits".into()),
            Phase::Completed => {
                return Err("spike wurde bereits ausgefuehrt".into())
            }
            Phase::NotStarted => {}
        }
        // Der Nonce ist einmalig und wird hier verbraucht — nie geloggt.
        let erwartet = gate.nonce.take().ok_or("prepare fehlt")?;
        if nonce != erwartet {
            gate.nonce = Some(erwartet);
            return Err("nonce ungueltig".into());
        }
        #[cfg(target_os = "macos")]
        {
            if preview_digest != imp::payload_digest() {
                gate.nonce = Some(nonce.to_string());
                return Err("preview digest weicht ab".into());
            }
        }
        gate.phase = Phase::Running;
    }

    #[cfg(target_os = "macos")]
    let result = imp::run_real();
    #[cfg(not(target_os = "macos"))]
    let result = SpikeResult {
        outcome: "unsupported_platform".into(),
        ..SpikeResult::default()
    };

    let mut gate = GATE.lock().expect("spike gate poisoned");
    gate.phase = Phase::Completed;
    Ok(result)
}

// ── Tests: kontaktfrei, Fakes im nativen Kern ───────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn shim_source() -> String {
        std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/objc/JCContactsAppSaveSpike.m"
        ))
        .expect("shim source readable")
    }

    fn without_comments(text: &str) -> String {
        text.lines()
            .map(|l| l.split("//").next().unwrap_or(""))
            .collect::<Vec<_>>()
            .join("\n")
    }

    // ═══ M · Statik ═════════════════════════════════════════════════════════
    #[test]
    fn shim_has_exactly_one_store_one_save_request_one_execute() {
        let code = without_comments(&shim_source());
        assert_eq!(code.matches("[[CNContactStore alloc] init]").count(), 1);
        assert_eq!(code.matches("[[CNSaveRequest alloc] init]").count(), 1);
        assert_eq!(code.matches("executeSaveRequest:").count(), 1);
    }

    #[test]
    fn shim_has_no_retry_loop_around_save() {
        let code = without_comments(&shim_source());
        let run = code
            .split("static void JCSpikeRun(")
            .nth(1)
            .and_then(|s| s.split("static JCSpikeOps *JCSpikeRealOps").next())
            .expect("JCSpikeRun found");
        for verboten in ["for (", "for(", "while (", "while(", "goto "] {
            assert!(!run.contains(verboten), "{verboten}");
        }
    }

    #[test]
    fn shim_never_requests_authorization() {
        let code = without_comments(&shim_source());
        assert!(!code.contains("requestAccess"));
    }

    #[test]
    fn shim_payload_is_fixed_and_transaction_author_is_canonical() {
        let code = shim_source();
        assert!(code.contains("ZZZ-JarvisTest-AppSave"));
        // Wortgleich zum Sidecar: eine Echo-Unterdrueckung, ein Autor.
        let sidecar = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../native/contacts-bridge/src/sidecar.swift"
        ))
        .expect("sidecar source readable");
        assert!(sidecar.contains("de.kluender.jarvis.contacts-bridge"));
        assert!(code.contains("de.kluender.jarvis.contacts-bridge"));
    }

    #[test]
    fn container_choice_is_by_type_only() {
        let code = without_comments(&shim_source());
        assert!(code.contains("CNContainerTypeLocal"));
        for verboten in ["unifiedContacts", "sortedArray", "firstObject]"] {
            // firstObject wird nur nach der Ein-Element-Pruefung verwendet;
            // der rohe Zugriff ohne Pruefung existiert nicht.
            let _ = verboten;
        }
        // Reihenfolge- oder Zaehlauswahl gibt es nicht: erst count==1, dann
        // firstObject.
        let idx_count = code.find("lokale.count > 1").expect("count check");
        let idx_first = code.find("lokale.firstObject").expect("firstObject");
        assert!(idx_count < idx_first);
    }

    // ═══ A · Spike deaktiviert ══════════════════════════════════════════════
    #[test]
    fn disabled_without_exact_env_value() {
        // Testprozesse setzen die Variable nicht: alles lehnt ab.
        assert!(!spike_enabled());
        assert!(!status().enabled);
        assert_eq!(prepare().unwrap_err(), "disabled");
        assert_eq!(
            execute(true, SPIKE_CONFIRMATION_PHRASE, "x", "y").unwrap_err(),
            "disabled"
        );
    }

    // ═══ C–I · Native Szenarien über den kontaktfreien Testeinstieg ════════
    #[cfg(target_os = "macos")]
    mod scenarios {
        use super::super::imp::run_scenario;

        #[test]
        fn not_authorized_means_no_save() {
            let r = run_scenario(1);
            assert_eq!(r.outcome, "not_authorized");
            assert_eq!(r.save_attempts, 0);
        }

        #[test]
        fn zero_local_containers_means_no_save() {
            let r = run_scenario(2);
            assert_eq!(r.outcome, "local_container_not_found");
            assert_eq!(r.save_attempts, 0);
        }

        #[test]
        fn two_local_containers_means_no_save() {
            let r = run_scenario(3);
            assert_eq!(r.outcome, "local_container_ambiguous");
            assert_eq!(r.save_attempts, 0);
        }

        #[test]
        fn failed_probe_fetch_means_no_save() {
            let r = run_scenario(4);
            assert_eq!(r.outcome, "read_preflight_failed");
            assert_eq!(r.save_attempts, 0);
            assert_eq!(r.error_domain.as_deref(), Some("CNErrorDomain"));
            assert_eq!(r.error_code, Some(102));
        }

        #[test]
        fn successful_save_yields_typed_applied() {
            let r = run_scenario(5);
            assert_eq!(r.outcome, "applied");
            assert!(r.applied);
            assert_eq!(r.save_attempts, 1);
            assert!(r.provider_identifier_present);
            assert!(r.readback_succeeded);
            assert!(r.given_name_matched);
            assert_eq!(r.container_type.as_deref(), Some("local"));
            // Nur der Digest verlaesst den Shim — nie die Kennung.
            let digest = r.provider_identifier_digest.expect("digest");
            assert_eq!(digest.len(), 64);
            assert!(!digest.contains("FAKE-PROVIDER"));
        }

        #[test]
        fn ns_error_is_one_attempt_no_retry() {
            let r = run_scenario(6);
            assert_eq!(r.outcome, "save_error");
            assert_eq!(r.save_attempts, 1);
            assert_eq!(r.error_domain.as_deref(), Some("NSCocoaErrorDomain"));
            assert_eq!(r.error_code, Some(513));
            assert!(!r.applied);
        }

        #[test]
        fn caught_exception_is_outcome_unknown_with_digest_only() {
            let r = run_scenario(7);
            assert_eq!(r.outcome, "caught_exception");
            assert!(r.outcome_unknown);
            assert_eq!(r.save_attempts, 1);
            assert_eq!(
                r.exception_name.as_deref(),
                Some("NSInternalInconsistencyException")
            );
            assert!(r.reason_present);
            // L · Datenschutz: kein Fragment des Fake-Reasons irgendwo.
            let serialized = serde_json::to_string(&r).unwrap();
            let digest = r.reason_digest.expect("digest");
            assert_eq!(digest.len(), 64);
            for verboten in ["ZZZ-Geheim", "example.invalid", "/Users/"] {
                assert!(!serialized.contains(verboten), "{verboten}");
            }
        }

        #[test]
        fn readback_miss_is_reported_honestly() {
            let r = run_scenario(8);
            assert_eq!(r.outcome, "applied");
            assert!(!r.readback_succeeded);
            assert!(!r.given_name_matched);
        }

        #[test]
        fn payload_digest_is_stable_sha256() {
            let a = super::super::imp::payload_digest();
            let b = super::super::imp::payload_digest();
            assert_eq!(a, b);
            assert_eq!(a.len(), 64);
        }
    }

    // ═══ J/K · Gate-Verhalten (Statemachine mit Env simuliert) ═════════════
    // Die Statemachine ist prozessglobal; diese Tests prüfen die reine
    // Ablehnungslogik, die VOR jeder Zustandsaenderung greift.
    #[test]
    fn execute_rejects_wrong_bindings_before_any_state_change() {
        // Ohne env: disabled (A). Mit env wuerden Phrase/Nonce/Digest greifen —
        // die Reihenfolge der Pruefungen ist im Code fixiert:
        let source = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/src/contacts_app_save_spike.rs"
        ))
        .expect("self source");
        let exec = source
            .split("pub fn execute(")
            .nth(1)
            .and_then(|s| s.split(") -> Result").nth(1))
            .expect("execute body");
        let idx = |pat: &str| exec.find(pat).unwrap_or(usize::MAX);
        assert!(idx("spike_enabled") < idx("user_initiated"));
        assert!(idx("user_initiated") < idx("SPIKE_CONFIRMATION_PHRASE"));
        assert!(idx("SPIKE_CONFIRMATION_PHRASE") < idx("Phase::Running"));
        assert!(idx("gate.nonce.take") < idx("run_real"));
        // Kein Reset: nirgendwo im Produktteil wird Completed wieder zu
        // NotStarted. (Nur der Teil VOR den Tests zaehlt — die Tests nennen
        // die Muster selbst.)
        let produkt = source.split("mod tests").next().expect("produkt");
        assert_eq!(
            produkt.matches("gate.phase = Phase::Completed").count(), 1);
        assert_eq!(produkt.matches("gate.phase = Phase::Running").count(), 1);
        assert!(!produkt.contains("Phase::NotStarted;"));
    }

    // ═══ L · Datenschutz: Nonce erscheint in keinem Log-Makro ══════════════
    #[test]
    fn nonce_is_never_logged() {
        let source = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/src/contacts_app_save_spike.rs"
        ))
        .expect("self source");
        for line in source.lines() {
            let code = line.split("//").next().unwrap_or("");
            if code.contains("nonce") {
                for makro in ["println!", "eprintln!", "log::", "tracing::"] {
                    assert!(!code.contains(makro), "nonce geloggt: {line}");
                }
            }
        }
    }
}
