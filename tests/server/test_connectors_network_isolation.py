"""The Slack connect rejection path reaches no real network (B0f finding).

Block B0e's handoff flagged ``test_connect_slack_bot_token_returns_400`` as a
possible sibling of the repaired Granola test, whose patch was discarded by a
module reload so the test silently probed the real network. The structural
analysis for B0f found the Slack case different: the ``xoxb-`` rejection is a
pure shape check (``_validate_user_token``) raised before the ``auth.test``
liveness call, and the test installs no patch a reload could discard.

This module turns that analysis into a mechanical proof, in both directions:

* the rejection test re-runs the exact request under a socket guard that
  makes any connection attempt raise — it can only pass if no network path
  is reached, and

* rule R9 applies to the guard itself: a second test proves the guard bites
  by driving the one token shape that *does* reach the liveness call and
  asserting the guard's marker surfaces in the HTTP error detail. A guard
  whose effect is never observed would be the very defect class B0e fixed.

No test here opens a real connection: the guard raises inside
``socket.socket.connect`` before any packet leaves the host.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

GUARD_MARKER = "b0f-network-guard"


@pytest.fixture()
def app():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    from openjarvis.server.connectors_router import create_connectors_router

    _app = FastAPI()
    _app.include_router(create_connectors_router())
    return TestClient(_app)


class NetworkAttempt(Exception):
    """Raised by the guard instead of letting a connection leave the host."""


@pytest.fixture()
def no_network(monkeypatch):
    """Make every socket connection attempt fail loudly."""

    def _blocked(self, address):
        raise NetworkAttempt(f"{GUARD_MARKER}: connection attempt to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    return _blocked


@pytest.fixture()
def slack_instance(tmp_path: Path):
    from openjarvis.connectors.slack_connector import SlackConnector
    from openjarvis.server.connectors_router import (
        _ensure_connectors_registered,
        _instances,
    )

    _ensure_connectors_registered()
    creds = tmp_path / "slack.json"
    _instances["slack"] = SlackConnector(credentials_path=str(creds))
    yield creds
    _instances.pop("slack", None)


def test_bot_token_rejection_reaches_no_network(app, slack_instance, no_network):
    """The xoxb rejection must hold with every network path hard-blocked."""
    resp = app.post("/v1/connectors/slack/connect", json={"token": "xoxb-fake-token"})
    assert resp.status_code == 400
    assert "xoxb" in resp.json()["detail"].lower()
    assert GUARD_MARKER not in resp.json()["detail"]
    assert not slack_instance.exists()


def test_the_network_guard_itself_bites(app, slack_instance, no_network):
    """Rule R9 for the guard: a user-shaped token reaches the liveness call,
    and the guard's marker must surface — proving the blocked path is the
    path the connector really takes, not a guard that guards nothing."""
    resp = app.post(
        "/v1/connectors/slack/connect", json={"token": "xoxp-shaped-but-fake"}
    )
    assert resp.status_code == 400
    assert GUARD_MARKER in resp.json()["detail"]
    assert not slack_instance.exists()
