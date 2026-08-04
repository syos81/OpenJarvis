"""Härtung der Phase-A-Abnahme: Kanalsemantik und Smoke-Isolation.

**Kontaktfrei, ohne Netz, ohne Livedatenbank.** Alle Datenbanken sind
temporär; alle Pfade sind erfundene Verzeichnisse. Kein Test dieser Datei
darf die produktive Datenbank auch nur öffnen — mehrere von ihnen prüfen
genau das.

Zwei Fehler dieses Stands werden hier festgenagelt, damit sie nicht
zurückkehren:

1. Ein Release meldete `create_supported: true`, obwohl kein nativer Save
   existiert. „Unterstützt" heisst ab jetzt: ausführbar.
2. Ein Smoke lief gegen `~/.openjarvis` und migrierte die produktive
   Datenbank. Der Smoke-Vertrag prüft seinen eigenen Datenpfad, bevor
   irgendetwas startet.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from personaljarvis.contacts.application.app_channel import (
    MODE_DISABLED,
    MODE_FAKE_DEBUG,
    AppChannelCapabilities,
    InconsistentCapabilities,
    app_channel_capabilities,
    fake_debug_capabilities,
)

WURZEL = Path(__file__).resolve().parents[3]


def _smoke_modul():
    """Lädt den Harness aus `scripts/` — er gehört bewusst nicht ins Paket.

    Ein Abnahmewerkzeug im Wheel wäre Testlogik im Produktpfad; genau das
    soll es nicht geben. Der Import über den Dateipfad hält die Grenze.
    """
    pfad = WURZEL / "scripts/personal/phase_a_smoke.py"
    spec = importlib.util.spec_from_file_location("phase_a_smoke", pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules["phase_a_smoke"] = modul
    spec.loader.exec_module(modul)
    return modul


smoke = _smoke_modul()


# ═══ A · Release meldet nichts, was er nicht kann ═══════════════════════════
class TestReleaseFaehigkeiten:
    def test_release_meldet_jede_schreibfaehigkeit_falsch(self):
        caps = app_channel_capabilities()
        assert caps.channel == "app_process"
        assert caps.channel_mode == MODE_DISABLED
        assert caps.provider_write_enabled is False
        assert caps.create_supported is False
        assert caps.update_supported is False
        assert caps.delete_supported is False

    def test_keine_umgebungsvariable_oeffnet_den_kanal(self, monkeypatch):
        """Der Kern liest hier nichts aus der Umgebung — auch nichts Nettes."""
        for name in ("OPENJARVIS_CONTACTS_FAKE_EXECUTION",
                     "PERSONAL_JARVIS_PROVIDER_WRITE",
                     "OPENJARVIS_CONTACTS_CREATE_SUPPORTED",
                     "PJ_CONTACTS_FAKE", "DEBUG"):
            monkeypatch.setenv(name, "1")
        caps = app_channel_capabilities()
        assert caps.channel_available is False
        assert caps.provider_write_enabled is False
        assert caps.create_supported is False

    def test_das_modul_liest_die_umgebung_gar_nicht(self):
        quelle = (WURZEL / "src/personaljarvis/contacts/application/"
                  "app_channel.py").read_text(encoding="utf-8")
        # Der Modul-Docstring nennt `os.environ` als Verbot — eine Prüfung,
        # die daran scheitert, bestrafte die Begründung statt den Code.
        code = quelle.split('"""', 2)[-1]
        code = "\n".join(z for z in code.splitlines()
                         if not z.lstrip().startswith("#"))
        for verboten in ("os.environ", "getenv", "import os"):
            assert verboten not in code, verboten

    def test_der_kanal_ist_nicht_verfuegbar(self):
        assert app_channel_capabilities().channel_available is False

    def test_keine_operation_ist_erlaubt(self):
        caps = app_channel_capabilities()
        for operation in ("create", "update", "delete"):
            assert caps.darf_ausfuehren(operation) is False


# ═══ B · Der synthetische Kanal ist die einzige Ausnahme ════════════════════
class TestFakeDebug:
    def test_fake_meldet_create_und_nennt_sich_fake(self):
        caps = fake_debug_capabilities()
        assert caps.channel_mode == MODE_FAKE_DEBUG
        assert caps.provider_write_enabled is True
        assert caps.create_supported is True
        assert caps.update_supported is False
        assert caps.delete_supported is False

    def test_fake_erlaubt_nur_die_gemeldete_operation(self):
        caps = fake_debug_capabilities()
        assert caps.darf_ausfuehren("create") is True
        assert caps.darf_ausfuehren("update") is False
        assert caps.darf_ausfuehren("delete") is False

    def test_unbekannte_operationen_sind_falsch_nicht_wahr(self):
        caps = fake_debug_capabilities()
        for unfug in ("", "CREATE", "creat", "*", "upsert", None):
            assert caps.supports(unfug) is False, unfug
            assert caps.darf_ausfuehren(unfug) is False, unfug

    def test_der_fake_steht_in_keiner_route_und_keinem_start(self):
        for datei in ("src/personaljarvis/contacts/api/routes.py",
                      "src/personaljarvis/bootstrap.py",
                      "src/personaljarvis/__init__.py"):
            quelle = (WURZEL / datei).read_text(encoding="utf-8")
            assert "fake_debug_capabilities" not in quelle, datei


# ═══ C · Widersprüchliche Handshakes sind fail-closed ═══════════════════════
class TestWidersprueche:
    def _bau(self, **abweichung) -> AppChannelCapabilities:
        basis = dict(
            schema_version=3, channel="app_process",
            channel_mode=MODE_DISABLED, native_create_available=True,
            create_supported=False, update_supported=False,
            delete_supported=False, provider_write_enabled=False,
            architecture="x86_64", app_version="1.0.1",
            native_bridge_version="0",
        )
        basis.update(abweichung)
        return AppChannelCapabilities(**basis)

    def test_operation_ohne_schreibrecht_wird_abgewiesen(self):
        with pytest.raises(InconsistentCapabilities):
            self._bau(create_supported=True)

    def test_schreibrecht_bei_abgeschaltetem_kanal_wird_abgewiesen(self):
        with pytest.raises(InconsistentCapabilities):
            self._bau(provider_write_enabled=True)

    def test_unbekannter_kanalmodus_wird_abgewiesen(self):
        with pytest.raises(InconsistentCapabilities):
            self._bau(channel_mode="native_soon")

    def test_fremder_kanal_wird_abgewiesen(self):
        with pytest.raises(InconsistentCapabilities):
            self._bau(channel="cli_sidecar")

    def test_der_gueltige_fake_geht_durch(self):
        caps = self._bau(channel_mode=MODE_FAKE_DEBUG,
                         provider_write_enabled=True, create_supported=True)
        assert caps.darf_ausfuehren("create") is True


# ═══ D · Der Claim prüft beides ═════════════════════════════════════════════
class TestClaimTorwaechter:
    def test_ohne_faehigkeitssatz_gibt_es_keinen_auftrag(self, module):
        from personaljarvis.contacts.application.app_execution import (
            AppExecutionService,
            ChannelNotEnabled,
        )
        dienst = AppExecutionService(module, channel_capabilities=None)
        with pytest.raises(ChannelNotEnabled):
            dienst.claim("egal")

    def test_der_releasezustand_verweigert_jeden_claim(self, module):
        from personaljarvis.contacts.application.app_execution import (
            AppExecutionService,
            ChannelNotEnabled,
        )
        dienst = AppExecutionService(
            module, channel_capabilities=app_channel_capabilities())
        with pytest.raises(ChannelNotEnabled):
            dienst.claim("egal")

    def test_der_claim_prueft_die_operation_einzeln(self):
        """Ein Kanal mit `create` darf kein `delete` beanspruchen."""
        caps = fake_debug_capabilities(create=True, delete=False)
        assert caps.darf_ausfuehren("create") is True
        assert caps.darf_ausfuehren("delete") is False

    def test_der_quelltext_prueft_konjunktiv(self):
        quelle = (WURZEL / "src/personaljarvis/contacts/application/"
                  "app_execution.py").read_text(encoding="utf-8")
        assert "darf_ausfuehren(zeile[\"command\"])" in quelle


# ═══ E · Die Route bleibt fail-closed ═══════════════════════════════════════
class TestRoute:
    @staticmethod
    def _client(module):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from personaljarvis.contacts.api.routes import create_contacts_router
        app = FastAPI()
        app.include_router(create_contacts_router(module))
        return TestClient(app)

    def test_die_route_meldet_den_abgeschalteten_kanal(self, module):
        client = self._client(module)
        antwort = client.get("/v1/personal/contacts/app-channel")
        assert antwort.status_code == 200
        koerper = antwort.json()
        assert koerper["channel_mode"] == "disabled"
        assert koerper["provider_write_enabled"] is False
        assert koerper["create_supported"] is False
        assert koerper["update_supported"] is False
        assert koerper["delete_supported"] is False

    def test_die_route_nimmt_keine_faehigkeit_entgegen(self, module):
        """Ein Client, der Fähigkeiten *behauptet*, ändert nichts."""
        client = self._client(module)
        antwort = client.get(
            "/v1/personal/contacts/app-channel",
            params={"create_supported": "true", "provider_write_enabled": "true"},
            headers={"X-Provider-Write-Enabled": "true"})
        assert antwort.json()["create_supported"] is False
        assert antwort.json()["provider_write_enabled"] is False


# ═══ F · Smoke-Vertrag ══════════════════════════════════════════════════════
class TestSmokeVertrag:
    def test_das_profil_ist_privat_und_vollstaendig(self, tmp_path):
        profil = smoke.erzeuge_profil(tmp_path)
        assert profil.home.is_dir()
        assert oct(profil.home.stat().st_mode)[-3:] == "700"
        assert profil.config.is_file()
        assert "enabled = false" in profil.config.read_text(encoding="utf-8")
        assert profil.datenbank.parent.is_dir()

    def test_der_wirksame_pfad_folgt_dem_profil(self, tmp_path):
        profil = smoke.erzeuge_profil(tmp_path)
        wirksam = smoke.wirksamer_datenbankpfad(profil.home)
        assert wirksam == profil.datenbank
        assert str(wirksam).startswith(str(profil.home))

    def test_der_produktive_pfad_wird_unabhaengig_bestimmt(self, monkeypatch,
                                                          tmp_path):
        """Er darf sich nicht von derselben Variablen umlenken lassen.

        Sonst prüfte die Vorbedingung „meide die produktive Datei" gegen
        eine Datei, die es gar nicht mehr gibt — und bestünde immer.
        """
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
        assert smoke.produktiver_datenbankpfad() == (
            Path.home() / ".openjarvis" / "personal" / "jarvis.db")

    def test_ohne_produktive_datei_startet_nichts(self, tmp_path):
        profil = smoke.erzeuge_profil(tmp_path)
        with pytest.raises(smoke.SmokeVerletzung):
            smoke.pruefe_vorbedingungen(
                profil, produktiv=tmp_path / "gibt-es-nicht.db")

    def test_ein_profil_im_produktiven_ordner_wird_abgewiesen(self, tmp_path):
        gefaelscht = smoke.SmokeProfile(
            home=Path.home() / ".openjarvis",
            datenbank=Path.home() / ".openjarvis/personal/jarvis.db",
            config=Path.home() / ".openjarvis/config.toml")
        with pytest.raises(smoke.SmokeVerletzung):
            smoke.pruefe_vorbedingungen(gefaelscht)

    def test_ein_offenes_profilverzeichnis_wird_abgewiesen(self, tmp_path):
        profil = smoke.erzeuge_profil(tmp_path)
        os.chmod(profil.home, 0o755)
        produktiv = tmp_path / "produktiv.db"
        produktiv.write_bytes(b"SQLite format 3\x00")
        with pytest.raises(smoke.SmokeVerletzung):
            smoke.pruefe_vorbedingungen(profil, produktiv=produktiv)

    def test_ohne_analytics_abschaltung_startet_nichts(self, tmp_path):
        profil = smoke.erzeuge_profil(tmp_path)
        profil.config.write_text("[analytics]\nenabled = true\n", encoding="utf-8")
        produktiv = tmp_path / "produktiv.db"
        produktiv.write_bytes(b"SQLite format 3\x00")
        with pytest.raises(smoke.SmokeVerletzung):
            smoke.pruefe_vorbedingungen(profil, produktiv=produktiv)

    def test_der_gute_fall_liefert_beweise(self, tmp_path):
        profil = smoke.erzeuge_profil(tmp_path)
        produktiv = tmp_path / "produktiv.db"
        produktiv.write_bytes(b"SQLite format 3\x00" + b"\0" * 100)
        belege = smoke.pruefe_vorbedingungen(profil, produktiv=produktiv)
        assert belege["profil_rechte"] == "0o700"
        assert belege["wirksamer_pfad"] == str(profil.datenbank)
        assert belege["produktiv_digest_vorher"] == smoke.datei_digest(produktiv)

    def test_der_harness_uebergibt_die_variable_ueber_open(self):
        """`open` erbt die Shell-Umgebung nicht — deshalb `--env`."""
        quelle = (WURZEL / "scripts/personal/phase_a_smoke.py").read_text(
            encoding="utf-8")
        assert smoke.OPEN_ENV_FLAG == "--env"
        assert '"open", OPEN_ENV_FLAG, profil.env_argument' in quelle

    def test_der_harness_liegt_ausserhalb_des_pakets(self):
        assert not (WURZEL / "src/personaljarvis/tools").exists()
        for datei in WURZEL.glob("src/personaljarvis/**/*.py"):
            assert "phase_a_smoke" not in datei.read_text(encoding="utf-8"), datei
