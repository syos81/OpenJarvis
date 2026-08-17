//! Der Erteilungsweg für die dauerhafte Kontakte-Schreibfreigabe.
//!
//! **Warum hier und nicht im Backend.** Die Python-Routen sind das, was ein
//! Agent aufrufen kann. Läge der Schalter dort, könnte Jarvis sich selbst
//! freischalten — und „kein Self-Grant" wäre ein Satz in einer Datei statt
//! einer Eigenschaft des Systems. Der Schalter lebt deshalb im App-Prozess und
//! ist ausschliesslich über die Oberfläche erreichbar, die der Eigentümer
//! bedient.
//!
//! **Was das belegt und was nicht.** Der vorgesehene Produktweg zum Einschalten
//! verlangt eine interaktive Eigentümerauthentisierung des Betriebssystems.
//! Das ist die gesicherte Aussage. Nicht gesichert — und im Bericht nicht zu
//! behaupten — ist, dass eine Dauerfreigabe *nur* nach Touch ID entstehen
//! kann: Die Freigabedatei liegt im Home des Benutzers und ist von jedem
//! Prozess unter derselben Benutzerkennung schreibbar. Das war vorher so und
//! bleibt so; ein Herkunftsnachweis gegen gleichberechtigte lokale Prozesse
//! ist eine eigene Aufgabe und wird hier nicht vorgetäuscht.
//!
//! Geschrieben wird genau das Dokument, das beide Leser — `write_release.py`
//! und `contacts_create.rs` — als gültig annehmen. Der Schreiber kennt keine
//! Sonderregel; was er erzeugt, muss durch dieselbe Prüfung wie eine von Hand
//! erstellte Urkunde.

use std::io::Write;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::contacts_create::{
    default_release_path, write_release_erlaubt, MODE_STANDING, WRITE_RELEASE_CAPABILITY,
    WRITE_RELEASE_CONTRACT_V2,
};

/// Der Text, den das System im Authentisierungsdialog zeigt. Er nennt die
/// Handlung, nicht das Werkzeug: Wer authentisiert, soll wissen, wofür.
const AUTH_REASON: &str = "das dauerhafte Schreiben in deine Kontakte einzuschalten";

/// Wie lange auf die Entscheidung des Eigentümers gewartet wird. Grosszügig —
/// ein Zeitüberlauf ist ein Nein, und ein zu knappes Fenster erzeugt ein Nein,
/// das niemand gemeint hat.
const AUTH_TIMEOUT_SECONDS: f64 = 120.0;

/// Die Operationen, die der Schalter erteilt.
///
/// **Einzelobjekt-Schreiben, keine Mutationsklasse.** `create` und `update`
/// treffen je genau einen benannten Kontakt. `delete` ist bewusst nicht
/// enthalten: Es hängt am Sicherungsnachweis und wird nicht über einen
/// Dauerschalter erteilt.
const STANDING_OPERATIONS: [&str; 2] = ["create", "update"];

#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct JCOwnerAuthResult {
    pub can_evaluate: i32,
    pub callback_ran: i32,
    pub callback_count: i32,
    pub succeeded: i32,
    pub has_error: i32,
    pub error_code: i64,
    pub biometry_type: i64,
    pub error_domain: [std::os::raw::c_char; 128],
}

impl Default for JCOwnerAuthResult {
    /// Von Hand, weil `[c_char; 128]` kein `Default` hat. Alles null: Der
    /// Vorgabezustand ist „nicht authentisiert", nicht „unbekannt".
    fn default() -> Self {
        Self {
            can_evaluate: 0,
            callback_ran: 0,
            callback_count: 0,
            succeeded: 0,
            has_error: 0,
            error_code: 0,
            biometry_type: 0,
            error_domain: [0; 128],
        }
    }
}

#[cfg(target_os = "macos")]
extern "C" {
    fn jc_owner_auth_available(out: *mut JCOwnerAuthResult) -> i32;
    fn jc_owner_auth_require(
        out: *mut JCOwnerAuthResult,
        reason_utf8: *const std::os::raw::c_char,
        timeout_seconds: f64,
    ) -> i32;
}

/// Ergebnis eines Schaltversuchs — PII-frei und ohne Pfade.
#[derive(Debug, Serialize)]
pub struct StandingWriteState {
    /// Ob im Augenblick eine gültige Dauerfreigabe gilt.
    pub standing: bool,
    /// Die Operationen, die sie erteilt.
    pub operations: Vec<String>,
    /// Warum ein Versuch scheiterte. Geschlossene Kennungen, kein Freitext:
    /// `owner_authentication_failed`, `owner_authentication_unavailable`,
    /// `release_directory_not_private`, `write_failed`, `verification_failed`.
    pub reason_code: Option<String>,
}

impl StandingWriteState {
    fn aus_datei(pfad: &Path, jetzt_unix: i64, reason_code: Option<&str>) -> Self {
        let operations: Vec<String> = STANDING_OPERATIONS
            .iter()
            .filter(|op| write_release_erlaubt(pfad, op, jetzt_unix))
            .map(|op| (*op).to_string())
            .collect();
        Self {
            standing: !operations.is_empty(),
            operations,
            reason_code: reason_code.map(|s| s.to_string()),
        }
    }
}

fn jetzt_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Der aktuelle Zeitpunkt im Vertragsformat — auch fuer den Belegschreiber.
///
/// Eine Stelle fuer die eigenhaendige Zeitrechnung, nicht zwei: Sie ist die
/// unangenehmste Zeile in diesem Modul und wird an genau einem Ort geprueft.
pub fn iso_jetzt_oeffentlich() -> String {
    iso_jetzt(jetzt_unix())
}

fn iso_jetzt(jetzt: i64) -> String {
    // Nur so viel Zeitrechnung wie nötig — dasselbe Format, das der Kern
    // schreibt und beide Leser erwarten.
    let tage = jetzt.div_euclid(86_400);
    let rest = jetzt.rem_euclid(86_400);
    let (stunde, minute, sekunde) = (rest / 3600, (rest % 3600) / 60, rest % 60);

    // Howard Hinnants `civil_from_days`.
    let z = tage + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let tag = doy - (153 * mp + 2) / 5 + 1;
    let monat = if mp < 10 { mp + 3 } else { mp - 9 };
    let jahr = if monat <= 2 { y + 1 } else { y };

    format!(
        "{jahr:04}-{monat:02}-{tag:02}T{stunde:02}:{minute:02}:{sekunde:02}Z"
    )
}

/// Das Verzeichnis muss dem Benutzer gehören und 0700 sein — dieselbe
/// Bedingung, die beide Leser stellen. Ohne sie erzeugte der Schalter ein
/// Dokument, das nie gilt: ein stiller Fehlschlag.
fn verzeichnis_ist_privat(verzeichnis: &Path) -> bool {
    let Ok(meta) = std::fs::symlink_metadata(verzeichnis) else {
        return false;
    };
    meta.is_dir()
        && meta.permissions().mode() & 0o777 == 0o700
        && meta.uid() == unsafe { libc::geteuid() }
}

fn urkunde(jetzt: i64) -> String {
    let operationen: Vec<String> = STANDING_OPERATIONS
        .iter()
        .map(|o| format!("\"{o}\""))
        .collect();
    format!(
        concat!(
            "{{\n",
            "  \"contract\": \"{contract}\",\n",
            "  \"capability\": \"{capability}\",\n",
            "  \"mode\": \"{mode}\",\n",
            "  \"operations\": [{operations}],\n",
            "  \"granted_at\": \"{granted_at}\",\n",
            "  \"reason\": \"Im Produkt eingeschaltet nach ",
            "Eigentuemerauthentisierung\"\n",
            "}}\n"
        ),
        contract = WRITE_RELEASE_CONTRACT_V2,
        capability = WRITE_RELEASE_CAPABILITY,
        mode = MODE_STANDING,
        operations = operationen.join(", "),
        granted_at = iso_jetzt(jetzt),
    )
}

/// Schreibt die Urkunde mit 0600 — und zwar von Anfang an.
///
/// `mode(0o600)` beim Öffnen statt `set_permissions` danach: Sonst existierte
/// die Datei einen Augenblick lang mit den Vorgaberechten der Umgebung.
fn urkunde_schreiben(pfad: &Path, inhalt: &str) -> std::io::Result<()> {
    let temporaer = pfad.with_extension("json.neu");
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
    // Ersetzen statt schreiben: Ein abgebrochener Schreibvorgang hinterlässt
    // keine halbe Urkunde, die als ungültig gelesen würde.
    std::fs::rename(&temporaer, pfad)
}

/// Der Zustand, ohne etwas zu ändern.
pub fn standing_state_at(pfad: &Path, jetzt: i64) -> StandingWriteState {
    StandingWriteState::aus_datei(pfad, jetzt, None)
}

/// Einschalten — nur nach interaktiver Eigentümerauthentisierung.
#[cfg(target_os = "macos")]
pub fn enable_at(pfad: &Path, jetzt: i64) -> StandingWriteState {
    let Some(verzeichnis) = pfad.parent() else {
        return StandingWriteState::aus_datei(pfad, jetzt, Some("release_directory_not_private"));
    };
    if !verzeichnis_ist_privat(verzeichnis) {
        return StandingWriteState::aus_datei(pfad, jetzt, Some("release_directory_not_private"));
    }

    let mut ergebnis = JCOwnerAuthResult::default();
    if unsafe { jc_owner_auth_available(&mut ergebnis) } != 1 {
        return StandingWriteState::aus_datei(
            pfad,
            jetzt,
            Some("owner_authentication_unavailable"),
        );
    }

    let Ok(grund) = std::ffi::CString::new(AUTH_REASON) else {
        return StandingWriteState::aus_datei(pfad, jetzt, Some("owner_authentication_failed"));
    };
    let mut ergebnis = JCOwnerAuthResult::default();
    let ja = unsafe { jc_owner_auth_require(&mut ergebnis, grund.as_ptr(), AUTH_TIMEOUT_SECONDS) };
    if ja != 1 {
        // Abbruch, Fehlschlag und Zeitüberlauf sind derselbe Ausgang: aus
        // bleibt aus. Es gibt keinen Zweig, der im Zweifel einschaltet.
        return StandingWriteState::aus_datei(pfad, jetzt, Some("owner_authentication_failed"));
    }

    if urkunde_schreiben(pfad, &urkunde(jetzt)).is_err() {
        return StandingWriteState::aus_datei(pfad, jetzt, Some("write_failed"));
    }

    // Gegenlesen mit demselben Leser, den der Schreibpfad benutzt. Was der
    // Schalter meldet, ist damit nicht seine Absicht, sondern das Ergebnis.
    let zustand = StandingWriteState::aus_datei(pfad, jetzt, None);
    if !zustand.standing {
        return StandingWriteState::aus_datei(pfad, jetzt, Some("verification_failed"));
    }
    zustand
}

/// Ausschalten — ohne Authentisierung.
///
/// Wer abschaltet, verringert Rechte. Dafür eine Hürde zu verlangen hiesse,
/// den sicheren Weg teurer zu machen als den unsicheren.
pub fn disable_at(pfad: &Path, jetzt: i64) -> StandingWriteState {
    match std::fs::remove_file(pfad) {
        Ok(()) => {}
        Err(fehler) if fehler.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return StandingWriteState::aus_datei(pfad, jetzt, Some("write_failed")),
    }
    let zustand = StandingWriteState::aus_datei(pfad, jetzt, None);
    if zustand.standing {
        return StandingWriteState::aus_datei(pfad, jetzt, Some("verification_failed"));
    }
    zustand
}

fn release_path() -> PathBuf {
    default_release_path()
}

// ── Tauri-Kommandos ─────────────────────────────────────────────────────────

#[tauri::command]
pub fn personal_contacts_standing_write_state() -> StandingWriteState {
    standing_state_at(&release_path(), jetzt_unix())
}

#[cfg(target_os = "macos")]
#[tauri::command]
pub async fn personal_contacts_standing_write_enable() -> StandingWriteState {
    // Auf einem Hintergrundthread: der Shim legt den Dialog selbst auf die
    // Main Queue und wartet auf dem Aufrufer. Liefe er hier auf dem Main
    // Thread, zeichnete niemand den Dialog.
    tauri::async_runtime::spawn_blocking(|| enable_at(&release_path(), jetzt_unix()))
        .await
        .unwrap_or_else(|_| StandingWriteState {
            standing: false,
            operations: Vec::new(),
            reason_code: Some("owner_authentication_failed".into()),
        })
}

#[tauri::command]
pub fn personal_contacts_standing_write_disable() -> StandingWriteState {
    disable_at(&release_path(), jetzt_unix())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn privates_verzeichnis(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("jc-standing-{}-{}", name, std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
        dir
    }

    const JETZT: i64 = 1_787_000_000;

    #[test]
    fn die_urkunde_wird_vom_echten_leser_angenommen() {
        // Der Schreiber kennt keine Sonderregel: was er erzeugt, muss durch
        // dieselbe Pruefung wie eine von Hand erstellte Urkunde.
        let dir = privates_verzeichnis("urkunde");
        let pfad = dir.join("contacts-write-release.json");
        urkunde_schreiben(&pfad, &urkunde(JETZT)).unwrap();

        assert!(write_release_erlaubt(&pfad, "create", JETZT));
        assert!(write_release_erlaubt(&pfad, "update", JETZT));
        // Delete haengt am Sicherungsnachweis und wird nie per Dauerschalter
        // erteilt.
        assert!(!write_release_erlaubt(&pfad, "delete", JETZT));
        // Und sie ueberlebt den Neustart: Wochen spaeter gilt sie weiter.
        assert!(write_release_erlaubt(&pfad, "create", JETZT + 97 * 86_400));
    }

    #[test]
    fn die_urkunde_liegt_von_anfang_an_mit_0600() {
        let dir = privates_verzeichnis("rechte");
        let pfad = dir.join("contacts-write-release.json");
        urkunde_schreiben(&pfad, &urkunde(JETZT)).unwrap();
        let modus = std::fs::metadata(&pfad).unwrap().permissions().mode() & 0o777;
        assert_eq!(modus, 0o600, "Rechte muessen 0600 sein, sind {modus:o}");
    }

    #[test]
    fn ausschalten_entfernt_die_freigabe_und_ist_wiederholbar() {
        let dir = privates_verzeichnis("aus");
        let pfad = dir.join("contacts-write-release.json");
        urkunde_schreiben(&pfad, &urkunde(JETZT)).unwrap();
        assert!(standing_state_at(&pfad, JETZT).standing);

        let zustand = disable_at(&pfad, JETZT);
        assert!(!zustand.standing);
        assert!(zustand.operations.is_empty());
        assert!(zustand.reason_code.is_none());
        // Ein zweites Ausschalten ist kein Fehler.
        assert!(disable_at(&pfad, JETZT).reason_code.is_none());
    }

    #[test]
    fn ohne_privates_verzeichnis_wird_nicht_eingeschaltet() {
        let dir = privates_verzeichnis("offen");
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        let pfad = dir.join("contacts-write-release.json");
        let zustand = enable_at(&pfad, JETZT);
        assert!(!zustand.standing);
        assert_eq!(
            zustand.reason_code.as_deref(),
            Some("release_directory_not_private")
        );
        // Und es liegt nichts da: kein Dokument, das nie gelten koennte.
        assert!(!pfad.exists());
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
    }

    #[test]
    fn der_zustand_nennt_genau_die_erteilten_operationen() {
        let dir = privates_verzeichnis("zustand");
        let pfad = dir.join("contacts-write-release.json");
        assert!(!standing_state_at(&pfad, JETZT).standing);

        urkunde_schreiben(&pfad, &urkunde(JETZT)).unwrap();
        let zustand = standing_state_at(&pfad, JETZT);
        assert!(zustand.standing);
        assert_eq!(zustand.operations, vec!["create", "update"]);
    }

    #[test]
    fn die_zeitangabe_ist_die_erwartete_iso_form() {
        assert_eq!(iso_jetzt(1_786_968_000), "2026-08-17T12:00:00Z");
        assert_eq!(iso_jetzt(1_787_140_800), "2026-08-19T12:00:00Z");
        assert_eq!(iso_jetzt(0), "1970-01-01T00:00:00Z");
        // Schaltjahresrand — die Zeitrechnung ist eigenhaendig, also wird sie
        // auch an ihrer unangenehmsten Stelle geprueft.
        assert_eq!(iso_jetzt(1_709_208_000), "2024-02-29T12:00:00Z");
    }
}
