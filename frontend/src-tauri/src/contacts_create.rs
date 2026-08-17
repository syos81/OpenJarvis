// Nativer Create im App-Prozess (ADR-0026 §8.1, Phase B).
//
// Diese Schicht ist der Torwächter vor dem einen `CNSaveRequest`. Sie prüft
// **vor** jedem FFI-Aufruf in dieser Reihenfolge: Schreibfreigabe, dann
// Operationstyp, dann Feldvertrag, dann Zielcontainer. Erst danach reicht sie
// die bereits digest-geprüfte Nutzlast an den Objective-C-Shim weiter, der
// genau einen Kontakt baut, genau einen Save absetzt und über die gemeldete
// Kennung zurückliest.
//
// **Der Schalter ist eine Datei, keine Umgebungsvariable.** Eine Variable
// erbt sich in Kindprozesse, steht in jedem Prozessabbild und lässt sich
// versehentlich in einem Startskript setzen — zu wenig für einen Schalter,
// der fremde Kontaktdaten anfasst. Die Freigabe liegt als 0600-Datei in
// einem 0700-Verzeichnis, nennt Vertrag, Umfang und Grund und **läuft ab**.
// Dieselben Regeln liest der Kern (`application/write_release.py`); beide
// müssen dieselbe Antwort geben, sonst meldete die Oberfläche „darf",
// während der App-Prozess „darf nicht" meint.
//
// Ohne Freigabe endet jeder Create hier mit
// `not_sent / provider_channel_disabled_before_send` — beweisbar **vor**
// jeder Übergabe.

use serde::Deserialize;
use std::os::raw::{c_char, c_int};

use crate::contacts_execution::{sha256_hex, ExecutionOrderV1, ExecutionReportV1};

/// Ergebniscodes des Shims — Spiegel von `JCContactsCreateOutcome`.
const OUTCOME_NOT_AUTHORIZED: i32 = 1;
const OUTCOME_CONTAINER_NOT_FOUND: i32 = 2;
const OUTCOME_READ_PREFLIGHT_FAILED: i32 = 3;
const OUTCOME_INVALID_PAYLOAD: i32 = 4;
const OUTCOME_APPLIED: i32 = 5;
const OUTCOME_SAVE_ERROR: i32 = 6;
const OUTCOME_CAUGHT_EXCEPTION: i32 = 7;
const OUTCOME_IDENTIFIER_MISSING: i32 = 8;
const OUTCOME_READBACK_FAILED: i32 = 9;

const DOMAIN_CAPACITY: usize = 128;
const NAME_CAPACITY: usize = 65;
const DIGEST_CAPACITY: usize = 65;
const IDENTIFIER_CAPACITY: usize = 512;
const READBACK_CAPACITY: usize = 32768;

/// Der eingefrorene v1-Feldvorrat (ADR-0026 §7), kanonische Schlüssel.
/// Was hier fehlt, ist nicht schreibbar — und wird abgewiesen, nicht ignoriert.
pub const CREATE_V1_KEYS: [&str; 19] = [
    "contactType",
    "givenName",
    "middleName",
    "familyName",
    "previousFamilyName",
    "namePrefix",
    "nameSuffix",
    "nickname",
    "phoneticGivenName",
    "phoneticFamilyName",
    "organizationName",
    "departmentName",
    "jobTitle",
    "birthday",
    "emails",
    "phones",
    "postalAddresses",
    "urls",
    "dates",
];

#[repr(C)]
#[derive(Debug)]
pub struct JCContactsCreateResult {
    pub outcome: i32,
    pub save_attempts: i32,
    pub add_request_count: i32,
    pub provider_identifier_present: i32,
    pub readback_succeeded: i32,
    pub reason_present: i32,
    pub diagnostics_artifact_written: i32,
    pub error_code: i64,
    pub error_domain: [c_char; DOMAIN_CAPACITY],
    pub exception_name: [c_char; NAME_CAPACITY],
    pub reason_digest: [c_char; DIGEST_CAPACITY],
    pub provider_identifier_digest: [c_char; DIGEST_CAPACITY],
    pub provider_identifier: [c_char; IDENTIFIER_CAPACITY],
    pub readback_json: [c_char; READBACK_CAPACITY],
}

impl Default for JCContactsCreateResult {
    fn default() -> Self {
        // `unsafe { zeroed() }` wäre kürzer, aber ein Nullwert ist hier eine
        // fachliche Aussage (kein Save, keine Kennung) — die schreibt man aus.
        Self {
            outcome: 0,
            save_attempts: 0,
            add_request_count: 0,
            provider_identifier_present: 0,
            readback_succeeded: 0,
            reason_present: 0,
            diagnostics_artifact_written: 0,
            error_code: 0,
            error_domain: [0; DOMAIN_CAPACITY],
            exception_name: [0; NAME_CAPACITY],
            reason_digest: [0; DIGEST_CAPACITY],
            provider_identifier_digest: [0; DIGEST_CAPACITY],
            provider_identifier: [0; IDENTIFIER_CAPACITY],
            readback_json: [0; READBACK_CAPACITY],
        }
    }
}

#[cfg(target_os = "macos")]
extern "C" {
    fn jc_contacts_create_run(
        payload_json: *const c_char,
        container_identifier: *const c_char,
        transaction_author: *const c_char,
        out: *mut JCContactsCreateResult,
    );
    fn jc_contacts_create_run_scenario(
        scenario: c_int,
        payload_json: *const c_char,
        out: *mut JCContactsCreateResult,
    );
    fn jc_contacts_update_run(
        provider_identifier: *const c_char,
        patch_json: *const c_char,
        expected_previous_json: *const c_char,
        transaction_author: *const c_char,
        out: *mut JCContactsCreateResult,
    );
    fn jc_contacts_delete_run(
        provider_identifier: *const c_char,
        expected_previous_json: *const c_char,
        expected_container: *const c_char,
        transaction_author: *const c_char,
        out: *mut JCContactsCreateResult,
    );
    fn jc_contacts_update_run_scenario(
        scenario: c_int,
        patch_json: *const c_char,
        expected_previous_json: *const c_char,
        out: *mut JCContactsCreateResult,
    );
    fn jc_contacts_delete_run_scenario(
        scenario: c_int,
        expected_previous_json: *const c_char,
        out: *mut JCContactsCreateResult,
    );
}

fn c_string_to_rust(puffer: &[c_char]) -> String {
    let bytes: Vec<u8> = puffer
        .iter()
        .take_while(|z| **z != 0)
        .map(|z| *z as u8)
        .collect();
    String::from_utf8_lossy(&bytes).into_owned()
}

// ── Die Schreibfreigabe ─────────────────────────────────────────────────────

/// Vertragskennung — wortgleich zu `write_release.WRITE_RELEASE_CONTRACT`.
pub const WRITE_RELEASE_CONTRACT: &str = "contacts-write-v1";
/// Dauerhaftigkeitsvertrag — wortgleich zu `WRITE_RELEASE_CONTRACT_V2`.
/// Ein eigener Vertrag, damit eine bestehende v1-Datei nicht nachträglich als
/// Dauerfreigabe gelesen werden kann.
pub const WRITE_RELEASE_CONTRACT_V2: &str = "contacts-write-v2";
/// Fähigkeit, für die eine Freigabe gilt — wortgleich zum Kern.
pub const WRITE_RELEASE_CAPABILITY: &str = "contacts";
/// Modusnamen — wortgleich zum Kern.
pub const MODE_TEMPORARY: &str = "temporary";
pub const MODE_STANDING: &str = "standing";
/// Dateiname — wortgleich zu `write_release.WRITE_RELEASE_FILENAME`.
pub const WRITE_RELEASE_FILENAME: &str = "contacts-write-release.json";
/// Längste zulässige Geltungsdauer, in Stunden. Gilt nur befristet.
pub const MAX_RELEASE_HOURS: i64 = 4;

#[derive(Debug, Deserialize)]
struct RohFreigabe {
    contract: String,
    operations: Vec<String>,
    #[serde(default)]
    expires_at: Option<String>,
    #[serde(default)]
    reason: String,
    #[serde(default)]
    capability: Option<String>,
    #[serde(default)]
    mode: Option<String>,
    #[serde(default)]
    granted_at: Option<String>,
    #[serde(default)]
    revoked_at: Option<String>,
}

/// Prüft eine Freigabedatei nach denselben Regeln wie der Kern.
///
/// Absichtlich ohne jede Fehlermeldung nach aussen: Eine fehlende Freigabe
/// ist der Normalfall, kein Fehler — und ein Aufrufer soll daraus keine
/// Sonderbehandlung ableiten.
pub fn write_release_erlaubt(pfad: &std::path::Path, operation: &str, jetzt_unix: i64) -> bool {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let Ok(eltern) = pfad.parent().ok_or(()) else {
        return false;
    };
    let Ok(eltern_meta) = std::fs::symlink_metadata(eltern) else {
        return false;
    };
    if !eltern_meta.is_dir()
        || eltern_meta.permissions().mode() & 0o777 != 0o700
        || eltern_meta.uid() != unsafe { libc::geteuid() }
    {
        return false;
    }
    let Ok(meta) = std::fs::symlink_metadata(pfad) else {
        return false;
    };
    if !meta.is_file()
        || meta.permissions().mode() & 0o777 != 0o600
        || meta.uid() != unsafe { libc::geteuid() }
    {
        return false;
    }
    let Ok(inhalt) = std::fs::read_to_string(pfad) else {
        return false;
    };
    let Ok(freigabe) = serde_json::from_str::<RohFreigabe>(&inhalt) else {
        return false;
    };
    let vertrag_bekannt = freigabe.contract == WRITE_RELEASE_CONTRACT
        || freigabe.contract == WRITE_RELEASE_CONTRACT_V2;
    if !vertrag_bekannt
        || !freigabe.operations.iter().any(|o| o == operation)
        || freigabe.reason.trim().is_empty()
    {
        return false;
    }

    // v1 kennt weder Fähigkeit noch Modus: er *ist* der befristete
    // Kontaktvertrag. v2 muss beides ausdrücklich nennen.
    let (gemeinte_capability, modus) = if freigabe.contract == WRITE_RELEASE_CONTRACT {
        (WRITE_RELEASE_CAPABILITY.to_string(), MODE_TEMPORARY.to_string())
    } else {
        let Some(capability) = freigabe.capability.clone() else {
            return false;
        };
        let Some(modus) = freigabe.mode.clone() else {
            return false;
        };
        if modus != MODE_TEMPORARY && modus != MODE_STANDING {
            return false;
        }
        (capability, modus)
    };
    if gemeinte_capability != WRITE_RELEASE_CAPABILITY {
        return false;
    }

    if modus == MODE_STANDING {
        // Kein Ablauf — sonst stünden zwei Aussagen nebeneinander und keine
        // wäre die geltende. Dafür ein Beginn und keine Rücknahme.
        return freigabe.expires_at.is_none()
            && freigabe
                .granted_at
                .as_deref()
                .and_then(unix_aus_iso8601)
                .is_some()
            && freigabe
                .revoked_at
                .as_deref()
                .and_then(unix_aus_iso8601)
                .is_none();
    }

    let Some(endet) = freigabe.expires_at.as_deref().and_then(unix_aus_iso8601) else {
        return false;
    };
    endet > jetzt_unix && endet <= jetzt_unix + MAX_RELEASE_HOURS * 3600
}

/// Minimaler ISO-8601-Leser für `YYYY-MM-DDTHH:MM:SS(±HH:MM|Z)`.
///
/// Bewusst eigenhändig statt per Zeitbibliothek: Es geht um genau ein
/// Format, das der Kern schreibt, und eine zusätzliche Abhängigkeit für
/// vierzig Zeilen wäre die teurere Entscheidung.
pub(crate) fn unix_aus_iso8601(wert: &str) -> Option<i64> {
    let bytes = wert.as_bytes();
    if bytes.len() < 19 || bytes[4] != b'-' || bytes[7] != b'-' || bytes[10] != b'T' {
        return None;
    }
    let zahl = |von: usize, bis: usize| -> Option<i64> { wert[von..bis].parse::<i64>().ok() };
    let (jahr, monat, tag) = (zahl(0, 4)?, zahl(5, 7)?, zahl(8, 10)?);
    let (stunde, minute, sekunde) = (zahl(11, 13)?, zahl(14, 16)?, zahl(17, 19)?);
    if !(1..=12).contains(&monat) || !(1..=31).contains(&tag) {
        return None;
    }

    // Tage seit 1970-01-01 (Howard Hinnants `days_from_civil`).
    let y = if monat <= 2 { jahr - 1 } else { jahr };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (monat + 9) % 12;
    let doy = (153 * mp + 2) / 5 + tag - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let tage = era * 146097 + doe - 719468;

    let mut sekunden = tage * 86400 + stunde * 3600 + minute * 60 + sekunde;

    // Zeitzone: `Z` oder ±HH:MM. Fehlt sie, gilt UTC — der Kern schreibt
    // immer eine, aber Raten wäre hier schlimmer als eine feste Annahme.
    let rest = &wert[19..];
    if let Some(zeichen) = rest.chars().find(|z| *z == '+' || *z == '-') {
        let pos = rest.find(zeichen)?;
        let versatz = &rest[pos + 1..];
        if versatz.len() >= 5 {
            let h: i64 = versatz[0..2].parse().ok()?;
            let m: i64 = versatz[3..5].parse().ok()?;
            let delta = h * 3600 + m * 60;
            sekunden += if zeichen == '+' { -delta } else { delta };
        }
    }
    Some(sekunden)
}

pub fn default_release_path() -> std::path::PathBuf {
    let home = std::env::var("OPENJARVIS_HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            std::path::PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".openjarvis")
        });
    home.join("personal").join(WRITE_RELEASE_FILENAME)
}

// ── Der Ablauf ──────────────────────────────────────────────────────────────

/// Prüft den Feldvorrat der Nutzlast gegen den v1-Vertrag.
pub fn felder_sind_v1(payload: &serde_json::Value) -> bool {
    let Some(felder) = payload.get("fields").and_then(|f| f.as_object()) else {
        return false;
    };
    felder.keys().all(|k| CREATE_V1_KEYS.contains(&k.as_str()))
}

/// Der Zielcontainer aus dem Auftrag — der App-Prozess sucht sich keinen aus.
pub fn zielcontainer(order: &ExecutionOrderV1) -> Option<String> {
    order
        .provider_target
        .get("container_identifier")
        .and_then(|w| w.clone())
        .filter(|w| !w.is_empty())
}

/// Übersetzt das native Ergebnis in einen typisierten Bericht.
///
/// Die Zuordnung ist die eigentliche Sicherheitsaussage: Alles **vor** dem
/// Save wird `not_sent` (beweisbar nichts übergeben), alles **nach** einem
/// abgesetzten Save, das nicht sauber belegt ist, wird `outcome_unknown` —
/// niemals ein zweiter Versuch.
pub fn bericht_aus_ergebnis(
    order: &ExecutionOrderV1,
    r: &JCContactsCreateResult,
) -> ExecutionReportV1 {
    let mut bericht = ExecutionReportV1::not_sent(order, "provider_channel_disabled_before_send");
    bericht.save_request_count = r.save_attempts.clamp(0, 1) as u32;
    bericht.send_attempted = r.save_attempts > 0;
    bericht.diagnostic_artifact_present = r.diagnostics_artifact_written != 0;

    let fehlerdomaene = c_string_to_rust(&r.error_domain);
    let ausnahme = c_string_to_rust(&r.exception_name);
    let reason_digest = c_string_to_rust(&r.reason_digest);
    if !reason_digest.is_empty() {
        bericht.error_digest = Some(reason_digest);
    } else if !fehlerdomaene.is_empty() {
        bericht.error_digest = Some(sha256_hex(&format!(
            "{}:{}:{}",
            fehlerdomaene, r.error_code, ausnahme
        )));
    }

    match r.outcome {
        OUTCOME_NOT_AUTHORIZED => {
            bericht.outcome = "not_sent".into();
            bericht.error_class = Some("not_authorized".into());
        }
        OUTCOME_CONTAINER_NOT_FOUND => {
            bericht.outcome = "not_sent".into();
            bericht.error_class = Some("container_unavailable".into());
        }
        OUTCOME_READ_PREFLIGHT_FAILED => {
            bericht.outcome = "not_sent".into();
            bericht.error_class = Some("write_stack_unavailable".into());
        }
        OUTCOME_INVALID_PAYLOAD => {
            bericht.outcome = "not_sent".into();
            bericht.error_class = Some("invalid_payload".into());
        }
        OUTCOME_SAVE_ERROR => {
            // Der Save wurde abgesetzt und meldete einen Fehler. Ob dabei
            // etwas geschrieben wurde, weiss niemand — also ungewiss.
            bericht.outcome = "outcome_unknown".into();
            bericht.error_class = Some("provider_save_error".into());
        }
        OUTCOME_CAUGHT_EXCEPTION => {
            bericht.outcome = "outcome_unknown".into();
            bericht.error_class = Some("provider_exception".into());
        }
        OUTCOME_IDENTIFIER_MISSING => {
            bericht.outcome = "outcome_unknown".into();
            bericht.error_class = Some("readback_failed".into());
        }
        OUTCOME_READBACK_FAILED => {
            bericht.outcome = "outcome_unknown".into();
            bericht.readback_status = "failed".into();
            bericht.error_class = Some("readback_failed".into());
            let kennung = c_string_to_rust(&r.provider_identifier);
            if !kennung.is_empty() {
                bericht.provider_identifier_digest =
                    Some(c_string_to_rust(&r.provider_identifier_digest));
                bericht.provider_identifier = Some(kennung);
            }
        }
        OUTCOME_APPLIED => {
            bericht.outcome = "applied".into();
            bericht.readback_status = "confirmed".into();
            bericht.error_class = None;
            bericht.error_digest = None;
            bericht.provider_identifier_digest =
                Some(c_string_to_rust(&r.provider_identifier_digest));
            bericht.provider_identifier = Some(c_string_to_rust(&r.provider_identifier));
            let roh = c_string_to_rust(&r.readback_json);
            bericht.readback_contact = serde_json::from_str(&roh).ok();
            if bericht.readback_contact.is_none() {
                // Gespeichert, aber der gelesene Zustand ist unbrauchbar:
                // das ist kein `applied`, sondern ein ungewisser Ausgang.
                bericht.outcome = "outcome_unknown".into();
                bericht.readback_status = "failed".into();
                bericht.error_class = Some("readback_failed".into());
            }
        }
        _ => {
            bericht.outcome = "outcome_unknown".into();
            bericht.error_class = Some("provider_unavailable".into());
        }
    }
    bericht
}

/// Führt den nativen Create aus — den einen Save, oder gar nichts.
#[cfg(target_os = "macos")]
pub fn fuehre_create_aus(order: &ExecutionOrderV1, jetzt_unix: i64) -> ExecutionReportV1 {
    use std::ffi::CString;

    if order.operation_type != "create" {
        return ExecutionReportV1::not_sent(order, "schema_mismatch");
    }
    if !write_release_erlaubt(&default_release_path(), "create", jetzt_unix) {
        return ExecutionReportV1::not_sent(order, "provider_channel_disabled_before_send");
    }
    if !felder_sind_v1(&order.canonical_payload) {
        return ExecutionReportV1::not_sent(order, "unsupported_field");
    }
    let Some(container) = zielcontainer(order) else {
        return ExecutionReportV1::not_sent(order, "container_unavailable");
    };
    let Some(felder) = order.canonical_payload.get("fields") else {
        return ExecutionReportV1::not_sent(order, "invalid_payload");
    };
    let (Ok(payload), Ok(ziel), Ok(autor)) = (
        CString::new(serde_json::to_string(felder).unwrap_or_default()),
        CString::new(container),
        CString::new(order.transaction_author.clone()),
    ) else {
        return ExecutionReportV1::not_sent(order, "invalid_payload");
    };

    let mut ergebnis = JCContactsCreateResult::default();
    unsafe {
        jc_contacts_create_run(
            payload.as_ptr(),
            ziel.as_ptr(),
            autor.as_ptr(),
            &mut ergebnis,
        );
    }
    bericht_aus_ergebnis(order, &ergebnis)
}

/// Kontaktfreier Testeinstieg: derselbe Ablauf, Fake-Operationen im Shim.
#[cfg(all(target_os = "macos", debug_assertions))]
pub fn fuehre_szenario_aus(
    order: &ExecutionOrderV1,
    szenario: i32,
) -> Option<ExecutionReportV1> {
    use std::ffi::CString;

    let felder = order.canonical_payload.get("fields")?;
    let payload = CString::new(serde_json::to_string(felder).ok()?).ok()?;
    let mut ergebnis = JCContactsCreateResult::default();
    unsafe {
        jc_contacts_create_run_scenario(szenario, payload.as_ptr(), &mut ergebnis);
    }
    Some(bericht_aus_ergebnis(order, &ergebnis))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;

    fn order(felder: serde_json::Value) -> ExecutionOrderV1 {
        let payload = serde_json::json!({"fields": felder});
        crate::contacts_execution::testhilfe_order("create", payload)
    }

    // ── Feldvertrag ─────────────────────────────────────────────────────────
    #[test]
    fn alle_v1_felder_gehen_durch() {
        let o = order(serde_json::json!({
            "contactType": "person", "givenName": "A", "familyName": "B",
            "emails": [{"label": "home", "value": "a@example.invalid"}],
            "phones": [{"label": null, "value": "+49 000 0"}],
            "postalAddresses": [{"label": "work", "city": "Ort"}],
            "urls": [{"label": null, "value": "https://example.invalid"}],
            "dates": [{"label": "other", "month": 5, "day": 6}],
            "birthday": {"year": 1990, "month": 1, "day": 2}
        }));
        assert!(felder_sind_v1(&o.canonical_payload));
    }

    #[test]
    fn zurueckgestellte_felder_werden_abgewiesen() {
        for verboten in ["note", "socialProfiles", "instantMessages", "relations",
                         "imageData", "thumbnailImageData", "nonGregorianBirthday"] {
            let o = order(serde_json::json!({ verboten: "x" }));
            assert!(!felder_sind_v1(&o.canonical_payload), "{verboten}");
        }
    }

    #[test]
    fn ohne_fields_gibt_es_keinen_vertrag() {
        let o = crate::contacts_execution::testhilfe_order("create", serde_json::json!({}));
        assert!(!felder_sind_v1(&o.canonical_payload));
    }

    // ── Zielcontainer ───────────────────────────────────────────────────────
    #[test]
    fn der_container_kommt_aus_dem_auftrag() {
        let mut o = order(serde_json::json!({"givenName": "A"}));
        assert_eq!(zielcontainer(&o).as_deref(), Some("C-TEST"));
        o.provider_target
            .insert("container_identifier".into(), Some(String::new()));
        assert_eq!(zielcontainer(&o), None);
        o.provider_target.remove("container_identifier");
        assert_eq!(zielcontainer(&o), None);
    }

    // ── Schreibfreigabe ─────────────────────────────────────────────────────
    fn schreibe_freigabe(dir: &std::path::Path, inhalt: &str, modus: u32) -> std::path::PathBuf {
        let pfad = dir.join(WRITE_RELEASE_FILENAME);
        let mut f = std::fs::File::create(&pfad).unwrap();
        f.write_all(inhalt.as_bytes()).unwrap();
        std::fs::set_permissions(&pfad, std::fs::Permissions::from_mode(modus)).unwrap();
        pfad
    }

    fn privates_verzeichnis(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("jc-create-{}-{}", name, std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
        dir
    }

    const JETZT: i64 = 1_785_800_000; // fester Zeitpunkt, keine Wanduhr

    fn gueltig(bis: &str) -> String {
        format!(
            r#"{{"contract":"contacts-write-v1","operations":["create"],
                 "expires_at":"{bis}","reason":"kontrollierter Intel-Livetest"}}"#
        )
    }

    #[test]
    fn ohne_datei_gibt_es_keine_freigabe() {
        let dir = privates_verzeichnis("leer");
        assert!(!write_release_erlaubt(
            &dir.join(WRITE_RELEASE_FILENAME),
            "create",
            JETZT
        ));
    }

    #[test]
    fn eine_gueltige_freigabe_oeffnet_genau_create() {
        let dir = privates_verzeichnis("gueltig");
        let pfad = schreibe_freigabe(&dir, &gueltig("2026-08-04T02:00:00+00:00"), 0o600);
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(write_release_erlaubt(&pfad, "create", jetzt));
        assert!(!write_release_erlaubt(&pfad, "update", jetzt));
        assert!(!write_release_erlaubt(&pfad, "delete", jetzt));
    }

    // ── Dauerfreigabe (v2) ──────────────────────────────────────────────────
    //
    // Dieselben Regeln wie im Kern (`write_release.py`). Laufen die beiden
    // Seiten auseinander, meldet die eine „darf" und die andere „darf nicht" —
    // genau der Zustand, den dieser Vertrag verhindern soll.
    fn dauerhaft(zusatz: &str) -> String {
        format!(
            r#"{{"contract":"contacts-write-v2","capability":"contacts",
                 "mode":"standing","operations":["create"],
                 "granted_at":"2026-08-17T12:00:00+00:00",
                 "reason":"Im Produkt eingeschaltet"{zusatz}}}"#
        )
    }

    #[test]
    fn eine_dauerfreigabe_gilt_auch_lange_danach() {
        let dir = privates_verzeichnis("dauer");
        let pfad = schreibe_freigabe(&dir, &dauerhaft(""), 0o600);
        let start = unix_aus_iso8601("2026-08-17T12:00:00+00:00").unwrap();
        assert!(write_release_erlaubt(&pfad, "create", start));
        // Ein Neustart Wochen spaeter aendert nichts.
        assert!(write_release_erlaubt(&pfad, "create", start + 97 * 86400));
        // Dauerhaft ist trotzdem nicht universell.
        assert!(!write_release_erlaubt(&pfad, "update", start));
        assert!(!write_release_erlaubt(&pfad, "delete", start));
    }

    #[test]
    fn eine_dauerfreigabe_mit_ablauf_gilt_nicht() {
        let dir = privates_verzeichnis("dauer-ablauf");
        let pfad = schreibe_freigabe(
            &dir,
            &dauerhaft(r#","expires_at":"2026-08-17T13:00:00+00:00""#),
            0o600,
        );
        let start = unix_aus_iso8601("2026-08-17T12:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", start));
    }

    #[test]
    fn eine_zurueckgenommene_dauerfreigabe_gilt_nicht() {
        let dir = privates_verzeichnis("dauer-zurueck");
        let pfad = schreibe_freigabe(
            &dir,
            &dauerhaft(r#","revoked_at":"2026-08-18T12:00:00+00:00""#),
            0o600,
        );
        let start = unix_aus_iso8601("2026-08-17T12:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", start));
    }

    #[test]
    fn eine_dauerfreigabe_fuer_eine_fremde_faehigkeit_gilt_nicht() {
        let dir = privates_verzeichnis("dauer-fremd");
        let inhalt = dauerhaft("").replace(r#""capability":"contacts""#, r#""capability":"calendar""#);
        let pfad = schreibe_freigabe(&dir, &inhalt, 0o600);
        let start = unix_aus_iso8601("2026-08-17T12:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", start));
    }

    #[test]
    fn ein_v1_dokument_wird_nie_zur_dauerfreigabe() {
        // Der Schutz gegen Umdeutung: das Wort `standing` in einer alten,
        // befristeten Urkunde aendert nichts an ihrem Ablauf.
        let dir = privates_verzeichnis("v1-standing");
        let inhalt = r#"{"contract":"contacts-write-v1","operations":["create"],
             "mode":"standing","expires_at":"2026-08-04T02:00:00+00:00",
             "reason":"alt"}"#;
        let pfad = schreibe_freigabe(&dir, inhalt, 0o600);
        let vorher = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        let nachher = unix_aus_iso8601("2026-08-04T03:00:00+00:00").unwrap();
        assert!(write_release_erlaubt(&pfad, "create", vorher));
        assert!(!write_release_erlaubt(&pfad, "create", nachher));
    }

    #[test]
    fn eine_dauerfreigabe_mit_zu_offenen_rechten_gilt_nicht() {
        let dir = privates_verzeichnis("dauer-rechte");
        let pfad = schreibe_freigabe(&dir, &dauerhaft(""), 0o644);
        let start = unix_aus_iso8601("2026-08-17T12:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", start));
    }

    #[test]
    fn zu_offene_rechte_verwerfen_die_freigabe() {
        let dir = privates_verzeichnis("rechte");
        let pfad = schreibe_freigabe(&dir, &gueltig("2026-08-04T02:00:00+00:00"), 0o644);
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", jetzt));
    }

    #[test]
    fn ein_offenes_verzeichnis_verwirft_die_freigabe() {
        let dir = privates_verzeichnis("offen");
        let pfad = schreibe_freigabe(&dir, &gueltig("2026-08-04T02:00:00+00:00"), 0o600);
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", jetzt));
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
    }

    #[test]
    fn abgelaufen_ist_nicht_freigegeben() {
        let dir = privates_verzeichnis("abgelaufen");
        let pfad = schreibe_freigabe(&dir, &gueltig("2026-08-03T23:00:00+00:00"), 0o600);
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", jetzt));
    }

    #[test]
    fn eine_freigabe_weit_in_der_zukunft_ist_ein_dauerzustand() {
        let dir = privates_verzeichnis("dauer");
        let pfad = schreibe_freigabe(&dir, &gueltig("2027-01-01T00:00:00+00:00"), 0o600);
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", jetzt));
    }

    #[test]
    fn ein_fremder_vertrag_oeffnet_nichts() {
        let dir = privates_verzeichnis("fremd");
        let pfad = schreibe_freigabe(
            &dir,
            r#"{"contract":"anderer","operations":["create"],
                "expires_at":"2026-08-04T02:00:00+00:00","reason":"x"}"#,
            0o600,
        );
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", jetzt));
    }

    #[test]
    fn ohne_begruendung_gibt_es_keine_freigabe() {
        let dir = privates_verzeichnis("ohnegrund");
        let pfad = schreibe_freigabe(
            &dir,
            r#"{"contract":"contacts-write-v1","operations":["create"],
                "expires_at":"2026-08-04T02:00:00+00:00","reason":"   "}"#,
            0o600,
        );
        let jetzt = unix_aus_iso8601("2026-08-04T00:00:00+00:00").unwrap();
        assert!(!write_release_erlaubt(&pfad, "create", jetzt));
    }

    #[test]
    fn keine_umgebungsvariable_taucht_im_quelltext_auf() {
        // Der Schalter ist eine Datei. Eine Variable, die ihn ersetzt, waere
        // genau der Rueckschritt, den dieser Vertrag verhindert.
        // Nur der Produktivteil: Der Test selbst nennt die verbotenen Namen
        // als Verbot — eine Pruefung, die daran scheitert, bestrafte die
        // Begruendung statt den Code.
        let quelle = include_str!("contacts_create.rs");
        let produktiv = quelle.split("#[cfg(test)]").next().unwrap();
        let code: String = produktiv
            .lines()
            .filter(|z| !z.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        for verboten in [
            "OPENJARVIS_CONTACTS_WRITE",
            "PERSONAL_JARVIS_WRITE",
            "CONTACTS_CREATE_ENABLED",
        ] {
            assert!(!code.contains(verboten), "{verboten}");
        }
    }

    // ── Zeitleser ───────────────────────────────────────────────────────────
    #[test]
    fn iso8601_wird_korrekt_gelesen() {
        assert_eq!(unix_aus_iso8601("1970-01-01T00:00:00+00:00"), Some(0));
        assert_eq!(unix_aus_iso8601("2026-08-04T00:00:00Z"), Some(1_785_801_600));
        // Ein Versatz verschiebt in die richtige Richtung: 02:00+02:00 == 00:00Z
        assert_eq!(
            unix_aus_iso8601("2026-08-04T02:00:00+02:00"),
            unix_aus_iso8601("2026-08-04T00:00:00Z")
        );
        assert_eq!(unix_aus_iso8601("keine Zeit"), None);
        assert_eq!(unix_aus_iso8601("2026-13-04T00:00:00Z"), None);
    }

    // ── Ergebnisabbildung ───────────────────────────────────────────────────
    fn ergebnis(outcome: i32, save: i32) -> JCContactsCreateResult {
        JCContactsCreateResult {
            outcome,
            save_attempts: save,
            add_request_count: save,
            ..Default::default()
        }
    }

    #[test]
    fn alles_vor_dem_save_ist_beweisbar_nicht_gesendet() {
        let o = order(serde_json::json!({"givenName": "A"}));
        for (code, klasse) in [
            (OUTCOME_NOT_AUTHORIZED, "not_authorized"),
            (OUTCOME_CONTAINER_NOT_FOUND, "container_unavailable"),
            (OUTCOME_READ_PREFLIGHT_FAILED, "write_stack_unavailable"),
            (OUTCOME_INVALID_PAYLOAD, "invalid_payload"),
        ] {
            let b = bericht_aus_ergebnis(&o, &ergebnis(code, 0));
            assert_eq!(b.outcome, "not_sent", "{klasse}");
            assert!(!b.send_attempted);
            assert_eq!(b.save_request_count, 0);
            assert_eq!(b.error_class.as_deref(), Some(klasse));
            assert!(b.provider_identifier.is_none());
        }
    }

    #[test]
    fn alles_nach_dem_save_ohne_beleg_ist_ungewiss() {
        let o = order(serde_json::json!({"givenName": "A"}));
        for (code, klasse) in [
            (OUTCOME_SAVE_ERROR, "provider_save_error"),
            (OUTCOME_CAUGHT_EXCEPTION, "provider_exception"),
            (OUTCOME_IDENTIFIER_MISSING, "readback_failed"),
            (OUTCOME_READBACK_FAILED, "readback_failed"),
        ] {
            let b = bericht_aus_ergebnis(&o, &ergebnis(code, 1));
            assert_eq!(b.outcome, "outcome_unknown", "{klasse}");
            assert!(b.send_attempted);
            assert_eq!(b.save_request_count, 1);
            assert_eq!(b.error_class.as_deref(), Some(klasse));
        }
    }

    #[test]
    fn applied_ohne_lesbaren_rueckgabewert_ist_ungewiss() {
        let o = order(serde_json::json!({"givenName": "A"}));
        let b = bericht_aus_ergebnis(&o, &ergebnis(OUTCOME_APPLIED, 1));
        assert_eq!(b.outcome, "outcome_unknown");
        assert_eq!(b.readback_status, "failed");
    }

    #[test]
    fn ein_unbekannter_ausgang_ist_ungewiss_nicht_erfolgreich() {
        let o = order(serde_json::json!({"givenName": "A"}));
        let b = bericht_aus_ergebnis(&o, &ergebnis(4242, 1));
        assert_eq!(b.outcome, "outcome_unknown");
    }

    #[test]
    fn mehr_als_ein_save_wird_niemals_gemeldet() {
        let o = order(serde_json::json!({"givenName": "A"}));
        let b = bericht_aus_ergebnis(&o, &ergebnis(OUTCOME_APPLIED, 5));
        assert_eq!(b.save_request_count, 1);
    }

    // ── Nativer Ablauf gegen Fakes (kontaktfrei) ────────────────────────────
    #[cfg(debug_assertions)]
    #[test]
    fn der_native_ablauf_deckt_alle_szenarien_ab() {
        let o = order(serde_json::json!({
            "contactType": "person",
            "givenName": "Jarvis",
            "familyName": "Create Intel Test 2026-08-04",
            "emails": [{"label": "work", "value": "j@example.invalid"}]
        }));
        let faelle = [
            (1, "not_sent", Some("not_authorized")),
            (2, "not_sent", Some("container_unavailable")),
            (3, "not_sent", Some("write_stack_unavailable")),
            (4, "applied", None),
            (5, "outcome_unknown", Some("provider_save_error")),
            (6, "outcome_unknown", Some("provider_exception")),
            (7, "outcome_unknown", Some("readback_failed")),
            (8, "outcome_unknown", Some("readback_failed")),
        ];
        for (szenario, ausgang, klasse) in faelle {
            let b = fuehre_szenario_aus(&o, szenario).expect("Szenario liefert Bericht");
            assert_eq!(b.outcome, ausgang, "Szenario {szenario}");
            assert_eq!(b.error_class.as_deref(), klasse, "Szenario {szenario}");
            assert!(b.save_request_count <= 1);
        }
    }

    #[cfg(debug_assertions)]
    #[test]
    fn der_erfolgsfall_liest_ueber_die_kennung_zurueck() {
        let o = order(serde_json::json!({
            "contactType": "person",
            "givenName": "Jarvis",
            "familyName": "Create Intel Test 2026-08-04",
            "organizationName": "OpenJarvis Synthetic Test",
            "emails": [{"label": "work", "value": "j@example.invalid"}],
            "phones": [{"label": "mobile", "value": "+49 000 0000000"}]
        }));
        let b = fuehre_szenario_aus(&o, 4).unwrap();
        assert_eq!(b.outcome, "applied");
        assert_eq!(b.readback_status, "confirmed");
        assert_eq!(b.save_request_count, 1);
        assert!(b.provider_identifier.is_some());
        assert_eq!(b.provider_identifier_digest.as_ref().unwrap().len(), 64);
        let gelesen = b.readback_contact.expect("Read-back vorhanden");
        assert_eq!(gelesen["givenName"], "Jarvis");
        assert_eq!(gelesen["organizationName"], "OpenJarvis Synthetic Test");
        assert_eq!(gelesen["emails"][0]["label"], "work");
        assert_eq!(gelesen["phones"][0]["label"], "mobile");
    }

    #[cfg(debug_assertions)]
    #[test]
    fn ein_abweichender_rueckgabewert_bleibt_ein_beleg_und_wird_im_kern_verglichen() {
        // Der App-Prozess urteilt nicht: Er meldet, was er gelesen hat. Dass
        // der Wert abweicht, stellt der Kern beim Digestvergleich fest.
        let o = order(serde_json::json!({"contactType": "person", "givenName": "Jarvis"}));
        let b = fuehre_szenario_aus(&o, 9).unwrap();
        assert_eq!(b.outcome, "applied");
        assert_eq!(b.readback_contact.unwrap()["givenName"], "Abweichend");
    }

    #[cfg(debug_assertions)]
    #[test]
    fn ein_nicht_freigegebenes_feld_erreicht_den_store_nie() {
        let o = order(serde_json::json!({"givenName": "A", "note": "geheim"}));
        assert!(!felder_sind_v1(&o.canonical_payload));
        // Selbst wenn es der Shim saehe: er weist es vor jedem Save ab.
        let b = fuehre_szenario_aus(&o, 4).unwrap();
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(b.save_request_count, 0);
    }
}

// ═══ Update und Delete (ADR-0026 §8.2/§8.3, DEC-053) ════════════════════════

/// Ausgänge des Schreibpfads — deckungsgleich mit `JCContactsWriteOutcome`.
const W_NOT_AUTHORIZED: i32 = 1;
const W_TARGET_NOT_FOUND: i32 = 2;
const W_REVISION_CONFLICT: i32 = 3;
const W_INVALID_PAYLOAD: i32 = 4;
const W_APPLIED: i32 = 5;
const W_SAVE_ERROR: i32 = 6;
const W_CAUGHT_EXCEPTION: i32 = 7;
const W_READBACK_FAILED: i32 = 8;
const W_ABSENCE_UNPROVEN: i32 = 9;
const W_ME_CARD_PROTECTED: i32 = 10;
const W_CONTAINER_MISMATCH: i32 = 11;

/// Übersetzt ein Schreibergebnis in den typisierten Bericht.
///
/// Die Trennlinie ist dieselbe wie beim Create und wichtiger als jede
/// Feinheit: Alles **vor** dem Save wird `not_sent` — nachweislich nichts
/// übergeben. Alles **danach** ohne Beleg wird `outcome_unknown`, nie ein
/// zweiter Versuch.
pub fn bericht_aus_schreibergebnis(
    order: &ExecutionOrderV1,
    r: &JCContactsCreateResult,
) -> ExecutionReportV1 {
    let mut bericht = ExecutionReportV1::not_sent(order, "provider_unavailable");
    bericht.save_request_count = r.save_attempts.clamp(0, 1) as u32;
    bericht.send_attempted = r.save_attempts > 0;
    bericht.diagnostic_artifact_present = r.diagnostics_artifact_written != 0;

    let domaene = c_string_to_rust(&r.error_domain);
    let ausnahme = c_string_to_rust(&r.exception_name);
    let reason_digest = c_string_to_rust(&r.reason_digest);
    if !reason_digest.is_empty() {
        bericht.error_digest = Some(reason_digest);
    } else if !domaene.is_empty() {
        bericht.error_digest = Some(sha256_hex(&format!(
            "{}:{}:{}",
            domaene, r.error_code, ausnahme
        )));
    }

    let vor_dem_send = |klasse: &str, b: &mut ExecutionReportV1| {
        b.outcome = "not_sent".into();
        b.send_attempted = false;
        b.save_request_count = 0;
        b.readback_status = "not_attempted".into();
        b.error_class = Some(klasse.into());
    };

    match r.outcome {
        W_NOT_AUTHORIZED => vor_dem_send("not_authorized", &mut bericht),
        W_TARGET_NOT_FOUND => vor_dem_send("target_not_found", &mut bericht),
        W_REVISION_CONFLICT => vor_dem_send("revision_conflict", &mut bericht),
        W_INVALID_PAYLOAD => vor_dem_send("invalid_payload", &mut bericht),
        // `me_card_protected` ist keine Vertragsklasse (der 0008-CHECK ist
        // produktiv angewandt und geschlossen): Die Schutzregel verweigert
        // die Operation gegen dieses Ziel — das ist `capability_denied`.
        W_ME_CARD_PROTECTED => vor_dem_send("capability_denied", &mut bericht),
        W_CONTAINER_MISMATCH => vor_dem_send("container_unavailable", &mut bericht),
        W_SAVE_ERROR => {
            // Der Save wurde übergeben und meldete einen Fehler. Ob dabei
            // etwas geschrieben wurde, weiss niemand — also Abgleich.
            bericht.outcome = "outcome_unknown".into();
            bericht.readback_status = "not_attempted".into();
            bericht.error_class = Some("provider_save_error".into());
        }
        W_CAUGHT_EXCEPTION => {
            bericht.outcome = "outcome_unknown".into();
            bericht.readback_status = "not_attempted".into();
            bericht.error_class = Some("provider_exception".into());
        }
        W_READBACK_FAILED => {
            bericht.outcome = "outcome_unknown".into();
            bericht.readback_status = "failed".into();
            bericht.error_class = Some("readback_failed".into());
        }
        W_ABSENCE_UNPROVEN => {
            // Gespeichert, aber die Abwesenheit ist nicht belegt. „Nicht
            // lesbar" ist kein Löschnachweis (ADR-0026 §8.3).
            bericht.outcome = "outcome_unknown".into();
            bericht.readback_status = "failed".into();
            bericht.error_class = Some("readback_failed".into());
            bericht.provider_identifier_digest =
                Some(c_string_to_rust(&r.provider_identifier_digest));
        }
        W_APPLIED => {
            bericht.outcome = "applied".into();
            bericht.error_class = None;
            bericht.error_digest = None;
            bericht.provider_identifier_digest =
                Some(c_string_to_rust(&r.provider_identifier_digest));
            bericht.provider_identifier = Some(c_string_to_rust(&r.provider_identifier));
            if order.operation_type == "delete" {
                bericht.readback_status = "absent_confirmed".into();
                bericht.readback_contact = None;
            } else {
                bericht.readback_status = "confirmed".into();
                let roh = c_string_to_rust(&r.readback_json);
                bericht.readback_contact = serde_json::from_str(&roh).ok();
                if bericht.readback_contact.is_none() {
                    bericht.outcome = "outcome_unknown".into();
                    bericht.readback_status = "failed".into();
                    bericht.error_class = Some("readback_failed".into());
                }
            }
        }
        _ => {
            bericht.outcome = "outcome_unknown".into();
            bericht.error_class = Some("provider_unavailable".into());
        }
    }
    bericht
}

/// Liest die drei Pflichtstücke eines Update-/Delete-Auftrags.
///
/// Sie stehen im **digest-gebundenen** Payload, nicht in einem Seitenkanal:
/// Was hier gelesen wird, hat der Mensch in der Vorschau gesehen.
fn schreibziel(order: &ExecutionOrderV1) -> Option<(String, serde_json::Value)> {
    let ziel = order
        .provider_target
        .get("provider_identifier")?
        .clone()?;
    if ziel.is_empty() {
        return None;
    }
    let vorher = order.canonical_payload.get("expectedPrevious")?.clone();
    if !vorher.is_object() {
        return None;
    }
    Some((ziel, vorher))
}

/// Prüft, dass der erwartete Vorzustand zu seinem Digest passt.
///
/// Ohne diese Prüfung liesse sich der Vergleichsmassstab austauschen, ohne
/// dass der `payload_digest` es merkte — der Konflikt-Check prüfte dann
/// gegen etwas, das nie freigegeben wurde.
fn vorzustand_ist_gebunden(order: &ExecutionOrderV1, vorher: &serde_json::Value) -> bool {
    let Some(erwartet) = order
        .canonical_payload
        .get("expectedFieldsDigest")
        .and_then(|w| w.as_str())
    else {
        return false;
    };
    let gerechnet = crate::contacts_execution::payload_digest(&serde_json::json!({
        "fieldContractVersion": order.field_contract_version,
        "fields": vorher,
    }));
    gerechnet == erwartet
}

#[cfg(target_os = "macos")]
fn fuehre_schreiben_aus(
    order: &ExecutionOrderV1,
    jetzt_unix: i64,
    loeschen: bool,
) -> ExecutionReportV1 {
    use std::ffi::CString;

    let operation = if loeschen { "delete" } else { "update" };
    if order.operation_type != operation {
        return ExecutionReportV1::not_sent(order, "schema_mismatch");
    }
    if !write_release_erlaubt(&default_release_path(), operation, jetzt_unix) {
        return ExecutionReportV1::not_sent(order, "provider_channel_disabled_before_send");
    }
    let Some((ziel, vorher)) = schreibziel(order) else {
        return ExecutionReportV1::not_sent(order, "invalid_payload");
    };
    if !vorzustand_ist_gebunden(order, &vorher) {
        return ExecutionReportV1::not_sent(order, "digest_mismatch");
    }
    if !loeschen && !felder_sind_v1(&order.canonical_payload) {
        return ExecutionReportV1::not_sent(order, "unsupported_field");
    }

    let (Ok(c_ziel), Ok(c_vorher), Ok(c_autor)) = (
        CString::new(ziel),
        CString::new(serde_json::to_string(&vorher).unwrap_or_default()),
        CString::new(order.transaction_author.clone()),
    ) else {
        return ExecutionReportV1::not_sent(order, "invalid_payload");
    };

    let mut ergebnis = JCContactsCreateResult::default();
    if loeschen {
        let container = order
            .provider_target
            .get("container_identifier")
            .and_then(|w| w.clone())
            .unwrap_or_default();
        let Ok(c_container) = CString::new(container) else {
            return ExecutionReportV1::not_sent(order, "invalid_payload");
        };
        unsafe {
            jc_contacts_delete_run(
                c_ziel.as_ptr(),
                c_vorher.as_ptr(),
                c_container.as_ptr(),
                c_autor.as_ptr(),
                &mut ergebnis,
            );
        }
    } else {
        let Some(felder) = order.canonical_payload.get("fields") else {
            return ExecutionReportV1::not_sent(order, "invalid_payload");
        };
        let Ok(c_patch) = CString::new(serde_json::to_string(felder).unwrap_or_default()) else {
            return ExecutionReportV1::not_sent(order, "invalid_payload");
        };
        unsafe {
            jc_contacts_update_run(
                c_ziel.as_ptr(),
                c_patch.as_ptr(),
                c_vorher.as_ptr(),
                c_autor.as_ptr(),
                &mut ergebnis,
            );
        }
    }
    bericht_aus_schreibergebnis(order, &ergebnis)
}

/// Führt den nativen Update aus — den einen Save, oder gar nichts.
#[cfg(target_os = "macos")]
pub fn fuehre_update_aus(order: &ExecutionOrderV1, jetzt_unix: i64) -> ExecutionReportV1 {
    fuehre_schreiben_aus(order, jetzt_unix, false)
}

/// Führt den nativen Delete aus — den einen Save, oder gar nichts.
#[cfg(target_os = "macos")]
pub fn fuehre_delete_aus(order: &ExecutionOrderV1, jetzt_unix: i64) -> ExecutionReportV1 {
    fuehre_schreiben_aus(order, jetzt_unix, true)
}

/// Kontaktfreie Testeinstiege — derselbe Ablauf, Fake-Anbindung im Shim.
#[cfg(all(target_os = "macos", debug_assertions))]
pub fn fuehre_schreibszenario_aus(
    order: &ExecutionOrderV1,
    szenario: i32,
    loeschen: bool,
) -> Option<ExecutionReportV1> {
    use std::ffi::CString;

    let (_, vorher) = schreibziel(order)?;
    let c_vorher = CString::new(serde_json::to_string(&vorher).ok()?).ok()?;
    let mut ergebnis = JCContactsCreateResult::default();
    if loeschen {
        unsafe {
            jc_contacts_delete_run_scenario(szenario, c_vorher.as_ptr(), &mut ergebnis);
        }
    } else {
        let felder = order.canonical_payload.get("fields")?;
        let c_patch = CString::new(serde_json::to_string(felder).ok()?).ok()?;
        unsafe {
            jc_contacts_update_run_scenario(
                szenario,
                c_patch.as_ptr(),
                c_vorher.as_ptr(),
                &mut ergebnis,
            );
        }
    }
    Some(bericht_aus_schreibergebnis(order, &ergebnis))
}

#[cfg(all(test, target_os = "macos"))]
mod schreib_tests {
    use super::*;
    use crate::contacts_execution::payload_digest;

    const W_SZENARIO_NICHT_AUTORISIERT: i32 = 1;
    const W_SZENARIO_ZIEL_FEHLT: i32 = 2;
    const W_SZENARIO_KONFLIKT: i32 = 3;
    const W_SZENARIO_SAVE_OK: i32 = 4;
    const W_SZENARIO_SAVE_NSERROR: i32 = 5;
    const W_SZENARIO_SAVE_WIRFT: i32 = 6;
    const W_SZENARIO_READBACK_FEHLT: i32 = 7;
    const W_SZENARIO_NOCH_DA: i32 = 8;
    const W_SZENARIO_NICHT_LESBAR: i32 = 9;
    const W_SZENARIO_ME_CARD: i32 = 10;
    const W_SZENARIO_CONTAINER: i32 = 11;

    fn vorher() -> serde_json::Value {
        serde_json::json!({
            "contactType": "person",
            "givenName": "Synthetisch",
            "familyName": "Attrappe",
            "emails": [{"label": "work", "value": "a@example.invalid"}]
        })
    }

    fn auftrag(operation: &str, patch: serde_json::Value) -> ExecutionOrderV1 {
        let vor = vorher();
        let mut payload = serde_json::json!({
            "fields": patch,
            "expectedPrevious": vor,
        });
        let digest = payload_digest(&serde_json::json!({
            "fieldContractVersion": 1,
            "fields": vor,
        }));
        payload["expectedFieldsDigest"] = serde_json::Value::String(digest);
        let roh = serde_json::json!({
            "schema_version": 1,
            "operation_id": "0".repeat(36),
            "mutation_id": "1".repeat(36),
            "claim_token": "a".repeat(64),
            "operation_type": operation,
            "payload_digest": payload_digest(&payload),
            "preview_digest": "c".repeat(64),
            "canonical_payload": payload,
            "readback_requirements": {"required": true},
            "issued_at": "2026-08-04T10:00:00+00:00",
            "expires_at": "2026-08-04T10:10:00+00:00",
            "mutation_contract_version": 1,
            "field_contract_version": 1,
            "transaction_author": "de.kluender.jarvis.contacts-bridge",
            "provider_target": {"provider_identifier": "ZIEL",
                                "container_identifier": "erwarteter-container"}
        });
        serde_json::from_value(roh).unwrap()
    }

    fn lauf(operation: &str, szenario: i32, patch: serde_json::Value)
        -> ExecutionReportV1
    {
        let o = auftrag(operation, patch);
        fuehre_schreibszenario_aus(&o, szenario, operation == "delete").unwrap()
    }

    // ── Vor dem Save: nichts uebergeben ─────────────────────────────────────
    #[test]
    fn ohne_autorisierung_wird_nichts_uebergeben() {
        let b = lauf("update", W_SZENARIO_NICHT_AUTORISIERT,
                     serde_json::json!({"jobTitle": "X"}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.save_request_count, 0);
        assert!(!b.send_attempted);
        assert_eq!(b.error_class.as_deref(), Some("not_authorized"));
    }

    #[test]
    fn ein_fehlendes_ziel_ist_kein_send() {
        let b = lauf("update", W_SZENARIO_ZIEL_FEHLT,
                     serde_json::json!({"jobTitle": "X"}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("target_not_found"));
    }

    #[test]
    fn ein_abweichender_vorzustand_endet_als_konflikt() {
        let b = lauf("update", W_SZENARIO_KONFLIKT,
                     serde_json::json!({"jobTitle": "X"}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.save_request_count, 0);
        assert_eq!(b.error_class.as_deref(), Some("revision_conflict"));
    }

    #[test]
    fn nicht_lesbar_ist_kein_befund_ueber_die_existenz() {
        let b = lauf("delete", W_SZENARIO_NICHT_LESBAR, serde_json::json!({}));
        assert_eq!(b.outcome, "outcome_unknown");
        assert_eq!(b.save_request_count, 0);
        assert_eq!(b.error_class.as_deref(), Some("readback_failed"));
    }

    #[test]
    fn die_me_karte_wird_nie_geloescht() {
        let b = lauf("delete", W_SZENARIO_ME_CARD, serde_json::json!({}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.save_request_count, 0);
        assert_eq!(b.error_class.as_deref(), Some("capability_denied"));
    }

    #[test]
    fn ein_fremder_container_wird_nicht_geloescht() {
        let b = lauf("delete", W_SZENARIO_CONTAINER, serde_json::json!({}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("container_unavailable"));
    }

    // ── Genau ein Save ──────────────────────────────────────────────────────
    #[test]
    fn ein_erfolgreicher_update_meldet_genau_einen_save() {
        let b = lauf("update", W_SZENARIO_SAVE_OK,
                     serde_json::json!({"jobTitle": "Neu"}));
        assert_eq!(b.outcome, "applied");
        assert_eq!(b.save_request_count, 1);
        assert!(b.send_attempted);
        assert_eq!(b.readback_status, "confirmed");
        let gelesen = b.readback_contact.expect("Read-back fehlt");
        assert_eq!(gelesen["jobTitle"], "Neu");
        // Der Patch laesst alles Uebrige stehen.
        assert_eq!(gelesen["givenName"], "Synthetisch");
    }

    #[test]
    fn ein_erfolgreiches_delete_belegt_die_abwesenheit() {
        let b = lauf("delete", W_SZENARIO_SAVE_OK, serde_json::json!({}));
        assert_eq!(b.outcome, "applied");
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.readback_status, "absent_confirmed");
        assert!(b.readback_contact.is_none());
        assert!(b.provider_identifier.is_some());
    }

    #[test]
    fn ein_noch_vorhandener_datensatz_ist_kein_loeschbeweis() {
        let b = lauf("delete", W_SZENARIO_NOCH_DA, serde_json::json!({}));
        assert_eq!(b.outcome, "outcome_unknown");
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.error_class.as_deref(), Some("readback_failed"));
    }

    // ── Nach dem Save ohne Beleg: ungewiss, nie ein zweiter Versuch ─────────
    #[test]
    fn ein_savefehler_endet_ungewiss() {
        let b = lauf("update", W_SZENARIO_SAVE_NSERROR,
                     serde_json::json!({"jobTitle": "X"}));
        assert_eq!(b.outcome, "outcome_unknown");
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.error_class.as_deref(), Some("provider_save_error"));
        assert!(b.error_digest.is_some());
    }

    #[test]
    fn eine_ausnahme_endet_ungewiss() {
        let b = lauf("update", W_SZENARIO_SAVE_WIRFT,
                     serde_json::json!({"jobTitle": "X"}));
        assert_eq!(b.outcome, "outcome_unknown");
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.error_class.as_deref(), Some("provider_exception"));
    }

    #[test]
    fn ein_fehlender_readback_endet_ungewiss() {
        let b = lauf("update", W_SZENARIO_READBACK_FEHLT,
                     serde_json::json!({"jobTitle": "X"}));
        assert_eq!(b.outcome, "outcome_unknown");
        assert_eq!(b.readback_status, "failed");
    }

    // ── Patch- und Loeschsemantik ───────────────────────────────────────────
    #[test]
    fn ein_fehlendes_feld_bleibt_unveraendert() {
        let b = lauf("update", W_SZENARIO_SAVE_OK,
                     serde_json::json!({"jobTitle": "Neu"}));
        let gelesen = b.readback_contact.unwrap();
        assert_eq!(gelesen["familyName"], "Attrappe");
        assert!(gelesen["emails"].is_array());
    }

    #[test]
    fn ein_ausdrueckliches_null_loescht_einen_skalar() {
        let b = lauf("update", W_SZENARIO_SAVE_OK,
                     serde_json::json!({"familyName": serde_json::Value::Null}));
        let gelesen = b.readback_contact.unwrap();
        // Geloescht heisst: erscheint in der kanonischen Form nicht mehr.
        assert!(gelesen.get("familyName").is_none());
        assert_eq!(gelesen["givenName"], "Synthetisch");
    }

    #[test]
    fn eine_leere_liste_loescht_alle_werte() {
        let b = lauf("update", W_SZENARIO_SAVE_OK,
                     serde_json::json!({"emails": []}));
        let gelesen = b.readback_contact.unwrap();
        assert!(gelesen.get("emails").is_none());
    }

    #[test]
    fn eine_ersetzte_liste_traegt_label_und_reihenfolge() {
        let b = lauf("update", W_SZENARIO_SAVE_OK, serde_json::json!({
            "emails": [{"label": "home", "value": "b@example.invalid"},
                       {"label": "work", "value": "c@example.invalid"}]
        }));
        let mails = b.readback_contact.unwrap()["emails"].clone();
        assert_eq!(mails[0]["label"], "home");
        assert_eq!(mails[0]["value"], "b@example.invalid");
        assert_eq!(mails[1]["label"], "work");
    }

    #[test]
    fn ein_unbekanntes_feld_wird_abgewiesen() {
        let b = lauf("update", W_SZENARIO_SAVE_OK,
                     serde_json::json!({"note": "verboten"}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.save_request_count, 0);
    }

    #[test]
    fn ein_typwechsel_wird_abgewiesen() {
        let b = lauf("update", W_SZENARIO_SAVE_OK,
                     serde_json::json!({"contactType": "organization"}));
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
    }

    // ── Bindung des Vergleichsmassstabs ────────────────────────────────────
    #[test]
    fn ein_ungebundener_vorzustand_wird_abgewiesen() {
        // Direkt an der Bindungspruefung: `fuehre_update_aus` haette hier
        // schon an der Freigabe angehalten — richtig so, aber dann prueft
        // der Test das Tor und nicht die Bindung.
        let mut o = auftrag("update", serde_json::json!({"jobTitle": "X"}));
        let (_, vorher) = schreibziel(&o).unwrap();
        assert!(vorzustand_ist_gebunden(&o, &vorher));
        o.canonical_payload["expectedFieldsDigest"] =
            serde_json::Value::String("f".repeat(64));
        assert!(!vorzustand_ist_gebunden(&o, &vorher));
    }

    #[test]
    fn ein_ausgetauschter_vorzustand_faellt_auf() {
        let o = auftrag("update", serde_json::json!({"jobTitle": "X"}));
        let gefaelscht = serde_json::json!({"contactType": "person",
                                            "givenName": "Jemand anders"});
        assert!(!vorzustand_ist_gebunden(&o, &gefaelscht));
    }

    #[test]
    fn ohne_freigabe_geschieht_nichts() {
        let o = auftrag("delete", serde_json::json!({}));
        let b = fuehre_delete_aus(&o, 0);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.save_request_count, 0);
        assert_eq!(b.error_class.as_deref(),
                   Some("provider_channel_disabled_before_send"));
    }

    #[test]
    fn eine_fremde_operation_wird_abgewiesen() {
        let o = auftrag("create", serde_json::json!({}));
        let b = fuehre_update_aus(&o, 0);
        assert_eq!(b.error_class.as_deref(), Some("schema_mismatch"));
    }
}

// ═══ Der opferbare Schreibhelfer — GUI-Seite (ADR-0026-Nachtrag 2026-08-04) ═

/// Wie lange die GUI auf den Helfer wartet. Grosszügig: ein Save gegen
/// contactsd braucht Sekunden, nicht Minuten — aber ein zäher erster
/// TCC-Kontakt soll nicht künstlich zum Absturzbefund werden.
pub const HELPER_TIMEOUT_SECONDS: u64 = 90;

/// Name des Helfers im App-Bundle (neben dem Hauptbinary in Contents/MacOS).
pub const HELPER_BINARY_NAME: &str = "contacts-write-helper";

/// Der Helfer neben dem eigenen Binary — oder nichts.
///
/// Kein Fallback auf einen In-Prozess-Save: fehlt der Helfer, gibt es
/// **keinen** Schreibweg. Der SIGABRT vom 2026-08-04 hat gezeigt, dass die
/// CoreData-Ausnahme im eigenen Prozess nicht fangbar ist — ein „zur Not
/// eben doch hier" wäre exakt der widerlegte Zustand.
pub fn helper_pfad() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let pfad = exe.parent()?.join(HELPER_BINARY_NAME);
    pfad.is_file().then_some(pfad)
}

/// Verzeichnis der Diagnoseartefakte: `~/.openjarvis/personal/diagnostics`,
/// 0700. Der Shim verlangt genau diese Rechte und verweigert sonst still —
/// deshalb wird hier angelegt **und** nachgezogen.
fn diagnose_verzeichnis() -> Option<std::path::PathBuf> {
    use std::os::unix::fs::PermissionsExt;
    let basis = default_release_path().parent()?.join("diagnostics");
    std::fs::create_dir_all(&basis).ok()?;
    std::fs::set_permissions(&basis, std::fs::Permissions::from_mode(0o700)).ok()?;
    Some(basis)
}

fn juengstes_artefakt_nach(
    verzeichnis: &std::path::Path,
    seit: std::time::SystemTime,
) -> bool {
    let Ok(eintraege) = std::fs::read_dir(verzeichnis) else {
        return false;
    };
    eintraege
        .flatten()
        .filter_map(|e| e.metadata().ok()?.modified().ok())
        .any(|m| m >= seit)
}

/// Führt die Order im Helfer aus — genau ein Start, genau ein Bericht.
///
/// Die Abbildung eines Helfertods folgt dem Marker, nicht dem Exit-Code:
///
/// * Marker **fehlt** → der Shim hat die Übergabe nie begonnen →
///   `not_sent / write_stack_unavailable` (beweisbar nichts gesendet).
/// * Marker **da** → möglicherweise gesendet → `outcome_unknown /
///   app_process_crash`. Nie ein zweiter Start.
pub fn fuehre_im_helfer_aus(
    helper: &std::path::Path,
    order: &ExecutionOrderV1,
    order_json: &str,
    timeout: std::time::Duration,
) -> ExecutionReportV1 {
    use std::io::Write;
    use std::process::{Command, Stdio};

    let start = std::time::SystemTime::now();

    // Markerpfad: einmalig je Versuch, garantiert nicht vorhanden.
    let marker = std::env::temp_dir().join(format!(
        "jc-save-marker-{}-{}", std::process::id(), order.operation_id));
    let _ = std::fs::remove_file(&marker);

    let mut cmd = Command::new(helper);
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .env("OPENJARVIS_CONTACTS_SAVE_MARKER", &marker);
    if let Some(diag) = diagnose_verzeichnis() {
        cmd.env("OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH", &diag);
    }

    let mut kind = match cmd.spawn() {
        Ok(k) => k,
        Err(_) => {
            return ExecutionReportV1::not_sent(order, "write_stack_unavailable");
        }
    };

    // Order hinueber, stdin schliessen — der Helfer liest genau eine.
    if let Some(mut stdin) = kind.stdin.take() {
        let _ = stdin.write_all(order_json.as_bytes());
    }

    // Warten mit Frist. `try_wait`-Polling statt Zusatzabhaengigkeit.
    let frist = std::time::Instant::now() + timeout;
    let status = loop {
        match kind.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if std::time::Instant::now() >= frist => {
                // Haengender Helfer: er ist opferbar, die GUI nicht.
                let _ = kind.kill();
                let _ = kind.wait();
                break None;
            }
            Ok(None) => std::thread::sleep(std::time::Duration::from_millis(50)),
            Err(_) => break None,
        }
    };

    let marker_da = marker.is_file();
    let _ = std::fs::remove_file(&marker);
    let artefakt = diagnose_verzeichnis()
        .map(|d| juengstes_artefakt_nach(&d, start))
        .unwrap_or(false);

    // Nur ein sauber beendeter Helfer mit parsbarem, zugehörigem Bericht
    // zaehlt als Antwort. Alles andere entscheidet der Marker.
    if let Some(status) = status {
        if status.success() {
            if let Some(mut stdout) = kind.stdout.take() {
                let mut roh = String::new();
                use std::io::Read;
                if stdout.read_to_string(&mut roh).is_ok() {
                    if let Ok(bericht) =
                        serde_json::from_str::<ExecutionReportV1>(roh.trim())
                    {
                        if bericht.operation_id == order.operation_id {
                            return bericht;
                        }
                    }
                }
            }
        }
    }

    let mut bericht = if marker_da {
        let mut b = ExecutionReportV1::not_sent(order, "app_process_crash");
        b.outcome = "outcome_unknown".into();
        b.send_attempted = true;
        b.save_request_count = 1;
        b.readback_status = "not_attempted".into();
        b
    } else {
        ExecutionReportV1::not_sent(order, "write_stack_unavailable")
    };
    bericht.diagnostic_artifact_present = artefakt;
    bericht
}

#[cfg(all(test, target_os = "macos"))]
mod helfer_tests {
    use super::*;
    use crate::contacts_execution::payload_digest;
    use std::io::Write as _;
    use std::os::unix::fs::PermissionsExt;

    fn order() -> (ExecutionOrderV1, String) {
        let payload = serde_json::json!({"fields": {"givenName": "Synthetisch"}});
        let roh = serde_json::json!({
            "schema_version": 1,
            "operation_id": "9".repeat(36),
            "mutation_id": "8".repeat(36),
            "claim_token": "a".repeat(64),
            "operation_type": "create",
            "payload_digest": payload_digest(&payload),
            "preview_digest": "c".repeat(64),
            "canonical_payload": payload,
            "readback_requirements": {"required": true},
            "issued_at": "2026-08-04T10:00:00+00:00",
            "expires_at": "2026-08-04T10:10:00+00:00",
            "mutation_contract_version": 1,
            "field_contract_version": 1,
            "transaction_author": "de.kluender.jarvis.contacts-bridge",
            "provider_target": {"container_identifier": "C1"}
        });
        let json = roh.to_string();
        (serde_json::from_value(roh).unwrap(), json)
    }

    fn fake_helper(inhalt: &str) -> std::path::PathBuf {
        use std::hash::{Hash, Hasher};
        let mut h = std::collections::hash_map::DefaultHasher::new();
        inhalt.hash(&mut h);
        let pfad = std::env::temp_dir().join(format!(
            "fake-helper-{}-{:x}", std::process::id(), h.finish()));
        std::fs::write(&pfad, format!("#!/bin/sh\n{inhalt}\n")).unwrap();
        std::fs::set_permissions(&pfad, std::fs::Permissions::from_mode(0o700))
            .unwrap();
        pfad
    }

    #[test]
    fn ein_gueltiger_bericht_wird_durchgereicht() {
        let (o, json) = order();
        let mut bericht = ExecutionReportV1::not_sent(&o, "not_authorized");
        bericht.operation_id = o.operation_id.clone();
        let script = format!(
            "cat >/dev/null\nprintf '%s' '{}'",
            serde_json::to_string(&bericht).unwrap().replace('\'', ""));
        let helper = fake_helper(&script);
        let ergebnis = fuehre_im_helfer_aus(
            &helper, &o, &json, std::time::Duration::from_secs(10));
        std::fs::remove_file(&helper).ok();
        assert_eq!(ergebnis.outcome, "not_sent");
        assert_eq!(ergebnis.error_class.as_deref(), Some("not_authorized"));
    }

    #[test]
    fn absturz_vor_dem_marker_ist_beweisbar_nichts_gesendet() {
        let (o, json) = order();
        let helper = fake_helper("cat >/dev/null\nexit 134");
        let ergebnis = fuehre_im_helfer_aus(
            &helper, &o, &json, std::time::Duration::from_secs(10));
        std::fs::remove_file(&helper).ok();
        assert_eq!(ergebnis.outcome, "not_sent");
        assert!(!ergebnis.send_attempted);
        assert_eq!(ergebnis.save_request_count, 0);
        assert_eq!(ergebnis.error_class.as_deref(),
                   Some("write_stack_unavailable"));
    }

    #[test]
    fn absturz_nach_dem_marker_ist_ungewiss() {
        let (o, json) = order();
        let helper = fake_helper(
            "cat >/dev/null\n: > \"$OPENJARVIS_CONTACTS_SAVE_MARKER\"\nexit 134");
        let ergebnis = fuehre_im_helfer_aus(
            &helper, &o, &json, std::time::Duration::from_secs(10));
        std::fs::remove_file(&helper).ok();
        assert_eq!(ergebnis.outcome, "outcome_unknown");
        assert!(ergebnis.send_attempted);
        assert_eq!(ergebnis.save_request_count, 1);
        assert_eq!(ergebnis.error_class.as_deref(), Some("app_process_crash"));
    }

    #[test]
    fn ein_haengender_helfer_wird_geopfert_nicht_die_gui() {
        let (o, json) = order();
        let helper = fake_helper("cat >/dev/null\nsleep 300");
        let start = std::time::Instant::now();
        let ergebnis = fuehre_im_helfer_aus(
            &helper, &o, &json, std::time::Duration::from_secs(1));
        std::fs::remove_file(&helper).ok();
        assert!(start.elapsed() < std::time::Duration::from_secs(20));
        // Kein Marker: der Fake hat nie eine Uebergabe begonnen.
        assert_eq!(ergebnis.outcome, "not_sent");
        assert_eq!(ergebnis.error_class.as_deref(),
                   Some("write_stack_unavailable"));
    }

    #[test]
    fn ein_fremder_bericht_zaehlt_nicht_als_antwort() {
        let (o, json) = order();
        let mut fremd = ExecutionReportV1::not_sent(&o, "not_authorized");
        fremd.operation_id = "f".repeat(36);
        let script = format!(
            "cat >/dev/null\nprintf '%s' '{}'",
            serde_json::to_string(&fremd).unwrap().replace('\'', ""));
        let helper = fake_helper(&script);
        let ergebnis = fuehre_im_helfer_aus(
            &helper, &o, &json, std::time::Duration::from_secs(10));
        std::fs::remove_file(&helper).ok();
        // Sauberer Exit, aber falscher Bericht: kein Marker -> not_sent.
        assert_eq!(ergebnis.error_class.as_deref(),
                   Some("write_stack_unavailable"));
    }

    #[test]
    fn ohne_helper_binary_gibt_es_keinen_schreibweg() {
        let (o, json) = order();
        let ergebnis = fuehre_im_helfer_aus(
            std::path::Path::new("/nonexistent/helper"), &o, &json,
            std::time::Duration::from_secs(1));
        assert_eq!(ergebnis.outcome, "not_sent");
        assert_eq!(ergebnis.error_class.as_deref(),
                   Some("write_stack_unavailable"));
    }
}
