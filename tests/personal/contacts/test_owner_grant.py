"""G · Die Freigabe ist eine Eigentümerhandlung, kein Zeichenkettenvergleich.

**Kontaktfrei.** Fake-Provider, temporäre Datenbank, erfundene Daten.

Der Defekt: `ApprovalStore.grant()` prüfte eine Denylist — `llm_assisted`,
`automation`, `system` raus, alles andere rein. Der Literal `'lukas'` genügte
damit für eine Eigentümerfreigabe, und genau den setzte der Kontaktzweig der
Command Bar programmatisch **im Ausführungsschritt** ein
(`writeAdapter.ts`, `const ENTSCHEIDER = 'lukas'`).

Eine Allowlist derselben Sorte (`actor == 'lukas'`) wäre dieselbe Lücke mit
umgekehrtem Vorzeichen. Geprüft wird deshalb nicht, ob ein bestimmter Name
durchkommt, sondern ob **irgendein selbst gewählter Name** eine
Eigentümerfreigabe erzeugen kann. Er kann es nicht: Die Freigabe verlangt ein
`OwnerDecision`, und das entsteht ausschliesslich in `owner_decision_for_tests()`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from personaljarvis.base.approvals import (
    ApprovalExpired,
    ApprovalState,
    ApprovalStore,
    OwnerDecision,
    SelfApprovalRejected,
    owner_decision_for_tests,
)
from personaljarvis.contacts.application import ContactsMutationService
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    MutationNotExecutable,
)
from personaljarvis.contacts.application.queries import ContactsQueryService

from .conftest import WORKSPACE
from .test_mutation_pipeline import MENSCH, AttrappenProvider
from .test_write_lifecycle_repair import _lokal, _update_befehl

_REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def vorbereitet(module):
    """Ein vorbereiteter Vorgang — freigabepflichtig, nicht freigegeben.

    Die Attrappe liest dieselbe Providerkennung zurueck, die das Ziel traegt:
    Sonst faende `_spiegeln` den Ablageort der bestehenden Identitaet nicht
    und scheiterte an einer leeren Containerkennung — ein Artefakt der
    Attrappe, nicht des Freigabewegs.
    """
    dienst = ContactsMutationService(
        module, AttrappenProvider(provider_identifier="raw-1"))
    kontakt = _lokal(module)
    befehl = _update_befehl(kontakt)
    dienst.prepare(befehl)
    return dienst, befehl


# ═══ Die geschlossene Repräsentation ════════════════════════════════════════
class TestOwnerDecision:
    def test_ohne_siegel_entsteht_keine_entscheidung(self):
        """Der Konstruktor ist kein zweiter Weg."""
        with pytest.raises(SelfApprovalRejected):
            OwnerDecision("lukas")

    @pytest.mark.parametrize("ursprung", ["llm_assisted", "automation",
                                          "system"])
    def test_maschinelle_ursprünge_werden_abgewiesen(self, ursprung):
        with pytest.raises(SelfApprovalRejected):
            owner_decision_for_tests(ursprung)

    @pytest.mark.parametrize("leer", ["", "   "])
    def test_eine_freigabe_ohne_entscheider_ist_keine(self, leer):
        with pytest.raises(SelfApprovalRejected):
            owner_decision_for_tests(leer)

    def test_der_name_bleibt_protokoll(self):
        """Er ist Auditangabe, nicht mehr Nachweis."""
        assert owner_decision_for_tests("  lukas  ").actor == "lukas"


class TestGrantVerlangtDieHandlung:
    def test_ein_selbst_gewaehlter_name_erzeugt_keine_freigabe(self, module,
                                                               vorbereitet):
        """Der Kern des Defekts — und er ist namensunabhängig geschlossen."""
        dienst, befehl = vorbereitet
        for erfundener_name in ["lukas", "owner", "eigentuemer", "admin"]:
            with pytest.raises(TypeError):
                dienst.grant(befehl.mutation_id,
                             decision_actor=erfundener_name)

    def test_auch_direkt_am_store_nicht(self, module, vorbereitet):
        """Nicht nur der Modulweg ist eng, sondern der Freigabekern selbst."""
        _, befehl = vorbereitet
        with module.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT approval_id FROM contacts_mutations "
                "WHERE mutation_id = ?", (befehl.mutation_id,)).fetchone()
            with pytest.raises(SelfApprovalRejected):
                ApprovalStore(uow).grant(zeile["approval_id"],
                                         decision="lukas")

    def test_die_ausdrueckliche_handlung_erzeugt_genau_den_gebundenen_grant(
            self, module, vorbereitet):
        dienst, befehl = vorbereitet
        freigabe = dienst.grant(befehl.mutation_id,
                                decision=owner_decision_for_tests(MENSCH))

        assert freigabe.state == ApprovalState.GRANTED
        assert freigabe.decision_actor == MENSCH
        # Gebunden an Vorgang, Nutzlast und Vorschau — nicht an einen Namen.
        assert freigabe.subject_id == befehl.mutation_id
        assert freigabe.payload_digest
        assert freigabe.preview_digest

    def test_die_bindung_gilt_an_genau_dieser_vorbereitung(self, module,
                                                           vorbereitet):
        """Eine Freigabe deckt keine andere Nutzlast und keine andere Vorschau."""
        from personaljarvis.base.approvals import ApprovalPayloadMismatch

        dienst, befehl = vorbereitet
        dienst.grant(befehl.mutation_id, decision=owner_decision_for_tests(MENSCH))

        with module.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT approval_id, payload_digest, preview_digest "
                "FROM contacts_mutations WHERE mutation_id = ?",
                (befehl.mutation_id,)).fetchone()
            store = ApprovalStore(uow)
            with pytest.raises(ApprovalPayloadMismatch):
                store.consume(zeile["approval_id"],
                              payload_digest="eine-andere-nutzlast",
                              preview_digest=zeile["preview_digest"])
            with pytest.raises(ApprovalPayloadMismatch):
                store.consume(zeile["approval_id"],
                              payload_digest=zeile["payload_digest"],
                              preview_digest="eine-andere-vorschau")


# ═══ Der Ausführungspfad erzeugt nie eine Freigabe ══════════════════════════
class TestExecuteErzeugtKeineFreigabe:
    def test_execute_auf_wartendem_vorgang_erzeugt_keine_freigabe(
            self, module, vorbereitet):
        dienst, befehl = vorbereitet

        with pytest.raises(MutationNotExecutable):
            dienst.execute(befehl.mutation_id)

        with module.unit_of_work() as uow:
            zustand = uow.execute(
                "SELECT state FROM personal_approvals").fetchone()["state"]
        assert zustand == ApprovalState.AWAITING

    def test_execute_auf_wartendem_vorgang_mutiert_nicht(self, module):
        provider = AttrappenProvider()
        dienst = ContactsMutationService(module, provider)
        kontakt = _lokal(module)
        befehl = _update_befehl(kontakt)
        dienst.prepare(befehl)

        with pytest.raises(MutationNotExecutable):
            dienst.execute(befehl.mutation_id)

        # Der Provider wurde nicht einmal angesprochen.
        assert provider.calls == []
        with module.unit_of_work() as uow:
            vorgang = uow.execute(
                "SELECT state, attempt_count FROM contacts_mutations "
                "WHERE mutation_id = ?", (befehl.mutation_id,)).fetchone()
        assert vorgang["state"] == "awaiting_approval"
        assert vorgang["attempt_count"] == 0

    def test_nach_der_freigabe_ist_execute_ein_eigener_schritt(self, module,
                                                               vorbereitet):
        dienst, befehl = vorbereitet
        dienst.grant(befehl.mutation_id, decision=owner_decision_for_tests(MENSCH))

        fragen = ContactsQueryService(module)
        nach_freigabe = fragen.get_mutation(befehl.mutation_id,
                                            workspace_id=WORKSPACE)
        # Freigegeben heisst nicht ausgeführt: Der Vorgang wartet sichtbar.
        assert nach_freigabe.state == "approved"
        assert nach_freigabe.attempt_count == 0

        dienst.execute(befehl.mutation_id)
        assert fragen.get_mutation(
            befehl.mutation_id, workspace_id=WORKSPACE).state != "approved"

    def test_ein_zweites_execute_findet_nicht_statt(self, module, vorbereitet):
        dienst, befehl = vorbereitet
        dienst.grant(befehl.mutation_id, decision=owner_decision_for_tests(MENSCH))
        dienst.execute(befehl.mutation_id)

        # Terminal ist terminal: Der zweite Versuch wird typisiert abgewiesen,
        # bevor irgendetwas gesendet wird.
        with pytest.raises(AlreadySettled):
            dienst.execute(befehl.mutation_id)

    def test_eine_abgelaufene_freigabe_traegt_kein_execute(self, module,
                                                           vorbereitet):
        dienst, befehl = vorbereitet
        dienst.grant(befehl.mutation_id, decision=owner_decision_for_tests(MENSCH))

        # Beide Zeitpunkte zurueck: Der CHECK der Migration verlangt
        # `expires_at > requested_at`, und eine Freigabe, die nie gueltig war,
        # waere ein anderer Fall als eine abgelaufene.
        with module.unit_of_work() as uow:
            uow.execute(
                "UPDATE personal_approvals SET requested_at = ?, expires_at = ?",
                ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:01+00:00"))

        with pytest.raises(ApprovalExpired):
            dienst.execute(befehl.mutation_id)

    def test_der_abgelaufene_grant_liest_sich_ohne_mutation_als_expired(
            self, module, vorbereitet):
        """Sichtbar abgelaufen — und die Anzeige hat nichts geschrieben."""
        dienst, befehl = vorbereitet
        dienst.grant(befehl.mutation_id, decision=owner_decision_for_tests(MENSCH))

        gelesen = ContactsQueryService(module).list_approvals(
            workspace_id=WORKSPACE, now="2099-01-01T00:00:00+00:00")
        assert gelesen[0].state == ApprovalState.EXPIRED

        with module.unit_of_work() as uow:
            gespeichert = uow.execute(
                "SELECT state FROM personal_approvals").fetchone()["state"]
        assert gespeichert == ApprovalState.GRANTED


# ═══ Statisch: die Herkunft der Freigabe ist eng ════════════════════════════
def _aufrufstellen(wurzel: Path, name: str) -> list[str]:
    """Wo wird `name` im Produktcode tatsächlich **aufgerufen**?"""
    treffer = []
    for pfad in wurzel.rglob("*.py"):
        if "__pycache__" in str(pfad):
            continue
        baum = ast.parse(pfad.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Call)
                    and isinstance(knoten.func, ast.Name)
                    and knoten.func.id == name):
                treffer.append(f"{pfad.relative_to(wurzel)}:{knoten.lineno}")
    return sorted(treffer)


def test_owner_decision_wird_nur_am_freigabeweg_aufgerufen():
    """Eine Stelle je Modul — und beide verlangen einen Beleg.

    Ohne diese Enge wäre die geschlossene Repräsentation folgenlos: Wer sie
    überall bauen darf, hat wieder den freien String, nur mit mehr Zeichen.
    """
    stellen = _aufrufstellen(_REPO / "src" / "personaljarvis",
                             "owner_decision_attested")
    dateien = {s.split(":")[0] for s in stellen}
    assert dateien == {
        "contacts/api/routes.py",
        "calendar/mutations/service.py",
    }, stellen


def test_der_testweg_erreicht_keinen_produktcode():
    """Der Riegel hinter der Reparatur vom 2026-08-17.

    `owner_decision_for_tests()` baut eine Entscheidung ohne Beleg. Für Suiten
    ist das richtig; in Produktcode wäre es genau die Hintertür, die
    `owner_decision_attested()` gerade geschlossen hat. Ruft irgendwann eine
    Datei unter `src/` sie auf, ist die Grenze wieder ein String.
    """
    stellen = _aufrufstellen(_REPO / "src" / "personaljarvis",
                             "owner_decision_for_tests")
    assert stellen == [], stellen


def test_der_ausfuehrungspfad_ruft_keine_freigabe():
    """`execute` und alles darunter kennen `grant` nicht."""
    quelle = (_REPO / "src/personaljarvis/contacts/application/"
              "mutation_service.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    ausfuehren = next(
        k for k in ast.walk(baum)
        if isinstance(k, ast.FunctionDef) and k.name == "execute")
    aufrufe = {k.func.attr for k in ast.walk(ausfuehren)
               if isinstance(k, ast.Call)
               and isinstance(k.func, ast.Attribute)}
    assert "grant" not in aufrufe
    assert "owner_decision_for_tests" not in aufrufe


def test_die_command_bar_gibt_im_ausfuehrungsschritt_nicht_frei():
    """Der Kontaktzweig fuehrt aus, was freigegeben ist — er gibt nicht frei.

    Umgestellt am 2026-08-16. Bis dahin verlangte dieser Test, dass
    `approveMutation` in `writeAdapter.ts` **gar nicht** vorkommt. Das war zu
    grob und zugleich zu schwach: Zu grob, weil der Adapter seit der Trennung
    einen eigenen, reinen Freigabeweg hat (`genehmige`); zu schwach, weil ein
    Zeichenkettenverbot den Kalenderzweig derselben Datei nie erfasste — dort
    stand `gibFrei(...)` im Ausfuehrungsschritt und blieb drei Tage
    unbemerkt.

    Die Aussage ist jetzt die richtige: **der Ausfuehrungsschritt** erreicht
    die Freigabegrenze nicht. Geprueft ueber Erreichbarkeit, nicht ueber
    Namen; normativ in `tools/guards/approval_boundary.py`.
    """
    from tools.guards.approval_boundary import analysiere

    ergebnis = analysiere(_REPO / "frontend/src")
    assert not ergebnis.erreicht("core/writeAdapter.ts", "fuehreAus")
    # Und er fuehrt nur aus, was bereits freigegeben ist.
    roh = (_REPO / "frontend/src/core/writeAdapter.ts").read_text(
        encoding="utf-8")
    code = "\n".join(z for z in roh.splitlines()
                      if not z.lstrip().startswith("//"))
    assert code.count("zustand.approval_state !== 'granted'") == 2, \
        "beide Kanaele pruefen den wirksamen Freigabezustand"


def test_der_strukturwaechter_umfasst_auch_den_kalender():
    """Die Luecke, an der die erste G-Reparatur vorbeilief.

    Der alte Wächter suchte `.approve(` und `approveMutation(` und hielt eine
    Menge aus drei Kontaktdateien fuer geschlossen. `gibFrei(` — derselbe
    Grenzuebergang im Kalender — war fuer ihn unsichtbar. Dass die Grenze
    beide Module umfasst, ist deshalb eine eigene Behauptung und wird eigens
    geprueft.

    Die geschlossene Mengenaussage selbst steht in
    `tests/personal/test_approval_boundary_produkt.py` — eine normative
    Stelle je Sachverhalt.
    """
    from tools.guards.approval_boundary import analysiere

    ergebnis = analysiere(_REPO / "frontend/src")
    saatdateien = {s.datei for s in ergebnis.saat}
    assert "personal/calendar/mutationsApi.ts" in saatdateien
    assert "personal/contacts/api.ts" in saatdateien
    # Und die Kalender-Freigabe haengt an einer reinen Freigabefunktion.
    for datei in ("personal/calendar/TerminFormular.tsx",
                  "personal/calendar/TerminLoeschen.tsx"):
        assert ergebnis.erreicht(datei, "freigeben"), datei


def test_jede_freigabe_haengt_an_einem_klick():
    """In beiden Oberflaechendateien steht `approve` in einem onClick."""
    for name in ["personal/contacts/status/ContactsStatusSurface.tsx",
                 "personal/contacts/editor/dialogs.tsx"]:
        text = (_REPO / "frontend/src" / name).read_text(encoding="utf-8")
        for i, zeile in enumerate(text.splitlines()):
            if ".approve(" not in zeile or zeile.lstrip().startswith("//"):
                continue
            umfeld = "\n".join(text.splitlines()[max(0, i - 3):i + 1])
            assert "onClick" in umfeld, f"{name}:{i + 1} — {zeile.strip()}"


def test_der_workspace_fuehrt_nichts_selbst_aus():
    """Vorbereiten oeffnet die Vorschau; ausgefuehrt wird am Vorgang."""
    quelle = (_REPO / "frontend/src/personal/contacts/workspace/"
              "ContactsWorkspace.tsx").read_text(encoding="utf-8")
    code = "\n".join(z for z in quelle.splitlines()
                     if not z.lstrip().startswith("//"))
    assert "quelle.approve(" not in code
    assert "quelle.execute(" not in code
    assert "setVorschau(m)" in code
