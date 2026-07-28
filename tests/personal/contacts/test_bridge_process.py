"""Prozessmanager der Native-Bridge — Fehlermodi gegen Fake-Sidecars.

Kontaktfrei: es wird **ausschliesslich** gegen kleine Python-Fakes getestet.
Der echte Sidecar wird hier nicht gestartet, es gibt keine Contacts-Operation,
keinen TCC-Dialog und keinen Zugriff auf echte Kontakte.
"""

from __future__ import annotations

import os
import sys

import pytest

from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.errors import (
    BridgeProcessError,
    BridgeProtocolError,
    MutationOutcomeUnknown,
    ProcessFailureClass,
)
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import SidecarLocation, host_architecture

READY = (
    '{"type":"ready","protocolVersion":1,"bundleIdentifier":"test",'
    '"transactionAuthor":"test","keySetVersion":1,'
    '"authorizationStatus":"notDetermined","operations":["ping"],'
    '"capabilities":{"notesSupported":false,"changeHistorySupported":true}}'
)


def _fake(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text("#!/usr/bin/env python3\n"
                    "import sys, time, json, os\n"
                    f"READY = {READY!r}\n" + body)
    path.chmod(0o755)
    return SidecarLocation(path=path, architectures=(host_architecture(),),
                           host_architecture=host_architecture())


def _process(location) -> SidecarProcess:
    # Der Fake ist ein Python-Skript; es wird direkt ausgeführt (Shebang).
    return SidecarProcess(location)


def test_normaler_kontaktfreier_handshake(tmp_path):
    loc = _fake(tmp_path, "ok.py", """
print(READY, flush=True)
for line in sys.stdin:
    d = json.loads(line)
    print(json.dumps({"protocolVersion": 1, "requestId": d["requestId"],
                      "ok": True, "result": {"pong": True}}), flush=True)
""")
    proc = _process(loc)
    hs = proc.start()
    try:
        assert hs.protocol_version == protocol.PROTOCOL_VERSION
        envelope = proc.request(protocol.Operation.PING, timeout=5)
        assert envelope["ok"] is True
    finally:
        proc.stop()
    assert not proc.is_running


def test_keine_antwort_ergibt_request_timeout(tmp_path):
    loc = _fake(tmp_path, "silent.py", "print(READY, flush=True)\ntime.sleep(600)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=1.0)
    assert exc.value.failure_class == ProcessFailureClass.REQUEST_TIMEOUT
    assert exc.value.diagnostics.elapsed_seconds >= 1.0


def test_child_exit_wird_erkannt(tmp_path):
    loc = _fake(tmp_path, "exiter.py",
                "print(READY, flush=True)\nsys.stdin.readline()\nsys.exit(3)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=5)
    assert exc.value.failure_class == ProcessFailureClass.CHILD_EXITED
    assert exc.value.diagnostics.child_exit_code == 3


def test_sigabrt_wird_als_signal_erkannt(tmp_path):
    loc = _fake(tmp_path, "abort.py",
                "print(READY, flush=True)\nsys.stdin.readline()\nos.abort()\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=5)
    assert exc.value.failure_class == ProcessFailureClass.CHILD_SIGNALLED
    assert exc.value.diagnostics.child_signal is not None


def test_stdout_eof_bei_laufendem_child(tmp_path):
    # os.close(1): sys.stdout.close() allein erzeugt beim Eltern kein EOF.
    loc = _fake(tmp_path, "eof.py",
                "print(READY, flush=True)\nsys.stdin.readline()\n"
                "os.close(1)\ntime.sleep(600)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=5)
    assert exc.value.failure_class == ProcessFailureClass.STDOUT_EOF
    assert exc.value.diagnostics.stdout_eof is True


def test_falsche_request_id_wird_festgehalten(tmp_path):
    loc = _fake(tmp_path, "wrongid.py", """
print(READY, flush=True)
for line in sys.stdin:
    for k in range(60):
        print(json.dumps({"protocolVersion": 1, "requestId": 9000 + k,
                          "ok": True, "result": {}}), flush=True)
""")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=5)
    assert exc.value.failure_class == ProcessFailureClass.RESPONSE_ID_MISMATCH
    assert exc.value.diagnostics.wrong_response_ids


def test_ungueltiges_json_ergibt_protocol_error(tmp_path):
    loc = _fake(tmp_path, "badjson.py",
                "print(READY, flush=True)\nsys.stdin.readline()\n"
                "print('kein json', flush=True)\ntime.sleep(600)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=5)
    assert exc.value.failure_class == ProcessFailureClass.PROTOCOL_ERROR


def test_inkompatible_protokollversion_im_handshake(tmp_path):
    bad = READY.replace('"protocolVersion":1', '"protocolVersion":99')
    path = tmp_path / "oldproto.py"
    path.write_text("#!/usr/bin/env python3\nimport sys, time\n"
                    f"print({bad!r}, flush=True)\ntime.sleep(600)\n")
    path.chmod(0o755)
    loc = SidecarLocation(path=path, architectures=(host_architecture(),),
                          host_architecture=host_architecture())
    proc = SidecarProcess(loc)
    with pytest.raises(BridgeProtocolError):
        proc.start(timeout=5)


def test_antwort_mit_falscher_protokollversion(tmp_path):
    loc = _fake(tmp_path, "badver.py", """
print(READY, flush=True)
for line in sys.stdin:
    d = json.loads(line)
    print(json.dumps({"protocolVersion": 42, "requestId": d["requestId"],
                      "ok": True, "result": {}}), flush=True)
""")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=5)
    assert exc.value.failure_class == ProcessFailureClass.PROTOCOL_VERSION_MISMATCH


def test_stderr_wird_begrenzt_und_saniert(tmp_path):
    loc = _fake(tmp_path, "noisy.py", r"""
print(READY, flush=True)
sys.stdin.readline()
for i in range(200):
    print("[contacts-bridge] stufe%d" % i, file=sys.stderr, flush=True)
print("geheim: person@example.invalid", file=sys.stderr, flush=True)
time.sleep(600)
""")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.PING, timeout=1.5)
    tail = exc.value.diagnostics.stderr_tail
    assert len(tail) <= 20
    assert not any("@" in line for line in tail)
    assert any("redigiert" in line for line in tail)


def test_mutationstimeout_ergibt_outcome_unknown(tmp_path):
    loc = _fake(tmp_path, "silent2.py", "print(READY, flush=True)\ntime.sleep(600)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(MutationOutcomeUnknown) as exc:
        proc.request(protocol.Operation.CREATE, {"mutationId": "m"}, timeout=1.0)
    assert exc.value.failure_class == ProcessFailureClass.MUTATION_OUTCOME_UNKNOWN
    assert exc.value.underlying_class == ProcessFailureClass.REQUEST_TIMEOUT


def test_lesende_operation_wird_nicht_zu_outcome_unknown(tmp_path):
    loc = _fake(tmp_path, "silent3.py", "print(READY, flush=True)\ntime.sleep(600)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError) as exc:
        proc.request(protocol.Operation.CONTAINERS, timeout=1.0)
    assert not isinstance(exc.value, MutationOutcomeUnknown)


def test_kein_automatischer_retry(tmp_path):
    counter = tmp_path / "count.txt"
    loc = _fake(tmp_path, "counter.py", f"""
print(READY, flush=True)
CNT = {str(counter)!r}
for line in sys.stdin:
    d = json.loads(line)
    if d.get("operation") == "create":
        open(CNT, "a").write("x")
    time.sleep(600)
""")
    proc = _process(loc)
    proc.start()
    with pytest.raises(MutationOutcomeUnknown):
        proc.request(protocol.Operation.CREATE, {"mutationId": "m"}, timeout=1.5)
    assert counter.read_text() == "x", "genau ein create darf den Sidecar erreichen"


def test_kein_zombie_nach_fehler(tmp_path):
    loc = _fake(tmp_path, "silent4.py", "print(READY, flush=True)\ntime.sleep(600)\n")
    proc = _process(loc)
    proc.start()
    with pytest.raises(BridgeProcessError):
        proc.request(protocol.Operation.PING, timeout=1.0)
    assert not proc.is_running, "der Child muss zuverlaessig beendet sein"


def test_stop_ist_mehrfach_harmlos(tmp_path):
    loc = _fake(tmp_path, "ok2.py", """
print(READY, flush=True)
for line in sys.stdin:
    d = json.loads(line)
    print(json.dumps({"protocolVersion": 1, "requestId": d["requestId"],
                      "ok": True, "result": {"bye": True}}), flush=True)
    if d.get("operation") == "shutdown":
        sys.exit(0)
""")
    proc = _process(loc)
    proc.start()
    proc.stop()
    proc.stop()
    assert not proc.is_running
