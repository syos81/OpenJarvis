"""Statische Architekturprüfungen des App-Prozess-Mutationskanals (ADR-0020).

**Kontaktfrei, rein lesend.** Diese Suite verhindert dokument- und
quelltextbasiert die neun in ADR-0020 §14 benannten Vertragsbrüche. Sie
prüft den heutigen Stand (vor Phase A) und die normativen Anker, an denen
jede spätere Implementierung gemessen wird.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[3]
ADR20 = WURZEL / "docs/adr/ADR-0020-app-process-mutation-channel.md"
ADR19 = WURZEL / "docs/adr/ADR-0019-provider-mutation-architecture.md"
ANWENDUNG = WURZEL / "src/personaljarvis/contacts/application"
MUTATION_SERVICE = ANWENDUNG / "mutation_service.py"
RECONCILE = ANWENDUNG / "reconcile.py"
FIELD_CONTRACT = ANWENDUNG / "field_contract.py"


def _lies(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def _nur_code(text: str) -> str:
    """Entfernt Python-Kommentare und Docstrings grob, damit Verbote Code treffen."""
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(z for z in text.split("\n") if not z.lstrip().startswith("#"))


# ═══ 1 · Der ADR existiert mit allen normativen Ankern ══════════════════════
def test_adr_0020_traegt_die_normativen_anker():
    # Whitespace-normalisiert: Markdown bricht Sätze beliebig um.
    text = " ".join(_lies(ADR20).split())
    for anker in [
        "Produktive Apple-Contacts-Writes laufen",
        "Tauri-App-Prozess",
        "ExecutionOrder",
        "ExecutionReport",
        "idempotente Settle-Route",
        "claim_token",
        "nur als SHA-256-Digest",
        "provider_send_started",
        "Claim-Verfall",
        "niemals einen neuen Send",
        "manually_resolved_applied",
        "Der Spiegel wird dabei nicht erfunden",
        "field_contract_version = 1",
        "NFC-Normalisierung",
        "goldene",
        "Delete ist **R2**",
        "confirm_delete",
        "DEC-D06",
        "Automatische Wiederholung nach `send_started`",
    ]:
        assert " ".join(anker.split()) in text, f"ADR-0020-Anker fehlt: {anker!r}"


def test_adr_0019_verweist_additiv_auf_adr_0020():
    text = _lies(ADR19)
    assert "ADR-0020" in text
    assert "Nachtrag 2026-08-03" in text
    # Additiv: die urspruengliche Entscheidung bleibt lesbar stehen.
    assert "Sidecar-Schreibvertrag" in text


def test_die_phasen_haben_entry_und_exit_kriterien():
    text = _lies(ADR20)
    for phase in ["**A**", "**B**", "**C**", "**D**", "**E**", "**F**", "**G**"]:
        assert phase in text, f"Phase {phase} fehlt"
    assert "Entry" in text and "Exit" in text
    assert "keine Phase beginnt ohne ausdrückliche Freigabe" in text.lower() \
        or "Keine Phase beginnt ohne ausdrückliche Freigabe" in text


# ═══ 2 · Kein zweiter Save-Versuch nach send_started ════════════════════════
def test_genau_eine_provider_apply_aufrufstelle():
    code = _nur_code(_lies(MUTATION_SERVICE))
    treffer = re.findall(r"provider\.apply\(", code)
    assert len(treffer) == 1, f"provider.apply-Aufrufe: {len(treffer)} (erwartet 1)"


def test_kein_retry_konstrukt_im_mutationsdienst():
    code = _nur_code(_lies(MUTATION_SERVICE))
    for verboten in ("retry", "while True", "for versuch", "backoff", "sleep("):
        assert verboten not in code, f"Retry-Konstrukt gefunden: {verboten!r}"


# ═══ 3 · Settle/Reconcile loesen nie einen Provider-Send aus ═════════════════
def test_reconcile_ruft_nie_den_provider():
    code = _nur_code(_lies(RECONCILE))
    assert "provider.apply" not in code
    assert ".apply(" not in code
    # Der Abgleich liest ausschliesslich:
    assert "observe" in code


def test_der_adr_verbietet_settle_sends():
    text = _lies(ADR20)
    assert "Settle-/Reconcile-Schicht löst keinen Provider-Send aus" in text \
        or "keinen Provider-Send" in text


# ═══ 4 · Unlesbare Felder sind nie schreibbar ═══════════════════════════════
def test_note_bleibt_nie_schreibbar():
    code = _lies(FIELD_CONTRACT)
    idx = code.index("NEVER_WRITABLE: frozenset")
    block = code[idx:idx + 600]
    for feld in ('"note"', '"notes"', '"thumbnail"', '"image"'):
        assert feld in block, f"{feld} fehlt in NEVER_WRITABLE"


def test_der_adr_verbietet_unlesbar_als_leer():
    text = _lies(ADR20)
    assert "nie „leer" in text or "gilt nie als leer" in text


# ═══ 5 · Keine Namenssuche im Abgleich ══════════════════════════════════════
def test_reconcile_sucht_nie_ueber_namen():
    code = _nur_code(_lies(RECONCILE))
    for verboten in ("display_name", "given_name LIKE", "familyName",
                     "name_search", "aehnlich", "similarity"):
        assert verboten not in code, f"Namenssuche-Indiz im Abgleich: {verboten!r}"


# ═══ 6 · Keine rohen Provider-Identifier in der normalen UI ═════════════════
def test_frontend_detailansicht_zeigt_keine_rohen_identifier():
    detail = _lies(
        WURZEL / "frontend/src/personal/contacts/detail/ContactDetailPane.tsx")
    # Erlaubt ist ausschliesslich die Anzahl (account_refs.length).
    for zeile in detail.split("\n"):
        z = zeile.strip()
        if z.startswith("//") or z.startswith("*"):
            continue
        if "account_refs" in z:
            assert ".length" in z, f"account_refs ohne .length: {z!r}"
        assert "provider_identifier" not in z
        assert "container_identifier" not in z


def test_der_transportvertrag_haelt_rohe_identifier_aus_ui_und_logs():
    text = _lies(ADR20)
    assert "nie in UI/Logs" in text or "**nie roh**" in text


# ═══ 7 · Kein Spike-/DEV-Gate im Produktpfad ════════════════════════════════
def test_spike_gate_kommt_im_hauptstand_nicht_vor():
    treffer = []
    for wurzelteil in ("frontend/src-tauri/src", "src/personaljarvis"):
        basis = WURZEL / wurzelteil
        for pfad in basis.rglob("*"):
            if pfad.suffix in (".rs", ".py", ".swift", ".m", ".h", ".ts", ".tsx") \
                    and pfad.is_file():
                if "OPENJARVIS_CONTACTS_APP_SAVE_SPIKE" in pfad.read_text(
                        encoding="utf-8", errors="ignore"):
                    treffer.append(str(pfad))
    assert treffer == [], f"Spike-Gate im Produktpfad: {treffer}"


def test_der_adr_verbietet_spike_uebernahme():
    text = _lies(ADR20)
    assert "wird nicht Produktcode" in text or "nicht** als Produktcode" in text
    assert "Bestätigungsphrase" in text and "Nonce" in text


# ═══ 8 · Delete nur mit zusaetzlicher Bestaetigung ══════════════════════════
def test_delete_ist_r2_mit_zusatzbestaetigung_und_dec_d06_riegel():
    text = _lies(ADR20)
    assert "Delete ist **R2**" in text
    assert "confirm_delete" in text
    assert "DEC-D06" in text
    # Phase F ist ausdruecklich dahinter verriegelt:
    assert "zuerst DEC-D06 entscheiden" in text


def test_frontend_delete_hat_heute_schon_eine_bestaetigung():
    dialoge = _lies(
        WURZEL / "frontend/src/personal/contacts/editor/dialogs.tsx")
    assert "Kontakt löschen" in dialoge
    assert "nicht rückgängig" in dialoge


# ═══ 9 · Keine Mutation ohne Approval-Digestbindung ═════════════════════════
def test_execute_verbraucht_die_freigabe_mit_digest():
    code = _nur_code(_lies(MUTATION_SERVICE))
    assert re.search(r"consume\([^)]*digest", code), \
        "consume() ohne Digestbindung"


def test_der_adr_bindet_payload_und_preview_digest():
    text = _lies(ADR20)
    assert "payload_digest" in text and "preview_digest" in text
    # L1-Schliessung ist normativ benannt:
    assert "`payload_digest`\n  **und** `preview_digest`" in text \
        or "payload_digest`\n  **und** `preview_digest" in text \
        or "und** `preview_digest`" in text


# ═══ Register und Historie ══════════════════════════════════════════════════
def test_dec_045_ist_registriert():
    register = _lies(WURZEL / "docs/personal-jarvis/decisions-register.md")
    assert "DEC-045" in register
    assert "ADR-0020" in register
    assert "44 akzeptierte Entscheidungen" in register
