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

    def __init__(self, database_path: Path | str | None = None) -> None:
        self._database_path = database_path
        self._runtime: PersonalRuntime | None = None

    @property
    def runtime(self) -> PersonalRuntime | None:
        return self._runtime

    def start(self) -> PersonalRuntime:
        """Startet Personal Jarvis. Idempotent bei mehrfachem Aufruf.

        Ein Fehler in Migration oder Schema wird **weitergereicht**; es bleibt
        keine halbfertige Registrierung zurück.
        """
        if self._runtime is not None:
            return self._runtime

        contacts = ContactsModule(self._database_path)
        try:
            contacts.start()
        except Exception:
            # Keine Teilregistrierung: was gestartet wurde, wird gestoppt.
            contacts.stop()
            self._runtime = None
            raise

        self._runtime = PersonalRuntime(contacts=contacts)
        return self._runtime

    def stop(self) -> None:
        if self._runtime is None:
            return
        self._runtime.contacts.stop()
        self._runtime = None
