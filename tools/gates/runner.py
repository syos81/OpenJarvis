"""Safe check execution and structured output parsing.

Checks are executed from an argv list only — never through a composed shell
string and never through ``eval``. Every run gets an explicit timeout, a fixed
locale and a reduced environment. The complete raw output goes to the
gitignored raw log; only structured, normalised information leaves this
module.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import evidence
from . import gitutil
from . import paths as gate_paths
from . import sanitize

OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"
OUTCOME_ERROR = "error"
OUTCOME_TIMEOUT = "timeout"

_UNITTEST_PROBLEM_RE = re.compile(
    r"^(FAIL|ERROR):\s+(\S+)\s+\(([^)]+)\)", re.MULTILINE
)
_UNITTEST_SUMMARY_RE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_UNITTEST_EXC_RE = re.compile(r"^([A-Za-z_][\w.]*Error|AssertionError):", re.MULTILINE)


class RunResult:
    __slots__ = (
        "check_id",
        "exit_code",
        "timed_out",
        "duration_ms",
        "raw_log_path",
        "raw_log_sha256",
        "structured",
        "display_argv",
    )

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    @property
    def outcome(self):
        return self.structured.get("outcome", OUTCOME_ERROR)

    @property
    def passed(self):
        return self.outcome == OUTCOME_PASSED


def resolve_argv(argv, substitutions):
    resolved = []
    for token in argv:
        for placeholder, value in substitutions.items():
            token = token.replace(placeholder, str(value))
        resolved.append(token)
    return resolved


def parse_unittest(stdout, stderr, exit_code):
    """Derive structured failures from ``python -m unittest`` output."""
    combined = f"{stdout}\n{stderr}"
    failures = []
    for kind, test_name, test_module in _UNITTEST_PROBLEM_RE.findall(combined):
        failures.append(
            {
                "id": f"{test_module}.{test_name}",
                "category": "test_failure" if kind == "FAIL" else "test_error",
                "class": kind,
                "code": "",
                "frames": [],
            }
        )
    for exception_class in sorted(set(_UNITTEST_EXC_RE.findall(combined))):
        for failure in failures:
            if failure["class"] in ("FAIL", "ERROR") and not failure["code"]:
                failure["code"] = exception_class
                break
    ran_match = _UNITTEST_SUMMARY_RE.search(combined)
    outcome = OUTCOME_PASSED if exit_code == 0 else OUTCOME_FAILED
    if exit_code != 0 and not failures:
        outcome = OUTCOME_ERROR
    return {
        "outcome": outcome,
        "structural": True,
        "failures": sorted(failures, key=lambda item: item["id"]),
        "diagnostics": [] if ran_match else ["unittest_summary_missing"],
        "tests_run": int(ran_match.group(1)) if ran_match else None,
    }


def parse_gate_report(report_path, exit_code):
    """Read the structured report a gate runner wrote to ``GATE_REPORT``."""
    path = Path(report_path)
    if not path.is_file():
        return {
            "outcome": OUTCOME_ERROR,
            "structural": False,
            "failures": [],
            "diagnostics": ["gate_report_missing"],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "outcome": OUTCOME_ERROR,
            "structural": False,
            "failures": [],
            "diagnostics": ["gate_report_unreadable"],
        }
    if not isinstance(data, dict) or data.get("outcome") not in (
        OUTCOME_PASSED,
        OUTCOME_FAILED,
        OUTCOME_ERROR,
    ):
        return {
            "outcome": OUTCOME_ERROR,
            "structural": False,
            "failures": [],
            "diagnostics": ["gate_report_invalid"],
        }
    failures = data.get("failures") or []
    if not isinstance(failures, list):
        failures = []
    diagnostics = data.get("diagnostics") or []
    if not isinstance(diagnostics, list):
        diagnostics = []
    if data.get("outcome") == OUTCOME_PASSED and exit_code != 0:
        return {
            "outcome": OUTCOME_ERROR,
            "structural": False,
            "failures": [],
            "diagnostics": ["gate_report_contradicts_exit_code"],
        }
    return {
        "outcome": data["outcome"],
        "structural": True,
        "failures": failures,
        "diagnostics": [str(item) for item in diagnostics],
        "detail_count": data.get("detail_count"),
    }


def parse_exit_only(exit_code):
    return {
        "outcome": OUTCOME_PASSED if exit_code == 0 else OUTCOME_FAILED,
        # An exit code alone is never a structural cause.
        "structural": False,
        "failures": [],
        "diagnostics": [] if exit_code == 0 else ["non_zero_exit_code"],
    }


def execute(
    check,
    *,
    worktree,
    target_dir,
    tools_dir,
    python_executable,
    raw_log_dir,
    run_id,
    label,
):
    """Execute one argv check and return a :class:`RunResult`."""
    runner = check.runner
    cwd = Path(target_dir if runner.get("cwd") == "target" else worktree)
    gate_paths.ensure_private_dir(raw_log_dir)
    report_path = Path(raw_log_dir) / f"{run_id}.{label}.{check.check_id}.report.json"
    raw_log_path = Path(raw_log_dir) / f"{run_id}.{label}.{check.check_id}.log"
    if report_path.exists():
        report_path.unlink()

    substitutions = {
        "${GATE_PYTHON}": python_executable,
        "${GATE_TOOLS}": str(Path(tools_dir)),
        "${GATE_WORKTREE}": str(Path(worktree)),
        "${GATE_REPORT}": str(report_path),
    }
    argv = resolve_argv(runner["argv"], substitutions)
    env = gitutil.deterministic_env(
        {
            "GATE_REPORT": str(report_path),
            "GATE_WORKTREE": str(worktree),
            "GATE_TARGET": str(cwd),
            "GATE_TOOLS": str(Path(tools_dir)),
            "GATE_ENGINE_ROOT": str(Path(worktree)),
            "PYTHONPATH": str(Path(worktree)),
        }
    )

    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, never a shell string
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=check.timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
    except FileNotFoundError as exc:
        timed_out = False
        exit_code = 127
        stdout = ""
        stderr = f"runner not executable: {exc}"
    duration_ms = int((time.monotonic() - started) * 1000)

    raw_log = (
        "# gate raw log — gitignored runtime evidence, never commit or quote\n"
        f"# check_id: {check.check_id}\n"
        f"# argv: {json.dumps(argv)}\n"
        f"# cwd: {cwd}\n"
        f"# exit_code: {exit_code}\n"
        f"# timed_out: {timed_out}\n"
        f"# duration_ms: {duration_ms}\n"
        "--- stdout ---\n"
        f"{stdout}\n"
        "--- stderr ---\n"
        f"{stderr}\n"
    )
    raw_log_sha256 = evidence.write_raw_log(raw_log_path, raw_log)

    if timed_out:
        structured = {
            "outcome": OUTCOME_TIMEOUT,
            "structural": False,
            "failures": [],
            "diagnostics": ["check_timeout"],
        }
    elif exit_code == 127 and not stdout:
        structured = {
            "outcome": OUTCOME_ERROR,
            "structural": False,
            "failures": [],
            "diagnostics": ["runner_not_executable"],
        }
    elif check.parser == "gate_json":
        structured = parse_gate_report(report_path, exit_code)
    elif check.parser == "unittest":
        structured = parse_unittest(stdout, stderr, exit_code)
    else:
        structured = parse_exit_only(exit_code)

    # Defence in depth: nothing structured may carry personal data onward.
    sanitize.assert_clean(structured, f"$structured.{check.check_id}")

    if report_path.exists():
        try:
            os.chmod(str(report_path), 0o600)
        except OSError:  # pragma: no cover
            pass

    return RunResult(
        check_id=check.check_id,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        raw_log_path=raw_log_path,
        raw_log_sha256=raw_log_sha256,
        structured=structured,
        display_argv=[sanitize.scrub(token, max_length=80) for token in argv],
    )
