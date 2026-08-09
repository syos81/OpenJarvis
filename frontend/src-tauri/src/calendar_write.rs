// Kalender-Schreibadapter im App-Prozess (Block B3, Position P1: create).
//
// Der Aufbau folgt dem belegten Kontakte-Schreibpfad (contacts_execution.rs /
// contacts_create.rs): erst die vollständige Auftragsprüfung mit
// **Nachrechnung** des Payload-Digests — sie bindet das, was der Mensch
// freigegeben hat, an das, was ausgeführt wird —, dann genau ein Save über
// einen schmalen Objective-C-Shim (objc/JCCalendarWrite.m), danach der
// Read-back über die gemeldete Kennung aus einem frischen Store.
//
// Eine Order, die die Prüfung nicht besteht, erreicht EventKit nie: die
// Operationen sind injizierbar, und der Testbeleg dafür ist ein Zähler auf
// der Fake-Save-Operation, der bei jeder Abweisung null bleiben muss.
//
// P1 schaltet ausschliesslich `create` frei. Jeder andere Operationstyp
// endet beweisbar vor jeder Übergabe als `not_sent / operation_not_enabled`.

use serde::{Deserialize, Serialize};

use crate::contacts_create::unix_aus_iso8601;
use crate::contacts_execution::{payload_digest, sha256_hex, MAX_ORDER_BYTES};

/// Version des Berichts — muss mit der Python-Seite übereinstimmen.
pub const CALENDAR_REPORT_SCHEMA_VERSION: u32 = 1;

// ── Auftrag (Vertrag zur Python-Seite) ──────────────────────────────────────

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalendarProviderTarget {
    pub provider_calendar_id: String,
    pub event_identifier: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalendarExecutionOrder {
    pub operation_id: String,
    pub mutation_id: String,
    pub claim_token: String,
    pub operation_type: String,
    pub payload_digest: String,
    pub preview_digest: String,
    pub canonical_payload: serde_json::Value,
    pub issued_at: String,
    pub expires_at: String,
    pub provider_target: CalendarProviderTarget,
    pub expected_fingerprint: Option<serde_json::Value>,
}

/// Die sechs Vertragsfelder eines Create-Payloads (`canonical_payload.fields`).
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventFelder {
    pub title: Option<String>,
    pub starts_at_utc: String,
    pub ends_at_utc: String,
    pub is_all_day: bool,
    pub location: Option<String>,
    pub notes: Option<String>,
}

// ── Bericht (Vertrag zur Python-Seite) ──────────────────────────────────────

/// Der zurückgelesene Zustand: die sechs Felder plus der Kalender, in dem
/// das Event tatsächlich liegt — Datumsformat exakt `YYYY-MM-DDTHH:MM:SSZ`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadbackEvent {
    pub title: Option<String>,
    pub starts_at_utc: String,
    pub ends_at_utc: String,
    pub is_all_day: bool,
    pub location: Option<String>,
    pub notes: Option<String>,
    pub provider_calendar_id: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalendarExecutionReportV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub mutation_id: String,
    pub operation_type: String,
    /// "applied" | "not_sent" | "unknown"
    pub outcome: String,
    pub send_attempted: bool,
    pub save_request_count: u32,
    /// "confirmed" | "absent_confirmed" | "unavailable" | "not_checked"
    pub readback_status: String,
    pub readback_event: Option<ReadbackEvent>,
    pub provider_identifier: Option<String>,
    pub fingerprint_checked: bool,
    pub fingerprint_matched: Option<bool>,
    pub error_class: Option<String>,
    pub error_digest: Option<String>,
    pub provider_completed_at: Option<String>,
}

impl CalendarExecutionReportV1 {
    /// Ein Bericht, der **beweisbar** nichts übergeben hat.
    pub fn not_sent(order: &CalendarExecutionOrder, error_class: &str) -> Self {
        Self {
            schema_version: CALENDAR_REPORT_SCHEMA_VERSION,
            operation_id: order.operation_id.clone(),
            mutation_id: order.mutation_id.clone(),
            operation_type: order.operation_type.clone(),
            outcome: "not_sent".into(),
            send_attempted: false,
            save_request_count: 0,
            readback_status: "not_checked".into(),
            readback_event: None,
            provider_identifier: None,
            fingerprint_checked: false,
            fingerprint_matched: None,
            error_class: Some(error_class.into()),
            error_digest: None,
            provider_completed_at: None,
        }
    }

    /// Ein Bericht ohne gültigen Auftrag: leere Kennungen, nicht settlebar —
    /// das ist Absicht (wie `ungebunden` im Kontakte-Kanal).
    fn ungebunden(error_class: &str) -> Self {
        Self {
            schema_version: CALENDAR_REPORT_SCHEMA_VERSION,
            operation_id: String::new(),
            mutation_id: String::new(),
            operation_type: "create".into(),
            outcome: "not_sent".into(),
            send_attempted: false,
            save_request_count: 0,
            readback_status: "not_checked".into(),
            readback_event: None,
            provider_identifier: None,
            fingerprint_checked: false,
            fingerprint_matched: None,
            error_class: Some(error_class.into()),
            error_digest: None,
            provider_completed_at: None,
        }
    }
}

// ── Operationen: injizierbar, damit Tests ohne EventKit und TCC laufen ─────

pub enum KalenderZugang {
    Vorhanden,
    NichtGefunden,
    NichtAutorisiert,
}

/// Ein Speicherfehler mit der einen Aussage, die zählt: ob er **vor** der
/// Übergabe lag (dann ist beweisbar nichts gespeichert) oder danach.
pub struct SpeicherFehler {
    pub vor_save: bool,
    pub beschreibung: String,
}

pub trait KalenderOperationen {
    fn kalender_zugang(&mut self, provider_calendar_id: &str) -> KalenderZugang;
    fn speichere_event(
        &mut self,
        felder: &EventFelder,
        provider_calendar_id: &str,
    ) -> Result<String, SpeicherFehler>;
    fn lese_event(&mut self, event_identifier: &str) -> Option<ReadbackEvent>;
}

// ── Auftragsprüfung: vor jeder Ausführung, vollständig ─────────────────────

fn ist_hex64(wert: &str) -> bool {
    wert.len() == 64 && wert.chars().all(|z| z.is_ascii_hexdigit())
}

/// Das eine Vertragsformat: `YYYY-MM-DDTHH:MM:SSZ`, nichts anderes.
fn ist_vertrags_utc(wert: &str) -> bool {
    wert.len() == 20 && wert.ends_with('Z') && unix_aus_iso8601(wert).is_some()
}

/// Prüft den Auftrag vollständig, **bevor** irgendetwas geschieht.
///
/// Reihenfolge: Pflichtfelder, Digestformat, Operationstyp, Ablauf,
/// Digest-Nachrechnung, Payloadform. Was hier scheitert, erreicht EventKit
/// nie — der Aufrufer bekommt einen fertigen `not_sent`-Bericht.
fn pruefe_order(
    roh: &str,
    jetzt_unix: i64,
) -> Result<(CalendarExecutionOrder, EventFelder), CalendarExecutionReportV1> {
    if roh.len() > MAX_ORDER_BYTES {
        return Err(CalendarExecutionReportV1::ungebunden("order_invalid"));
    }
    let order: CalendarExecutionOrder = match serde_json::from_str(roh) {
        Ok(o) => o,
        Err(_) => return Err(CalendarExecutionReportV1::ungebunden("order_invalid")),
    };
    if order.operation_id.is_empty()
        || order.mutation_id.is_empty()
        || order.claim_token.is_empty()
        || order.issued_at.is_empty()
    {
        return Err(CalendarExecutionReportV1::not_sent(&order, "order_invalid"));
    }
    if !ist_hex64(&order.payload_digest) || !ist_hex64(&order.preview_digest) {
        return Err(CalendarExecutionReportV1::not_sent(&order, "order_invalid"));
    }
    // P1 schaltet genau `create` frei — alles andere ist keine Formfrage,
    // sondern eine nicht erteilte Freigabe.
    if order.operation_type != "create" {
        return Err(CalendarExecutionReportV1::not_sent(
            &order,
            "operation_not_enabled",
        ));
    }
    let Some(ablauf) = unix_aus_iso8601(&order.expires_at) else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "order_invalid"));
    };
    if ablauf <= jetzt_unix {
        return Err(CalendarExecutionReportV1::not_sent(&order, "order_expired"));
    }
    // Der Kern hat den Digest gebildet; hier wird er nachgerechnet. Weicht
    // er ab, wurde der Payload nach der Freigabe angefasst.
    if payload_digest(&order.canonical_payload) != order.payload_digest {
        return Err(CalendarExecutionReportV1::not_sent(
            &order,
            "payload_digest_mismatch",
        ));
    }
    // Payloadform: `command` muss zur freigegebenen Operation passen, die
    // Felder müssen dem Vertrag entsprechen, die Daten dem einen UTC-Format.
    if order.canonical_payload.get("command").and_then(|w| w.as_str()) != Some("create") {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    }
    let Some(felder_roh) = order.canonical_payload.get("fields") else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    };
    let Ok(felder) = serde_json::from_value::<EventFelder>(felder_roh.clone()) else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    };
    if !ist_vertrags_utc(&felder.starts_at_utc) || !ist_vertrags_utc(&felder.ends_at_utc) {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    }
    // Ein Create adressiert nie ein bestehendes Event.
    if order.provider_target.event_identifier.is_some() {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    }
    Ok((order, felder))
}

/// `YYYY-MM-DDTHH:MM:SSZ` aus Unix-Sekunden — Gegenstück zu
/// `unix_aus_iso8601` (Howard Hinnants `civil_from_days`).
fn iso8601_utc_aus_unix(sekunden: i64) -> String {
    let tage = sekunden.div_euclid(86_400);
    let rest = sekunden.rem_euclid(86_400);
    let (h, min, s) = (rest / 3600, (rest % 3600) / 60, rest % 60);
    let z = tage + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let tag = doy - (153 * mp + 2) / 5 + 1;
    let monat = if mp < 10 { mp + 3 } else { mp - 9 };
    let jahr = if monat <= 2 { y + 1 } else { y };
    format!("{jahr:04}-{monat:02}-{tag:02}T{h:02}:{min:02}:{s:02}Z")
}

// ── Der eine Ablauf — echt und im Test derselbe ────────────────────────────

/// Führt einen geprüften Create über die übergebenen Operationen aus.
///
/// Die Trennlinie ist dieselbe wie beim Kontakte-Create und wichtiger als
/// jede Feinheit: Alles **vor** dem Save wird `not_sent` (beweisbar nichts
/// übergeben), alles **nach** einem abgesetzten Save ohne Beleg wird
/// `unknown` mit `readback_status: unavailable` — niemals ein zweiter
/// Versuch.
pub fn execute_order_mit_operationen(
    roh: &str,
    jetzt_unix: i64,
    ops: &mut dyn KalenderOperationen,
) -> CalendarExecutionReportV1 {
    let (order, felder) = match pruefe_order(roh, jetzt_unix) {
        Ok(paar) => paar,
        Err(bericht) => return bericht,
    };
    let kalender_id = order.provider_target.provider_calendar_id.clone();

    match ops.kalender_zugang(&kalender_id) {
        KalenderZugang::Vorhanden => {}
        KalenderZugang::NichtGefunden => {
            return CalendarExecutionReportV1::not_sent(&order, "calendar_not_found");
        }
        KalenderZugang::NichtAutorisiert => {
            return CalendarExecutionReportV1::not_sent(&order, "not_authorized");
        }
    }

    let mut bericht = CalendarExecutionReportV1::not_sent(&order, "provider_save_error");
    match ops.speichere_event(&felder, &kalender_id) {
        Err(fehler) if fehler.vor_save => {
            // Beweisbar nichts übergeben: der Fehler lag vor dem Save.
            bericht.error_digest = Some(sha256_hex(&fehler.beschreibung));
            bericht
        }
        Err(fehler) => {
            // Der Save war übergeben. Ob dabei etwas geschrieben wurde, weiss
            // niemand — also `unknown`, und der Read-back-Kanal ist ohne
            // Kennung nicht verfügbar.
            bericht.outcome = "unknown".into();
            bericht.send_attempted = true;
            bericht.save_request_count = 1;
            bericht.readback_status = "unavailable".into();
            bericht.error_digest = Some(sha256_hex(&fehler.beschreibung));
            bericht
        }
        Ok(kennung) => {
            bericht.send_attempted = true;
            bericht.save_request_count = 1;
            bericht.provider_identifier = Some(kennung.clone());
            bericht.provider_completed_at = Some(iso8601_utc_aus_unix(jetzt_unix));
            match ops.lese_event(&kennung) {
                Some(gelesen) => {
                    bericht.outcome = "applied".into();
                    bericht.readback_status = "confirmed".into();
                    bericht.readback_event = Some(gelesen);
                    bericht.error_class = None;
                }
                None => {
                    // Gespeichert, aber nicht rückgelesen: kein `applied`
                    // ohne Beleg — ein ungewisser Ausgang.
                    bericht.outcome = "unknown".into();
                    bericht.readback_status = "unavailable".into();
                    bericht.error_class = Some("readback_failed".into());
                }
            }
            bericht
        }
    }
}

// ── Echte Operationen: der Objective-C-Shim ────────────────────────────────

#[cfg(target_os = "macos")]
mod nativ {
    use super::*;
    use std::ffi::CString;
    use std::os::raw::c_char;

    const IDENTIFIER_CAPACITY: usize = 512;
    const ERROR_CAPACITY: usize = 512;
    const READBACK_CAPACITY: usize = 8192;

    /// Ergebniscodes des Shims — Spiegel von `JCCalendarSaveOutcome`.
    const SAVE_FAILED_BEFORE_SAVE: i32 = 1;
    const SAVE_SAVED: i32 = 2;

    extern "C" {
        fn jc_calendar_write_authorized() -> i32;
        fn jc_calendar_write_calendar_exists(calendar_identifier: *const c_char) -> i32;
        fn jc_calendar_write_save(
            fields_json: *const c_char,
            calendar_identifier: *const c_char,
            out_identifier: *mut c_char,
            identifier_capacity: i32,
            out_error: *mut c_char,
            error_capacity: i32,
        ) -> i32;
        fn jc_calendar_write_read_event(
            event_identifier: *const c_char,
            out_json: *mut c_char,
            json_capacity: i32,
        ) -> i32;
    }

    fn puffer_zu_string(puffer: &[c_char]) -> String {
        let bytes: Vec<u8> = puffer
            .iter()
            .take_while(|z| **z != 0)
            .map(|z| *z as u8)
            .collect();
        String::from_utf8_lossy(&bytes).into_owned()
    }

    /// Die produktive Anbindung: jede Methode ein schmaler FFI-Aufruf, keine
    /// eigene Entscheidung.
    pub struct EchteKalenderOperationen;

    impl KalenderOperationen for EchteKalenderOperationen {
        fn kalender_zugang(&mut self, provider_calendar_id: &str) -> KalenderZugang {
            if unsafe { jc_calendar_write_authorized() } != 1 {
                return KalenderZugang::NichtAutorisiert;
            }
            let Ok(kennung) = CString::new(provider_calendar_id) else {
                return KalenderZugang::NichtGefunden;
            };
            if unsafe { jc_calendar_write_calendar_exists(kennung.as_ptr()) } == 1 {
                KalenderZugang::Vorhanden
            } else {
                KalenderZugang::NichtGefunden
            }
        }

        fn speichere_event(
            &mut self,
            felder: &EventFelder,
            provider_calendar_id: &str,
        ) -> Result<String, SpeicherFehler> {
            let vor_save = |beschreibung: &str| SpeicherFehler {
                vor_save: true,
                beschreibung: beschreibung.into(),
            };
            let json = serde_json::to_string(felder)
                .map_err(|_| vor_save("fields_unserializable"))?;
            let c_json = CString::new(json).map_err(|_| vor_save("fields_unserializable"))?;
            let c_kalender = CString::new(provider_calendar_id)
                .map_err(|_| vor_save("calendar_identifier_invalid"))?;

            let mut kennung = [0 as c_char; IDENTIFIER_CAPACITY];
            let mut fehler = [0 as c_char; ERROR_CAPACITY];
            let code = unsafe {
                jc_calendar_write_save(
                    c_json.as_ptr(),
                    c_kalender.as_ptr(),
                    kennung.as_mut_ptr(),
                    IDENTIFIER_CAPACITY as i32,
                    fehler.as_mut_ptr(),
                    ERROR_CAPACITY as i32,
                )
            };
            match code {
                SAVE_SAVED => Ok(puffer_zu_string(&kennung)),
                SAVE_FAILED_BEFORE_SAVE => Err(SpeicherFehler {
                    vor_save: true,
                    beschreibung: puffer_zu_string(&fehler),
                }),
                _ => Err(SpeicherFehler {
                    vor_save: false,
                    beschreibung: puffer_zu_string(&fehler),
                }),
            }
        }

        fn lese_event(&mut self, event_identifier: &str) -> Option<ReadbackEvent> {
            let kennung = CString::new(event_identifier).ok()?;
            let mut json = [0 as c_char; READBACK_CAPACITY];
            let gelesen = unsafe {
                jc_calendar_write_read_event(
                    kennung.as_ptr(),
                    json.as_mut_ptr(),
                    READBACK_CAPACITY as i32,
                )
            };
            if gelesen != 1 {
                return None;
            }
            serde_json::from_str(&puffer_zu_string(&json)).ok()
        }
    }
}

/// Führt einen Kalender-Auftrag produktiv aus — den einen Save, oder gar
/// nichts. Nicht-macOS-Ziele haben keinen Schreibweg.
pub fn execute_order(roh: &str) -> CalendarExecutionReportV1 {
    let jetzt = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    #[cfg(target_os = "macos")]
    {
        execute_order_mit_operationen(roh, jetzt, &mut nativ::EchteKalenderOperationen)
    }
    #[cfg(not(target_os = "macos"))]
    {
        match pruefe_order(roh, jetzt) {
            Ok((order, _)) => CalendarExecutionReportV1::not_sent(&order, "provider_unavailable"),
            Err(bericht) => bericht,
        }
    }
}

// ── Tests: derselbe Ablauf, injizierte Operationen ─────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// Fester Zeitpunkt statt Wanduhr: 2026-08-09T00:00:00Z.
    const JETZT: i64 = 1_786_233_600;

    /// Fake-Anbindung mit Zählern: Der Beleg, dass eine abgewiesene Order
    /// EventKit nie erreicht, ist `save_aufrufe == 0` — nicht eine Behauptung.
    struct FakeKalenderOperationen {
        vorhandene_kalender: Vec<String>,
        save_aufrufe: u32,
        lese_aufrufe: u32,
        save_fehler: Option<SpeicherFehler>,
        readback_verfuegbar: bool,
        gespeichert: Option<(EventFelder, String)>,
    }

    impl FakeKalenderOperationen {
        fn mit_kalender(kennung: &str) -> Self {
            Self {
                vorhandene_kalender: vec![kennung.to_string()],
                save_aufrufe: 0,
                lese_aufrufe: 0,
                save_fehler: None,
                readback_verfuegbar: true,
                gespeichert: None,
            }
        }
    }

    impl KalenderOperationen for FakeKalenderOperationen {
        fn kalender_zugang(&mut self, provider_calendar_id: &str) -> KalenderZugang {
            if self
                .vorhandene_kalender
                .iter()
                .any(|k| k == provider_calendar_id)
            {
                KalenderZugang::Vorhanden
            } else {
                KalenderZugang::NichtGefunden
            }
        }

        fn speichere_event(
            &mut self,
            felder: &EventFelder,
            provider_calendar_id: &str,
        ) -> Result<String, SpeicherFehler> {
            self.save_aufrufe += 1;
            if let Some(fehler) = self.save_fehler.take() {
                return Err(fehler);
            }
            self.gespeichert = Some((felder.clone(), provider_calendar_id.to_string()));
            // Deterministische Kennung aus dem Gespeicherten — nie eine
            // erfundene Apple-Kennung.
            let inhalt = serde_json::to_string(felder).unwrap();
            Ok(format!("fake-event-{}", &sha256_hex(&inhalt)[..16]))
        }

        fn lese_event(&mut self, _event_identifier: &str) -> Option<ReadbackEvent> {
            self.lese_aufrufe += 1;
            if !self.readback_verfuegbar {
                return None;
            }
            let (felder, kalender) = self.gespeichert.as_ref()?;
            Some(ReadbackEvent {
                title: felder.title.clone(),
                starts_at_utc: felder.starts_at_utc.clone(),
                ends_at_utc: felder.ends_at_utc.clone(),
                is_all_day: felder.is_all_day,
                location: felder.location.clone(),
                notes: felder.notes.clone(),
                provider_calendar_id: kalender.clone(),
            })
        }
    }

    fn payload() -> serde_json::Value {
        serde_json::json!({
            "command": "create",
            "fields": {
                "title": "Synthetischer B3-Termin",
                "starts_at_utc": "2026-08-10T09:00:00Z",
                "ends_at_utc": "2026-08-10T10:00:00Z",
                "is_all_day": false,
                "location": "Testraum",
                "notes": null
            },
            "provider_target": {
                "provider_calendar_id": "CAL-TEST",
                "event_identifier": null
            },
            "expected_fingerprint": null
        })
    }

    fn auftrag(operation_type: &str, payload: serde_json::Value) -> String {
        serde_json::json!({
            "operation_id": "0".repeat(36),
            "mutation_id": "1".repeat(36),
            "claim_token": "a".repeat(64),
            "operation_type": operation_type,
            "payload_digest": payload_digest(&payload),
            "preview_digest": "b".repeat(64),
            "canonical_payload": payload,
            "issued_at": "2026-08-09T00:00:00Z",
            "expires_at": "2026-08-09T00:10:00Z",
            "provider_target": {
                "provider_calendar_id": "CAL-TEST",
                "event_identifier": null
            },
            "expected_fingerprint": null
        })
        .to_string()
    }

    #[test]
    fn gueltige_order_wird_applied_und_confirmed() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        assert_eq!(b.readback_status, "confirmed");
        assert!(b.send_attempted);
        assert_eq!(b.save_request_count, 1);
        assert_eq!(ops.save_aufrufe, 1);
        assert_eq!(b.error_class, None);
        assert_eq!(b.error_digest, None);
        assert!(b.provider_identifier.as_deref().unwrap().starts_with("fake-event-"));
        assert_eq!(b.provider_completed_at.as_deref(), Some("2026-08-09T00:00:00Z"));
        assert!(!b.fingerprint_checked);
        assert_eq!(b.fingerprint_matched, None);
        let gelesen = b.readback_event.expect("Read-back fehlt");
        assert_eq!(gelesen.title.as_deref(), Some("Synthetischer B3-Termin"));
        assert_eq!(gelesen.starts_at_utc, "2026-08-10T09:00:00Z");
        assert_eq!(gelesen.ends_at_utc, "2026-08-10T10:00:00Z");
        assert!(!gelesen.is_all_day);
        assert_eq!(gelesen.location.as_deref(), Some("Testraum"));
        assert_eq!(gelesen.notes, None);
        assert_eq!(gelesen.provider_calendar_id, "CAL-TEST");
    }

    #[test]
    fn ein_manipulierter_payload_erreicht_den_save_nie() {
        // R9: Der Beleg ist der Zähler, nicht der Bericht allein.
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag("create", payload())).unwrap();
        roh["canonical_payload"]["fields"]["title"] =
            serde_json::json!("Nach der Freigabe angefasst");
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("payload_digest_mismatch"));
        assert!(!b.send_attempted);
        assert_eq!(b.save_request_count, 0);
        assert_eq!(ops.save_aufrufe, 0, "Fake-Save wurde aufgerufen");
        assert_eq!(ops.lese_aufrufe, 0);
    }

    #[test]
    fn update_ist_in_p1_nicht_freigeschaltet() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("update", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("operation_not_enabled"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn eine_abgelaufene_order_wird_nicht_ausgefuehrt() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        // `expires_at` 2026-08-09T00:10:00Z liegt vor diesem Jetzt.
        let jetzt_danach = JETZT + 3600;
        let b = execute_order_mit_operationen(&auftrag("create", payload()), jetzt_danach, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("order_expired"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_unbekannter_kalender_ist_kein_send() {
        let mut ops = FakeKalenderOperationen::mit_kalender("ANDERER-KALENDER");
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("calendar_not_found"));
        assert!(!b.send_attempted);
        assert_eq!(b.save_request_count, 0);
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_fehler_vor_dem_save_ist_beweisbar_nicht_gesendet() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        ops.save_fehler = Some(SpeicherFehler {
            vor_save: true,
            beschreibung: "unparseable_dates".into(),
        });
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert!(!b.send_attempted);
        assert_eq!(b.save_request_count, 0);
        assert_eq!(b.error_class.as_deref(), Some("provider_save_error"));
        assert_eq!(b.error_digest.as_deref(), Some(sha256_hex("unparseable_dates").as_str()));
    }

    #[test]
    fn ein_fehler_im_save_ist_ungewiss_nicht_not_sent() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        ops.save_fehler = Some(SpeicherFehler {
            vor_save: false,
            beschreibung: "EKErrorDomain:11".into(),
        });
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "unknown");
        assert!(b.send_attempted);
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.readback_status, "unavailable");
        assert_eq!(b.error_class.as_deref(), Some("provider_save_error"));
    }

    #[test]
    fn gespeichert_ohne_readback_ist_ungewiss() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        ops.readback_verfuegbar = false;
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "unknown");
        assert_eq!(b.readback_status, "unavailable");
        assert_eq!(b.error_class.as_deref(), Some("readback_failed"));
        assert!(b.provider_identifier.is_some());
        assert_eq!(b.save_request_count, 1);
    }

    #[test]
    fn ein_unlesbarer_auftrag_bleibt_ungebunden() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen("kein json", JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.operation_id, "");
        assert_eq!(b.error_class.as_deref(), Some("order_invalid"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_unbekanntes_feld_wird_abgewiesen() {
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag("create", payload())).unwrap();
        roh["heimlich"] = serde_json::json!("wert");
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("order_invalid"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_abweichendes_datumsformat_ist_kein_vertragspayload() {
        for falsch in [
            "2026-08-10T09:00:00+00:00", // Versatz statt Z
            "2026-08-10 09:00:00Z",      // Leerzeichen statt T
            "2026-08-10T09:00Z",         // ohne Sekunden
        ] {
            let mut p = payload();
            p["fields"]["starts_at_utc"] = serde_json::json!(falsch);
            let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
            let b = execute_order_mit_operationen(&auftrag("create", p), JETZT, &mut ops);
            assert_eq!(b.error_class.as_deref(), Some("invalid_payload"), "{falsch}");
            assert_eq!(ops.save_aufrufe, 0, "{falsch}");
        }
    }

    #[test]
    fn ein_create_mit_eventkennung_wird_abgewiesen() {
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag("create", payload())).unwrap();
        roh["provider_target"]["event_identifier"] = serde_json::json!("FREMDES-EVENT");
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn der_bericht_traegt_die_vertragsfelder() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        let json = serde_json::to_value(&b).unwrap();
        for feld in [
            "schema_version", "operation_id", "mutation_id", "operation_type",
            "outcome", "send_attempted", "save_request_count", "readback_status",
            "readback_event", "provider_identifier", "fingerprint_checked",
            "fingerprint_matched", "error_class", "error_digest",
            "provider_completed_at",
        ] {
            assert!(json.get(feld).is_some(), "{feld} fehlt im Bericht");
        }
        assert_eq!(json["schema_version"], 1);
        assert_eq!(json["readback_event"]["provider_calendar_id"], "CAL-TEST");
        assert_eq!(json["fingerprint_matched"], serde_json::Value::Null);
    }

    #[test]
    fn zeitformatierung_und_leser_sind_umkehrbar() {
        for iso in ["1970-01-01T00:00:00Z", "2026-08-09T00:00:00Z", "2026-12-31T23:59:59Z"] {
            let unix = unix_aus_iso8601(iso).unwrap();
            assert_eq!(iso8601_utc_aus_unix(unix), iso);
        }
        assert_eq!(iso8601_utc_aus_unix(JETZT), "2026-08-09T00:00:00Z");
    }

    #[test]
    fn zwei_gleiche_auftraege_liefern_denselben_bericht() {
        let mut ops_a = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let mut ops_b = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let a = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops_a);
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops_b);
        assert_eq!(a, b);
    }
}
