"""The stand-in engine used when no inference backend is reachable.

Its whole job is to keep the API server startable while making every
inference request fail loudly and locally. Both halves are asserted here:
it must never look healthy, and it must never quietly succeed.
"""

from __future__ import annotations

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine import EngineConnectionError
from openjarvis.engine.unavailable import NO_ENGINE_MESSAGE, UnavailableEngine


def _messages() -> list[Message]:
    return [Message(role=Role.USER, content="hallo")]


def test_meldet_sich_nie_als_gesund() -> None:
    """Ein Health-Check darf nie eine funktionierende Engine behaupten."""
    assert UnavailableEngine().health() is False


def test_listet_keine_modelle() -> None:
    assert UnavailableEngine().list_models() == []


def test_kann_kein_modell_bedienen() -> None:
    """`can_serve` False haelt die Auswahl davon ab, sie einer echten
    Engine vorzuziehen."""
    assert UnavailableEngine().can_serve("irgendein-modell") is False


def test_generate_scheitert_statt_leer_zu_antworten() -> None:
    with pytest.raises(EngineConnectionError) as fehler:
        UnavailableEngine().generate(_messages(), model="m")
    # Die Meldung sagt, was fehlt und was zu tun ist — eine leere Antwort
    # waere die gefaehrlichere Variante, weil sie wie Erfolg aussieht.
    assert NO_ENGINE_MESSAGE in str(fehler.value)


@pytest.mark.asyncio
async def test_stream_scheitert_ebenfalls() -> None:
    with pytest.raises(EngineConnectionError):
        async for _ in UnavailableEngine().stream(_messages(), model="m"):
            pass


@pytest.mark.asyncio
async def test_stream_full_scheitert_ebenfalls() -> None:
    with pytest.raises(EngineConnectionError):
        async for _ in UnavailableEngine().stream_full(_messages(), model="m"):
            pass


def test_ist_nicht_registriert() -> None:
    """Entdeckung und Auswahl duerfen sie nie finden.

    Sie ist ausschliesslich eine ausdrueckliche Notloesung in `serve`,
    nachdem `get_engine()` leer zurueckkam.
    """
    assert "unavailable" not in set(EngineRegistry.keys())
