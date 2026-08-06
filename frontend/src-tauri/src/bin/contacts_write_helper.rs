// Der opferbare Schreibhelfer (ADR-0026-Nachtrag 2026-08-04).
//
// **Warum es diesen Prozess gibt.** Der Intel-Livetest vom 2026-08-04 hat
// die Grundannahme von ADR-0026 §10 widerlegt: Auch im GUI-Prozess kann
// `executeSaveRequest:` mit einer CoreData-Ausnahme sterben, die innerhalb
// von `performBlockAndWait` geworfen wird, die Dispatch-Grenze überquert
// und deshalb von keinem `@try/@catch` erreichbar ist — `std::terminate`,
// SIGABRT, die ganze App weg. Wenn der Save also grundsätzlich tödlich sein
// kann, muss er in einem Prozess laufen, dessen Tod nichts kostet.
//
// **Der Vertrag dieses Prozesses:**
//
// * Genau **eine** ExecutionOrder je Prozess — von stdin, größenbegrenzt.
// * Read-only-Preflight, höchstens **ein** CNSaveRequest (erzwungen vom
//   Shim, den sich dieser Helfer mit der Bibliothek teilt).
// * Genau **ein** Bericht — nach stdout, dann Ende. Kein Retry, keine
//   Schleife, kein zweiter Versuch: das Sterben ist eingeplant.
// * Der `save_started`-Marker (Umgebung, von der GUI gestellt) entsteht im
//   Shim unmittelbar vor der Übergabe. Stirbt dieser Prozess, liest die
//   GUI aus dem Marker die einzige Wahrheit, die dann noch existiert.
// * Gestartet wird er ausschließlich von der Tauri-App (posix_spawn über
//   `std::process::Command` — **kein** fork aus dem laufenden GUI-Prozess).
//   Die TCC-Verantwortung erbt er von ihr.
//
// Alle Torwächter (Schreibfreigabe-Datei, Digest, Feldvorrat, Vorzustand)
// laufen hier **erneut** — der Helfer vertraut der GUI nicht.

use std::io::Read;

fn main() {
    std::process::exit(lauf());
}

fn lauf() -> i32 {
    // Eine Order, größenbegrenzt — dieselbe Grenze wie im Kanalvertrag.
    let mut roh = String::new();
    let mut begrenzt = std::io::stdin()
        .take(openjarvis_desktop::contacts_execution::MAX_ORDER_BYTES as u64 + 1);
    if begrenzt.read_to_string(&mut roh).is_err() {
        eprintln!("contacts-write-helper: stdin unlesbar");
        return 2;
    }
    if roh.len() > openjarvis_desktop::contacts_execution::MAX_ORDER_BYTES {
        eprintln!("contacts-write-helper: Order über dem Limit");
        return 2;
    }

    let order: openjarvis_desktop::contacts_execution::ExecutionOrderV1 =
        match serde_json::from_str(&roh) {
            Ok(o) => o,
            Err(_) => {
                eprintln!("contacts-write-helper: Order unparsbar");
                return 2;
            }
        };

    let jetzt = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);

    #[cfg(target_os = "macos")]
    let bericht = match order.operation_type.as_str() {
        "create" => openjarvis_desktop::contacts_create::fuehre_create_aus(&order, jetzt),
        "update" => openjarvis_desktop::contacts_create::fuehre_update_aus(&order, jetzt),
        "delete" => openjarvis_desktop::contacts_create::fuehre_delete_aus(&order, jetzt),
        _ => openjarvis_desktop::contacts_execution::ExecutionReportV1::not_sent(
            &order, "schema_mismatch"),
    };
    #[cfg(not(target_os = "macos"))]
    let bericht = openjarvis_desktop::contacts_execution::ExecutionReportV1::not_sent(
        &order, "provider_channel_disabled_before_send");

    match serde_json::to_string(&bericht) {
        Ok(json) => {
            println!("{json}");
            0
        }
        Err(_) => 3,
    }
}
