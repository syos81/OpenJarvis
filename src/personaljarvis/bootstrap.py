"""PersonalBootstrap — die einzige Kompositionswurzel je Prozess (04 §1, AV-34).

Die Startreihenfolge folgt 04 §1. In Gate A sind ausschließlich die Schritte
materialisiert, die das Kontakte-Modul zwingend braucht (AV-33):

| 04 §1 | Gate A |
|---|---|
| 1 Prozesssperre | offen — Gate B/C (kein Worker, kein zweiter Schreiber) |
| 2 Konfiguration | Datenbankpfad |
| 3 ConnectionFactory | **umgesetzt** |
| 4 Migrations-Ledger | **umgesetzt, fail-closed** |
| 5 CredentialStore | offen — kein Credential in Gate A |
| 6 Auth | offen — keine Route in Gate A |
| 7 OJRA/Ports | offen — kein Port wird benutzt |
| 8 Basisdienste | offen — keine Outbox, kein Executor |
| 9 Module komponieren | **umgesetzt** (nur Kontakte-Persistenz) |
| 10 Router registrieren | **entfällt** — Gate A hat keine Route |
| 11 Worker starten | **entfällt** |
| 12 Readiness melden | Modul bleibt `configuration_required`, nie `ready` |

**Fail-closed-Regel:** Scheitert Schritt 3 oder 4, startet kein Personal-
Teilbetrieb. Der Fehler wird weitergereicht und **nicht** verschluckt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personaljarvis.base.process_lock import ProcessLock
from personaljarvis.contacts.lifecycle import ContactsModule, ModuleState

__all__ = ["PersonalRuntime", "PersonalBootstrap"]


@dataclass(frozen=True)
class PersonalRuntime:
    """Ergebnis eines erfolgreichen Bootstraps.

    Bewusst klein: In Gate A gibt es genau ein Modul und keine Dienste
    darüber hinaus.
    """

    contacts: ContactsModule

    @property
    def module_states(self) -> dict[str, ModuleState]:
        return {"contacts": self.contacts.state}

    @property
    def is_ready(self) -> bool:
        """Gate A meldet **niemals** `ready` — es gibt weder Route noch Adapter."""
        return False


class PersonalBootstrap:
    """Baut die Personal-Objekte auf und wieder ab."""

    def __init__(self, database_path: Path | str | None = None, *,
                 lock_path: Path | str | None = None,
                 sidecar_path: Path | str | None = None,
                 bundle_dir: Path | str | None = None) -> None:
        self._database_path = database_path
        self._lock_path = lock_path
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir
        self._runtime: PersonalRuntime | None = None
        self._lock: ProcessLock | None = None
        self._recovered: tuple[str, ...] = ()

    @property
    def runtime(self) -> PersonalRuntime | None:
        return self._runtime

    @property
    def process_lock(self) -> ProcessLock | None:
        return self._lock

    def start(self) -> PersonalRuntime:
        """Startet Personal Jarvis. Idempotent bei mehrfachem Aufruf.

        Reihenfolge nach 04 §1: **zuerst** die exklusive Prozesssperre
        (Schritt 1), danach Datenbank und Migrationen. Ein Fehler in Migration
        oder Schema wird **weitergereicht**; es bleibt keine halbfertige
        Registrierung zurück und die Sperre wird in jedem Fehlerfall wieder
        freigegeben.
        """
        if self._runtime is not None:
            return self._runtime

        # Schritt 1 (04 §1): exklusive Sperre. Ein zweiter Schreibprozess wird
        # ausgeschlossen — auch im CLI-In-Process-Modus (07 §5).
        #
        # Gate-C-Audit: Die Sperre folgt der Datenbank. Wer einen Datenbank-
        # pfad injiziert (Tests, Zweitinstallationen), bekommt die Sperre im
        # SELBEN Verzeichnis — niemals stillschweigend am globalen
        # Standardpfad. Sonst wuerde ein Testlauf das echte Home anfassen und
        # mit einem laufenden Serve-Prozess um dessen Sperre konkurrieren.
        lock_path = self._lock_path
        if lock_path is None and self._database_path is not None:
            from personaljarvis.base.process_lock import LOCK_FILENAME

            lock_path = Path(self._database_path).parent / LOCK_FILENAME
        lock = ProcessLock(lock_path)
        lock.acquire()
        self._lock = lock

        contacts = ContactsModule(self._database_path,
                                  sidecar_path=self._sidecar_path,
                                  bundle_dir=self._bundle_dir)
        try:
            contacts.start()
        except Exception:
            # Keine Teilregistrierung: was gestartet wurde, wird gestoppt,
            # und die Sperre wird freigegeben.
            contacts.stop()
            lock.release()
            self._lock = None
            self._runtime = None
            raise

        # Gate-C-Auflage: Erholung verwaister Ausfuehrungen — **nach** dem
        # Erwerb der Sperre (erst dann ist bewiesen, dass kein Executor
        # laeuft) und **vor** der Annahme mutierender Requests. Sie fuehrt
        # keine Provideroperation aus: verwaiste `executing`-Vorgaenge werden
        # ausschliesslich nach `outcome_unknown` ueberfuehrt und warten dort
        # auf den Abgleich. Mehrfacher Start ist idempotent, weil ein
        # zweiter Lauf nichts mehr in `executing` findet.
        try:
            self._recovered = contacts.mutation_service().recover_interrupted()
        except Exception:
            contacts.stop()
            lock.release()
            self._lock = None
            self._runtime = None
            raise

        self._runtime = PersonalRuntime(contacts=contacts)
        return self._runtime

    @property
    def recovered_mutations(self) -> tuple[str, ...]:
        """Beim letzten Start erholte Vorgänge (Gate-C-Auflage)."""
        return self._recovered

    def stop(self) -> None:
        """Fährt herunter und gibt die Sperre frei. Mehrfacher Aufruf ist harmlos."""
        runtime, self._runtime = self._runtime, None
        lock, self._lock = self._lock, None
        try:
            if runtime is not None:
                runtime.contacts.stop()
        finally:
            # Die Sperre wird auch dann freigegeben, wenn der Modul-Stop
            # scheitert — sonst bliebe der Prozess dauerhaft blockiert.
            if lock is not None:
                lock.release()
