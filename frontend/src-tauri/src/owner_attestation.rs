//! Der Schreiber des Eigentümerbelegs — die andere Hälfte von
//! `personaljarvis/base/owner_attestation.py`.
//!
//! **Warum hier.** Der Kern liest den Beleg, erzeugt ihn aber nie. Läge der
//! Erzeugungsweg im Python-Backend, könnte der Agent ihn über HTTP erreichen —
//! genau die Lücke, die am 2026-08-17 gemessen wurde: 25 von 25 Mutationen
//! liefen mit frei gesetztem `decision_actor` durch. Der Weg lebt deshalb im
//! App-Prozess, aufrufbar nur aus der Fläche, die der Eigentümer bedient.
//!
//! **Was der Beleg bindet.** Vorgang, Nutzlast **und Darstellung**. Die
//! Darstellung gehört dazu, weil der Eigentümer eine Fläche freigibt und
//! keinen Digest: Ändert sich danach die Nutzlast oder die Anzeige, passt der
//! Beleg nicht mehr, und der Kern lehnt ab.
//!
//! **Die Grenze, ausgesprochen.** Gesichert ist: es gibt im Kern, im Backend
//! und in der HTTP-Schicht keinen Codepfad, der einen Beleg erzeugt — der
//! Agent erreicht damit keinen Erzeugungsweg. Nicht gesichert ist, dass nur
//! der Eigentümer einen Beleg schreiben kann: Die Datei liegt in seinem
//! Benutzerordner, und jeder Prozess unter derselben Benutzerkennung kann sie
//! anlegen. Dieselbe Lage wie bei der Freigabedatei und beim Guard —
//! `requires_interactive_owner_authentication`, nicht
//! `technically_impossible`. Ein stärkerer Herkunftsnachweis gegen
//! gleichberechtigte lokale Prozesse ist eine eigene Aufgabe.

use std::io::Write;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

use serde::Serialize;

/// Vertragskennung — wortgleich zu `ATTESTATION_CONTRACT`.
pub const ATTESTATION_CONTRACT: &str = "owner-approval-v1";
/// Verzeichnisname — wortgleich zu `ATTESTATION_DIRNAME`.
pub const ATTESTATION_DIRNAME: &str = "owner-approvals";

/// Wie der Eigentümer gehandelt hat. Protokoll, nicht Nachweis: Der Nachweis
/// ist, dass der Beleg überhaupt aus diesem Prozess kommt.
const METHOD_APP_INTERACTION: &str = "app_interaction";

#[derive(Debug, Serialize)]
pub struct AttestationResult {
    /// Ob ein gültiger Beleg jetzt liegt.
    pub written: bool,
    /// Geschlossene Kennung im Fehlerfall: `attestation_directory_unavailable`,
    /// `invalid_binding`, `write_failed`.
    pub reason_code: Option<String>,
}

impl AttestationResult {
    fn fehler(code: &str) -> Self {
        Self { written: false, reason_code: Some(code.into()) }
    }
}

fn attestation_dir() -> PathBuf {
    let home = std::env::var("OPENJARVIS_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".openjarvis")
        });
    home.join("personal").join(ATTESTATION_DIRNAME)
}

/// Eine Kennung, die in einen Dateinamen darf.
///
/// Eingeschränkt statt bereinigt — dieselbe Regel wie im Kern. Ein Punkt oder
/// ein Schrägstrich wäre ein Ausbruch aus dem Verzeichnis.
fn kennung_ist_zulaessig(wert: &str) -> bool {
    !wert.is_empty()
        && wert.len() <= 64
        && wert.chars().all(|z| z.is_ascii_alphanumeric() || z == '-')
}

fn ist_hex64(wert: &str) -> bool {
    wert.len() == 64 && wert.chars().all(|z| z.is_ascii_hexdigit() && !z.is_ascii_uppercase())
}

/// Legt das Belegverzeichnis an — 0700 vom Anlegen an.
///
/// Der Kern verlangt genau diese Rechte und lehnt sonst ab. Ein Verzeichnis
/// erst anzulegen und dann zu verschärfen liesse einen Augenblick offen.
fn verzeichnis_bereit(ort: &Path) -> bool {
    if let Ok(meta) = std::fs::symlink_metadata(ort) {
        return meta.is_dir()
            && meta.permissions().mode() & 0o777 == 0o700
            && meta.uid() == unsafe { libc::geteuid() };
    }
    let Some(eltern) = ort.parent() else {
        return false;
    };
    if !eltern.is_dir() {
        return false;
    }
    if std::fs::create_dir(ort).is_err() {
        return false;
    }
    std::fs::set_permissions(ort, std::fs::Permissions::from_mode(0o700)).is_ok()
}

fn urkunde(mutation_id: &str, payload_digest: &str, preview_digest: &str,
           jetzt_iso: &str) -> String {
    format!(
        concat!(
            "{{\n",
            "  \"contract\": \"{contract}\",\n",
            "  \"capability\": \"contacts\",\n",
            "  \"mutation_id\": \"{mutation}\",\n",
            "  \"payload_digest\": \"{payload}\",\n",
            "  \"preview_digest\": \"{preview}\",\n",
            "  \"attested_at\": \"{jetzt}\",\n",
            "  \"method\": \"{method}\"\n",
            "}}\n"
        ),
        contract = ATTESTATION_CONTRACT,
        mutation = mutation_id,
        payload = payload_digest,
        preview = preview_digest,
        jetzt = jetzt_iso,
        method = METHOD_APP_INTERACTION,
    )
}

fn schreiben(ort: &Path, inhalt: &str) -> std::io::Result<()> {
    let temporaer = ort.with_extension("json.neu");
    {
        let mut datei = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(&temporaer)?;
        datei.write_all(inhalt.as_bytes())?;
        datei.sync_all()?;
    }
    std::fs::rename(&temporaer, ort)
}

/// Der prüfbare Kern, ohne Tauri und ohne Uhr.
pub fn attestieren_in(verzeichnis: &Path, mutation_id: &str, payload_digest: &str,
                      preview_digest: &str, jetzt_iso: &str) -> AttestationResult {
    // Die Bindung muss vollstaendig sein, bevor irgendetwas entsteht. Ein
    // Beleg ohne sie waere ein Blankoscheck.
    if !kennung_ist_zulaessig(mutation_id)
        || !ist_hex64(payload_digest)
        || !ist_hex64(preview_digest)
    {
        return AttestationResult::fehler("invalid_binding");
    }
    if !verzeichnis_bereit(verzeichnis) {
        return AttestationResult::fehler("attestation_directory_unavailable");
    }
    let ort = verzeichnis.join(format!("{mutation_id}.json"));
    if schreiben(&ort, &urkunde(mutation_id, payload_digest, preview_digest, jetzt_iso))
        .is_err()
    {
        return AttestationResult::fehler("write_failed");
    }
    AttestationResult { written: true, reason_code: None }
}

// ── Tauri-Kommando ──────────────────────────────────────────────────────────

/// Die Eigentümerhandlung: Der Aufruf **ist** die Zustimmung.
///
/// Er ist ausschliesslich aus der Freigabefläche des App-Prozesses erreichbar.
/// Eine zusätzliche Systemauthentifizierung verlangt er bewusst nicht — der
/// sicherheitsentscheidende Punkt ist die Herkunft der Handlung, nicht
/// möglichst häufiges Fingerauflegen. Der Übergang der **Dauerfreigabe** von
/// aus auf an verlangt sie weiterhin.
#[tauri::command]
pub fn personal_contacts_attest_owner_approval(
    mutation_id: String,
    payload_digest: String,
    preview_digest: String,
) -> AttestationResult {
    attestieren_in(
        &attestation_dir(),
        &mutation_id,
        &payload_digest,
        &preview_digest,
        &crate::contacts_standing_write::iso_jetzt_oeffentlich(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    const MUTATION: &str = "11111111-1111-4111-8111-111111111111";
    const PAYLOAD: &str = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90";
    const PREVIEW: &str = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";
    const JETZT: &str = "2026-08-17T12:00:00Z";

    fn ordner(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("jc-beleg-{}-{}", name, std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("owner-approvals")
    }

    #[test]
    fn der_beleg_traegt_vorgang_nutzlast_und_darstellung() {
        let ort = ordner("vollstaendig");
        let ergebnis = attestieren_in(&ort, MUTATION, PAYLOAD, PREVIEW, JETZT);
        assert!(ergebnis.written, "{:?}", ergebnis.reason_code);

        let inhalt = std::fs::read_to_string(ort.join(format!("{MUTATION}.json"))).unwrap();
        for erwartet in [MUTATION, PAYLOAD, PREVIEW, ATTESTATION_CONTRACT, "contacts"] {
            assert!(inhalt.contains(erwartet), "fehlt: {erwartet}");
        }
    }

    #[test]
    fn der_beleg_liegt_von_anfang_an_mit_0600_in_einem_0700_ordner() {
        let ort = ordner("rechte");
        assert!(attestieren_in(&ort, MUTATION, PAYLOAD, PREVIEW, JETZT).written);
        let datei = std::fs::metadata(ort.join(format!("{MUTATION}.json")))
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        let verzeichnis = std::fs::metadata(&ort).unwrap().permissions().mode() & 0o777;
        assert_eq!(datei, 0o600, "Datei {datei:o}");
        assert_eq!(verzeichnis, 0o700, "Verzeichnis {verzeichnis:o}");
    }

    #[test]
    fn eine_unvollstaendige_bindung_erzeugt_keinen_beleg() {
        let ort = ordner("bindung");
        for (mutation, payload, preview) in [
            ("", PAYLOAD, PREVIEW),
            ("../ausbruch", PAYLOAD, PREVIEW),
            ("a/b", PAYLOAD, PREVIEW),
            (MUTATION, "zu-kurz", PREVIEW),
            (MUTATION, PAYLOAD, "zu-kurz"),
            (MUTATION, &PAYLOAD.to_uppercase(), PREVIEW),
        ] {
            let ergebnis = attestieren_in(&ort, mutation, payload, preview, JETZT);
            assert!(!ergebnis.written, "{mutation} {payload} {preview}");
            assert_eq!(ergebnis.reason_code.as_deref(), Some("invalid_binding"));
        }
        // Und es liegt nichts da — auch kein halber Beleg.
        assert!(!ort.exists() || std::fs::read_dir(&ort).unwrap().count() == 0);
    }

    #[test]
    fn ein_zweiter_beleg_ersetzt_den_ersten_statt_daneben_zu_liegen() {
        let ort = ordner("ersetzen");
        assert!(attestieren_in(&ort, MUTATION, PAYLOAD, PREVIEW, JETZT).written);
        assert!(attestieren_in(&ort, MUTATION, PAYLOAD, PREVIEW, JETZT).written);
        let anzahl = std::fs::read_dir(&ort).unwrap().count();
        assert_eq!(anzahl, 1, "es liegen {anzahl} Dateien");
    }
}
