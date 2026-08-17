"""Die produktive Vorschau — wohin geschrieben wird, für einen Menschen lesbar.

Bis Migration 0012 konnte die Vorschau die Frage „wohin?" nicht beantworten:
Sie führte `5EBEB6A2-…:ABAccount` und eine Art. Technisch eindeutig, für die
Entscheidung wertlos.

Drei Eigenschaften, deren Verletzung eine Freigabe erschleichen würde:

* Der Name kommt aus dem **Bestand**, nicht aus einer Ableitung der Kennung
  und schon gar nicht aus dem Frontend.
* Fehlt er, sagt die Vorschau das — statt die Kennung als Namen auszugeben.
* Ein lokaler Ablageort und ein synchronisiertes Konto sind unterscheidbar,
  **auch wenn beide leer sind**. Die Art trägt die Kategorie, die Anzahl nur
  den Zusammenhang.

Kontaktfrei: erfundene Werte, temporäre Datenbank.
"""

from __future__ import annotations

from personaljarvis.contacts.application import ContactsMutationService
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import (
    SqliteSyncStateRepository,
)

from .test_mutation_pipeline import (
    KONTO,
    AttrappenProvider,
    _container_bekannt,
    _create,
)


def _ablageort(module, kennung, *, art, name=None):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=kennung,
            key_set_version="v1", mode="delta", container_type=art,
            container_name=name))


def _vorschau(module, container):
    dienst = ContactsMutationService(module, AttrappenProvider())
    return dienst.prepare(_create(container_identifier=container)).preview


# ── Der Name stammt aus dem Bestand ──────────────────────────────────────────
def test_der_name_kommt_aus_dem_bestand(module):
    _container_bekannt(module)
    _ablageort(module, "container-1", art="cardDAV", name="iCloud")

    vorschau = _vorschau(module, "container-1")
    assert vorschau.container_name == "iCloud"
    assert vorschau.container_type == "cardDAV"
    # Die Kennung bleibt daneben stehen, sie wird nicht ersetzt.
    assert vorschau.container_identifier == "container-1"


def test_ohne_nachsync_sagt_die_vorschau_dass_der_name_fehlt(module):
    """Der Zustand direkt nach Migration 0012: die Zeile hat keinen Namen.

    `None` ist hier die ehrliche Antwort. Ein Rückfall auf die Kennung sähe
    aus wie eine Angabe und wäre keine.
    """
    _container_bekannt(module)
    _ablageort(module, "container-1", art="cardDAV", name=None)

    vorschau = _vorschau(module, "container-1")
    assert vorschau.container_name is None
    # Die Art ist trotzdem da — sie hing nie am Namen.
    assert vorschau.container_type == "cardDAV"
    assert vorschau.container_identifier == "container-1"


def test_der_name_wird_wortgleich_durchgereicht(module):
    """Weder abgeleitet noch geglättet — was der Provider nennt, steht da.

    Ein Name, den irgendeine Schicht „aufräumt", ist nicht mehr der Name, den
    der Eigentümer in seiner Kontakte-App sieht. Dann zeigte die Fläche eine
    dritte Wahrheit.
    """
    _container_bekannt(module)
    for gemeldet in ["iCloud", "Auf meinem Mac", "lukas@example.invalid",
                     "  Konto mit Rand  ".strip()]:
        _ablageort(module, "container-1", art="cardDAV", name=gemeldet)
        assert _vorschau(module, "container-1").container_name == gemeldet


# ── Art trägt die Kategorie, Anzahl nur den Zusammenhang ─────────────────────
def test_leeres_konto_und_leerer_lokaler_ablageort_bleiben_unterscheidbar(module):
    """Die Schärfung: Eine Null macht aus einem Konto keinen lokalen Ort."""
    _container_bekannt(module)
    _ablageort(module, "container-1", art="cardDAV", name="iCloud")
    _ablageort(module, "container-lokal", art="local", name="Auf meinem Mac")

    konto = _vorschau(module, "container-1")
    lokal = _vorschau(module, "container-lokal")

    # Beide leer …
    assert konto.container_contact_count == 0
    assert lokal.container_contact_count == 0
    # … und trotzdem verschieden, weil die Art es sagt.
    assert konto.container_type == "cardDAV"
    assert lokal.container_type == "local"
    assert konto.container_type != lokal.container_type


def test_die_anzahl_zaehlt_den_wirklichen_bestand(module):
    _container_bekannt(module)
    _ablageort(module, "container-1", art="cardDAV", name="iCloud")
    assert _vorschau(module, "container-1").container_contact_count == 0


# ── Die Anzeige ist Bestandteil der Freigabe ─────────────────────────────────
def test_ein_anderer_zielname_ergibt_einen_anderen_vorschaudigest(module):
    """Der Digest bindet, was auf der Fläche stand.

    Ohne diese Bindung deckte eine Freigabe dieselbe Nutzlast unter einem
    anderen Zielnamen — und der Zielname ist genau die Angabe, an der ein
    Mensch „wohin" erkennt.
    """
    _container_bekannt(module)
    _ablageort(module, "container-1", art="cardDAV", name="iCloud")
    erster = _vorschau(module, "container-1").digest

    _ablageort(module, "container-1", art="cardDAV", name="Arbeitskonto")
    zweiter = _vorschau(module, "container-1").digest

    assert erster != zweiter


def test_ein_fehlender_name_ist_ein_eigener_digest(module):
    """„Noch nicht gelesen" und „heisst iCloud" sind zwei Darstellungen."""
    _container_bekannt(module)
    _ablageort(module, "container-1", art="cardDAV", name=None)
    ohne = _vorschau(module, "container-1").digest

    _ablageort(module, "container-1", art="cardDAV", name="iCloud")
    mit = _vorschau(module, "container-1").digest

    assert ohne != mit
