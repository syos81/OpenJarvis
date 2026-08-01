"""Produktives Ausführungsziel und Abgleichleser gegen den Sidecar.

Hier — und nur hier — wird im Kern eine Providerschreibung ausgelöst. Die
Schicht ist bewusst dünn: sie übersetzt zwischen `MutationPayload` und dem
JSON-Lines-Vertrag, prüft die Vertragsversionen und bildet den geschlossenen
Ergebnisvertrag auf den Zustandsvorrat der Pipeline ab. Sie entscheidet
**nichts** über Freigaben, Zustände oder lokale Daten.

Drei Eigenschaften sind nicht verhandelbar:

* **Genau ein Sidecaraufruf je `apply()`.** Kein Retry, keine Schleife, kein
  zweiter Versuch nach einem Fehler.
* **Fail-closed nach oben, nicht nach unten.** Was nicht beweisbar vor dem
  Send scheiterte, wird `outcome_unknown` — auch ein unbekannter Ausgang, ein
  kaputtes Protokoll oder eine Antwort ausserhalb der geschlossenen Menge.
  Der Preis ist manuelle Nacharbeit; der Preis der Gegenrichtung wäre ein
  doppelt angelegter Kontakt.
* **`update` und `delete` erreichen den Provider nicht.** Sie werden vor
  jedem Prozessstart als nicht implementiert abgewiesen.

**Belegte Grenze des Abgleichs** (SDK-Befund, macOS 12–13):
`CNChangeHistoryFetchRequest` kennt ausschliesslich `excludedTransactionAuthors`
— es gibt kein `includedTransactionAuthors`, und `CNChangeHistoryEvent` trägt
keinen Autor. Ein Add-Ereignis lässt sich über die öffentliche API deshalb
**nicht** dem eigenen Transaktionsautor zuordnen. Damit gibt es für einen
`create`, dessen Antwort verloren ging, keinen belastbaren Bezug: der Abgleich
urteilt dann mehrdeutig und ein Mensch entscheidet. Eine Namens- oder
Ähnlichkeitssuche findet **nicht** statt — sie könnte einen fremden Kontakt
treffen.
"""

from __future__ import annotations

from typing import Any

from personaljarvis.contacts.application.field_contract import (
    FIELD_CONTRACT_VERSION,
    MUTATION_CONTRACT_VERSION,
    project_bridge_contact,
    readback_digest,
)
from personaljarvis.contacts.application.models import (
    MutationPayload,
    ProviderOutcome,
)
from personaljarvis.contacts.application.mutation_service import ProviderResponse
from personaljarvis.contacts.application.reconcile import ReconcileObservation
from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.client import ContactsBridgeClient
from personaljarvis.contacts.bridge.errors import (
    BridgeConfigurationError,
    BridgeError,
    BridgeOperationError,
    MutationOutcomeUnknown,
)
from personaljarvis.contacts.bridge.models import BridgeContact
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import resolve_sidecar

__all__ = [
    "ContactsBridgeMutationProvider",
    "ContactsBridgeReconcileReader",
    "contract_compatible",
    "PRE_SEND_ERROR_CODES",
]

#: Fehlercodes, die der Sidecar **ausschliesslich** vor jeder Übergabe an den
#: Store senden kann. Nur bei ihnen darf aus einer typisierten Fehlerantwort
#: auf „nachweislich nichts gesendet" geschlossen werden; alles andere ist
#: fail-closed `outcome_unknown`.
PRE_SEND_ERROR_CODES: frozenset[str] = frozenset({
    protocol.ErrorCode.NOT_IMPLEMENTED,
    protocol.ErrorCode.PROTOCOL_MISMATCH,
    protocol.ErrorCode.INVALID_REQUEST,
    protocol.ErrorCode.TCC_DENIED,
    protocol.ErrorCode.UNSUPPORTED,
})


def contract_compatible(capabilities) -> bool:
    """Ob Sidecar und Kern denselben Mutations- und Feldvertrag sprechen."""
    return (capabilities.mutation_contract_version == MUTATION_CONTRACT_VERSION
            and capabilities.field_contract_version == FIELD_CONTRACT_VERSION)


class _SidecarSession:
    """Startet den Sidecar für **einen** Aufruf und beendet ihn immer.

    Ein dauerhaft laufender Schreibprozess wäre ein zweiter Ausführungsweg,
    den niemand ausdrücklich angestossen hat. Der Prozess lebt deshalb genau
    so lange wie der Aufruf.
    """

    def __init__(self, sidecar_path=None, bundle_dir=None) -> None:
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir

    def __enter__(self) -> ContactsBridgeClient:
        location = resolve_sidecar(self._sidecar_path,
                                   bundle_dir=self._bundle_dir)
        self._process = SidecarProcess(location)
        client = ContactsBridgeClient(self._process)
        try:
            client.start()
        except BridgeError:
            self._process.stop()
            raise
        return client

    def __exit__(self, *_exc) -> None:
        self._process.stop()


class ContactsBridgeMutationProvider:
    """Führt eine freigegebene `create`-Mutation gegen Apple Contacts aus."""

    def __init__(self, *, sidecar_path=None, bundle_dir=None) -> None:
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir

    # ── Der einzige Schreibpfad ─────────────────────────────────────────────
    def apply(self, payload: MutationPayload, *, mutation_id: str,
              idempotency_key: str, approval_id: str) -> ProviderResponse:
        if payload.command != "create":
            # Beweisbar vor jedem Send: der Prozess startet gar nicht erst.
            return ProviderResponse(ProviderOutcome.REJECTED_BEFORE_SEND,
                                    error_code="not_implemented")
        if not payload.container_identifier:
            return ProviderResponse(ProviderOutcome.REJECTED_BEFORE_SEND,
                                    error_code="container_missing")

        try:
            session = _SidecarSession(self._sidecar_path, self._bundle_dir)
        except BridgeConfigurationError:                # pragma: no cover
            return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                    error_code="bridge_not_found")
        try:
            with session as client:
                caps = client.capabilities
                if not contract_compatible(caps):
                    return ProviderResponse(
                        ProviderOutcome.REJECTED_BEFORE_SEND,
                        error_code="contract_version_mismatch")
                if not caps.create_implemented:
                    return ProviderResponse(
                        ProviderOutcome.REJECTED_BEFORE_SEND,
                        error_code="create_not_implemented")
                roh = client.create(
                    mutation_id=mutation_id, idempotency_key=idempotency_key,
                    approval_id=approval_id,
                    container_identifier=payload.container_identifier,
                    fields=dict(payload.fields))
        except BridgeConfigurationError:
            # Der Sidecar wurde nicht gefunden — es gab keinen Prozess und
            # damit nachweislich keinen Send.
            return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                    error_code="bridge_not_found")
        except MutationOutcomeUnknown as exc:
            # Abbruch **waehrend** der Mutation. Weder Erfolg noch Fehlschlag.
            return ProviderResponse(ProviderOutcome.OUTCOME_UNKNOWN,
                                    error_code=exc.underlying_class)
        except BridgeOperationError as exc:
            if exc.code in PRE_SEND_ERROR_CODES:
                return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                        error_code=exc.code)
            return ProviderResponse(ProviderOutcome.OUTCOME_UNKNOWN,
                                    error_code=exc.code)
        except BridgeError as exc:
            # Startfehler sind vor dem Send; alles andere bleibt fail-closed
            # unbekannt, weil der Zeitpunkt nicht belegt ist.
            klasse = type(exc).__name__
            if not getattr(exc, "diagnostics", None):
                return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                        error_code=klasse)
            return ProviderResponse(ProviderOutcome.OUTCOME_UNKNOWN,
                                    error_code=klasse)

        return self._auswerten(roh)

    # ── Geschlossener Ergebnisvertrag → Pipeline-Zustand ────────────────────
    @staticmethod
    def _auswerten(roh: dict[str, Any]) -> ProviderResponse:
        ausgang = roh.get("outcome")
        fehler = roh.get("errorCode")

        if ausgang == protocol.MutationOutcome.NOT_SENT:
            return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                    error_code=str(fehler or "not_sent"))
        if ausgang == protocol.MutationOutcome.APPLIED:
            kennung = roh.get("providerIdentifier")
            rohkontakt = roh.get("contact")
            if not kennung or not isinstance(rohkontakt, dict):
                # „Angewandt" ohne Beleg ist keine Anwendung. Der Vorgang wurde
                # gesendet — also unbekannt, nie Erfolg.
                return ProviderResponse(ProviderOutcome.OUTCOME_UNKNOWN,
                                        error_code="applied_without_readback")
            try:
                kontakt = BridgeContact.parse(rohkontakt)
            except (KeyError, TypeError, ValueError):
                return ProviderResponse(ProviderOutcome.OUTCOME_UNKNOWN,
                                        error_code="readback_unparsable")
            return ProviderResponse(
                ProviderOutcome.SUCCEEDED,
                provider_identifier=str(kennung),
                container_identifier=roh.get("containerIdentifier"),
                readback=kontakt,
                # Der Digest entsteht **hier**, nicht im Sidecar: seine Bildung
                # verlangt die Ruecknormalisierung der Apple-Rohlabels, und
                # Normalisierung ist Kernaufgabe (ADR-0016 Punkt 4).
                readback_digest=readback_digest(project_bridge_contact(kontakt)))
        # `outcome_unknown` und jeder unbekannte Wert landen hier. Ein Ausgang
        # ausserhalb der geschlossenen Menge ist genau der Fall, in dem raten
        # am teuersten waere.
        return ProviderResponse(
            ProviderOutcome.OUTCOME_UNKNOWN,
            error_code=str(fehler or "unknown_outcome"),
            exception_diagnostics=_exception_diagnostics(roh))


#: Bezeichnerzeichen eines Objective-C-Klassennamens. Alles andere — `/`,
#: `@`, Leerzeichen — hat in einem Ausnahmenamen nichts verloren und wird
#: entfernt statt maskiert. Zweiter Riegel zur gleichen Regel im Shim: auch
#: eine manipulierte Sidecar-Antwort traegt keinen Freitext in den Kern.
_EXCEPTION_NAME_ALLOWED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")

_HEX_DIGITS = frozenset("0123456789abcdef")


def _exception_diagnostics(roh: dict[str, Any]) -> dict[str, Any] | None:
    """PII-armer Befund einer nativ gefangenen NSException — oder None.

    Übernommen wird ausschliesslich die geschlossene Feldmenge des
    Shim-Vertrags, jedes Feld erneut geprüft: der Name auf Bezeichnerzeichen
    reduziert und gekappt, der Digest nur als exakter SHA-256-Hex akzeptiert.
    Der Reason-Text selbst hat in dieser Antwort keinen Platz — tauchte er
    auf, würde er hier schlicht nicht mitgelesen.
    """
    if roh.get("errorCode") != "objc_exception":
        return None
    name = "".join(c for c in str(roh.get("exceptionName") or "")
                   if c in _EXCEPTION_NAME_ALLOWED)[:64]
    befund: dict[str, Any] = {
        "exception_name": name or "UnknownException",
        "reason_present": bool(roh.get("reasonPresent")),
    }
    digest = roh.get("reasonDigest")
    if (isinstance(digest, str) and len(digest) == 64
            and set(digest) <= _HEX_DIGITS):
        befund["reason_digest"] = digest
    return befund


class ContactsBridgeReconcileReader:
    """Liest den Providerzustand für den Abgleich — **ausschliesslich lesend**.

    Zulässig ist genau ein Zugriffsweg: der exakte, bereits bekannte
    Provider-Identifier. Fehlt er, liefert der Leser ein mehrdeutiges Ergebnis
    und der Vorgang endet bei einer menschlichen Entscheidung. Es gibt hier
    weder eine Suche über Namen, E-Mail oder Nummer noch eine Ähnlichkeits-
    oder Erst-Treffer-Heuristik — siehe die belegte API-Grenze im Modulkopf.
    """

    def __init__(self, *, sidecar_path=None, bundle_dir=None) -> None:
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir

    def observe(self, *, command: str, provider_identifier: str | None,
                expected_fields: dict[str, Any],
                idempotency_key: str) -> ReconcileObservation:
        if not provider_identifier:
            return ReconcileObservation(exists=None, ambiguous=True)
        try:
            with _SidecarSession(self._sidecar_path, self._bundle_dir) as client:
                kontakt = client.get(provider_identifier)
        except BridgeOperationError as exc:
            if exc.code == protocol.ErrorCode.NOT_FOUND:
                return ReconcileObservation(exists=False)
            return ReconcileObservation(exists=None, ambiguous=True)
        except BridgeError:
            return ReconcileObservation(exists=None, ambiguous=True)
        return ReconcileObservation(
            exists=True, provider_identifier=kontakt.provider_identifier,
            fields=dict(project_bridge_contact(kontakt).scalars),
            # Der Kontakt selbst wird durchgereicht, damit die lokale
            # Nachfuehrung dieselbe Providerwahrheit benutzt wie ein Read-back.
            transaction_author=None, readback=kontakt)
