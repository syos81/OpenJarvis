// Kalender-Schreibadapter im App-Prozess (Block B3, P1: create · P2: update).
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
// P2-Update ist DELTA, kein Full Replace (verbindliche Eigentümerentscheidung):
// VOR der Mutation wird das Event frisch gelesen und der VOLLSTÄNDIGE stabile
// Read-Fingerprint gebildet — exakt dieselbe Feldmenge und Kanonisierung wie
// `preimage_fingerprint_of` auf der Python-Seite (ein Paritätspin hält beide
// Seiten zusammen). Weicht er vom gebundenen `expected_fingerprint` ab, endet
// der Auftrag beweisbar vor jeder Übergabe als `not_sent / revision_conflict`.
// Bei Identität werden AUSSCHLIESSLICH die Delta-Felder gesetzt — nie wird
// ein Event aus dem Jarvis-Modell rekonstruiert.
//
// P3-Delete trägt DREI getrennte, freigabegebundene Nachweise (verbindliche
// Eigentümerentscheidung): den vollständigen stabilen Read-Fingerprint
// (Konfliktbindung), den Digest der Delete-Safety-Probe (Eligibility als
// Allowlist: jede belegte, nicht verlustfrei wiederherstellbare Eigenschaft
// blockiert) und den Digest des Restore-Artefakts. Unmittelbar vor dem
// Remove wird alles drei aus dem FRISCHEN Zustand nachgerechnet; jede
// Abweichung endet beweisbar vor der Löschung — der Testbeleg ist der
// Delete-Zähler der Fake-Operationen, der null bleiben muss.
//
// Jeder fremde Operationstyp endet weiterhin beweisbar vor jeder Übergabe
// als `not_sent / capability_denied`.

use serde::{Deserialize, Serialize};

use crate::contacts_create::unix_aus_iso8601;
use crate::contacts_execution::{payload_digest, sha256_hex, MAX_ORDER_BYTES};

/// Version des Berichts — muss mit der Python-Seite übereinstimmen.
pub const CALENDAR_REPORT_SCHEMA_VERSION: u32 = 1;

/// Produktreife des Kalender-Schreibpfads — **wortgleich** zum Reifebestand
/// des Kerns (`personaljarvis/base/product_readiness.py`, Eintrag `calendar`).
///
/// Solange dies `false` ist, erreicht kein Auftrag EventKit, gleich wie
/// formvollendet er aussieht. Ein Gleichheitstest auf der Python-Seite liest
/// diese Zeile und vergleicht sie mit dem Reifebestand: zwei Orte, aber
/// erzwungen eine Wahrheit.
///
/// Geöffnet wird ausschliesslich in B2 — und dann nicht allein durch das
/// Umstellen dieser Zeile (siehe Kommentar in `execute_order_mit_operationen`).
pub const CALENDAR_PRODUCT_WRITE_READY: bool = false;

/// Die Reife, wie der Ausführungspfad sie liest.
///
/// Im Produktbau ist das die Konstante und sonst nichts — sie lässt sich zur
/// Laufzeit nicht umstellen. Im Testbau ist sie umschaltbar und steht auf
/// „reif", sonst wären die rund dreissig Pipelineprüfungen dieser Datei stumm;
/// dieselbe sichtbare Annahme wie in der Python-Suite. Das Schloss selbst
/// prüft `das_produktschloss_haelt_vor_jedem_providerkontakt`, indem es
/// ausdrücklich auf „nicht reif" stellt.
#[cfg(not(test))]
fn produktreif() -> bool {
    CALENDAR_PRODUCT_WRITE_READY
}

#[cfg(test)]
thread_local! {
    static TEST_PRODUKTREIF: std::cell::Cell<bool> = std::cell::Cell::new(true);
}

#[cfg(test)]
fn produktreif() -> bool {
    TEST_PRODUKTREIF.with(|z| z.get())
}

// ── Auftrag (Vertrag zur Python-Seite) ──────────────────────────────────────

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalendarProviderTarget {
    pub provider_calendar_id: String,
    pub event_identifier: Option<String>,
}

fn schema_version_eins() -> u32 {
    1
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalendarExecutionOrder {
    /// Vertragsversion des Auftrags — die Python-Seite sendet sie immer;
    /// eine fremde Version wird abgewiesen, nie ignoriert.
    #[serde(default = "schema_version_eins")]
    pub schema_version: u32,
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

/// Serde-Kniff für den Zeitzonenanker: der Wert bleibt nullbar, aber der
/// SCHLÜSSEL wird Pflicht — `deserialize_with` schaltet Serdes stilles
/// „fehlendes `Option` = None" ab. Ein fehlendes `time_zone` ist ein
/// Schemafehler, nie ein stilles „schwebend".
fn pflicht_option<'de, D>(d: D) -> Result<Option<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    serde::Deserialize::deserialize(d)
}

/// Die sieben Vertragsfelder eines Create-Payloads (`canonical_payload.fields`).
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventFelder {
    pub title: Option<String>,
    pub starts_at_utc: String,
    pub ends_at_utc: String,
    pub is_all_day: bool,
    pub location: Option<String>,
    pub notes: Option<String>,
    /// IANA-Name oder `null` (bewusst schwebend) — der Schlüssel ist Pflicht.
    #[serde(deserialize_with = "pflicht_option")]
    pub time_zone: Option<String>,
}

// ── Bericht (Vertrag zur Python-Seite) ──────────────────────────────────────

/// Der zurückgelesene Zustand: die sieben Felder plus der Kalender, in dem
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
    /// `event.timeZone.name` des gelesenen Events; `null` = schwebend.
    #[serde(deserialize_with = "pflicht_option")]
    pub time_zone: Option<String>,
    pub provider_calendar_id: String,
}

/// Der VOLLSTÄNDIGE stabile Read-Zustand eines Events, wie ihn der frische
/// EventKit-Leser sieht: die sieben Vertragsfelder plus Event- und
/// Kalenderidentität. Exakt DIESE Feldmenge bindet auch die Python-Seite
/// (`PREIMAGE_FIELD_NAMES` in contracts.py) — eine Funktion je Seite,
/// dieselbe Kanonisierung, ein Paritätspin im Test.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FingerprintFelder {
    pub title: Option<String>,
    pub starts_at_utc: String,
    pub ends_at_utc: String,
    pub is_all_day: bool,
    pub location: Option<String>,
    pub notes: Option<String>,
    /// `null` = schwebend; der Schlüssel ist Pflicht — wie überall im Kanal.
    #[serde(deserialize_with = "pflicht_option")]
    pub time_zone: Option<String>,
    pub provider_calendar_id: String,
    pub event_identifier: String,
}

/// Fingerprint des vollständigen stabilen Read-Zustands — dieselbe
/// kanonische Serialisierung (sortierte Schlüssel, kompakte Trenner) wie
/// `digest_of` im Python-Kern, über `payload_digest` nachgerechnet.
pub fn fingerprint_of(felder: &FingerprintFelder) -> String {
    payload_digest(&serde_json::to_value(felder).expect("Felder sind serialisierbar"))
}

// ── Delete-Safety-Probe (B3 P3) ─────────────────────────────────────────────

/// Vertragsversion der Probe — muss mit `ELIGIBILITY_SCHEMA_VERSION` der
/// Python-Seite übereinstimmen (Paritätspin im Test).
pub const ELIGIBILITY_SCHEMA_VERSION: u32 = 1;

/// Die ROHEN, PII-armen Fakten des Shims über die am nativen Event belegten
/// Eigenschaften ausserhalb des wiederherstellbaren B3-Vertrags. Nur
/// Wahrheitswerte und Zähler — nie ein Inhalt. Abgeleitet aus dem real
/// verwendeten EventKit-Vertrag (EKEvent/EKCalendarItem, macOS-SDK);
/// Attachments haben dort keine öffentliche lesbare Eigenschaft und werden
/// deshalb nicht behauptet (dokumentierte Vertragsgrenze).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RohProbe {
    pub event_identifier: String,
    pub provider_calendar_id: String,
    pub has_recurrence_rules: bool,
    pub recurrence_rule_count: u32,
    pub is_detached: bool,
    pub has_attendees: bool,
    pub attendee_count: u32,
    pub has_organizer: bool,
    pub has_alarms: bool,
    pub alarm_count: u32,
    pub has_url: bool,
    pub has_structured_location_geo: bool,
    pub has_birthday_link: bool,
    pub availability_marked: bool,
    pub has_participation_status: bool,
}

/// Übersetzt die rohen Fakten in die KANONISCHE Probe — exakt das Objekt,
/// das die Python-Seite (`validate_eligibility_probe`) bindet: sortierte,
/// eindeutige Flags aus der geschlossenen Menge, immer alle drei Zähler,
/// `eligible` IST die Abwesenheit jedes Flags.
pub fn kanonische_probe(roh: &RohProbe) -> serde_json::Value {
    let mut flags: Vec<&str> = Vec::new();
    // Alphabetische Reihenfolge = sortierte Liste, wortgleich mit
    // `ELIGIBILITY_FLAG_NAMES` in contracts.py.
    if roh.has_alarms || roh.alarm_count > 0 {
        flags.push("alarms");
    }
    if roh.has_attendees || roh.attendee_count > 0 {
        flags.push("attendees");
    }
    if roh.availability_marked {
        flags.push("availability_marked");
    }
    if roh.has_birthday_link {
        flags.push("birthday_link");
    }
    if roh.is_detached {
        flags.push("detached_occurrence");
    }
    if roh.has_organizer {
        flags.push("organizer");
    }
    if roh.has_participation_status {
        flags.push("participation_status");
    }
    if roh.has_recurrence_rules || roh.recurrence_rule_count > 0 {
        flags.push("recurrence_rules");
    }
    if roh.has_structured_location_geo {
        flags.push("structured_location_geo");
    }
    if roh.has_url {
        flags.push("url");
    }
    serde_json::json!({
        "schema_version": ELIGIBILITY_SCHEMA_VERSION,
        "event_identifier": roh.event_identifier,
        "provider_calendar_id": roh.provider_calendar_id,
        "eligible": flags.is_empty(),
        "unsupported_feature_flags": flags,
        "counts": {
            "alarms": roh.alarm_count,
            "attendees": roh.attendee_count,
            "recurrence_rules": roh.recurrence_rule_count,
        },
    })
}

/// Digest der kanonischen Probe — dieselbe Kanonisierung wie der
/// Payload-Digest; die Python-Seite rechnet über `eligibility_digest_of`
/// DENSELBEN Wert (Paritätspin im Test).
pub fn eligibility_digest_of(probe: &serde_json::Value) -> String {
    payload_digest(probe)
}

/// Das Restore-Artefakt aus dem frisch gelesenen Zustand: die sieben
/// Vertragsfelder plus Zielkalender — exakt die Form, die die Python-Seite
/// (`restore_preimage_of`) beim Vorbereiten gebunden hat. Der Digest-
/// Vergleich unmittelbar vor dem Remove ist die erneute
/// Wiederherstellbarkeitsprüfung der Eigentümerentscheidung.
pub fn restore_preimage_of(felder: &FingerprintFelder) -> serde_json::Value {
    serde_json::json!({
        "fields": {
            "title": felder.title,
            "starts_at_utc": felder.starts_at_utc,
            "ends_at_utc": felder.ends_at_utc,
            "is_all_day": felder.is_all_day,
            "location": felder.location,
            "notes": felder.notes,
            "time_zone": felder.time_zone,
        },
        "provider_calendar_id": felder.provider_calendar_id,
    })
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
    /// Liest den VOLLSTÄNDIGEN stabilen Fingerprint-Zustand eines Events
    /// frisch (eigener Store) — der Vorher-Beleg eines Updates.
    fn lese_fingerprint_felder(&mut self, event_identifier: &str)
        -> Option<FingerprintFelder>;
    /// Setzt AUSSCHLIESSLICH die im Delta enthaltenen Felder auf dem
    /// bestehenden Event und speichert genau einmal (span thisEvent).
    /// KEIN Rekonstruieren aus dem Jarvis-Modell.
    fn aktualisiere_event(
        &mut self,
        event_identifier: &str,
        changes: &serde_json::Map<String, serde_json::Value>,
    ) -> Result<String, SpeicherFehler>;
    /// Erhebt die READ-ONLY Delete-Safety-Probe am nativen Event —
    /// rohe, PII-arme Fakten, nie eine Mutation.
    fn delete_probe(&mut self, event_identifier: &str) -> Option<RohProbe>;
    /// Löscht GENAU EIN Event (span thisEvent, sofortiger Commit).
    /// Kein Fallback, kein zweiter Versuch.
    fn loesche_event(&mut self, event_identifier: &str)
        -> Result<(), SpeicherFehler>;
}

// ── Auftragsprüfung: vor jeder Ausführung, vollständig ─────────────────────

fn ist_hex64(wert: &str) -> bool {
    wert.len() == 64 && wert.chars().all(|z| z.is_ascii_hexdigit())
}

/// Das eine Vertragsformat: `YYYY-MM-DDTHH:MM:SSZ`, nichts anderes.
fn ist_vertrags_utc(wert: &str) -> bool {
    wert.len() == 20 && wert.ends_with('Z') && unix_aus_iso8601(wert).is_some()
}

/// Die sieben Vertragsfeldnamen — die einzigen, die ein Update-Delta
/// tragen darf.
const DELTA_FELD_NAMEN: [&str; 7] = [
    "title", "starts_at_utc", "ends_at_utc", "is_all_day", "location",
    "notes", "time_zone",
];

/// Der geprüfte Inhalt eines Auftrags: Create trägt den vollen Feldsatz,
/// Update das Delta samt Ziel und gebundenem Vorzustands-Fingerprint,
/// Delete die drei getrennten Nachweise der Freigabe (P3).
enum Auftragsinhalt {
    Create(EventFelder),
    Update {
        changes: serde_json::Map<String, serde_json::Value>,
        event_identifier: String,
        expected_fingerprint: String,
    },
    Delete {
        event_identifier: String,
        expected_fingerprint: String,
        eligibility_digest: String,
        restore_preimage_digest: String,
    },
}

/// Prüft ein Update-Delta fail-closed: nicht leer, nur Vertragsfelder,
/// typrichtige Werte. `null` ist bei `title`/`location`/`notes`/`time_zone`
/// ein fachlicher Wert (löschen bzw. schwebend) — Nicht-ändern heisst
/// weglassen. Sind BEIDE Zeitpunkte im Delta, muss das Ende nach dem
/// Beginn liegen; ein halbes Zeitpaar prüft erst der Ablauf gegen den
/// frisch gelesenen Zustand.
fn pruefe_changes(
    wert: &serde_json::Value,
) -> Option<serde_json::Map<String, serde_json::Value>> {
    let map = wert.as_object()?;
    if map.is_empty() {
        return None;
    }
    for (schluessel, w) in map {
        if !DELTA_FELD_NAMEN.contains(&schluessel.as_str()) {
            return None;
        }
        match schluessel.as_str() {
            "starts_at_utc" | "ends_at_utc" => {
                if !w.as_str().map_or(false, ist_vertrags_utc) {
                    return None;
                }
            }
            "is_all_day" => {
                if !w.is_boolean() {
                    return None;
                }
            }
            _ => {
                if !(w.is_null() || w.is_string()) {
                    return None;
                }
            }
        }
    }
    if let (Some(starts), Some(ends)) = (
        map.get("starts_at_utc").and_then(|w| w.as_str()),
        map.get("ends_at_utc").and_then(|w| w.as_str()),
    ) {
        if ends <= starts {
            return None;
        }
    }
    Some(map.clone())
}

/// Prüft den Auftrag vollständig, **bevor** irgendetwas geschieht.
///
/// Reihenfolge: Pflichtfelder, Digestformat, Operationstyp, Ablauf,
/// Digest-Nachrechnung, Payloadform. Was hier scheitert, erreicht EventKit
/// nie — der Aufrufer bekommt einen fertigen `not_sent`-Bericht.
fn pruefe_order(
    roh: &str,
    jetzt_unix: i64,
) -> Result<(CalendarExecutionOrder, Auftragsinhalt), CalendarExecutionReportV1> {
    if roh.len() > MAX_ORDER_BYTES {
        return Err(CalendarExecutionReportV1::ungebunden("schema_mismatch"));
    }
    let order: CalendarExecutionOrder = match serde_json::from_str(roh) {
        Ok(o) => o,
        Err(_) => return Err(CalendarExecutionReportV1::ungebunden("schema_mismatch")),
    };
    if order.operation_id.is_empty()
        || order.mutation_id.is_empty()
        || order.claim_token.is_empty()
        || order.issued_at.is_empty()
    {
        return Err(CalendarExecutionReportV1::not_sent(&order, "schema_mismatch"));
    }
    if !ist_hex64(&order.payload_digest) || !ist_hex64(&order.preview_digest) {
        return Err(CalendarExecutionReportV1::not_sent(&order, "schema_mismatch"));
    }
    // P3 schaltet `create`, `update` und `delete` frei — alles Fremde ist
    // keine Formfrage, sondern eine nicht erteilte Freigabe.
    if order.schema_version != 1 {
        return Err(CalendarExecutionReportV1::not_sent(&order, "schema_mismatch"));
    }
    if order.operation_type != "create"
        && order.operation_type != "update"
        && order.operation_type != "delete"
    {
        return Err(CalendarExecutionReportV1::not_sent(
            &order,
            "capability_denied",
        ));
    }
    let Some(ablauf) = unix_aus_iso8601(&order.expires_at) else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "schema_mismatch"));
    };
    if ablauf <= jetzt_unix {
        return Err(CalendarExecutionReportV1::not_sent(&order, "expired_claim_before_send"));
    }
    // Der Kern hat den Digest gebildet; hier wird er nachgerechnet. Weicht
    // er ab, wurde der Payload nach der Freigabe angefasst.
    if payload_digest(&order.canonical_payload) != order.payload_digest {
        return Err(CalendarExecutionReportV1::not_sent(
            &order,
            "digest_mismatch",
        ));
    }
    // Payloadform: `command` muss zur freigegebenen Operation passen.
    if order.canonical_payload.get("command").and_then(|w| w.as_str())
        != Some(order.operation_type.as_str())
    {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    }

    if order.operation_type == "create" {
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
        return Ok((order, Auftragsinhalt::Create(felder)));
    }

    // Update/Delete: Ziel und Vorzustands-Fingerprint aus dem
    // DIGEST-GEDECKTEN Payload lesen — die Order-Felder müssen dazu passen.
    let ziel = order.canonical_payload.get("provider_target");
    let Some(event_identifier) = ziel
        .and_then(|z| z.get("event_identifier"))
        .and_then(|w| w.as_str())
        .filter(|k| !k.is_empty())
        .map(str::to_string)
    else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    };
    let payload_kalender = ziel
        .and_then(|z| z.get("provider_calendar_id"))
        .and_then(|w| w.as_str())
        .unwrap_or_default();
    if payload_kalender.is_empty()
        || payload_kalender != order.provider_target.provider_calendar_id
        || order.provider_target.event_identifier.as_deref() != Some(event_identifier.as_str())
    {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    }
    let Some(expected_fingerprint) = order
        .canonical_payload
        .get("expected_fingerprint")
        .and_then(|w| w.as_str())
        .filter(|f| ist_hex64(f))
        .map(str::to_string)
    else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    };

    if order.operation_type == "delete" {
        // Delete: kein Feldsatz, kein Delta — dafür die BEIDEN weiteren
        // freigabegebundenen Nachweise. Ein Delete-Payload, der trotzdem
        // `fields` oder `changes` trägt, ist kein Vertragspayload.
        if order.canonical_payload.get("fields").is_some()
            || order.canonical_payload.get("changes").is_some()
        {
            return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
        }
        let digest_feld = |name: &str| {
            order
                .canonical_payload
                .get(name)
                .and_then(|w| w.as_str())
                .filter(|f| ist_hex64(f))
                .map(str::to_string)
        };
        let Some(eligibility_digest) = digest_feld("eligibility_digest") else {
            return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
        };
        let Some(restore_preimage_digest) = digest_feld("restore_preimage_digest")
        else {
            return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
        };
        return Ok((
            order,
            Auftragsinhalt::Delete {
                event_identifier,
                expected_fingerprint,
                eligibility_digest,
                restore_preimage_digest,
            },
        ));
    }

    let Some(changes) = order
        .canonical_payload
        .get("changes")
        .and_then(pruefe_changes)
    else {
        return Err(CalendarExecutionReportV1::not_sent(&order, "invalid_payload"));
    };
    Ok((
        order,
        Auftragsinhalt::Update {
            changes,
            event_identifier,
            expected_fingerprint,
        },
    ))
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
    let (order, inhalt) = match pruefe_order(roh, jetzt_unix) {
        Ok(paar) => paar,
        Err(bericht) => return bericht,
    };

    // ── Das native Produktschloss ───────────────────────────────────────────
    //
    // Hier, und nicht nur im Kern. Der Kern prueft die Produktreife im Claim,
    // aber dieser Ausfuehrungspfad nimmt einen Auftrag als JSON entgegen und
    // prueft ihn sonst nur auf **Form**: nicht-leere Kennungen, Hex-Digests,
    // bekannter Operationstyp. Ein frei zusammengesetzter, formal gueltiger
    // Auftrag kaeme damit bis zum Save; dass der Kern hinterher den
    // Settle-Bericht ablehnt, waere zu spaet — nach einem Providerschreiben
    // ist die Sicherheitsentscheidung gefallen.
    //
    // Deshalb steht die Ablehnung **vor** jedem `ops`-Aufruf. Nicht nur vor
    // dem Save: auch die Autorisierungs- und Kalenderabfrage unterbleibt. Wer
    // nicht schreiben darf, fasst den Provider gar nicht erst an.
    //
    // Die Konstante ist wortgleich zum Reifebestand des Kerns
    // (`personaljarvis/base/product_readiness.py`); ein Gleichheitstest haelt
    // beide Seiten zusammen, damit aus zwei Orten nicht zwei Wahrheiten
    // werden. Eine Uebersetzungszeitkonstante ist hier die staerkere Form:
    // sie laesst sich zur Laufzeit gar nicht umstellen.
    //
    // Was das NICHT ist: die vollstaendige Claim-Verifikation. Mit B2 reicht
    // es nicht, diese Konstante auf `true` zu drehen — dann muss der native
    // Pfad zusaetzlich einen autoritativen, an genau diese Mutation
    // gebundenen Claim VOR dem Save pruefen. Frei erfindbare Hex-Digests und
    // ein frei erfindbarer `claim_token` duerfen EventKit nie erreichen.
    //
    // Die Fehlerklasse ist `provider_channel_disabled_before_send` und keine
    // neu erfundene: Das Vokabular ist geschlossen und steht als
    // CHECK-Bedingung in Migration 0008. Genau das sagt der Fall auch aus —
    // der Kanal ist abgeschaltet, und zwar vor jedem Senden.
    if !produktreif() {
        return CalendarExecutionReportV1::not_sent(
            &order,
            "provider_channel_disabled_before_send",
        );
    }

    let kalender_id = order.provider_target.provider_calendar_id.clone();

    match ops.kalender_zugang(&kalender_id) {
        KalenderZugang::Vorhanden => {}
        KalenderZugang::NichtGefunden => {
            return CalendarExecutionReportV1::not_sent(&order, "target_not_found");
        }
        KalenderZugang::NichtAutorisiert => {
            return CalendarExecutionReportV1::not_sent(&order, "not_authorized");
        }
    }

    // Delete hat einen EIGENEN Ablauf: drei Nachweise vor der Übergabe,
    // Read-back auf ABWESENHEIT statt Anwesenheit.
    if let Auftragsinhalt::Delete {
        event_identifier,
        expected_fingerprint,
        eligibility_digest,
        restore_preimage_digest,
    } = inhalt
    {
        return fuehre_delete_aus(
            &order,
            ops,
            jetzt_unix,
            &event_identifier,
            &expected_fingerprint,
            &eligibility_digest,
            &restore_preimage_digest,
        );
    }

    let mut bericht = CalendarExecutionReportV1::not_sent(&order, "provider_save_error");

    let speicher_ergebnis = match inhalt {
        Auftragsinhalt::Create(felder) => ops.speichere_event(&felder, &kalender_id),
        Auftragsinhalt::Delete { .. } => unreachable!("oben behandelt"),
        Auftragsinhalt::Update {
            changes,
            event_identifier,
            expected_fingerprint,
        } => {
            // VOR der Mutation: das Event frisch lesen und den VOLLSTÄNDIGEN
            // stabilen Read-Fingerprint bilden. Ohne lesbaren Vorzustand
            // gibt es keinen Vergleich und damit keinen Save.
            let Some(vorher) = ops.lese_fingerprint_felder(&event_identifier) else {
                return CalendarExecutionReportV1::not_sent(&order, "target_not_found");
            };
            bericht.fingerprint_checked = true;
            if fingerprint_of(&vorher) != expected_fingerprint {
                // Der Termin ist nicht mehr der, den der Mensch freigegeben
                // hat — beweisbar nichts übergeben, Save-Zähler bleibt null.
                bericht.fingerprint_matched = Some(false);
                bericht.error_class = Some("revision_conflict".into());
                return bericht;
            }
            bericht.fingerprint_matched = Some(true);
            // Halbes Zeitpaar im Delta: erst der ZUSAMMENGEFÜHRTE Zustand
            // aus frischem Vorzustand und Delta ist prüfbar.
            let starts = changes
                .get("starts_at_utc")
                .and_then(|w| w.as_str())
                .unwrap_or(&vorher.starts_at_utc);
            let ends = changes
                .get("ends_at_utc")
                .and_then(|w| w.as_str())
                .unwrap_or(&vorher.ends_at_utc);
            if ends <= starts {
                bericht.error_class = Some("invalid_payload".into());
                return bericht;
            }
            ops.aktualisiere_event(&event_identifier, &changes)
        }
    };

    match speicher_ergebnis {
        Err(fehler) if fehler.vor_save => {
            // Beweisbar nichts übergeben: der Fehler lag vor dem Save.
            // Ein vom Shim abgewiesener Zeitzonenname ist ein Payload-
            // Defekt, kein Providerfehler — nur EventKit kennt die Zonen-
            // datenbank, deshalb fällt er erst hier und trägt die Klasse.
            if fehler.beschreibung == "unknown_time_zone" {
                bericht.error_class = Some("invalid_payload".into());
            }
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

/// Der Delete-Ablauf (B3 P3): unmittelbar vor dem Remove wird der gesamte
/// gebundene Zustand aus dem FRISCHEN Event nachgerechnet — Fingerprint,
/// Eligibility-Digest, Restore-Digest. Jede Abweichung endet beweisbar vor
/// der Löschung (`not_sent`, Delete-Zähler bleibt null). Nach dem Remove
/// zählt nur die BESTÄTIGTE Abwesenheit als Erfolg: ein weiterhin lesbares
/// Event macht den Ausgang ungewiss, nie „applied".
#[allow(clippy::too_many_arguments)]
fn fuehre_delete_aus(
    order: &CalendarExecutionOrder,
    ops: &mut dyn KalenderOperationen,
    jetzt_unix: i64,
    event_identifier: &str,
    expected_fingerprint: &str,
    eligibility_digest: &str,
    restore_preimage_digest: &str,
) -> CalendarExecutionReportV1 {
    let mut bericht = CalendarExecutionReportV1::not_sent(order, "provider_save_error");
    bericht.operation_type = "delete".into();

    // 1. Konfliktbindung: den vollständigen stabilen Read-Zustand frisch
    //    lesen und gegen den freigegebenen Fingerprint halten.
    let Some(vorher) = ops.lese_fingerprint_felder(event_identifier) else {
        return CalendarExecutionReportV1::not_sent(order, "target_not_found");
    };
    bericht.fingerprint_checked = true;
    if fingerprint_of(&vorher) != expected_fingerprint {
        bericht.fingerprint_matched = Some(false);
        bericht.error_class = Some("revision_conflict".into());
        return bericht;
    }
    bericht.fingerprint_matched = Some(true);

    // 2. Eligibility: die Probe ERNEUT am nativen Event erheben. Eine
    //    belegte unsupported Eigenschaft blockiert (Allowlist-Grundregel);
    //    ein abweichender Digest heisst: der Zustand ist nicht mehr der
    //    freigegebene.
    let Some(roh) = ops.delete_probe(event_identifier) else {
        return CalendarExecutionReportV1::not_sent(order, "target_not_found");
    };
    if roh.event_identifier != event_identifier
        || roh.provider_calendar_id != vorher.provider_calendar_id
    {
        bericht.error_class = Some("revision_conflict".into());
        return bericht;
    }
    let probe = kanonische_probe(&roh);
    if probe.get("eligible").and_then(|w| w.as_bool()) != Some(true) {
        bericht.error_class = Some("unsupported_field".into());
        return bericht;
    }
    if eligibility_digest_of(&probe) != eligibility_digest {
        bericht.error_class = Some("revision_conflict".into());
        return bericht;
    }

    // 3. Wiederherstellbarkeit erneut: das Restore-Artefakt aus dem
    //    frischen Zustand nachrechnen — es muss exakt das gebundene sein
    //    und ein gültiger Create-Kandidat bleiben.
    if vorher.ends_at_utc <= vorher.starts_at_utc {
        bericht.error_class = Some("invalid_payload".into());
        return bericht;
    }
    if payload_digest(&restore_preimage_of(&vorher)) != restore_preimage_digest {
        bericht.error_class = Some("revision_conflict".into());
        return bericht;
    }

    // 4. Genau EIN Remove — oder gar nichts.
    match ops.loesche_event(event_identifier) {
        Err(fehler) if fehler.vor_save => {
            bericht.error_digest = Some(sha256_hex(&fehler.beschreibung));
            bericht
        }
        Err(fehler) => {
            bericht.outcome = "unknown".into();
            bericht.send_attempted = true;
            bericht.save_request_count = 1;
            bericht.readback_status = "unavailable".into();
            bericht.error_digest = Some(sha256_hex(&fehler.beschreibung));
            bericht
        }
        Ok(()) => {
            bericht.send_attempted = true;
            bericht.save_request_count = 1;
            bericht.provider_identifier = Some(event_identifier.to_string());
            bericht.provider_completed_at = Some(iso8601_utc_aus_unix(jetzt_unix));
            match ops.lese_event(event_identifier) {
                None => {
                    // Die gezielte Nachlese bestätigt die Abwesenheit —
                    // erst DAS ist der Erfolgsbeleg eines Deletes.
                    bericht.outcome = "applied".into();
                    bericht.readback_status = "absent_confirmed".into();
                    bericht.error_class = None;
                }
                Some(_) => {
                    // Entfernt gemeldet, aber weiterhin lesbar: ehrlich
                    // ungewiss — der Read-back hat die Anwesenheit gesehen.
                    bericht.outcome = "unknown".into();
                    bericht.readback_status = "confirmed".into();
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
        fn jc_calendar_write_update(
            changes_json: *const c_char,
            event_identifier: *const c_char,
            out_identifier: *mut c_char,
            identifier_capacity: i32,
            out_error: *mut c_char,
            error_capacity: i32,
        ) -> i32;
        fn jc_calendar_write_read_fingerprint_fields(
            event_identifier: *const c_char,
            out_json: *mut c_char,
            json_capacity: i32,
        ) -> i32;
        fn jc_calendar_write_delete_probe(
            event_identifier: *const c_char,
            out_json: *mut c_char,
            json_capacity: i32,
        ) -> i32;
        fn jc_calendar_write_delete(
            event_identifier: *const c_char,
            out_error: *mut c_char,
            error_capacity: i32,
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

        fn lese_fingerprint_felder(
            &mut self,
            event_identifier: &str,
        ) -> Option<FingerprintFelder> {
            let kennung = CString::new(event_identifier).ok()?;
            let mut json = [0 as c_char; READBACK_CAPACITY];
            let gelesen = unsafe {
                jc_calendar_write_read_fingerprint_fields(
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

        fn aktualisiere_event(
            &mut self,
            event_identifier: &str,
            changes: &serde_json::Map<String, serde_json::Value>,
        ) -> Result<String, SpeicherFehler> {
            let vor_save = |beschreibung: &str| SpeicherFehler {
                vor_save: true,
                beschreibung: beschreibung.into(),
            };
            let json = serde_json::to_string(changes)
                .map_err(|_| vor_save("changes_unserializable"))?;
            let c_json =
                CString::new(json).map_err(|_| vor_save("changes_unserializable"))?;
            let c_kennung = CString::new(event_identifier)
                .map_err(|_| vor_save("event_identifier_invalid"))?;

            let mut kennung = [0 as c_char; IDENTIFIER_CAPACITY];
            let mut fehler = [0 as c_char; ERROR_CAPACITY];
            let code = unsafe {
                jc_calendar_write_update(
                    c_json.as_ptr(),
                    c_kennung.as_ptr(),
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

        fn delete_probe(&mut self, event_identifier: &str) -> Option<RohProbe> {
            let kennung = CString::new(event_identifier).ok()?;
            let mut json = [0 as c_char; READBACK_CAPACITY];
            let gelesen = unsafe {
                jc_calendar_write_delete_probe(
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

        fn loesche_event(&mut self, event_identifier: &str)
            -> Result<(), SpeicherFehler>
        {
            let vor_save = |beschreibung: &str| SpeicherFehler {
                vor_save: true,
                beschreibung: beschreibung.into(),
            };
            let c_kennung = CString::new(event_identifier)
                .map_err(|_| vor_save("event_identifier_invalid"))?;
            let mut fehler = [0 as c_char; ERROR_CAPACITY];
            let code = unsafe {
                jc_calendar_write_delete(
                    c_kennung.as_ptr(),
                    fehler.as_mut_ptr(),
                    ERROR_CAPACITY as i32,
                )
            };
            match code {
                SAVE_SAVED => Ok(()),
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
    }

    /// Erhebt die Delete-Safety-Probe am nativen Event und liefert die
    /// KANONISCHE Form — oder die TYPISIERTE Fehlstufe (P3-Livebefund vom
    /// 2026-08-09: drei verschiedene Fehlstufen als ein und dasselbe `null`
    /// zu melden ist ein Diagnosemangel derselben Klasse wie der
    /// 422-ohne-Grund-Befund). Read-only in jeder Stufe; die Bewertung
    /// bleibt unangetastet.
    pub fn delete_probe_diagnose(event_identifier: &str) -> serde_json::Value {
        if unsafe { jc_calendar_write_authorized() } != 1 {
            return serde_json::json!({ "stage": "not_authorized" });
        }
        let kennung = match CString::new(event_identifier) {
            Ok(k) => k,
            Err(_) => {
                return serde_json::json!({ "stage": "event_unreadable" });
            }
        };
        let mut json = [0 as c_char; READBACK_CAPACITY];
        let gelesen = unsafe {
            jc_calendar_write_delete_probe(
                kennung.as_ptr(),
                json.as_mut_ptr(),
                READBACK_CAPACITY as i32,
            )
        };
        if gelesen != 1 {
            // Der Shim hat das Event unter dieser Kennung nicht aufgelöst
            // (oder die Serialisierung scheiterte shimseitig).
            return serde_json::json!({ "stage": "event_unreadable" });
        }
        let text = puffer_zu_string(&json);
        match serde_json::from_str::<RohProbe>(&text) {
            Ok(roh) => serde_json::json!({
                "stage": "ok",
                "probe": kanonische_probe(&roh),
            }),
            // Die ROHE Emission reist mit (P3-Livebefund, R6: beobachten
            // statt ableiten). Sie ist PII-arm PER KONSTRUKTION: der Shim
            // emittiert ausschliesslich Flags, Zähler und die beiden
            // Kennungen — nie einen Inhalt. Ohne diesen Beleg wäre der
            // nächste Emissionsdrift wieder nur eine Vermutung.
            Err(_) => serde_json::json!({
                "stage": "probe_unparseable",
                "raw_len": text.len(),
                "raw": text,
            }),
        }
    }
}

/// Die READ-ONLY Delete-Safety-Probe für das Tauri-Kommando: entweder
/// `{"stage":"ok","probe":…}` mit der kanonischen Probe oder die typisierte
/// Fehlstufe (`not_authorized` | `event_unreadable` | `probe_unparseable`).
/// Nicht-macOS-Ziele haben keinen Kalenderzugriff — ehrlich benannt, kein
/// Ersatzweg.
pub fn delete_probe(event_identifier: &str) -> serde_json::Value {
    #[cfg(target_os = "macos")]
    {
        nativ::delete_probe_diagnose(event_identifier)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = event_identifier;
        serde_json::json!({ "stage": "platform_unavailable" })
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
            Ok((order, _)) => CalendarExecutionReportV1::not_sent(&order, "write_stack_unavailable"),
            Err(bericht) => bericht,
        }
    }
}

// ── Tests: derselbe Ablauf, injizierte Operationen ─────────────────────────

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    /// Fester Zeitpunkt statt Wanduhr: 2026-08-09T00:00:00Z.
    const JETZT: i64 = 1_786_233_600;

    /// Ein bestehendes Event im Fake-Store. `extra_eigenschaft` modelliert
    /// eine native Eigenschaft AUSSERHALB der sieben Vertragsfelder (etwa
    /// eine URL oder einen Alarm): sie muss ein Delta-Update unangetastet
    /// überleben — der Beleg, dass nichts rekonstruiert wird.
    #[derive(Clone)]
    pub(crate) struct FakeEvent {
        pub(crate) felder: FingerprintFelder,
        pub(crate) extra_eigenschaft: Option<String>,
    }

    /// Fake-Anbindung mit Zählern: Der Beleg, dass eine abgewiesene Order
    /// EventKit nie erreicht, ist `save_aufrufe == 0` (bzw. für P3
    /// `delete_aufrufe == 0`) — nicht eine Behauptung.
    pub(crate) struct FakeKalenderOperationen {
        vorhandene_kalender: Vec<String>,
        pub(crate) save_aufrufe: u32,
        pub(crate) delete_aufrufe: u32,
        lese_aufrufe: u32,
        save_fehler: Option<SpeicherFehler>,
        delete_fehler: Option<SpeicherFehler>,
        /// Simuliert einen Remove, der Erfolg meldet, ohne zu wirken: der
        /// Bestand bleibt lesbar — der Read-back muss das ehrlich zeigen.
        delete_wirkt_nicht: bool,
        readback_verfuegbar: bool,
        gespeichert: Option<(EventFelder, String)>,
        pub(crate) bestehend: Option<FakeEvent>,
        /// Die Probe, die der Fake am Event „erhebt" (P3).
        pub(crate) probe: Option<RohProbe>,
    }

    impl FakeKalenderOperationen {
        pub(crate) fn mit_kalender(kennung: &str) -> Self {
            Self {
                vorhandene_kalender: vec![kennung.to_string()],
                save_aufrufe: 0,
                delete_aufrufe: 0,
                lese_aufrufe: 0,
                save_fehler: None,
                delete_fehler: None,
                delete_wirkt_nicht: false,
                readback_verfuegbar: true,
                gespeichert: None,
                bestehend: None,
                probe: None,
            }
        }

        pub(crate) fn mit_bestehendem_event(
            kalender: &str,
            felder: FingerprintFelder,
        ) -> Self {
            let mut ops = Self::mit_kalender(kalender);
            ops.bestehend = Some(FakeEvent {
                felder,
                extra_eigenschaft: Some("nativer-alarm".into()),
            });
            ops
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

        fn lese_event(&mut self, event_identifier: &str) -> Option<ReadbackEvent> {
            self.lese_aufrufe += 1;
            if !self.readback_verfuegbar {
                return None;
            }
            // Erst der bestehende Bestand (Update-Pfad), dann das frisch
            // Gespeicherte (Create-Pfad) — wie ein frischer Store.
            if let Some(ev) = self
                .bestehend
                .as_ref()
                .filter(|ev| ev.felder.event_identifier == event_identifier)
            {
                let f = &ev.felder;
                return Some(ReadbackEvent {
                    title: f.title.clone(),
                    starts_at_utc: f.starts_at_utc.clone(),
                    ends_at_utc: f.ends_at_utc.clone(),
                    is_all_day: f.is_all_day,
                    location: f.location.clone(),
                    notes: f.notes.clone(),
                    time_zone: f.time_zone.clone(),
                    provider_calendar_id: f.provider_calendar_id.clone(),
                });
            }
            let (felder, kalender) = self.gespeichert.as_ref()?;
            Some(ReadbackEvent {
                title: felder.title.clone(),
                starts_at_utc: felder.starts_at_utc.clone(),
                ends_at_utc: felder.ends_at_utc.clone(),
                is_all_day: felder.is_all_day,
                location: felder.location.clone(),
                notes: felder.notes.clone(),
                // Exakt das Gespeicherte — der Fake erfindet nie eine Zone.
                time_zone: felder.time_zone.clone(),
                provider_calendar_id: kalender.clone(),
            })
        }

        fn lese_fingerprint_felder(
            &mut self,
            event_identifier: &str,
        ) -> Option<FingerprintFelder> {
            self.bestehend
                .as_ref()
                .filter(|ev| ev.felder.event_identifier == event_identifier)
                .map(|ev| ev.felder.clone())
        }

        fn aktualisiere_event(
            &mut self,
            event_identifier: &str,
            changes: &serde_json::Map<String, serde_json::Value>,
        ) -> Result<String, SpeicherFehler> {
            self.save_aufrufe += 1;
            if let Some(fehler) = self.save_fehler.take() {
                return Err(fehler);
            }
            let Some(ev) = self
                .bestehend
                .as_mut()
                .filter(|ev| ev.felder.event_identifier == event_identifier)
            else {
                return Err(SpeicherFehler {
                    vor_save: true,
                    beschreibung: "event_vanished_before_save".into(),
                });
            };
            let text = |w: &serde_json::Value| w.as_str().map(str::to_string);
            // AUSSCHLIESSLICH die enthaltenen Schlüssel — wie der Shim.
            for (schluessel, wert) in changes {
                match schluessel.as_str() {
                    "title" => ev.felder.title = text(wert),
                    "location" => ev.felder.location = text(wert),
                    "notes" => ev.felder.notes = text(wert),
                    "time_zone" => ev.felder.time_zone = text(wert),
                    "starts_at_utc" => {
                        ev.felder.starts_at_utc = text(wert).unwrap()
                    }
                    "ends_at_utc" => ev.felder.ends_at_utc = text(wert).unwrap(),
                    "is_all_day" => {
                        ev.felder.is_all_day = wert.as_bool().unwrap()
                    }
                    _ => unreachable!("pruefe_changes lässt nur Vertragsfelder durch"),
                }
            }
            // `extra_eigenschaft` wird BEWUSST nicht angefasst.
            Ok(ev.felder.event_identifier.clone())
        }

        fn delete_probe(&mut self, event_identifier: &str) -> Option<RohProbe> {
            self.probe
                .as_ref()
                .filter(|p| p.event_identifier == event_identifier)
                .cloned()
        }

        fn loesche_event(&mut self, event_identifier: &str)
            -> Result<(), SpeicherFehler>
        {
            self.delete_aufrufe += 1;
            if let Some(fehler) = self.delete_fehler.take() {
                return Err(fehler);
            }
            let vorhanden = self
                .bestehend
                .as_ref()
                .is_some_and(|ev| ev.felder.event_identifier == event_identifier);
            if !vorhanden {
                return Err(SpeicherFehler {
                    vor_save: true,
                    beschreibung: "event_vanished_before_delete".into(),
                });
            }
            if !self.delete_wirkt_nicht {
                self.bestehend = None;
            }
            Ok(())
        }
    }

    /// Ein Doppel, das **jede** Berührung des Providers zählt.
    ///
    /// Der Fake oben zählt nur Save und Delete. Für das Produktschloss genügt
    /// das nicht: Die Behauptung lautet nicht „es wurde nicht gespeichert",
    /// sondern „der Provider wurde gar nicht erst angefasst". Wer das prüfen
    /// will, muss auch die Autorisierungs- und Leseabfragen sehen.
    #[derive(Default)]
    pub(crate) struct ZaehlendeOperationen {
        pub(crate) beruehrungen: u32,
    }

    impl KalenderOperationen for ZaehlendeOperationen {
        fn kalender_zugang(&mut self, _: &str) -> KalenderZugang {
            self.beruehrungen += 1;
            KalenderZugang::Vorhanden
        }
        fn speichere_event(
            &mut self,
            _: &EventFelder,
            _: &str,
        ) -> Result<String, SpeicherFehler> {
            self.beruehrungen += 1;
            Ok("EV-NIE".into())
        }
        fn lese_event(&mut self, _: &str) -> Option<ReadbackEvent> {
            self.beruehrungen += 1;
            None
        }
        fn lese_fingerprint_felder(&mut self, _: &str) -> Option<FingerprintFelder> {
            self.beruehrungen += 1;
            None
        }
        fn aktualisiere_event(
            &mut self,
            _: &str,
            _: &serde_json::Map<String, serde_json::Value>,
        ) -> Result<String, SpeicherFehler> {
            self.beruehrungen += 1;
            Ok("EV-NIE".into())
        }
        fn delete_probe(&mut self, _: &str) -> Option<RohProbe> {
            self.beruehrungen += 1;
            None
        }
        fn loesche_event(&mut self, _: &str) -> Result<(), SpeicherFehler> {
            self.beruehrungen += 1;
            Ok(())
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
                "notes": null,
                "time_zone": "Europe/Berlin"
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

    // ── Das native Produktschloss ───────────────────────────────────────────
    #[test]
    fn calendar_ist_im_produkt_nicht_schreibreif() {
        // Der ausgelieferte Wert, ungefiltert. Die Testumschaltung oben
        // beruehrt ihn nicht.
        assert!(!CALENDAR_PRODUCT_WRITE_READY);
    }

    #[test]
    fn das_produktschloss_haelt_vor_jedem_providerkontakt() {
        // Ein formal einwandfreier, frei zusammengesetzter Auftrag: gueltige
        // Kennungen, richtiger payload_digest, gueltige Frist. Genau der Fall,
        // der bisher bis zum Save gekommen waere.
        let mut ops = ZaehlendeOperationen::default();
        let bericht = TEST_PRODUKTREIF.with(|z| {
            z.set(false);
            let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
            z.set(true);
            b
        });

        assert_eq!(bericht.outcome, "not_sent");
        assert_eq!(
            bericht.error_class.as_deref(),
            Some("provider_channel_disabled_before_send")
        );
        // Der eigentliche Beleg: **kein einziger** Providerkontakt. Nicht der
        // Save, nicht der Readback, nicht einmal die Autorisierungsabfrage.
        assert_eq!(ops.beruehrungen, 0, "der Provider wurde beruehrt");
        // Und der Bericht ist an genau diesen Auftrag gebunden, damit der Kern
        // ihn zuordnen kann.
        assert_eq!(bericht.mutation_id, "1".repeat(36));
    }

    #[test]
    fn das_produktschloss_gilt_fuer_jede_operationsart() {
        for art in ["create", "update", "delete"] {
            let mut ops = ZaehlendeOperationen::default();
            let bericht = TEST_PRODUKTREIF.with(|z| {
                z.set(false);
                let b = execute_order_mit_operationen(&auftrag(art, payload()), JETZT, &mut ops);
                z.set(true);
                b
            });
            assert_eq!(bericht.outcome, "not_sent", "{art}");
            assert_eq!(ops.beruehrungen, 0, "{art}: der Provider wurde beruehrt");
        }
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
        assert_eq!(gelesen.time_zone.as_deref(), Some("Europe/Berlin"));
        assert_eq!(gelesen.provider_calendar_id, "CAL-TEST");
    }

    #[test]
    fn die_zone_erreicht_save_und_readback_unveraendert() {
        // Verankerter Create (B3-P1-Zeitzonenkorrektur): die Zone kommt bei
        // der Save-Operation an und der Read-back meldet DIESELBE zurück.
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        let (gespeichert, _) = ops.gespeichert.as_ref().expect("Save fehlt");
        assert_eq!(gespeichert.time_zone.as_deref(), Some("Europe/Berlin"));
        assert_eq!(
            b.readback_event.expect("Read-back fehlt").time_zone.as_deref(),
            Some("Europe/Berlin")
        );
    }

    #[test]
    fn ein_bewusst_schwebender_create_bleibt_null() {
        // `null` ist eine Entscheidung: kein Layer ersetzt sie still durch
        // eine Systemzone — weder Save noch Read-back.
        let mut p = payload();
        p["fields"]["time_zone"] = serde_json::Value::Null;
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("create", p), JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        let (gespeichert, _) = ops.gespeichert.as_ref().expect("Save fehlt");
        assert_eq!(gespeichert.time_zone, None);
        assert_eq!(b.readback_event.expect("Read-back fehlt").time_zone, None);
    }

    #[test]
    fn ein_fehlender_time_zone_schluessel_faellt_vor_dem_save() {
        // Fehlend ist NICHT null: der Pflichtschlüssel fällt als
        // Payloadfehler, beweisbar vor jeder Übergabe.
        let mut p = payload();
        p["fields"].as_object_mut().unwrap().remove("time_zone");
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("create", p), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_unbekannter_zonenname_des_shims_ist_invalid_payload() {
        // Nur EventKit kennt die Zonendatenbank: weist der Shim den Namen
        // vor dem Save ab, trägt der Bericht die Payload-Klasse.
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        ops.save_fehler = Some(SpeicherFehler {
            vor_save: true,
            beschreibung: "unknown_time_zone".into(),
        });
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert!(!b.send_attempted);
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(b.error_digest.as_deref(), Some(sha256_hex("unknown_time_zone").as_str()));
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
        assert_eq!(b.error_class.as_deref(), Some("digest_mismatch"));
        assert!(!b.send_attempted);
        assert_eq!(b.save_request_count, 0);
        assert_eq!(ops.save_aufrufe, 0, "Fake-Save wurde aufgerufen");
        assert_eq!(ops.lese_aufrufe, 0);
    }

    #[test]
    fn ein_fremder_operationstyp_bleibt_capability_denied() {
        // P3 schaltet `delete` frei; alles ausserhalb der drei Kommandos
        // bleibt eine nicht erteilte Freigabe — beweisbar vor jeder Übergabe.
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("move", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("capability_denied"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_delete_auftrag_mit_create_payload_faellt() {
        // Ein Delete-Payload trägt keinen Feldsatz: `fields` im Payload
        // ist kein Vertragspayload — beweisbar vor jeder Übergabe.
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("delete", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
        assert_eq!(ops.delete_aufrufe, 0);
    }

    #[test]
    fn ein_update_auftrag_mit_create_payload_faellt() {
        // `command` muss zur freigegebenen Operation passen.
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&auftrag("update", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn eine_abgelaufene_order_wird_nicht_ausgefuehrt() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        // `expires_at` 2026-08-09T00:10:00Z liegt vor diesem Jetzt.
        let jetzt_danach = JETZT + 3600;
        let b = execute_order_mit_operationen(&auftrag("create", payload()), jetzt_danach, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("expired_claim_before_send"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_unbekannter_kalender_ist_kein_send() {
        let mut ops = FakeKalenderOperationen::mit_kalender("ANDERER-KALENDER");
        let b = execute_order_mit_operationen(&auftrag("create", payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("target_not_found"));
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
        assert_eq!(b.error_class.as_deref(), Some("schema_mismatch"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_unbekanntes_feld_wird_abgewiesen() {
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag("create", payload())).unwrap();
        roh["heimlich"] = serde_json::json!("wert");
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-TEST");
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("schema_mismatch"));
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
        assert_eq!(json["readback_event"]["time_zone"], "Europe/Berlin");
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

    // ── Update: Delta-Semantik (B3 P2) ─────────────────────────────────────

    /// Der Vorzustand des Fake-Events — wortgleich mit `PREIMAGE` in
    /// tests/personal/calendar/test_mutations.py (Paritätspin).
    pub(crate) fn preimage_felder() -> FingerprintFelder {
        FingerprintFelder {
            title: Some("Zahnarzt".into()),
            starts_at_utc: "2026-08-12T09:00:00Z".into(),
            ends_at_utc: "2026-08-12T10:00:00Z".into(),
            is_all_day: false,
            location: None,
            notes: None,
            time_zone: Some("Europe/Berlin".into()),
            provider_calendar_id: "cal-1".into(),
            event_identifier: "EK-EVENT-1".into(),
        }
    }

    /// Der beidseitig gepinnte Fingerprint desselben synthetischen Zustands —
    /// die Python-Seite pinnt DIESELBE Konstante (`PREIMAGE_FINGERPRINT_PIN`).
    const PREIMAGE_FINGERPRINT_PIN: &str =
        "a6394e8dd0a8804bb41c6ab1ca6b7840b568c1bd6901f3f21db8a5622cb198b1";

    fn update_payload(changes: serde_json::Value) -> serde_json::Value {
        serde_json::json!({
            "command": "update",
            "changes": changes,
            "provider_target": {
                "provider_calendar_id": "cal-1",
                "event_identifier": "EK-EVENT-1"
            },
            "expected_fingerprint": fingerprint_of(&preimage_felder())
        })
    }

    fn update_auftrag(payload: serde_json::Value) -> String {
        serde_json::json!({
            "operation_id": "2".repeat(36),
            "mutation_id": "3".repeat(36),
            "claim_token": "c".repeat(64),
            "operation_type": "update",
            "payload_digest": payload_digest(&payload),
            "preview_digest": "d".repeat(64),
            "canonical_payload": payload.clone(),
            "issued_at": "2026-08-09T00:00:00Z",
            "expires_at": "2026-08-09T00:10:00Z",
            "provider_target": payload["provider_target"].clone(),
            "expected_fingerprint": payload["expected_fingerprint"].clone()
        })
        .to_string()
    }

    fn update_ops() -> FakeKalenderOperationen {
        FakeKalenderOperationen::mit_bestehendem_event("cal-1", preimage_felder())
    }

    #[test]
    fn der_fingerprint_pin_stimmt_mit_der_python_seite_ueberein() {
        // Weicht diese Rechnung ab, sprechen Rust und Python verschiedene
        // Kanonisierungen — und der Preimage-Vergleich wäre wertlos.
        assert_eq!(fingerprint_of(&preimage_felder()), PREIMAGE_FINGERPRINT_PIN);
    }

    #[test]
    fn ein_titel_delta_aendert_nur_den_titel() {
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(
            serde_json::json!({"title": "Kieferorthopäde"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "applied", "{:?}", b.error_class);
        assert_eq!(b.readback_status, "confirmed");
        assert_eq!(b.save_request_count, 1);
        assert_eq!(ops.save_aufrufe, 1);
        assert!(b.fingerprint_checked);
        assert_eq!(b.fingerprint_matched, Some(true));
        assert_eq!(b.provider_identifier.as_deref(), Some("EK-EVENT-1"));
        let ev = ops.bestehend.as_ref().unwrap();
        assert_eq!(ev.felder.title.as_deref(), Some("Kieferorthopäde"));
        // Nicht-Delta-Felder bleiben UNVERÄNDERT.
        assert_eq!(ev.felder.starts_at_utc, "2026-08-12T09:00:00Z");
        assert_eq!(ev.felder.ends_at_utc, "2026-08-12T10:00:00Z");
        assert_eq!(ev.felder.time_zone.as_deref(), Some("Europe/Berlin"));
        assert!(!ev.felder.is_all_day);
        assert_eq!(ev.felder.location, None);
        // Der Read-back zeigt den GELESENEN Endzustand.
        let gelesen = b.readback_event.expect("Read-back fehlt");
        assert_eq!(gelesen.title.as_deref(), Some("Kieferorthopäde"));
        assert_eq!(gelesen.starts_at_utc, "2026-08-12T09:00:00Z");
        assert_eq!(gelesen.provider_calendar_id, "cal-1");
    }

    #[test]
    fn eine_native_zusatzeigenschaft_ueberlebt_das_delta() {
        // Der Kern der Delta-Entscheidung: was ausserhalb der sieben Felder
        // liegt, wird weder gelesen noch geschrieben noch rekonstruiert.
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(serde_json::json!({"title": "Neu"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        assert_eq!(
            ops.bestehend.as_ref().unwrap().extra_eigenschaft.as_deref(),
            Some("nativer-alarm")
        );
    }

    #[test]
    fn ein_leeres_delta_faellt_vor_dem_save() {
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(serde_json::json!({})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_unbekanntes_delta_feld_faellt_vor_dem_save() {
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(
            serde_json::json!({"title": "Neu", "url": "https://x.invalid"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_extern_geaendertes_delta_feld_ist_revision_conflict() {
        // Der Titel wurde extern geändert, das Delta will genau ihn ändern.
        let mut ops = update_ops();
        ops.bestehend.as_mut().unwrap().felder.title = Some("Extern geändert".into());
        let roh = update_auftrag(update_payload(serde_json::json!({"title": "Neu"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert!(!b.send_attempted);
        assert_eq!(b.save_request_count, 0);
        assert_eq!(ops.save_aufrufe, 0);
        assert!(b.fingerprint_checked);
        assert_eq!(b.fingerprint_matched, Some(false));
        assert_eq!(b.error_class.as_deref(), Some("revision_conflict"));
    }

    #[test]
    fn ein_extern_geaendertes_nicht_delta_feld_ist_ebenfalls_conflict() {
        // Der Fingerprint deckt den VOLLSTÄNDIGEN Zustand: auch ein Feld,
        // das das Delta gar nicht anfasst (Ort), bricht den Vergleich.
        let mut ops = update_ops();
        ops.bestehend.as_mut().unwrap().felder.location = Some("Anderswo".into());
        let roh = update_auftrag(update_payload(serde_json::json!({"title": "Neu"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("revision_conflict"));
        assert_eq!(b.fingerprint_matched, Some(false));
        assert_eq!(ops.save_aufrufe, 0);
        // Der Bestand blieb unangetastet.
        assert_eq!(
            ops.bestehend.as_ref().unwrap().felder.title.as_deref(),
            Some("Zahnarzt")
        );
    }

    #[test]
    fn ein_identischer_vorzustand_laesst_das_update_laufen() {
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(
            serde_json::json!({"location": "Raum 2"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        assert_eq!(b.fingerprint_matched, Some(true));
        assert_eq!(
            ops.bestehend.as_ref().unwrap().felder.location.as_deref(),
            Some("Raum 2")
        );
    }

    #[test]
    fn ein_manipuliertes_update_payload_erreicht_den_save_nie() {
        // Nach der Freigabe angefasst: der Digest bricht, beweisbar vor
        // jeder Übergabe — der Fake-Zähler ist der Beleg (R9).
        let mut roh: serde_json::Value = serde_json::from_str(&update_auftrag(
            update_payload(serde_json::json!({"title": "Neu"})))).unwrap();
        roh["canonical_payload"]["changes"]["title"] =
            serde_json::json!("Heimlich anders");
        let mut ops = update_ops();
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("digest_mismatch"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn eine_zeitverschiebung_erhaelt_die_zone() {
        // Offline-Zeitverschiebung: starts+ends aus dem Dauererhalt; die
        // Zone ist NICHT im Delta und bleibt exakt die alte.
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(serde_json::json!({
            "starts_at_utc": "2026-08-12T11:00:00Z",
            "ends_at_utc": "2026-08-12T12:00:00Z"
        })));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        let ev = ops.bestehend.as_ref().unwrap();
        assert_eq!(ev.felder.starts_at_utc, "2026-08-12T11:00:00Z");
        assert_eq!(ev.felder.ends_at_utc, "2026-08-12T12:00:00Z");
        assert!(ev.felder.ends_at_utc > ev.felder.starts_at_utc);
        assert_eq!(ev.felder.time_zone.as_deref(), Some("Europe/Berlin"));
    }

    #[test]
    fn eine_bewusste_ende_aenderung_ist_moeglich() {
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(
            serde_json::json!({"ends_at_utc": "2026-08-12T11:30:00Z"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        let ev = ops.bestehend.as_ref().unwrap();
        assert_eq!(ev.felder.ends_at_utc, "2026-08-12T11:30:00Z");
        assert_eq!(ev.felder.starts_at_utc, "2026-08-12T09:00:00Z");
    }

    #[test]
    fn ein_zusammengefuehrtes_ende_vor_dem_beginn_faellt() {
        // Nur das Ende im Delta, aber vor dem BESTEHENDEN Beginn: erst der
        // frisch gelesene Zustand macht das prüfbar — und es fällt vor
        // dem Save.
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(
            serde_json::json!({"ends_at_utc": "2026-08-12T08:00:00Z"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(b.fingerprint_matched, Some(true));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn floating_bleibt_floating() {
        // Vorzustand schwebend (time_zone null); das Delta fasst die Zone
        // nicht an — sie bleibt null, kein Layer erfindet eine.
        let mut felder = preimage_felder();
        felder.time_zone = None;
        let expected = fingerprint_of(&felder);
        let mut ops =
            FakeKalenderOperationen::mit_bestehendem_event("cal-1", felder);
        let mut payload = update_payload(serde_json::json!({"title": "Neu"}));
        payload["expected_fingerprint"] = serde_json::json!(expected);
        let b = execute_order_mit_operationen(
            &update_auftrag(payload), JETZT, &mut ops);
        assert_eq!(b.outcome, "applied", "{:?}", b.error_class);
        assert_eq!(ops.bestehend.as_ref().unwrap().felder.time_zone, None);
        assert_eq!(b.readback_event.expect("Read-back fehlt").time_zone, None);
    }

    #[test]
    fn null_ist_ein_fachlicher_wert_im_delta() {
        // `{"title": null}` löscht den Titel — Nicht-ändern wäre Weglassen.
        let mut ops = update_ops();
        let roh = update_auftrag(update_payload(serde_json::json!({"title": null})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "applied");
        assert_eq!(ops.bestehend.as_ref().unwrap().felder.title, None);
    }

    #[test]
    fn ein_update_ohne_eventkennung_faellt() {
        let mut payload = update_payload(serde_json::json!({"title": "Neu"}));
        payload["provider_target"]["event_identifier"] = serde_json::Value::Null;
        let mut roh: serde_json::Value =
            serde_json::from_str(&update_auftrag(payload)).unwrap();
        roh["provider_target"]["event_identifier"] = serde_json::Value::Null;
        let mut ops = update_ops();
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_update_ohne_expected_fingerprint_faellt() {
        let mut payload = update_payload(serde_json::json!({"title": "Neu"}));
        payload["expected_fingerprint"] = serde_json::Value::Null;
        let mut ops = update_ops();
        let b = execute_order_mit_operationen(
            &update_auftrag(payload), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_nicht_lesbares_event_ist_target_not_found() {
        // Kein Bestand unter der Kennung: ohne Vorzustand kein Vergleich,
        // ohne Vergleich kein Save.
        let mut ops = FakeKalenderOperationen::mit_kalender("cal-1");
        let roh = update_auftrag(update_payload(serde_json::json!({"title": "Neu"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("target_not_found"));
        assert!(!b.fingerprint_checked);
        assert_eq!(ops.save_aufrufe, 0);
    }

    #[test]
    fn ein_update_fehler_im_save_ist_ungewiss() {
        // Nach übergebenem Save gibt es keinen zweiten Versuch — der
        // Ausgang ist ungewiss, die Fingerprint-Aussage bleibt stehen.
        let mut ops = update_ops();
        ops.save_fehler = Some(SpeicherFehler {
            vor_save: false,
            beschreibung: "EKErrorDomain:11".into(),
        });
        let roh = update_auftrag(update_payload(serde_json::json!({"title": "Neu"})));
        let b = execute_order_mit_operationen(&roh, JETZT, &mut ops);
        assert_eq!(b.outcome, "unknown");
        assert!(b.send_attempted);
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.fingerprint_matched, Some(true));
        assert_eq!(b.error_class.as_deref(), Some("provider_save_error"));
    }

    // ── Delete: drei Nachweise, Allowlist-Eligibility (B3 P3) ──────────────

    /// Eine Probe ohne jede belegte unsupported Eigenschaft — der
    /// Ausgangszustand des synthetischen Bestandsevents.
    pub(crate) fn unauffaellige_probe() -> RohProbe {
        RohProbe {
            event_identifier: "EK-EVENT-1".into(),
            provider_calendar_id: "cal-1".into(),
            has_recurrence_rules: false,
            recurrence_rule_count: 0,
            is_detached: false,
            has_attendees: false,
            attendee_count: 0,
            has_organizer: false,
            has_alarms: false,
            alarm_count: 0,
            has_url: false,
            has_structured_location_geo: false,
            has_birthday_link: false,
            availability_marked: false,
            has_participation_status: false,
        }
    }

    /// Beidseitig gepinnte Digests desselben synthetischen Zustands — die
    /// Python-Seite pinnt DIESELBEN Konstanten. Weicht eine Seite ab,
    /// rechnen Rust und Python verschiedene Kanonisierungen, und die
    /// Approval-Bindung des Deletes wäre wertlos.
    const ELIGIBILITY_DIGEST_PIN: &str =
        "d5b92ebce7a158d4213ffe8b946c4f5f93c91917fd37756478d5b4cad4261f33";
    const RESTORE_PREIMAGE_DIGEST_PIN: &str =
        "a33587d4e03bba7fd50481a7b386440e229dc9762cb65b022739e6210978ab09";

    fn delete_payload() -> serde_json::Value {
        let vorher = preimage_felder();
        serde_json::json!({
            "command": "delete",
            "provider_target": {
                "provider_calendar_id": "cal-1",
                "event_identifier": "EK-EVENT-1"
            },
            "expected_fingerprint": fingerprint_of(&vorher),
            "eligibility_digest":
                eligibility_digest_of(&kanonische_probe(&unauffaellige_probe())),
            "restore_preimage_digest":
                payload_digest(&restore_preimage_of(&vorher)),
        })
    }

    fn delete_auftrag(payload: serde_json::Value) -> String {
        serde_json::json!({
            "operation_id": "4".repeat(36),
            "mutation_id": "5".repeat(36),
            "claim_token": "e".repeat(64),
            "operation_type": "delete",
            "payload_digest": payload_digest(&payload),
            "preview_digest": "f".repeat(64),
            "canonical_payload": payload.clone(),
            "issued_at": "2026-08-09T00:00:00Z",
            "expires_at": "2026-08-09T00:10:00Z",
            "provider_target": payload["provider_target"].clone(),
            "expected_fingerprint": payload["expected_fingerprint"].clone()
        })
        .to_string()
    }

    fn delete_ops() -> FakeKalenderOperationen {
        let mut ops =
            FakeKalenderOperationen::mit_bestehendem_event("cal-1", preimage_felder());
        ops.probe = Some(unauffaellige_probe());
        ops
    }

    #[test]
    fn die_beobachtete_defekte_emission_faellt_fail_closed() {
        // DER P3-Livebefund (Stufe probe_unparseable), als Regression
        // festgehalten: der Shim boxte vier Wahrheitswerte über nackte
        // Vergleichsausdrücke — Clang emittiert die als 0/1-ZAHLEN, nicht
        // als true/false (beobachtet am gleichen Clang/SDK mit denselben
        // Ausdrucksformen, nicht abgeleitet). Genau diese Emission MUSS
        // weiterhin fallen: eine Zahl ist kein Wahrheitswert, und die
        // Reparatur gehört auf die Shim-Seite, nie in eine Lockerung des
        // Parsers.
        let beobachtet_defekt = r#"{
            "event_identifier": "EK-EVENT-1",
            "provider_calendar_id": "cal-1",
            "has_recurrence_rules": false,
            "recurrence_rule_count": 0,
            "is_detached": false,
            "has_attendees": false,
            "attendee_count": 0,
            "has_organizer": 0,
            "has_alarms": false,
            "alarm_count": 0,
            "has_url": 0,
            "has_structured_location_geo": false,
            "has_birthday_link": 0,
            "availability_marked": false,
            "has_participation_status": 0
        }"#;
        assert!(
            serde_json::from_str::<RohProbe>(beobachtet_defekt).is_err(),
            "0/1 als Wahrheitswert darf NIE parsbar werden (keine Lockerung)"
        );
    }

    #[test]
    fn das_objc_probe_json_parst_in_die_rohprobe() {
        // Streckenpin: nach der Shim-Reparatur (alle Wahrheitswerte über
        // BOOL-typisierte Variablen geboxt) ist DIES die Emissionsform —
        // die Wertformen sind BEOBACHTET (gleiches Clang/SDK, gleiche
        // NSJSONSerialization: BOOL-geboxt → true/false, NSUInteger →
        // Zahl), nicht aus dem Quelltext geraten; der byte-genaue
        // Realbeleg am echten Event kommt zusätzlich über das
        // `raw`-Feld der probe_unparseable-Stufe, sobald je wieder eine
        // Drift auftritt. Muss fail-closed in die RohProbe und weiter in
        // die gepinnte kanonische Probe laufen.
        let literal = r#"{
            "event_identifier": "EK-EVENT-1",
            "provider_calendar_id": "cal-1",
            "has_recurrence_rules": false,
            "recurrence_rule_count": 0,
            "is_detached": false,
            "has_attendees": false,
            "attendee_count": 0,
            "has_organizer": false,
            "has_alarms": false,
            "alarm_count": 0,
            "has_url": false,
            "has_structured_location_geo": false,
            "has_birthday_link": false,
            "availability_marked": false,
            "has_participation_status": false
        }"#;
        let roh: RohProbe = serde_json::from_str(literal).expect("Shim-JSON parst nicht");
        assert_eq!(roh, unauffaellige_probe());
        assert_eq!(
            eligibility_digest_of(&kanonische_probe(&roh)),
            ELIGIBILITY_DIGEST_PIN
        );
        // Gegentest: ein fremder Schlüssel fällt (deny_unknown_fields) —
        // eine gedriftete Shim-Emission wird nie still verdaut.
        let fremd = literal.replace(
            "\"has_url\": false",
            "\"has_url\": false, \"heimlich\": 1");
        assert!(serde_json::from_str::<RohProbe>(&fremd).is_err());
    }

    #[test]
    fn die_delete_digest_pins_stimmen_mit_der_python_seite_ueberein() {
        assert_eq!(
            eligibility_digest_of(&kanonische_probe(&unauffaellige_probe())),
            ELIGIBILITY_DIGEST_PIN
        );
        assert_eq!(
            payload_digest(&restore_preimage_of(&preimage_felder())),
            RESTORE_PREIMAGE_DIGEST_PIN
        );
    }

    #[test]
    fn ein_einfacher_unterstuetzter_event_wird_geloescht_und_abwesend_bestaetigt() {
        // Fixture A: eligible, Freigabe vorhanden — der Delete erreicht den
        // nativen Remove genau einmal, der Read-back bestätigt ABWESENHEIT.
        let mut ops = delete_ops();
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "applied", "{:?}", b.error_class);
        assert_eq!(b.readback_status, "absent_confirmed");
        assert!(b.send_attempted);
        assert_eq!(b.save_request_count, 1);
        assert_eq!(ops.delete_aufrufe, 1);
        assert_eq!(ops.save_aufrufe, 0);
        assert!(b.fingerprint_checked);
        assert_eq!(b.fingerprint_matched, Some(true));
        assert_eq!(b.provider_identifier.as_deref(), Some("EK-EVENT-1"));
        assert_eq!(b.readback_event, None);
        assert_eq!(b.error_class, None);
        assert!(ops.bestehend.is_none(), "der Bestand wurde entfernt");
    }

    /// R9-Helfer: erst BELEGEN, dass die unsupported Eigenschaft an der
    /// Probe tatsächlich gesetzt ist, dann blocked erwarten — und der
    /// Beleg, dass der native Delete nie erreicht wurde, ist der Zähler.
    fn blocked_wegen(probe: RohProbe, erwartete_flags: &[&str]) {
        let kanonisch = kanonische_probe(&probe);
        let flags: Vec<String> = kanonisch["unsupported_feature_flags"]
            .as_array()
            .unwrap()
            .iter()
            .map(|w| w.as_str().unwrap().to_string())
            .collect();
        for flag in erwartete_flags {
            assert!(
                flags.iter().any(|f| f == flag),
                "R9: Eigenschaft {flag} ist an der Fixture nicht belegt"
            );
        }
        assert_eq!(kanonisch["eligible"], serde_json::json!(false));

        let mut ops = delete_ops();
        ops.probe = Some(probe);
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert!(!b.send_attempted);
        assert_eq!(b.save_request_count, 0);
        assert_eq!(b.error_class.as_deref(), Some("unsupported_field"));
        assert_eq!(ops.delete_aufrufe, 0, "nativer Delete wurde erreicht");
        assert!(ops.bestehend.is_some(), "der Bestand blieb unangetastet");
    }

    #[test]
    fn ein_event_mit_wiederholungsregel_ist_blocked() {
        // Fixture B.
        let mut probe = unauffaellige_probe();
        probe.has_recurrence_rules = true;
        probe.recurrence_rule_count = 1;
        blocked_wegen(probe, &["recurrence_rules"]);
    }

    #[test]
    fn ein_event_mit_teilnehmersemantik_ist_blocked() {
        // Fixture C: Teilnehmer, Organisator und Teilnahmestatus — die
        // volle Einladungssemantik.
        let mut probe = unauffaellige_probe();
        probe.has_attendees = true;
        probe.attendee_count = 2;
        probe.has_organizer = true;
        probe.has_participation_status = true;
        blocked_wegen(probe, &["attendees", "organizer", "participation_status"]);
    }

    #[test]
    fn ein_event_mit_wecker_ist_blocked() {
        // Fixture D: Wecker sind im B3-Restore nicht verlustfrei.
        let mut probe = unauffaellige_probe();
        probe.has_alarms = true;
        probe.alarm_count = 1;
        blocked_wegen(probe, &["alarms"]);
    }

    #[test]
    fn ein_event_mit_url_ist_blocked() {
        // Fixture E: verfügbare, nicht unterstützte Semantik (URL).
        let mut probe = unauffaellige_probe();
        probe.has_url = true;
        blocked_wegen(probe, &["url"]);
    }

    #[test]
    fn ein_event_mit_geo_ort_ist_blocked() {
        // Fixture E': strukturierter Ort mit Geokoordinate — mehr als der
        // B3-Ortstext wiederherstellen kann.
        let mut probe = unauffaellige_probe();
        probe.has_structured_location_geo = true;
        blocked_wegen(probe, &["structured_location_geo"]);
    }

    #[test]
    fn eine_kombination_unsupported_eigenschaften_ist_blocked() {
        // Fixture F.
        let mut probe = unauffaellige_probe();
        probe.has_recurrence_rules = true;
        probe.recurrence_rule_count = 2;
        probe.has_attendees = true;
        probe.attendee_count = 5;
        probe.has_alarms = true;
        probe.alarm_count = 1;
        probe.availability_marked = true;
        blocked_wegen(
            probe,
            &["alarms", "attendees", "availability_marked", "recurrence_rules"],
        );
    }

    #[test]
    fn eine_zwischen_freigabe_und_execute_geaenderte_eligibility_blockt() {
        // Fixture G: die Freigabe band einen eligible Zustand; unmittelbar
        // vor dem Execute zeigt die frische Probe eine URL. Blocked — und
        // der native Delete wurde nachweislich nicht erreicht.
        let mut probe = unauffaellige_probe();
        probe.has_url = true;
        let mut ops = delete_ops();
        ops.probe = Some(probe);
        // Der Auftrag trägt den Digest des URSPRÜNGLICH eligible Zustands.
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("unsupported_field"));
        assert_eq!(ops.delete_aufrufe, 0);
        assert!(ops.bestehend.is_some());
    }

    #[test]
    fn ein_abweichender_eligibility_digest_ist_revision_conflict() {
        // Fixture G': die Probe ist eligible, aber NICHT der Zustand, den
        // die Freigabe band (hier: Digest einer fremden Eventidentität im
        // Payload). Kein Delete, Approval-Bindung bricht sichtbar.
        let mut fremde = unauffaellige_probe();
        fremde.event_identifier = "EK-ANDERES-EVENT".into();
        let mut payload = delete_payload();
        payload["eligibility_digest"] = serde_json::json!(
            eligibility_digest_of(&kanonische_probe(&fremde)));
        let mut ops = delete_ops();
        let b = execute_order_mit_operationen(
            &delete_auftrag(payload), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("revision_conflict"));
        assert_eq!(b.fingerprint_matched, Some(true));
        assert_eq!(ops.delete_aufrufe, 0);
        assert!(ops.bestehend.is_some());
    }

    #[test]
    fn ein_zwischen_freigabe_und_execute_geaendertes_feld_ist_revision_conflict() {
        // Fixture H: ein unterstütztes Feld (Titel) wurde extern geändert —
        // der 9-Feld-Fingerprint bricht, bevor irgendetwas übergeben wird.
        let mut ops = delete_ops();
        ops.bestehend.as_mut().unwrap().felder.title = Some("Extern geändert".into());
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert!(b.fingerprint_checked);
        assert_eq!(b.fingerprint_matched, Some(false));
        assert_eq!(b.error_class.as_deref(), Some("revision_conflict"));
        assert_eq!(ops.delete_aufrufe, 0);
        assert!(ops.bestehend.is_some());
    }

    #[test]
    fn ein_abweichender_restore_digest_ist_revision_conflict() {
        // Die Wiederherstellbarkeitsprüfung unmittelbar vor dem Execute:
        // das gebundene Restore-Artefakt muss aus dem frischen Zustand
        // exakt nachrechenbar sein.
        let mut anderes = preimage_felder();
        anderes.title = Some("Anderer Termin".into());
        let mut payload = delete_payload();
        payload["restore_preimage_digest"] = serde_json::json!(
            payload_digest(&restore_preimage_of(&anderes)));
        let mut ops = delete_ops();
        let b = execute_order_mit_operationen(
            &delete_auftrag(payload), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("revision_conflict"));
        assert_eq!(ops.delete_aufrufe, 0);
        assert!(ops.bestehend.is_some());
    }

    #[test]
    fn ein_nicht_lesbares_delete_ziel_ist_target_not_found() {
        let mut ops = FakeKalenderOperationen::mit_kalender("cal-1");
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("target_not_found"));
        assert_eq!(ops.delete_aufrufe, 0);
    }

    #[test]
    fn ein_delete_ohne_probe_ist_target_not_found() {
        // Der Bestand ist lesbar, aber die Probe nicht erhebbar — ohne
        // frische Eligibility-Messung gibt es keinen Delete.
        let mut ops =
            FakeKalenderOperationen::mit_bestehendem_event("cal-1", preimage_felder());
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("target_not_found"));
        assert_eq!(ops.delete_aufrufe, 0);
        assert!(ops.bestehend.is_some());
    }

    #[test]
    fn ein_delete_fehler_im_remove_ist_ungewiss() {
        let mut ops = delete_ops();
        ops.delete_fehler = Some(SpeicherFehler {
            vor_save: false,
            beschreibung: "EKErrorDomain:11".into(),
        });
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "unknown");
        assert!(b.send_attempted);
        assert_eq!(b.save_request_count, 1);
        assert_eq!(b.readback_status, "unavailable");
        assert_eq!(b.error_class.as_deref(), Some("provider_save_error"));
    }

    #[test]
    fn ein_nach_dem_remove_weiter_lesbares_event_ist_kein_applied() {
        // R10-Geist für den Delete: eine leere Zielsuche wäre kein Beweis —
        // und ein VOLLES Ziel erst recht keiner. Meldet der Store Erfolg,
        // aber das Event bleibt lesbar, ist der Ausgang ehrlich ungewiss.
        let mut ops = delete_ops();
        ops.delete_wirkt_nicht = true;
        let b = execute_order_mit_operationen(
            &delete_auftrag(delete_payload()), JETZT, &mut ops);
        assert_eq!(b.outcome, "unknown");
        assert_eq!(b.readback_status, "confirmed");
        assert_eq!(b.error_class.as_deref(), Some("readback_failed"));
        assert_eq!(b.save_request_count, 1);
    }

    #[test]
    fn ein_manipulierter_delete_payload_erreicht_den_remove_nie() {
        // R9: Nach der Freigabe angefasst — der Digest bricht, der Zähler
        // ist der Beleg.
        let mut roh: serde_json::Value = serde_json::from_str(
            &delete_auftrag(delete_payload())).unwrap();
        roh["canonical_payload"]["provider_target"]["event_identifier"] =
            serde_json::json!("EK-HEIMLICH-ANDERES");
        let mut ops = delete_ops();
        let b = execute_order_mit_operationen(&roh.to_string(), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("digest_mismatch"));
        assert_eq!(ops.delete_aufrufe, 0);
        assert!(ops.bestehend.is_some());
    }

    #[test]
    fn ein_delete_ohne_eligibility_digest_faellt() {
        let mut payload = delete_payload();
        payload.as_object_mut().unwrap().remove("eligibility_digest");
        let mut ops = delete_ops();
        let b = execute_order_mit_operationen(
            &delete_auftrag(payload), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.delete_aufrufe, 0);
    }

    #[test]
    fn ein_delete_ohne_restore_digest_faellt() {
        let mut payload = delete_payload();
        payload.as_object_mut().unwrap().remove("restore_preimage_digest");
        let mut ops = delete_ops();
        let b = execute_order_mit_operationen(
            &delete_auftrag(payload), JETZT, &mut ops);
        assert_eq!(b.error_class.as_deref(), Some("invalid_payload"));
        assert_eq!(ops.delete_aufrufe, 0);
    }
}

#[cfg(test)]
mod serververtrag_tests {
    use super::tests::FakeKalenderOperationen;
    use super::*;

    const JETZT: i64 = 1_786_233_600; // 2026-08-09T00:00:00Z

    fn serverauftrag(schema_version: u32) -> String {
        let payload = serde_json::json!({
            "command": "create", "expected_fingerprint": null,
            "fields": {"ends_at_utc": "2036-08-10T08:00:00Z", "is_all_day": false,
                        "location": null, "notes": null,
                        "starts_at_utc": "2036-08-10T07:00:00Z",
                        "time_zone": "Europe/Berlin",
                        "title": "B3-Abnahmetermin"},
            "provider_target": {"event_identifier": null,
                                 "provider_calendar_id": "CAL-1"}});
        serde_json::json!({
            "schema_version": schema_version,
            "operation_id": "op-server", "mutation_id": "m-server",
            "claim_token": "token",
            "operation_type": "create",
            "payload_digest": payload_digest(&payload),
            "preview_digest": "0".repeat(64),
            "canonical_payload": payload,
            // Exakt die Serverform vom 2026-08-09: +00:00 statt Z.
            "issued_at": "2026-08-09T12:01:57+00:00",
            "expires_at": "2099-08-09T12:11:57+00:00",
            "provider_target": {"event_identifier": null,
                                 "provider_calendar_id": "CAL-1"},
            "expected_fingerprint": null})
        .to_string()
    }

    /// Schärfungstest der B3-Reparatur: ein Auftrag EXAKT in der Form, die
    /// der Python-Server real sendet (inkl. `schema_version` und
    /// `+00:00`-Zeitstempeln), passiert die Validierung. Genau diese Form
    /// wurde am 2026-08-09 mit `order_invalid` abgewiesen.
    #[test]
    fn ein_echter_serverauftrag_passiert_die_validierung() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-1");
        let b = execute_order_mit_operationen(&serverauftrag(1), JETZT, &mut ops);
        assert_eq!(b.outcome, "applied", "{:?}", b.error_class);
        assert_eq!(ops.save_aufrufe, 1);
    }

    /// Gegentest: eine fremde Vertragsversion faellt weiterhin — beweisbar
    /// vor jeder Uebergabe (Save-Zaehler bleibt null), mit kanonischer Klasse.
    #[test]
    fn eine_fremde_schemaversion_faellt_vor_dem_speichern() {
        let mut ops = FakeKalenderOperationen::mit_kalender("CAL-1");
        let b = execute_order_mit_operationen(&serverauftrag(2), JETZT, &mut ops);
        assert_eq!(b.outcome, "not_sent");
        assert_eq!(b.error_class.as_deref(), Some("schema_mismatch"));
        assert_eq!(ops.save_aufrufe, 0);
    }
}
