"""Geschlossene Fehlermenge der Native-Bridge (08 §3 Nr. 5).

**Keine rohe Provider-Exception verlässt den Adapter** und keine dieser
Meldungen enthält jemals Kontaktdaten — weder Namen, Adressen, Nummern noch
Provider-Identifier. Diagnosetexte beschreiben ausschließlich Technik.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personaljarvis.errors import PersonalJarvisError

__all__ = [
    "BridgeError",
    "BridgeConfigurationError",
    "BridgeProtocolError",
    "BridgeProcessError",
    "BridgeOperationError",
    "BridgeCapabilityMismatch",
    "MutationOutcomeUnknown",
    "ProcessDiagnostics",
    "ProcessFailureClass",
]


class BridgeError(PersonalJarvisError):
    """Wurzel aller Bridge-Fehler."""


class BridgeConfigurationError(BridgeError):
    """Das Sidecar-Binary fehlt, passt nicht zur Architektur oder ist unbrauchbar."""


class BridgeProtocolError(BridgeError):
    """Die Gegenseite hält den JSON-Lines-Vertrag nicht ein."""


class BridgeCapabilityMismatch(BridgeError):
    """Eine Fähigkeit wurde verlangt, die der Provider nicht deklariert.

    Ehrliche Grenzen statt Verschweigen (08 §3 Nr. 2/7): der Aufrufer erhält
    einen Typ, keine stillschweigend leere Antwort.
    """


class BridgeOperationError(BridgeError):
    """Der Sidecar hat eine typisierte Fehlerantwort geliefert.

    `code` stammt aus der geschlossenen Menge des Vertrags
    (`tcc_denied`, `not_found`, `invalid_request`, `not_implemented`, …).
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 provider_domain: str = "", provider_code: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        #: Apple-Fehlerdomain, falls der Provider eine geliefert hat. Nur
        #: Domain und numerischer Code — nie `localizedDescription`, die
        #: Pfade oder private Angaben enthalten kann.
        self.provider_domain = provider_domain
        self.provider_code = provider_code
        self.retryable = retryable

    @property
    def provider_detail(self) -> str:
        """`domain/code` als stabile, PII-freie Kurzform. Leer ohne Angabe."""
        if not self.provider_domain or self.provider_code is None:
            return ""
        return f"{self.provider_domain}/{self.provider_code}"


class ProcessFailureClass:
    """Fehlerklassen eines Requests. Ein Request endet **nie** ohne Klasse."""

    REQUEST_TIMEOUT = "request_timeout"
    CHILD_EXITED = "child_exited"
    CHILD_SIGNALLED = "child_signalled"
    STDOUT_EOF = "stdout_eof"
    PROTOCOL_ERROR = "protocol_error"
    RESPONSE_ID_MISMATCH = "response_id_mismatch"
    PROTOCOL_VERSION_MISMATCH = "protocol_version_mismatch"
    MUTATION_OUTCOME_UNKNOWN = "mutation_outcome_unknown"


@dataclass(frozen=True)
class ProcessDiagnostics:
    """PII-freie Diagnose eines gescheiterten Requests."""

    request_id: int
    operation: str
    elapsed_seconds: float
    child_exit_code: int | None
    child_signal: int | None
    child_alive: bool
    stdout_eof: bool
    stderr_eof: bool
    wrong_response_ids: tuple[int | None, ...] = ()
    stderr_tail: tuple[str, ...] = ()
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "elapsed_seconds": self.elapsed_seconds,
            "child_exit_code": self.child_exit_code,
            "child_signal": self.child_signal,
            "child_alive": self.child_alive,
            "stdout_eof": self.stdout_eof,
            "stderr_eof": self.stderr_eof,
            "wrong_response_ids": list(self.wrong_response_ids),
            "stderr_tail": list(self.stderr_tail),
            "detail": self.detail,
        }


class BridgeProcessError(BridgeError):
    """Der Sidecar-Prozess hat den Request nicht beantwortet.

    Trägt immer eine `failure_class` und PII-freie Diagnosefelder. Es findet
    **kein** automatischer Retry statt.
    """

    def __init__(self, failure_class: str, diagnostics: ProcessDiagnostics) -> None:
        super().__init__(f"{failure_class}: {diagnostics.detail}")
        self.failure_class = failure_class
        self.diagnostics = diagnostics

    def as_dict(self) -> dict[str, object]:
        return {"failure_class": self.failure_class, **self.diagnostics.as_dict()}


class MutationOutcomeUnknown(BridgeProcessError):
    """Abbruch **während** einer Mutation.

    Bedeutet ausdrücklich **weder fehlgeschlagen noch erfolgreich** (Plan §7.2).
    Die zugrunde liegende Klasse bleibt in `underlying_class` erhalten. Ein
    automatischer Retry ist verboten; zuerst muss abgeglichen werden.
    """

    def __init__(self, underlying_class: str, diagnostics: ProcessDiagnostics) -> None:
        super().__init__(ProcessFailureClass.MUTATION_OUTCOME_UNKNOWN, diagnostics)
        self.underlying_class = underlying_class

    def as_dict(self) -> dict[str, object]:
        return {**super().as_dict(), "underlying_class": self.underlying_class}
