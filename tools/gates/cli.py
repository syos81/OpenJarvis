"""Command line layer behind ``scripts/gate.sh``.

Block and phase are mandatory; there are no silent defaults, no interactive
selection and no status derived from free text. stdout always carries exactly
one machine readable JSON document, stderr only sanitized progress.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import ENGINE_VERSION
from . import RESULT_SCHEMA_VERSION
from . import engine as engine_module
from . import gitutil
from . import manifest as manifest_module
from . import sanitize
from . import statuses

USAGE = "usage: scripts/gate.sh --block <block-id> --phase <phase>"
PARAMETERS = ("block", "phase")


class UsageError(Exception):
    def __init__(self, reason_code, message):
        self.reason_code = reason_code
        super().__init__(message)


def parse_args(argv):
    values = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("--help", "-h"):
            raise UsageError("help_requested", USAGE)
        name = None
        inline = None
        if token.startswith("--") and "=" in token:
            name, _, inline = token[2:].partition("=")
        elif token.startswith("--"):
            name = token[2:]
        if name not in PARAMETERS:
            raise UsageError("unknown_parameter", f"unknown parameter: {token}")
        if name in values:
            raise UsageError(
                "duplicate_parameter", f"parameter given more than once: --{name}"
            )
        if inline is not None:
            value = inline
            index += 1
        else:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise UsageError(
                    "missing_value", f"parameter --{name} requires a value"
                )
            value = argv[index + 1]
            index += 2
        if not value:
            raise UsageError("missing_value", f"parameter --{name} requires a value")
        values[name] = value
    missing = [name for name in PARAMETERS if name not in values]
    if missing:
        raise UsageError(
            "missing_parameter",
            f"missing mandatory parameter(s): {', '.join('--' + m for m in missing)}",
        )
    return values


def _emit(document, stdout):
    stdout.write(json.dumps(document, sort_keys=True, indent=2) + "\n")
    stdout.flush()


def _error_document(reason_code, message, *, block=None, phase=None, status=None):
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "block": block,
        "phase": phase,
        "status": status,
        "error": True,
        "reason_code": reason_code,
        "message": sanitize.scrub(message),
    }


def main(argv=None, *, stdout=None, stderr=None, cwd=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    try:
        values = parse_args(argv)
    except UsageError as exc:
        stderr.write(f"{USAGE}\n")
        _emit(_error_document(exc.reason_code, str(exc)), stdout)
        return statuses.EXIT_USAGE

    block_id = values["block"]
    phase = values["phase"]

    if phase not in manifest_module.PHASES:
        _emit(
            _error_document(
                "unknown_phase",
                f"unknown phase: {phase}; known: {', '.join(manifest_module.PHASES)}",
                block=block_id,
                phase=phase,
            ),
            stdout,
        )
        return statuses.EXIT_USAGE

    try:
        worktree = gitutil.toplevel(cwd or Path.cwd())
    except gitutil.GitError as exc:
        _emit(
            _error_document("worktree_undetermined", str(exc), block=block_id, phase=phase),
            stdout,
        )
        return statuses.EXIT_BLOCKED

    manifest_path = manifest_module.manifest_path_for(worktree, block_id)
    if not manifest_path.is_file():
        known = ", ".join(manifest_module.known_block_ids(worktree)) or "none"
        _emit(
            _error_document(
                "unknown_block",
                f"unknown block: {block_id}; known blocks: {known}",
                block=block_id,
                phase=phase,
            ),
            stdout,
        )
        return statuses.EXIT_USAGE

    try:
        manifest = manifest_module.load(manifest_path)
    except manifest_module.ManifestError as exc:
        _emit(
            _error_document(
                "manifest_invalid",
                str(exc),
                block=block_id,
                phase=phase,
                status=statuses.FAIL,
            ),
            stdout,
        )
        return statuses.EXIT_FAIL

    if manifest.block_id != block_id:
        _emit(
            _error_document(
                "manifest_block_mismatch",
                f"manifest declares {manifest.block_id}, requested {block_id}",
                block=block_id,
                phase=phase,
                status=statuses.FAIL,
            ),
            stdout,
        )
        return statuses.EXIT_FAIL

    gate = engine_module.GateEngine(
        worktree=worktree, manifest=manifest, progress=stderr
    )
    try:
        result = gate.run_phase(phase)
    except Exception as exc:  # noqa: BLE001 - deterministic internal error path
        gate.release_baseline()
        _emit(
            _error_document(
                "engine_internal_error",
                f"{type(exc).__name__}: {exc}",
                block=block_id,
                phase=phase,
            ),
            stdout,
        )
        return statuses.EXIT_INTERNAL
    _emit(result, stdout)
    return statuses.exit_code(result["status"])


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
