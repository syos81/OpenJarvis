"""Kein Auseinanderdriften zwischen Zustandsvorrat, SQL, API und ADR.

**Kontaktfrei, rein lesend.** Ein Zustand, den die Datenbank kennt und der
Code nicht (oder umgekehrt), ist eine Falle: Er fällt erst auf, wenn ihn ein
echter Vorgang erreicht — und dann steht ein Mensch vor einer Mutation, die
sich nicht mehr bewegen lässt. Diese Suite hält die vier Orte deckungsgleich.
"""

from __future__ import annotations

import re
from pathlib import Path

from personaljarvis.base.audit import AuditStage
from personaljarvis.base.db.migrations.versions.m0008_app_process_channel import (
    AUDIT_STAGES_0008,
    EXECUTION_ERROR_CLASSES,
    MUTATION_STATES_0008,
)
from personaljarvis.contacts.application.execution_contracts import (
    ERROR_CLASSES,
    OPERATION_TYPES,
    REPORT_OUTCOMES,
)
from personaljarvis.contacts.application.mutation_service import MutationState
from personaljarvis.contacts.application.state_machine import (
    ERLAUBTE_UEBERGAENGE,
    NACH_SEND,
    TERMINAL,
    ZUSTAENDE,
    UnzulaessigerUebergang,
    pruefe_uebergang,
)

WURZEL = Path(__file__).resolve().parents[3]
ADR20 = WURZEL / "docs/adr/ADR-0026-app-process-mutation-channel.md"
FRONTEND = WURZEL / "frontend/src/personal/contacts"


# ═══ F · Zustandsvorrat ═════════════════════════════════════════════════════
def test_python_und_sql_kennen_denselben_zustandsvorrat():
    assert set(ZUSTAENDE) == set(MUTATION_STATES_0008)


def test_der_dienst_kennt_dieselben_zustaende():
    im_dienst = {
        wert for name, wert in vars(MutationState).items()
        if name.isupper() and isinstance(wert, str)
    }
    assert im_dienst <= set(ZUSTAENDE), im_dienst - set(ZUSTAENDE)


def test_jeder_zustand_steht_in_der_uebergangstabelle():
    assert set(ERLAUBTE_UEBERGAENGE) == set(ZUSTAENDE)


def test_terminalzustaende_haben_keine_ausgaenge():
    for zustand in TERMINAL:
        assert ERLAUBTE_UEBERGAENGE[zustand] == frozenset(), zustand


def test_kein_rueckweg_nach_send_started():
    """Aus einem moeglicherweise gesendeten Zustand fuehrt kein Weg zurueck."""
    vor_send = {"prepared", "awaiting_approval", "approved"}
    for zustand in NACH_SEND:
        assert not (ERLAUBTE_UEBERGAENGE[zustand] & vor_send), zustand


def test_verbotene_uebergaenge_werfen():
    for von, nach in [
        ("executing", "approved"),
        ("outcome_unknown", "executing"),
        ("succeeded", "executing"),
        ("failed_before_send", "approved"),
        ("provider_applied_pending_reconcile", "outcome_unknown"),
        ("manually_resolved_applied", "succeeded"),
    ]:
        try:
            pruefe_uebergang(von, nach)
        except UnzulaessigerUebergang:
            continue
        raise AssertionError(f"{von} → {nach} haette scheitern muessen")


def test_erlaubte_uebergaenge_gehen_durch():
    for von, nach in [
        ("prepared", "awaiting_approval"),
        ("awaiting_approval", "approved"),
        ("approved", "executing"),
        ("approved", "failed_before_send"),
        ("executing", "provider_applied_pending_reconcile"),
        ("executing", "outcome_unknown"),
        ("provider_applied_pending_reconcile", "succeeded"),
        ("outcome_unknown", "manually_resolved_applied"),
    ]:
        pruefe_uebergang(von, nach)


# ═══ Audit ══════════════════════════════════════════════════════════════════
def test_auditstufen_in_python_und_sql_sind_gleich():
    assert set(AuditStage.ALL) == set(AUDIT_STAGES_0008)


# ═══ Fehlerklassen ══════════════════════════════════════════════════════════
def test_fehlerklassen_in_vertrag_und_sql_sind_gleich():
    assert set(ERROR_CLASSES) == set(EXECUTION_ERROR_CLASSES)


def test_der_adr_nennt_jede_fehlerklasse():
    text = ADR20.read_text(encoding="utf-8")
    for klasse in ERROR_CLASSES:
        assert klasse in text, klasse


# ═══ Frontend-Typen ═════════════════════════════════════════════════════════
def test_frontend_kennt_dieselben_ausgaenge_und_operationen():
    quelle = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    block = quelle.split("export interface ExecutionReportV1")[1].split("}")[0]
    for ausgang in REPORT_OUTCOMES:
        assert f"'{ausgang}'" in block, ausgang
    for operation in OPERATION_TYPES:
        assert f"'{operation}'" in block, operation


def test_frontend_traegt_dieselben_auftragsfelder():
    quelle = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    block = quelle.split("export interface ExecutionOrderV1")[1].split("\n}")[0]
    from personaljarvis.contacts.application.execution_contracts import (
        ExecutionOrderV1,
    )
    for feld in ExecutionOrderV1.__dataclass_fields__:
        assert re.search(rf"\b{feld}\b", block), feld


def test_frontend_traegt_dieselben_berichtsfelder():
    quelle = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    block = quelle.split("export interface ExecutionReportV1")[1].split("\n}")[0]
    from personaljarvis.contacts.application.execution_contracts import (
        ExecutionReportV1,
    )
    for feld in ExecutionReportV1.__dataclass_fields__:
        assert re.search(rf"\b{feld}\b", block), feld


# ═══ Rust-Vertrag ═══════════════════════════════════════════════════════════
def test_rust_traegt_dieselben_berichtsfelder():
    quelle = (WURZEL / "frontend/src-tauri/src/contacts_execution.rs").read_text(
        encoding="utf-8")
    block = quelle.split("pub struct ExecutionReportV1 {")[1].split("\n}")[0]
    from personaljarvis.contacts.application.execution_contracts import (
        ExecutionReportV1,
    )
    for feld in ExecutionReportV1.__dataclass_fields__:
        assert re.search(rf"\b{feld}\b", block), feld


def test_rust_kennt_dieselben_operationen():
    quelle = (WURZEL / "frontend/src-tauri/src/contacts_execution.rs").read_text(
        encoding="utf-8")
    for operation in OPERATION_TYPES:
        assert f'"{operation}"' in quelle, operation
