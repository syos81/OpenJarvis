//! Contacts authorization, requested from the app process itself.
//!
//! Why this lives in the Tauri main process
//! ----------------------------------------
//! macOS shows a TCC prompt for the *responsible* process, and that process
//! must be one it can attribute the request to: it needs an Info.plist with
//! `NSContactsUsageDescription` and it has to be able to put a window on
//! screen. Reached through `uv` and `python`, the sidecar is neither.
//!
//! Why the call itself is Objective-C
//! ----------------------------------
//! The first version sent raw Objective-C messages from Rust. That compiles,
//! but its correctness cannot be *shown*: return type, `BOOL` representation,
//! block signature, retain semantics and object lifetime are all implicit, and
//! a mistake in any of them fails at runtime rather than at build time.
//!
//! The call now lives in `objc/JCContactsAuthorization.m`, compiled with ARC
//! into this binary and reached over a narrow C ABI. The Objective-C compiler
//! checks the block signature against the real SDK header, uses the system's
//! own `BOOL`, takes `CNEntityTypeContacts` from the header instead of a
//! hand-written integer, and ARC keeps the completion block and its state box
//! alive even when the waiting thread has already timed out.
//!
//! What this module still guarantees
//! ---------------------------------
//! * No call at startup, none when the Contacts page opens — only the exported
//!   command, wired to a single button.
//! * No retry. One user action, one request.
//! * No contact is read. The shim knows exactly two selectors, both about
//!   authorization.
//! * `localizedDescription` and `userInfo` never leave the shim; only the
//!   error domain and the numeric code travel.

use serde::Serialize;

/// Result of a status read or an authorization request, plus the PII-poor
/// runtime diagnostics needed to tell the failure modes apart.
///
/// Everything here is a state, a number, or a bundle identifier. No path, no
/// system message, no contact value.
#[derive(Debug, Clone, Serialize, Default)]
pub struct AuthorizationOutcome {
    pub status: String,
    pub granted: bool,
    pub prompt_attempted: bool,
    pub error_domain: Option<String>,
    pub error_code: Option<i64>,
    /// TCC identity of this process.
    pub bundle_identifier: String,
    /// Does the main bundle carry `NSContactsUsageDescription`?
    pub has_usage_description: bool,
    /// Was the app in the foreground when the call went out?
    pub app_active: bool,
    /// Did the system call run on the main thread?
    pub called_on_main_thread: bool,
    /// `CNEntityType` value actually used — read from the SDK, not guessed.
    pub entity_type: i64,
    /// Status immediately before the call.
    pub status_before: String,
    /// Did the completion handler run at all? `false` means timeout.
    pub callback_ran: bool,
    /// How often it ran. Must be 0 or 1 — never more.
    pub callback_count: i32,
}

/// `CNAuthorizationStatus`, verified against `CNContactStore.h:35`:
/// notDetermined 0, restricted 1, denied 2, authorized 3.
fn status_text(raw: i64) -> &'static str {
    match raw {
        0 => "notDetermined",
        1 => "restricted",
        2 => "denied",
        3 => "authorized",
        // Reported honestly rather than guessed into one of the four.
        _ => "unknown",
    }
}

#[cfg(target_os = "macos")]
mod imp {
    use super::{status_text, AuthorizationOutcome};
    use std::ffi::CStr;
    use std::os::raw::c_char;

    const DOMAIN_CAPACITY: usize = 128;
    const BUNDLE_CAPACITY: usize = 256;

    /// The user has this long to answer. On timeout we report exactly that —
    /// the prompt stays on screen, and the next status read picks up whatever
    /// was decided.
    const DECISION_TIMEOUT_SECONDS: f64 = 120.0;

    /// Mirrors `JCContactsAuthDiagnostics` in `objc/JCContactsAuthorization.h`.
    /// Field order and types must match that header exactly.
    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Diagnostics {
        status_before: i64,
        status_after: i64,
        entity_type: i64,
        callback_ran: i32,
        callback_count: i32,
        granted: i32,
        has_error: i32,
        error_code: i64,
        called_on_main_thread: i32,
        app_active: i32,
        has_usage_description: i32,
        error_domain: [c_char; DOMAIN_CAPACITY],
        bundle_identifier: [c_char; BUNDLE_CAPACITY],
    }

    impl Default for Diagnostics {
        fn default() -> Self {
            // Safe: the struct is plain data with no padding requirements
            // beyond alignment, and the shim overwrites it on every call.
            unsafe { std::mem::zeroed() }
        }
    }

    extern "C" {
        fn jc_contacts_authorization_status() -> i64;
        fn jc_contacts_environment(out: *mut Diagnostics);
        fn jc_contacts_request_access(out: *mut Diagnostics, timeout_seconds: f64) -> i32;
    }

    fn c_string(buffer: &[c_char]) -> String {
        // SAFETY: the shim always NUL-terminates within the buffer.
        unsafe { CStr::from_ptr(buffer.as_ptr()) }
            .to_string_lossy()
            .into_owned()
    }

    fn to_outcome(d: &Diagnostics, prompt_attempted: bool) -> AuthorizationOutcome {
        let domain = c_string(&d.error_domain);
        AuthorizationOutcome {
            status: status_text(d.status_after).to_string(),
            granted: d.granted != 0,
            prompt_attempted,
            error_domain: (d.has_error != 0 && !domain.is_empty()).then_some(domain),
            error_code: (d.has_error != 0).then_some(d.error_code),
            bundle_identifier: c_string(&d.bundle_identifier),
            has_usage_description: d.has_usage_description != 0,
            app_active: d.app_active != 0,
            called_on_main_thread: d.called_on_main_thread != 0,
            entity_type: d.entity_type,
            status_before: status_text(d.status_before).to_string(),
            callback_ran: d.callback_ran != 0,
            callback_count: d.callback_count,
        }
    }

    /// Reads `CNAuthorizationStatus`. Shows no dialog, touches no contact.
    pub fn authorization_status() -> String {
        status_text(unsafe { jc_contacts_authorization_status() }).to_string()
    }

    /// Environment only — no store call at all.
    pub fn environment() -> AuthorizationOutcome {
        let mut d = Diagnostics::default();
        unsafe { jc_contacts_environment(&mut d) };
        to_outcome(&d, false)
    }

    /// Runs exactly one authorization request and waits for the decision.
    ///
    /// Must not be called from the main thread: the shim dispatches the system
    /// call onto the main queue and then blocks the *calling* thread. Called
    /// from the main thread, that would deadlock the very thread that has to
    /// draw the dialog.
    pub fn request_access() -> AuthorizationOutcome {
        // Never prompt twice. Outside `notDetermined` the system shows no
        // dialog anyway, and asking again is how double prompts get built.
        let before = authorization_status();
        if before != "notDetermined" {
            let mut settled = environment();
            settled.granted = before == "authorized";
            settled.status = before;
            return settled;
        }

        let mut d = Diagnostics::default();
        unsafe { jc_contacts_request_access(&mut d, DECISION_TIMEOUT_SECONDS) };
        let mut outcome = to_outcome(&d, true);
        if !outcome.callback_ran && outcome.error_domain.is_none() {
            // A timeout is not an Apple error. Keeping the two apart matters:
            // downstream maps a domain to `tcc_request_rejected` and a timeout
            // to `request_timeout`.
            outcome.error_domain = Some("timeout".into());
            outcome.error_code = Some(0);
        }
        outcome
    }
}

#[cfg(not(target_os = "macos"))]
mod imp {
    use super::AuthorizationOutcome;

    pub fn authorization_status() -> String {
        "unknown".to_string()
    }

    pub fn environment() -> AuthorizationOutcome {
        AuthorizationOutcome {
            status: "unknown".into(),
            ..Default::default()
        }
    }

    pub fn request_access() -> AuthorizationOutcome {
        AuthorizationOutcome {
            status: "unknown".into(),
            error_domain: Some("unsupported_platform".into()),
            ..Default::default()
        }
    }
}

pub use imp::{authorization_status, environment, request_access};

#[cfg(test)]
mod tests {
    use super::*;

    /// The production part of this file — comments and the test block removed.
    ///
    /// Without cutting the test block, the prohibition checks below find their
    /// own search terms in the assertions and fire although the production code
    /// is clean: the test would be checking itself.
    fn production_code() -> String {
        let source = include_str!("contacts_authorization.rs");
        let end = source.find("#[cfg(test)]").unwrap_or(source.len());
        source[..end]
            .lines()
            .filter(|l| !l.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n")
    }

    fn shim_source() -> String {
        let source = include_str!("../objc/JCContactsAuthorization.m");
        source
            .lines()
            .filter(|l| !l.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[test]
    fn status_values_match_the_sdk_enum() {
        // CNContactStore.h:35 — notDetermined 0, restricted 1, denied 2,
        // authorized 3.
        assert_eq!(status_text(0), "notDetermined");
        assert_eq!(status_text(1), "restricted");
        assert_eq!(status_text(2), "denied");
        assert_eq!(status_text(3), "authorized");
        assert_eq!(status_text(99), "unknown");
    }

    #[test]
    fn the_entity_type_comes_from_the_header() {
        // Not a magic integer in Rust: the shim uses the header's own constant.
        let shim = shim_source();
        assert!(shim.contains("CNEntityTypeContacts"));
        let production = production_code();
        assert!(
            !production.contains("ENTITY_TYPE_CONTACTS"),
            "the Rust side must not carry its own entity-type constant"
        );
    }

    #[test]
    fn the_class_method_and_the_instance_method_are_used_correctly() {
        let shim = shim_source();
        // Class method (CNContactStore.h:74): sent to the class.
        assert!(shim.contains("[CNContactStore\n        authorizationStatusForEntityType")
            || shim.contains("[CNContactStore authorizationStatusForEntityType"));
        // Instance method (CNContactStore.h:86): needs an instance.
        assert!(shim.contains("[[CNContactStore alloc] init]"));
        assert!(shim.contains("[store requestAccessForEntityType"));
    }

    #[test]
    fn the_block_signature_matches_the_header() {
        let shim = shim_source();
        assert!(shim.contains("^(BOOL granted, NSError *error)"));
    }

    #[test]
    fn the_completion_block_outlives_a_timeout() {
        // The state box is an Objective-C object, so ARC keeps it alive for the
        // block. A timeout must never leave the handler writing into freed
        // memory.
        let shim = shim_source();
        assert!(shim.contains("JCAuthBox"));
        assert!(shim.contains("dispatch_semaphore_wait"));
        assert!(
            !shim.contains("__unsafe_unretained"),
            "the box must be strongly held"
        );
    }

    #[test]
    fn the_main_thread_is_never_blocked() {
        let shim = shim_source();
        // The system call goes onto the main queue…
        assert!(shim.contains("dispatch_async(dispatch_get_main_queue()"));
        // …and the wait happens after that block, on the calling thread.
        let dispatch = shim.find("dispatch_async(dispatch_get_main_queue()").unwrap();
        let wait = shim.find("dispatch_semaphore_wait").unwrap();
        assert!(wait > dispatch, "the wait must not sit inside the main-queue block");
        assert!(
            !shim.contains("dispatch_sync(dispatch_get_main_queue()"),
            "dispatch_sync onto the main queue would deadlock the dialog"
        );
    }

    #[test]
    fn exactly_one_request_site_exists() {
        let shim = shim_source();
        assert_eq!(shim.matches("requestAccessForEntityType").count(), 1);
        // And no retry loop around it.
        assert!(!shim.contains("while ("));
        assert!(!shim.contains("for ("));
    }

    #[test]
    fn a_double_callback_would_be_visible() {
        // The shim counts the invocations, so a second one cannot pass unseen.
        let shim = shim_source();
        assert!(shim.contains("callbackCount += 1"));
        let production = production_code();
        assert!(production.contains("callback_count"));
    }

    #[test]
    fn neither_side_reads_or_writes_a_contact() {
        for (name, code) in [("shim", shim_source()), ("rust", production_code())] {
            for forbidden in [
                "CNSaveRequest",
                "CNMutableContact",
                "unifiedContact",
                "enumerateContacts",
                "CNContactFetchRequest",
                "executeSaveRequest",
                "containersMatchingPredicate",
            ] {
                assert!(!code.contains(forbidden), "{forbidden} in {name}");
            }
        }
    }

    #[test]
    fn no_system_free_text_leaves_the_shim() {
        let shim = shim_source();
        assert!(!shim.contains("localizedDescription"));
        assert!(!shim.contains("userInfo"));
        assert!(!shim.contains("description]"));
    }

    #[test]
    fn the_diagnostics_carry_no_path_and_no_free_text() {
        let outcome = AuthorizationOutcome {
            status: "notDetermined".into(),
            status_before: "notDetermined".into(),
            granted: false,
            prompt_attempted: true,
            error_domain: Some("CNErrorDomain".into()),
            error_code: Some(100),
            bundle_identifier: "de.kluender.jarvis".into(),
            has_usage_description: true,
            app_active: true,
            called_on_main_thread: true,
            entity_type: 0,
            callback_ran: true,
            callback_count: 1,
        };
        let json = serde_json::to_string(&outcome).unwrap();
        assert!(json.contains("CNErrorDomain") && json.contains("100"));
        assert!(!json.contains("localizedDescription"));
        assert!(!json.contains('/'), "no path may appear: {json}");
        assert!(!json.contains('@'), "no address-like value may appear");
    }

    #[test]
    fn a_settled_status_never_prompts() {
        // Geprueft wird die Reihenfolge im Quelltext, NICHT durch einen echten
        // Aufruf.
        //
        // Die erste Fassung rief `request_access()` wirklich auf. In einem
        // `cargo test`-Binary lief der Systemaufruf nie — die Main Queue wird
        // ohne laufende Run-Loop nicht abgearbeitet, der Test wartete nur 120
        // Sekunden ins Leere. Aber in jeder Umgebung MIT lebender Run-Loop
        // haette er einen echten TCC-Dialog ausgeloest. Ein Test darf keine
        // Systemberechtigung anfordern.
        let code = production_code();
        let rumpf = code
            .split("pub fn request_access()")
            .nth(1)
            .expect("request_access is missing");
        let wache = rumpf
            .find("if before != \"notDetermined\"")
            .expect("the guard against a second prompt is missing");
        let aufruf = rumpf
            .find("jc_contacts_request_access")
            .expect("the request site is missing");
        assert!(
            wache < aufruf,
            "the guard must sit before the request, or a settled status would prompt again"
        );
        assert!(
            rumpf[..aufruf].contains("return settled"),
            "the guard must return early instead of falling through"
        );
    }

    #[test]
    fn the_environment_probe_touches_no_store() {
        // It reports identity and usage description and reads the status —
        // nothing that could show a dialog.
        let env = environment();
        assert!(!env.prompt_attempted);
        assert_eq!(env.callback_count, 0);
        assert_eq!(env.entity_type, 0, "CNEntityTypeContacts is the header's 0");
    }
}
