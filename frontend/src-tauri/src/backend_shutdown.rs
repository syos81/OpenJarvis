//! Geordnetes Beenden der von Jarvis gestarteten Backend-Prozessgruppen.
//!
//! Der behobene Fehler (zehnfach live reproduziert, x86_64/macOS 12.7.6)
//! -------------------------------------------------------------------
//! `ExitRequested` spawnte `stop_all()` nur asynchron, ohne den App-Exit
//! anzuhalten — der Task verlor das Rennen gegen das Prozessende. Zusätzlich
//! kannte der `ChildHandle` nur das **direkte** Kind (`uv` bzw. `ollama`);
//! `jarvis serve` läuft aber als Enkel (`uv → python3`) und überlebte selbst
//! einen gelungenen Kill des Kindes. Ergebnis: ein verwaister Backendprozess
//! auf Port 8000, der nach jedem App-Ende von Hand per SIGTERM beendet werden
//! musste.
//!
//! Der Vertrag dieses Moduls
//! -------------------------
//! * Jedes Backend-Kind startet in einer **eigenen Unix-Prozessgruppe**
//!   (`process_group(0)`: das Kind wird Gruppenleiter, PGID == Kind-PID).
//!   Direkte und indirekte Kinder erben die Gruppe; Jarvis selbst gehört ihr
//!   nie an.
//! * Beendet wird ausschließlich über die **gespeicherte** PGID des selbst
//!   gestarteten Kindes — nie über Prozessnamen, nie per `pkill`, nie anhand
//!   des Portinhabers. Ein fremder Prozess kann nicht getroffen werden.
//! * Ablauf: SIGTERM an die Gruppe → begrenztes Warten → SIGKILL an exakt
//!   dieselbe Gruppe → Leader reapen. `ESRCH` („keine solche Gruppe") ist an
//!   jeder Stelle ein **erfolgreicher Endzustand**, kein Fehler.
//! * PGID-Wiederverwendung: zwischen Signal und Prüfung wird ausschließlich
//!   die beim Start gemerkte Gruppe des eigenen, noch nicht gereapten Leaders
//!   verwendet; nach dem Reap wird die PGID nie wieder angefasst.

use std::time::{Duration, Instant};

/// SIGTERM-Frist, bevor SIGKILL folgt. uvicorn/FastAPI beendet auf SIGTERM
/// regulär in unter zwei Sekunden; acht Sekunden decken langsame Teardowns
/// (Modell-Unload, offene Verbindungen), ohne den App-Exit spürbar minutenlang
/// zu blockieren. Zusammen mit dem KILL-Reap bleibt der Exit unter ~10 s.
pub const TERM_TIMEOUT: Duration = Duration::from_secs(8);

/// Abfrageintervall während des Wartens.
const POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Ausgang eines Gruppen-Shutdowns — alle drei sind Erfolgszustände.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GroupShutdown {
    /// Die Gruppe endete innerhalb der SIGTERM-Frist.
    Exited,
    /// Die Gruppe musste per SIGKILL beendet werden.
    Killed,
    /// Es gab nichts zu beenden (nie gestartet oder bereits vollständig weg).
    AlreadyGone,
}

#[cfg(unix)]
fn signal_group(pgid: i32, signal: i32) -> Result<(), std::io::Error> {
    // SAFETY: `killpg` ist ein einfacher Syscall auf eine explizit
    // übergebene, von uns gestartete Gruppe. Kein Speicherzugriff.
    let rc = unsafe { libc::killpg(pgid, signal) };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

/// Lebt in der Gruppe noch irgendein Prozess? Signal 0 prüft, ohne zu senden.
/// `ESRCH` heißt: die Gruppe ist vollständig leer — auch alle Enkel sind weg.
#[cfg(unix)]
fn group_alive(pgid: i32) -> bool {
    signal_group(pgid, 0).is_ok()
}

/// Beendet die Prozessgruppe eines von uns gestarteten Kindes.
///
/// `child` ist der Gruppenleiter (gestartet mit `process_group(0)`); seine
/// PID ist die PGID. Gearbeitet wird ausschließlich mit dieser gespeicherten
/// Kennung — niemals mit Namen oder Portinhabern.
#[cfg(unix)]
pub async fn terminate_group(
    child: &mut tokio::process::Child,
    term_timeout: Duration,
) -> GroupShutdown {
    let Some(pid) = child.id() else {
        // Leader bereits gereaped: es kann keine gespeicherte Gruppe mehr
        // geben, auf die zu warten wäre.
        return GroupShutdown::AlreadyGone;
    };
    let pgid = pid as i32;

    // SIGTERM an die ganze Gruppe — trifft uv UND python3 samt Enkeln.
    let already_gone = matches!(
        signal_group(pgid, libc::SIGTERM),
        Err(ref e) if e.raw_os_error() == Some(libc::ESRCH)
    );

    // Begrenzt warten, bis die GRUPPE leer ist (nicht nur der Leader).
    let deadline = Instant::now() + term_timeout;
    loop {
        // Leader reapen, sobald er fällt — sonst bliebe er Zombie und die
        // Gruppe gälte fälschlich als lebendig.
        let _ = child.try_wait();
        if !group_alive(pgid) {
            let _ = child.wait().await;
            return if already_gone {
                GroupShutdown::AlreadyGone
            } else {
                GroupShutdown::Exited
            };
        }
        if Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }

    // Frist verstrichen: SIGKILL an exakt dieselbe Gruppe.
    let _ = signal_group(pgid, libc::SIGKILL);
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let _ = child.try_wait();
        if !group_alive(pgid) {
            break;
        }
        if Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
    let _ = child.wait().await;
    GroupShutdown::Killed
}

// ---------------------------------------------------------------------------
// Shutdown-Zustandsmaschine des App-Exits
// ---------------------------------------------------------------------------

/// `running → shutting_down → completed`, ohne Rückweg. Sie stellt sicher,
/// dass der Shutdown genau einmal läuft, parallele Exit-Ereignisse idempotent
/// bleiben und der App-Exit erst nach abgeschlossenem `stop_all` fortgesetzt
/// wird.
pub mod phase {
    use std::sync::atomic::{AtomicU8, Ordering};

    pub const RUNNING: u8 = 0;
    pub const SHUTTING_DOWN: u8 = 1;
    pub const COMPLETED: u8 = 2;

    static PHASE: AtomicU8 = AtomicU8::new(RUNNING);

    /// Was der `ExitRequested`-Handler mit diesem Ereignis tun soll.
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub enum ExitDecision {
        /// Exit anhalten und den (einen) Shutdown starten.
        BeginShutdown,
        /// Exit anhalten — ein Shutdown läuft bereits.
        WaitForShutdown,
        /// Shutdown ist fertig — den Exit jetzt durchlassen.
        AllowExit,
    }

    pub fn on_exit_requested() -> ExitDecision {
        match PHASE.compare_exchange(
            RUNNING,
            SHUTTING_DOWN,
            Ordering::SeqCst,
            Ordering::SeqCst,
        ) {
            Ok(_) => ExitDecision::BeginShutdown,
            Err(SHUTTING_DOWN) => ExitDecision::WaitForShutdown,
            _ => ExitDecision::AllowExit,
        }
    }

    pub fn mark_completed() {
        PHASE.store(COMPLETED, Ordering::SeqCst);
    }

    /// Backendstarts sind nur im Normalbetrieb zulässig — nie während oder
    /// nach einem Shutdown.
    pub fn start_allowed() -> bool {
        PHASE.load(Ordering::SeqCst) == RUNNING
    }

    #[cfg(test)]
    pub fn reset_for_test() {
        PHASE.store(RUNNING, Ordering::SeqCst);
    }
}

// ---------------------------------------------------------------------------
// serve.lock-Bereinigung
// ---------------------------------------------------------------------------

/// Löscht die `serve.lock` des Personal-Backends — aber nur, wenn die darin
/// genannte PID nachweislich zu **unserer** Backendgruppe gehört (vor dem
/// Signal erhoben) oder nicht mehr existiert. Eine Lock-Datei eines fremden
/// oder unklaren Prozesses bleibt unangetastet.
#[cfg(unix)]
pub fn lock_pid_belongs_to_group(lock_path: &std::path::Path, pgid: i32) -> bool {
    let Ok(text) = std::fs::read_to_string(lock_path) else {
        return false;
    };
    // Format: {"pid":12345,...} — bewusst ohne JSON-Abhängigkeit gelesen.
    let Some(pid) = text
        .split("\"pid\":")
        .nth(1)
        .and_then(|s| {
            s.chars()
                .take_while(|c| c.is_ascii_digit())
                .collect::<String>()
                .parse::<i32>()
                .ok()
        })
    else {
        return false;
    };
    // SAFETY: reiner Syscall mit Wertparameter.
    let lock_pgid = unsafe { libc::getpgid(pid) };
    lock_pgid == pgid
}

#[cfg(unix)]
pub fn cleanup_serve_lock(lock_path: &std::path::Path, owned: bool) {
    if owned {
        let _ = std::fs::remove_file(lock_path);
    }
}

/// Pfad der Personal-Backend-Lockdatei — dieselbe, die `jarvis serve` anlegt.
pub fn serve_lock_path() -> Option<std::path::PathBuf> {
    std::env::var_os("HOME").map(|h| {
        std::path::PathBuf::from(h)
            .join(".openjarvis")
            .join("personal")
            .join("serve.lock")
    })
}

// ---------------------------------------------------------------------------
// Tests — kontaktfrei, datenbankfrei, nur eigene Wegwerf-Kindprozesse
// ---------------------------------------------------------------------------

#[cfg(all(test, unix))]
mod tests {
    use super::phase::{self, ExitDecision};
    use super::*;

    /// Die Phase ist prozessglobal — Tests, die sie veraendern, laufen
    /// serialisiert, sonst racen sie im parallelen Test-Runner.
    static PHASE_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn spawn_group(script: &str) -> tokio::process::Child {
        let mut cmd = tokio::process::Command::new("/bin/sh");
        cmd.arg("-c").arg(script);
        cmd.process_group(0);
        cmd.stdout(std::process::Stdio::null());
        cmd.stderr(std::process::Stdio::null());
        cmd.spawn().expect("spawn test child")
    }

    fn my_pgid() -> i32 {
        // SAFETY: reiner Syscall.
        unsafe { libc::getpgid(0) }
    }

    // ═══ A · Prozessgruppe ══════════════════════════════════════════════════
    #[tokio::test]
    async fn child_runs_in_its_own_group_without_us() {
        let mut child = spawn_group("sleep 30");
        let pid = child.id().expect("pid") as i32;
        // SAFETY: reiner Syscall.
        let child_pgid = unsafe { libc::getpgid(pid) };
        assert_eq!(child_pgid, pid, "Kind ist Gruppenleiter");
        assert_ne!(child_pgid, my_pgid(), "Testprozess gehoert nicht dazu");
        let out = terminate_group(&mut child, Duration::from_secs(2)).await;
        assert_eq!(out, GroupShutdown::Exited);
    }

    // ═══ B · Normales Ende beendet auch den Enkel ═══════════════════════════
    #[tokio::test]
    async fn sigterm_ends_direct_child_and_grandchild() {
        // sh startet einen Enkel-sh; beide erben die Gruppe.
        let mut child = spawn_group("/bin/sh -c 'sleep 30' & sleep 30");
        let pgid = child.id().expect("pid") as i32;
        tokio::time::sleep(Duration::from_millis(200)).await;
        assert!(group_alive(pgid));
        let out = terminate_group(&mut child, Duration::from_secs(3)).await;
        assert_eq!(out, GroupShutdown::Exited);
        // Die GRUPPE ist leer — der Enkel ist mitgestorben.
        assert!(!group_alive(pgid));
    }

    // ═══ C · Erzwungenes Ende ═══════════════════════════════════════════════
    #[tokio::test]
    async fn sigkill_follows_when_sigterm_is_ignored() {
        let mut child = spawn_group("trap '' TERM; sleep 30");
        tokio::time::sleep(Duration::from_millis(300)).await; // trap installiert
        let pgid = child.id().expect("pid") as i32;
        let out = terminate_group(&mut child, Duration::from_millis(400)).await;
        assert_eq!(out, GroupShutdown::Killed);
        assert!(!group_alive(pgid));
    }

    // ═══ D · Idempotenz ═════════════════════════════════════════════════════
    #[tokio::test]
    async fn second_shutdown_call_is_a_noop() {
        let mut child = spawn_group("sleep 30");
        let first = terminate_group(&mut child, Duration::from_secs(2)).await;
        assert_eq!(first, GroupShutdown::Exited);
        let second = terminate_group(&mut child, Duration::from_secs(2)).await;
        assert_eq!(second, GroupShutdown::AlreadyGone);
    }

    #[test]
    fn exit_phase_runs_shutdown_exactly_once() {
        let _wache = PHASE_TEST_LOCK.lock().unwrap();
        phase::reset_for_test();
        assert_eq!(phase::on_exit_requested(), ExitDecision::BeginShutdown);
        // Paralleles zweites Ereignis waehrend des Shutdowns:
        assert_eq!(phase::on_exit_requested(), ExitDecision::WaitForShutdown);
        assert!(!phase::start_allowed());
        phase::mark_completed();
        // Der vom Shutdown ausgeloeste Exit wird durchgelassen:
        assert_eq!(phase::on_exit_requested(), ExitDecision::AllowExit);
        assert_eq!(phase::on_exit_requested(), ExitDecision::AllowExit);
        phase::reset_for_test();
    }

    // ═══ E · Bereits beendet ════════════════════════════════════════════════
    #[tokio::test]
    async fn already_dead_child_is_not_an_error() {
        let mut child = spawn_group("true");
        tokio::time::sleep(Duration::from_millis(300)).await;
        let out = terminate_group(&mut child, Duration::from_secs(1)).await;
        assert!(matches!(
            out,
            GroupShutdown::AlreadyGone | GroupShutdown::Exited
        ));
    }

    // ═══ F · Kein Kill nach Namen oder Port ═════════════════════════════════
    #[test]
    fn shutdown_never_targets_by_name_or_port() {
        let source = include_str!("backend_shutdown.rs");
        // Nur CODE zaehlt — die Doku-Kommentare benennen die Verbote ja.
        let produkt: String = source
            .split("mod tests")
            .next()
            .expect("produkt")
            .lines()
            .map(|l| l.split("//").next().unwrap_or(""))
            .collect::<Vec<_>>()
            .join("\n");
        for verboten in ["pkill", "killall", "pgrep", "lsof", "netstat"] {
            assert!(!produkt.contains(verboten), "{verboten}");
        }
        // Signale gehen ausschliesslich an die uebergebene PGID.
        assert!(produkt.contains("libc::killpg"));
    }

    // ═══ G · Start waehrend Shutdown ════════════════════════════════════════
    #[test]
    fn backend_start_is_refused_during_shutdown() {
        let _wache = PHASE_TEST_LOCK.lock().unwrap();
        phase::reset_for_test();
        assert!(phase::start_allowed());
        let _ = phase::on_exit_requested();
        assert!(!phase::start_allowed());
        phase::mark_completed();
        assert!(!phase::start_allowed());
        phase::reset_for_test();
    }

    // ═══ H · Lock-Datei ═════════════════════════════════════════════════════
    #[tokio::test]
    async fn serve_lock_is_cleaned_only_for_our_group() {
        let dir = std::env::temp_dir().join(format!(
            "jc-lifecycle-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let lock = dir.join("serve.lock");

        // Eigenes Gruppen-Kind: seine PID im Lock → gehoert uns.
        let mut child = spawn_group("sleep 30");
        let pid = child.id().unwrap() as i32;
        std::fs::write(&lock, format!("{{\"pid\":{pid},\"port\":null}}")).unwrap();
        assert!(lock_pid_belongs_to_group(&lock, pid));
        // Fremde PID (unser Testprozess): gehoert NICHT zur Kindgruppe.
        std::fs::write(
            &lock,
            format!("{{\"pid\":{},\"port\":null}}", std::process::id()),
        )
        .unwrap();
        assert!(!lock_pid_belongs_to_group(&lock, pid));
        cleanup_serve_lock(&lock, false);
        assert!(lock.exists(), "fremde Lock bleibt");
        cleanup_serve_lock(&lock, true);
        assert!(!lock.exists(), "eigene Lock wird entfernt");

        let _ = terminate_group(&mut child, Duration::from_secs(2)).await;
        let _ = std::fs::remove_dir_all(&dir);
    }
}
