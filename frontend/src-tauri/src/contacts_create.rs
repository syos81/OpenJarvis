// Nativer Create im App-Prozess (ADR-0020 §8.1, Phase B).
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

/// Der eingefrorene v1-Feldvorrat (ADR-0020 §7), kanonische Schlüssel.
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
pub const WRITE_RELEASE_CONTRACT: &str = "contacts-create-v1";
/// Dateiname — wortgleich zu `write_release.WRITE_RELEASE_FILENAME`.
pub const WRITE_RELEASE_FILENAME: &str = "contacts-write-release.json";
/// Längste zulässige Geltungsdauer, in Stunden.
pub const MAX_RELEASE_HOURS: i64 = 4;

#[derive(Debug, Deserialize)]
struct RohFreigabe {
    contract: String,
    operations: Vec<String>,
    expires_at: String,
    #[serde(default)]
    reason: String,
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
    if freigabe.contract != WRITE_RELEASE_CONTRACT
        || !freigabe.operations.iter().any(|o| o == operation)
        || freigabe.reason.trim().is_empty()
    {
        return false;
    }
    let Some(endet) = unix_aus_iso8601(&freigabe.expires_at) else {
        return false;
    };
    endet > jetzt_unix && endet <= jetzt_unix + MAX_RELEASE_HOURS * 3600
}

/// Minimaler ISO-8601-Leser für `YYYY-MM-DDTHH:MM:SS(±HH:MM|Z)`.
///
/// Bewusst eigenhändig statt per Zeitbibliothek: Es geht um genau ein
/// Format, das der Kern schreibt, und eine zusätzliche Abhängigkeit für
/// vierzig Zeilen wäre die teurere Entscheidung.
fn unix_aus_iso8601(wert: &str) -> Option<i64> {
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
        return ExecutionReportV1::not_sent(order, "unsupported_operation");
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
            r#"{{"contract":"contacts-create-v1","operations":["create"],
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
            r#"{"contract":"contacts-create-v1","operations":["create"],
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
