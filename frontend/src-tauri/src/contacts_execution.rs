// Der App-Prozess-Ausführungskanal (ADR-0020, Phase A).
//
// **In Phase A gibt es hier keinen Contacts-Code.** Kein `CNSaveRequest`,
// kein `CNMutableContact`, kein Sidecar-Aufruf, kein Spike. Was dieses Modul
// tut, ist ausschliesslich: einen `ExecutionOrderV1` streng validieren, den
// Payload-Digest **nachrechnen** und einen typisierten `ExecutionReportV1`
// zurückgeben.
//
// Der Digest-Nachweis ist der eigentliche Zweck: Er bindet das, was der
// Mensch freigegeben hat, an das, was ausgeführt würde. Rechnete ihn das
// Frontend, wäre die Bindung wertlos — es ist genau die Schicht, die
// manipuliert sein könnte.
//
// Ohne ausdrückliches Entwicklungs-Gate antwortet das Command fail-closed
// `not_sent / provider_channel_disabled_before_send`. Im Release-Profil ist
// der Fake-Zweig **auskompiliert** (`#[cfg(debug_assertions)]`) — er lässt
// sich dort nicht durch eine Umgebungsvariable erwecken.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

/// Version der Transporthülle — muss mit dem Kern übereinstimmen.
pub const EXECUTION_SCHEMA_VERSION: u32 = 1;

/// Größenlimits aus ADR-0020 §5.
pub const MAX_ORDER_BYTES: usize = 64 * 1024;

/// Umgebungsvariable des Fake-Kanals. Wirkt **nur** in Debug-Builds.
pub const FAKE_ENV_VAR: &str = "OPENJARVIS_CONTACTS_FAKE_EXECUTION";

const OPERATION_TYPES: [&str; 3] = ["create", "update", "delete"];

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionOrderV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub mutation_id: String,
    pub claim_token: String,
    pub operation_type: String,
    pub payload_digest: String,
    pub preview_digest: String,
    pub canonical_payload: serde_json::Value,
    pub readback_requirements: serde_json::Value,
    pub issued_at: String,
    pub expires_at: String,
    pub mutation_contract_version: u32,
    pub field_contract_version: u32,
    pub transaction_author: String,
    #[serde(default)]
    pub expected_revision: Option<String>,
    #[serde(default)]
    pub provider_target: BTreeMap<String, Option<String>>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ExecutionReportV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub mutation_id: String,
    pub operation_type: String,
    pub outcome: String,
    pub send_attempted: bool,
    pub save_request_count: u32,
    pub readback_status: String,
    pub provider_identifier_digest: Option<String>,
    /// Die **rohe** Providerkennung (ADR-0020 §5). Sie reist ausschliesslich
    /// im Settle-Rumpf: Ohne sie koennte das Backend nach einem Create keine
    /// External-ID anlegen und den Kontakt nie wieder gezielt ansprechen.
    /// In Audit, Log und Oberflaeche steht der Digest — nie dieser Wert.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_identifier: Option<String>,
    /// Der gelesene Zustand in kanonischer v1-Form. Aus ihm bildet der Kern
    /// seinen `readback_digest` und fuehrt den lokalen Spiegel nach.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub readback_contact: Option<serde_json::Value>,
    pub readback_revision: Option<String>,
    pub readback_digest: Option<String>,
    pub error_class: Option<String>,
    pub error_digest: Option<String>,
    pub diagnostic_artifact_present: bool,
    pub provider_completed_at: Option<String>,
}

impl ExecutionReportV1 {
    /// Ein Bericht, der **beweisbar** nichts übergeben hat.
    pub fn not_sent(order: &ExecutionOrderV1, error_class: &str) -> Self {
        Self {
            schema_version: EXECUTION_SCHEMA_VERSION,
            operation_id: order.operation_id.clone(),
            mutation_id: order.mutation_id.clone(),
            operation_type: order.operation_type.clone(),
            outcome: "not_sent".into(),
            send_attempted: false,
            save_request_count: 0,
            readback_status: "not_attempted".into(),
            provider_identifier_digest: None,
            provider_identifier: None,
            readback_contact: None,
            readback_revision: None,
            readback_digest: None,
            error_class: Some(error_class.into()),
            error_digest: None,
            diagnostic_artifact_present: false,
            provider_completed_at: None,
        }
    }

    /// Ein Bericht ohne gültigen Auftrag — die Bindung fehlt, also auch die
    /// Zuordnung. Er trägt leere Kennungen und ist damit für das Backend
    /// nicht settlebar; das ist Absicht.
    fn ungebunden(error_class: &str) -> Self {
        Self {
            schema_version: EXECUTION_SCHEMA_VERSION,
            operation_id: String::new(),
            mutation_id: String::new(),
            operation_type: "create".into(),
            outcome: "not_sent".into(),
            send_attempted: false,
            save_request_count: 0,
            readback_status: "not_attempted".into(),
            provider_identifier_digest: None,
            provider_identifier: None,
            readback_contact: None,
            readback_revision: None,
            readback_digest: None,
            error_class: Some(error_class.into()),
            error_digest: None,
            diagnostic_artifact_present: false,
            provider_completed_at: None,
        }
    }
}

pub fn sha256_hex(inhalt: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(inhalt.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Kanonische JSON-Form — bitgleich zu `base/digest.canonical_json` im Kern:
/// Schlüssel sortiert, keine Leerzeichen, Nicht-ASCII unmaskiert.
///
/// Die Gleichheit ist keine Absichtserklärung: Goldene Vektoren aus dem Kern
/// prüfen sie (siehe `tests` unten und die Fixture-Suite in Python).
pub fn canonical_json(wert: &serde_json::Value) -> String {
    match wert {
        serde_json::Value::Object(map) => {
            let sortiert: BTreeMap<_, _> = map.iter().collect();
            let teile: Vec<String> = sortiert
                .iter()
                .map(|(k, v)| {
                    format!("{}:{}", serde_json::to_string(k).unwrap(), canonical_json(v))
                })
                .collect();
            format!("{{{}}}", teile.join(","))
        }
        serde_json::Value::Array(werte) => {
            let teile: Vec<String> = werte.iter().map(canonical_json).collect();
            format!("[{}]", teile.join(","))
        }
        andere => serde_json::to_string(andere).unwrap(),
    }
}

pub fn payload_digest(payload: &serde_json::Value) -> String {
    sha256_hex(&canonical_json(payload))
}

/// Prüft den Auftrag vollständig, **bevor** irgendetwas geschieht.
fn validiere(order: &ExecutionOrderV1) -> Result<(), &'static str> {
    if order.schema_version != EXECUTION_SCHEMA_VERSION
        || order.mutation_contract_version != 1
        || order.field_contract_version != 1
    {
        return Err("schema_mismatch");
    }
    if !OPERATION_TYPES.contains(&order.operation_type.as_str()) {
        return Err("schema_mismatch");
    }
    if order.operation_id.len() != 36 || order.mutation_id.len() != 36 {
        return Err("invalid_claim");
    }
    // 32 Byte CSPRNG als Hex — Format, nicht Gültigkeit (die kennt der Kern).
    if order.claim_token.len() != 64
        || !order.claim_token.chars().all(|z| z.is_ascii_hexdigit())
    {
        return Err("invalid_claim");
    }
    if order.payload_digest.len() != 64 || order.preview_digest.len() != 64 {
        return Err("digest_mismatch");
    }
    // Der Kern hat den Digest gebildet; hier wird er nachgerechnet. Weicht
    // er ab, wurde der Payload nach der Freigabe angefasst.
    if payload_digest(&order.canonical_payload) != order.payload_digest {
        return Err("digest_mismatch");
    }
    Ok(())
}

/// Die fünf deterministischen Fake-Ausgänge (ADR-0020, Phase A).
///
/// Gesteuert über ein Feld des kanonischen Payloads (`__fake_outcome`), damit
/// der Auslöser Teil des digest-gebundenen Auftrags ist: Ein Test kann kein
/// Ergebnis erzwingen, ohne dass der Digest es deckt.
#[cfg(debug_assertions)]
fn fake_bericht(order: &ExecutionOrderV1) -> ExecutionReportV1 {
    let szenario = order
        .canonical_payload
        .get("__fake_outcome")
        .and_then(|w| w.as_str())
        .unwrap_or("applied");

    let basis = |outcome: &str,
                 send: bool,
                 saves: u32,
                 readback: &str,
                 fehler: Option<&str>| ExecutionReportV1 {
        schema_version: EXECUTION_SCHEMA_VERSION,
        operation_id: order.operation_id.clone(),
        mutation_id: order.mutation_id.clone(),
        operation_type: order.operation_type.clone(),
        outcome: outcome.into(),
        send_attempted: send,
        save_request_count: saves,
        readback_status: readback.into(),
        // Der Fake erfindet weder Kennung noch gelesenen Zustand.
        provider_identifier: None,
        readback_contact: None,
        // Nie eine echte Providerkennung: der Fake erfindet keine Identitaet,
        // er markiert sich als Fake.
        provider_identifier_digest: if outcome == "applied" {
            Some(sha256_hex(&format!("fake:{}", order.operation_id)))
        } else {
            None
        },
        readback_revision: None,
        readback_digest: if readback == "confirmed" {
            Some(sha256_hex(&format!("fake-readback:{}", order.operation_id)))
        } else {
            None
        },
        error_class: fehler.map(|f| f.to_string()),
        error_digest: fehler.map(|f| sha256_hex(f)),
        diagnostic_artifact_present: false,
        provider_completed_at: if send {
            Some("2026-08-03T00:00:00+00:00".into())
        } else {
            None
        },
    };

    match szenario {
        "not_applied_before_send" => {
            basis("not_sent", false, 0, "not_attempted", Some("container_unavailable"))
        }
        "outcome_unknown_after_send" => {
            basis("outcome_unknown", true, 1, "not_attempted", Some("response_lost"))
        }
        "readback_failed_after_send" => {
            basis("outcome_unknown", true, 1, "failed", Some("readback_failed"))
        }
        "provider_exception_after_send" => {
            basis("outcome_unknown", true, 1, "not_attempted", Some("provider_exception"))
        }
        _ => basis("applied", true, 1, "confirmed", None),
    }
}

#[cfg(not(debug_assertions))]
fn fake_bericht(order: &ExecutionOrderV1) -> ExecutionReportV1 {
    // Im Release existiert kein Fake — der Zweig ist auskompiliert.
    ExecutionReportV1::not_sent(order, "provider_channel_disabled_before_send")
}

#[cfg(debug_assertions)]
fn fake_kanal_aktiv() -> bool {
    std::env::var(FAKE_ENV_VAR).map(|w| w == "1").unwrap_or(false)
}

#[cfg(not(debug_assertions))]
fn fake_kanal_aktiv() -> bool {
    // Release: keine Umgebungsvariable kann den Kanal oeffnen.
    false
}

/// Führt einen Ausführungsauftrag aus — in Phase A **ohne** Providerkontakt.
pub fn execute_order(roh: &str) -> ExecutionReportV1 {
    if roh.len() > MAX_ORDER_BYTES {
        return ExecutionReportV1::ungebunden("schema_mismatch");
    }
    let order: ExecutionOrderV1 = match serde_json::from_str(roh) {
        Ok(o) => o,
        Err(_) => return ExecutionReportV1::ungebunden("schema_mismatch"),
    };
    if let Err(klasse) = validiere(&order) {
        return ExecutionReportV1::not_sent(&order, klasse);
    }
    // Der produktive Weg zuerst: Liegt eine gueltige Schreibfreigabe vor,
    // fuehrt `create` nativ aus — genau ein Save, kein zweiter Versuch.
    // Ohne Freigabe faellt der Aufruf durch und endet weiter unten
    // fail-closed. Der Fake ist damit nie eine Alternative zum echten Weg,
    // sondern nur das, was uebrig bleibt, wenn es keinen echten gibt.
    #[cfg(target_os = "macos")]
    if order.operation_type == "create" {
        let jetzt = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        if crate::contacts_create::write_release_erlaubt(
            &crate::contacts_create::default_release_path(), "create", jetzt)
        {
            return crate::contacts_create::fuehre_create_aus(&order, jetzt);
        }
    }

    if !fake_kanal_aktiv() {
        // Der Normalfall dieses Stands: Transport steht, Provider nicht.
        return ExecutionReportV1::not_sent(
            &order, "provider_channel_disabled_before_send");
    }
    fake_bericht(&order)
}

/// Baut einen minimalen, gueltigen Auftrag fuer Tests anderer Module.
///
/// Er liegt hier, weil hier die kanonische Digestbildung liegt: ein
/// Testauftrag, dessen Digest nicht traegt, wuerde am eigentlichen Punkt
/// vorbeipruefen.
#[cfg(test)]
pub fn testhilfe_order(
    operation_type: &str,
    canonical_payload: serde_json::Value,
) -> ExecutionOrderV1 {
    let mut ziel = BTreeMap::new();
    ziel.insert("container_identifier".to_string(), Some("C-TEST".to_string()));
    ExecutionOrderV1 {
        schema_version: EXECUTION_SCHEMA_VERSION,
        operation_id: "0".repeat(36),
        mutation_id: "1".repeat(36),
        claim_token: "a".repeat(64),
        operation_type: operation_type.into(),
        payload_digest: payload_digest(&canonical_payload),
        preview_digest: "c".repeat(64),
        canonical_payload,
        readback_requirements: serde_json::json!({"required": true}),
        issued_at: "2026-08-04T00:00:00+00:00".into(),
        expires_at: "2026-08-04T00:10:00+00:00".into(),
        mutation_contract_version: 1,
        field_contract_version: 1,
        transaction_author: "de.kluender.jarvis.contacts-bridge".into(),
        expected_revision: None,
        provider_target: ziel,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, OnceLock};

    /// Die Gate-Tests teilen sich eine Prozess-Umgebungsvariable; ohne
    /// Serialisierung setzt der eine, was der andere gerade loescht.
    fn gate_sperre() -> std::sync::MutexGuard<'static, ()> {
        static SPERRE: OnceLock<Mutex<()>> = OnceLock::new();
        SPERRE
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|vergiftet| vergiftet.into_inner())
    }

    fn auftrag(payload: serde_json::Value) -> String {
        let digest = payload_digest(&payload);
        serde_json::json!({
            "schema_version": 1,
            "operation_id": "0".repeat(36),
            "mutation_id": "1".repeat(36),
            "claim_token": "a".repeat(64),
            "operation_type": "create",
            "payload_digest": digest,
            "preview_digest": "b".repeat(64),
            "canonical_payload": payload,
            "readback_requirements": {"required": true, "keys": "field_contract_v1"},
            "issued_at": "2026-08-03T00:00:00+00:00",
            "expires_at": "2026-08-03T00:10:00+00:00",
            "mutation_contract_version": 1,
            "field_contract_version": 1,
            "transaction_author": "de.kluender.jarvis.contacts-bridge",
            "expected_revision": null,
            "provider_target": {"container_identifier": "C1"}
        })
        .to_string()
    }

    #[test]
    fn kanonische_form_sortiert_und_verdichtet() {
        let wert = serde_json::json!({"b": 1, "a": {"z": [1, 2], "y": "ä"}});
        assert_eq!(canonical_json(&wert), r#"{"a":{"y":"ä","z":[1,2]},"b":1}"#);
    }

    #[test]
    fn goldene_vektoren_stimmen_mit_dem_kern_ueberein() {
        // Aus `base/digest.canonical_json` erzeugt; eine Abweichung hier
        // bedeutet, dass Rust und Kern verschiedene Digests bilden.
        let faelle: [(serde_json::Value, &str); 3] = [
            (serde_json::json!({}), "{}"),
            (serde_json::json!({"a": null, "b": ""}), r#"{"a":null,"b":""}"#),
            (
                serde_json::json!({"fields": {"emails": [{"label": "home", "value": "a@b.invalid"}]}}),
                r#"{"fields":{"emails":[{"label":"home","value":"a@b.invalid"}]}}"#,
            ),
        ];
        for (wert, erwartet) in faelle {
            assert_eq!(canonical_json(&wert), erwartet);
        }
    }

    #[test]
    fn ohne_gate_ist_der_kanal_geschlossen() {
        let _sperre = gate_sperre();
        std::env::remove_var(FAKE_ENV_VAR);
        let bericht = execute_order(&auftrag(serde_json::json!({"fields": {}})));
        assert_eq!(bericht.outcome, "not_sent");
        assert!(!bericht.send_attempted);
        assert_eq!(bericht.save_request_count, 0);
        assert_eq!(
            bericht.error_class.as_deref(),
            Some("provider_channel_disabled_before_send")
        );
    }

    #[test]
    fn manipulierter_payload_wird_erkannt() {
        let _sperre = gate_sperre();
        std::env::remove_var(FAKE_ENV_VAR);
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag(serde_json::json!({"fields": {}}))).unwrap();
        roh["canonical_payload"] = serde_json::json!({"fields": {"given_name": "Fremd"}});
        let bericht = execute_order(&roh.to_string());
        assert_eq!(bericht.error_class.as_deref(), Some("digest_mismatch"));
        assert!(!bericht.send_attempted);
    }

    #[test]
    fn unbekanntes_feld_wird_abgewiesen() {
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag(serde_json::json!({"fields": {}}))).unwrap();
        roh["heimlich"] = serde_json::json!("wert");
        let bericht = execute_order(&roh.to_string());
        assert_eq!(bericht.error_class.as_deref(), Some("schema_mismatch"));
    }

    #[test]
    fn fremde_schemaversion_wird_abgewiesen() {
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag(serde_json::json!({"fields": {}}))).unwrap();
        roh["schema_version"] = serde_json::json!(2);
        let bericht = execute_order(&roh.to_string());
        assert_eq!(bericht.error_class.as_deref(), Some("schema_mismatch"));
    }

    #[test]
    fn groessenlimit_wird_durchgesetzt() {
        let riesig = "x".repeat(MAX_ORDER_BYTES + 1);
        let bericht = execute_order(&riesig);
        assert_eq!(bericht.error_class.as_deref(), Some("schema_mismatch"));
        assert!(!bericht.send_attempted);
    }

    #[test]
    fn ungueltiges_claim_token_wird_abgewiesen() {
        let mut roh: serde_json::Value =
            serde_json::from_str(&auftrag(serde_json::json!({"fields": {}}))).unwrap();
        roh["claim_token"] = serde_json::json!("zu-kurz");
        let bericht = execute_order(&roh.to_string());
        assert_eq!(bericht.error_class.as_deref(), Some("invalid_claim"));
    }

    #[cfg(debug_assertions)]
    #[test]
    fn alle_fuenf_fake_ausgaenge_sind_deterministisch() {
        let _sperre = gate_sperre();
        std::env::set_var(FAKE_ENV_VAR, "1");
        let faelle = [
            ("applied", "applied", true, 1u32),
            ("not_applied_before_send", "not_sent", false, 0),
            ("outcome_unknown_after_send", "outcome_unknown", true, 1),
            ("readback_failed_after_send", "outcome_unknown", true, 1),
            ("provider_exception_after_send", "outcome_unknown", true, 1),
        ];
        for (szenario, erwartet, send, saves) in faelle {
            let payload = serde_json::json!({"fields": {}, "__fake_outcome": szenario});
            let erst = execute_order(&auftrag(payload.clone()));
            let zweit = execute_order(&auftrag(payload));
            assert_eq!(erst.outcome, erwartet, "{szenario}");
            assert_eq!(erst.send_attempted, send, "{szenario}");
            assert_eq!(erst.save_request_count, saves, "{szenario}");
            // Deterministisch: zweimal derselbe Auftrag, zweimal dasselbe.
            assert_eq!(erst, zweit, "{szenario}");
        }
        std::env::remove_var(FAKE_ENV_VAR);
    }

    #[cfg(debug_assertions)]
    #[test]
    fn der_fake_erfindet_keine_echte_providerkennung() {
        let _sperre = gate_sperre();
        std::env::set_var(FAKE_ENV_VAR, "1");
        let bericht = execute_order(&auftrag(serde_json::json!({"fields": {}})));
        // Nur ein Digest ueber "fake:<operation_id>" — nie eine Apple-Kennung.
        assert_eq!(
            bericht.provider_identifier_digest,
            Some(sha256_hex(&format!("fake:{}", "0".repeat(36))))
        );
        std::env::remove_var(FAKE_ENV_VAR);
    }

    #[test]
    fn der_quelltext_enthaelt_keinen_contacts_schreibcode() {
        // Nur der Produktivteil vor dem Testblock: Die Verbotsliste selbst
        // enthaelt die Begriffe naturgemaess.
        let ganze_datei = include_str!("contacts_execution.rs");
        let produktiv = ganze_datei
            .split("#[cfg(test)]")
            .next()
            .expect("Produktivteil");
        // Kommentarzeilen raus: Der Dateikopf nennt die Begriffe als
        // Verbot, nicht als Aufruf.
        let quelle: String = produktiv
            .lines()
            .filter(|z| !z.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        for verboten in [
            "CNSaveRequest",
            "CNMutableContact",
            "addContact",
            "executeSaveRequest",
            "CNContactStore",
        ] {
            assert!(!quelle.contains(verboten), "{verboten} im Phase-A-Kanal");
        }
    }
}
