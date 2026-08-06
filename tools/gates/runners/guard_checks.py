#!/usr/bin/env python3
"""B0a-4 guard runners.

Modes:

``rule-changes``        every changed check rule declares both mandatory tests
``violation-corpus``    the recognised violation set never shrinks
``history-matrix``      the local history rewrite audit is complete and bound
``fail-closed-paths``   no reachable silent exit remains in the guard entries
``package-determinism`` the package hash is reproducible from the source
``no-worktree-fallback`` the active chain never falls back into a worktree
``owner-activation``    the activation helper refuses to run unprivileged
``exception-policy``    the owner exception stays narrow and single use
``active-guard``        read only verification of the installed active guard
``tamper``              the guarded session cannot change the protection chain
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates.runners import _report  # noqa: E402
from tools.guard import owner_exception  # noqa: E402
from tools.guard import rules as guard_rules  # noqa: E402

GUARD_ENTRY_SCRIPTS = (
    ".claude/hooks/pretooluse_guard.sh",
    "tools/guardpkg/bootstrap.sh",
)
DEFAULT_INSTALL_ROOT = "/usr/local/jarvis-guard"
POLICY_FILE = "/Library/Application Support/ClaudeCode/managed-settings.json"
SYSTEM_PYTHON = "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"


def _fail(identifier, code):
    return _report.failure(identifier, category="guard", code=code)


def _load(root, relative):
    return json.loads((Path(root) / relative).read_text(encoding="utf-8"))


# -- rule change metagates --------------------------------------------------

def _test_reference_resolves(root, reference):
    file_part, _, test_part = str(reference).partition("::")
    target = Path(root) / file_part
    if not target.is_file():
        return False
    if not test_part:
        return True
    content = target.read_text(encoding="utf-8", errors="replace")
    return all(fragment in content for fragment in test_part.split("::") if fragment)


def mode_rule_changes(args):
    root = Path.cwd()
    failures = []
    data = _load(root, "config/guard/rule-changes.json")
    changes = data.get("changes", [])
    if not changes:
        failures.append(_fail("rule_changes.empty", "no_declared_rule_change"))
    for change in changes:
        identifier = change.get("change_id", "<unnamed>")
        for field in ("sharpening_test", "counter_test"):
            reference = change.get(field, "")
            if not reference:
                failures.append(_fail(f"{identifier}.{field}", "test_missing"))
                continue
            if not _test_reference_resolves(root, reference):
                failures.append(
                    _fail(f"{identifier}.{field}", "test_reference_unresolved")
                )
        if change.get("violation_set_effect") == "shrinks":
            if not change.get("owner_decision"):
                failures.append(
                    _fail(identifier, "shrinking_change_without_owner_decision")
                )
    for relaxation in data.get("declared_relaxations", []):
        if not relaxation.get("owner_decision"):
            failures.append(
                _fail(
                    relaxation.get("relaxation_id", "<unnamed>"),
                    "relaxation_without_owner_decision",
                )
            )
    for fixture in data.get("fixtures", []):
        path = fixture.get("path", "")
        if not path or not (root / path).exists():
            failures.append(_fail(f"fixture.{path}", "fixture_path_missing"))
        if path.startswith("/"):
            failures.append(_fail(f"fixture.{path}", "fixture_path_absolute"))
        if not fixture.get("purpose"):
            failures.append(_fail(f"fixture.{path}", "fixture_without_purpose"))
        if not _test_reference_resolves(root, fixture.get("abuse_test", "")):
            failures.append(_fail(f"fixture.{path}", "abuse_test_unresolved"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_violation_corpus(args):
    root = Path.cwd()
    failures = []
    corpus = _load(root, "config/guard/violation-corpus.json")
    rules = guard_rules.load_rules(root / "tools" / "guard" / "rules.json")
    detected = 0
    previously = 0
    for entry in corpus.get("entries", []):
        identifier = entry.get("entry_id", "<unnamed>")
        command = entry.get("command", "")
        expected = entry.get("expected_code")
        code, _layer = guard_rules.evaluate_command(rules, command, cwd=str(root))
        if expected is None:
            if code is not None:
                failures.append(_fail(identifier, "unexpected_detection"))
        else:
            detected += 1
            if code != expected:
                failures.append(_fail(identifier, "expected_detection_missing"))
        if entry.get("previously_detected"):
            previously += 1
            if code is None:
                failures.append(_fail(identifier, "violation_set_shrunk"))
    diagnostics = [
        f"corpus_entries={len(corpus.get('entries', []))}",
        f"expected_detections={detected}",
        f"previously_detected={previously}",
    ]
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_history_matrix(args):
    root = Path.cwd()
    failures = []
    matrix = _load(root, "config/guard/history-rewrite-matrix.json")
    rules = guard_rules.load_rules(root / "tools" / "guard" / "rules.json")
    known = set(rules.codes())
    categories = set(matrix.get("categories", []))
    seen_blocked = set()
    for entry in matrix.get("operations", []):
        name = entry.get("operation", "<unnamed>")
        category = entry.get("category")
        if category not in categories:
            failures.append(_fail(name, "unknown_category"))
        if not entry.get("rationale"):
            failures.append(_fail(name, "rationale_missing"))
        if category == "blocked":
            code = entry.get("code", "")
            if code not in known:
                failures.append(_fail(name, "blocked_without_active_rule"))
            seen_blocked.add(code)
        elif entry.get("code"):
            failures.append(_fail(name, "code_on_non_blocked_entry"))
    if "git_commit_amend" not in seen_blocked:
        failures.append(_fail("matrix.amend", "mandatory_operation_not_blocked"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


# -- fail closed static checks ---------------------------------------------

_FAIL_OPEN_SENTINELS = (
    "must never break the session",
    "stays silent (exit 0)",
)


def _handler_releases(node):
    """True when an ``except`` handler could release the request.

    A handler is acceptable when it blocks (``emit_deny``), re-raises, or
    returns a value that is not a release. A handler that only swallows the
    exception, or returns nothing, is a fail open path.
    """
    body = ast.dump(ast.Module(body=list(node.body), type_ignores=[]))
    if "emit_deny" in body or "Raise" in body:
        return False
    for statement in ast.walk(ast.Module(body=list(node.body), type_ignores=[])):
        if isinstance(statement, ast.Return):
            if statement.value is None:
                return True
            if (
                isinstance(statement.value, ast.Constant)
                and statement.value.value is True
            ):
                return True
            return False
    return True


def mode_fail_closed_paths(args):
    root = Path.cwd()
    failures = []
    for relative in GUARD_ENTRY_SCRIPTS:
        path = root / relative
        if not path.is_file():
            failures.append(_fail(relative, "guard_entry_missing"))
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        text = "\n".join(lines)
        for sentinel in _FAIL_OPEN_SENTINELS:
            if sentinel in text:
                failures.append(_fail(relative, "fail_open_intent_documented"))
        if "permissionDecision" not in text or "deny" not in text:
            failures.append(_fail(relative, "no_deny_emitter"))
        for index, line in enumerate(lines):
            if line.strip() != "exit 0":
                continue
            if index == len(lines) - 1:
                continue
            window = "\n".join(lines[max(0, index - 3):index])
            if "printf" not in window:
                failures.append(
                    _fail(f"{relative}:{index + 1}", "silent_exit_path")
                )

    bootstrap = root / "tools" / "guardpkg" / "bootstrap.py"
    if not bootstrap.is_file():
        failures.append(_fail("tools/guardpkg/bootstrap.py", "bootstrap_missing"))
    else:
        source = bootstrap.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if _handler_releases(node):
                failures.append(
                    _fail(
                        f"bootstrap.py:{node.lineno}",
                        "except_handler_without_block",
                    )
                )
        # The bootstrap must not read its location or its module path from the
        # environment: no project directory, no interpreter search path.
        if "os.environ" in source or "getenv" in source:
            failures.append(_fail("bootstrap.py", "reads_environment"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_no_worktree_fallback(args):
    root = Path.cwd()
    failures = []
    bootstrap_py = (root / "tools" / "guardpkg" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    bootstrap_sh = (root / "tools" / "guardpkg" / "bootstrap.sh").read_text(
        encoding="utf-8"
    )
    for needle in ("tools/gates", "tools.gates", "tools/guard/", "rev-parse"):
        if needle in bootstrap_py or needle in bootstrap_sh:
            failures.append(_fail("bootstrap", "repository_fallback_present"))
    if "@@GUARD_ROOT@@" not in bootstrap_sh:
        failures.append(_fail("bootstrap.sh", "install_root_not_substituted"))
    if "@@GUARD_PYTHON@@" not in bootstrap_sh:
        failures.append(_fail("bootstrap.sh", "interpreter_not_substituted"))
    for suspicious in ("$PATH", "command -v", "which "):
        if suspicious in bootstrap_sh:
            failures.append(_fail("bootstrap.sh", "path_lookup_present"))
    hook = (root / ".claude" / "hooks" / "pretooluse_guard.sh").read_text(
        encoding="utf-8"
    )
    if "trust anchor" not in hook:
        failures.append(_fail("repository_hook", "authority_not_declared"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_package_determinism(args):
    root = Path.cwd()
    failures = []
    build = root / "tools" / "guardpkg" / "build.py"
    digests = []
    for _round in range(2):
        with tempfile.TemporaryDirectory(prefix="guard-build-") as stage:
            completed = subprocess.run(  # noqa: S603 - fixed argv
                [sys.executable, str(build), "--source", str(root), "--out", stage],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                shell=False,
                check=False,
            )
            if completed.returncode != 0:
                failures.append(_fail("build", "build_failed"))
                break
            payload = json.loads(completed.stdout.decode("utf-8"))
            digests.append(payload["package_sha256"])
            for name in payload["files"]:
                if name.startswith("/") or ".." in name:
                    failures.append(_fail(name, "absolute_path_in_package"))
                if name.endswith(".pyc"):
                    failures.append(_fail(name, "generated_file_in_package"))
    if len(digests) == 2 and digests[0] != digests[1]:
        failures.append(_fail("package", "hash_not_reproducible"))
    diagnostics = [f"package_sha256={digests[0]}"] if digests else []
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_owner_activation(args):
    """The activation helper must refuse to run without root privileges."""
    root = Path.cwd()
    failures = []
    installer = root / "scripts" / "guard-install.sh"
    exception_helper = root / "scripts" / "guard-exception.sh"
    for script in (installer, exception_helper):
        if not script.is_file():
            failures.append(_fail(script.name, "owner_helper_missing"))
            continue
        source = script.read_text(encoding="utf-8")
        if 'id -u' not in source or '"0"' not in source:
            failures.append(_fail(script.name, "root_check_missing"))
    if os.geteuid() == 0:
        failures.append(_fail("environment", "gate_must_not_run_as_root"))
        return _report.emit(_report.FAILED, failures)
    completed = subprocess.run(  # noqa: S603 - fixed argv
        [
            "/bin/bash",
            str(installer),
            "--commit",
            "0" * 40,
            "--expect-hash",
            "0" * 64,
            "--session-user",
            "nobody",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        shell=False,
        check=False,
    )
    combined = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    if completed.returncode == 0:
        failures.append(_fail("installer", "unprivileged_run_succeeded"))
    if "must run as root" not in combined:
        failures.append(_fail("installer", "root_refusal_not_reported"))
    completed = subprocess.run(  # noqa: S603 - fixed argv
        [
            "/bin/bash",
            str(exception_helper),
            "--worktree",
            str(root),
            "--command",
            "true",
            "--reason",
            "gate self check",
            "--confirm",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        shell=False,
        check=False,
    )
    combined = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    if completed.returncode == 0:
        failures.append(_fail("exception_helper", "unprivileged_run_succeeded"))
    if "must run as root" not in combined:
        failures.append(_fail("exception_helper", "root_refusal_not_reported"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


def mode_exception_policy(args):
    root = Path.cwd()
    failures = []
    rules = guard_rules.load_rules(root / "tools" / "guard" / "rules.json")
    policy = rules.exception_policy
    if int(policy["max_ttl_seconds"]) > 600:
        failures.append(_fail("policy.ttl", "ttl_above_hard_limit"))
    if int(policy["nonce_hex_length"]) < 32:
        failures.append(_fail("policy.nonce", "nonce_too_short"))
    if int(policy["reason_min_length"]) < 1:
        failures.append(_fail("policy.reason", "reason_not_mandatory"))

    source = (root / "tools" / "guard" / "owner_exception.py").read_text(
        encoding="utf-8"
    )
    for needle in ("O_EXCL", "wildcard_command", "reason_missing"):
        if needle not in source:
            failures.append(_fail("owner_exception", f"missing_{needle.lower()}"))
    if "ALLOW_ALL" in source:
        failures.append(_fail("owner_exception", "global_allow_present"))

    # A wildcard command and a missing reason must be rejected structurally.
    sample = owner_exception.build(
        nonce="a" * 32,
        worktree=str(root),
        command="git status",
        reason="synthetic gate probe",
        created_at=1000,
        ttl_seconds=600,
        guard_version="1.0.0",
    )
    for mutation, expected in (
        ({"command_canonical": "git *"}, "wildcard_command"),
        ({"reason": ""}, "reason_missing"),
        ({"expires_at": 1000 + 601}, "ttl_too_long"),
    ):
        broken = dict(sample)
        broken.update(mutation)
        try:
            owner_exception.parse(
                json.dumps(broken), policy=policy, guard_version="1.0.0"
            )
        except owner_exception.ExceptionCorrupt as exc:
            if exc.args and exc.args[0] not in (expected, "integrity_digest"):
                failures.append(_fail(expected, "unexpected_rejection_reason"))
        else:
            failures.append(_fail(expected, "invalid_exception_accepted"))
    return _report.emit(_report.PASSED if not failures else _report.FAILED, failures)


# -- live verification of the installed guard -------------------------------

def _owner_and_mode(path):
    info = os.lstat(path)
    return info.st_uid, stat.S_IMODE(info.st_mode), stat.S_ISLNK(info.st_mode)


def mode_active_guard(args):
    failures = []
    diagnostics = []
    root = Path(args.install_root or DEFAULT_INSTALL_ROOT)
    if not root.is_dir():
        return _report.emit(
            _report.BLOCKED,
            [_fail("install_root", "active_guard_not_installed")],
            ["the owner activation has not been performed"],
        )
    manifest_path = root / "active.json"
    if not manifest_path.is_file():
        return _report.emit(
            _report.BLOCKED,
            [_fail("active.json", "active_manifest_missing")],
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    diagnostics.append("guard_version=" + str(manifest.get("guard_version")))
    diagnostics.append("source_commit=" + str(manifest.get("source_commit")))
    diagnostics.append("package_sha256=" + str(manifest.get("package_sha256")))

    protected = [
        root,
        root / "bootstrap.sh",
        root / "bootstrap.py",
        manifest_path,
        root / "active",
    ]
    for path in protected:
        if not path.exists():
            failures.append(_fail(path.name, "protected_component_missing"))
            continue
        uid, mode, is_link = _owner_and_mode(path)
        if is_link:
            failures.append(_fail(path.name, "symlink_in_protection_chain"))
        if uid != 0:
            failures.append(_fail(path.name, "not_root_owned"))
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            failures.append(_fail(path.name, "group_or_other_writable"))

    sys.path.insert(0, str(root))
    try:
        import bootstrap as active_bootstrap  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        failures.append(_fail("bootstrap.py", "active_bootstrap_unloadable"))
        return _report.emit(_report.FAILED, failures, diagnostics)
    digest = active_bootstrap.package_digest(str(root / "active"))
    if digest != manifest.get("package_sha256"):
        failures.append(_fail("package", "active_hash_mismatch"))

    if args.expect_hash and args.expect_hash != manifest.get("package_sha256"):
        failures.append(_fail("package", "expected_hash_mismatch"))
    if args.expect_version and args.expect_version != manifest.get("guard_version"):
        failures.append(_fail("package", "expected_version_mismatch"))

    policy = Path(POLICY_FILE)
    if not policy.is_file():
        failures.append(_fail("managed_settings", "hook_registration_missing"))
    else:
        uid, mode, is_link = _owner_and_mode(policy)
        if uid != 0:
            failures.append(_fail("managed_settings", "not_root_owned"))
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            failures.append(_fail("managed_settings", "group_or_other_writable"))
        registration = json.loads(policy.read_text(encoding="utf-8"))
        commands = []
        for group in registration.get("hooks", {}).get("PreToolUse", []):
            for hook in group.get("hooks", []):
                commands.append(str(hook.get("command", "")))
        if str(root / "bootstrap.sh") not in commands:
            failures.append(_fail("managed_settings", "guard_not_registered"))
        for command in commands:
            if not command.startswith("/"):
                failures.append(_fail("managed_settings", "relative_hook_command"))

    interpreter = manifest.get("interpreter", SYSTEM_PYTHON)
    if not os.path.isfile(interpreter):
        failures.append(_fail("interpreter", "interpreter_missing"))
    else:
        uid, mode, _link = _owner_and_mode(interpreter)
        if uid != 0 or mode & (stat.S_IWGRP | stat.S_IWOTH):
            failures.append(_fail("interpreter", "interpreter_not_owner_controlled"))

    var = root / "var"
    for relative, expect_uid in (
        ("guard.log", 0),
        ("exceptions/pending", 0),
        ("exceptions/spent", 0),
    ):
        path = var / relative
        if not path.exists():
            failures.append(_fail(relative, "runtime_component_missing"))
            continue
        uid, _mode, _link = _owner_and_mode(path)
        if uid != expect_uid:
            failures.append(_fail(relative, "not_root_owned"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def _write_probe(path):
    """Try to write ``path``. Returns ``True`` when the write succeeded."""
    try:
        handle = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError:
        return False
    try:
        os.write(handle, b"probe")
    except OSError:
        return False
    finally:
        try:
            os.close(handle)
        except OSError:  # pragma: no cover
            pass
    try:
        os.unlink(str(path))
    except OSError:  # pragma: no cover - a leftover probe is reported below
        pass
    return True


def mode_tamper(args):
    """Every protected component must resist a write from this session."""
    failures = []
    diagnostics = []
    root = Path(args.install_root or DEFAULT_INSTALL_ROOT)
    if not root.is_dir():
        return _report.emit(
            _report.BLOCKED,
            [_fail("install_root", "active_guard_not_installed")],
        )
    if os.geteuid() == 0:
        return _report.emit(
            _report.FAILED,
            [_fail("environment", "tamper_probe_must_not_run_as_root")],
        )

    probes = (
        ("install_root", root / "tamper-probe"),
        ("active_dir", root / "active" / "tamper-probe"),
        ("package_module", root / "active" / "guard" / "rules.json"),
        ("active_manifest", root / "active.json"),
        ("bootstrap_sh", root / "bootstrap.sh"),
        ("bootstrap_py", root / "bootstrap.py"),
        ("policy_dir", Path(POLICY_FILE).parent / "tamper-probe"),
        ("hook_registration", Path(POLICY_FILE)),
        ("exception_pending", root / "var" / "exceptions" / "pending" / "probe.json"),
    )
    for name, path in probes:
        if _write_probe(path):
            failures.append(_fail(name, "session_can_write_protected_component"))
        else:
            diagnostics.append(f"{name}=not_writable")

    # The protocol must be append only, not rewritable.
    log = root / "var" / "guard.log"
    if log.is_file():
        try:
            handle = os.open(str(log), os.O_WRONLY | os.O_TRUNC)
        except OSError:
            diagnostics.append("guard_log=not_truncatable")
        else:
            os.close(handle)
            failures.append(_fail("guard_log", "session_can_truncate_protocol"))
        try:
            handle = os.open(str(log), os.O_WRONLY | os.O_APPEND)
        except OSError:
            failures.append(_fail("guard_log", "session_cannot_append_protocol"))
        else:
            os.close(handle)
            diagnostics.append("guard_log=appendable")

    # A consumed exception marker must not be removable.
    spent = root / "var" / "exceptions" / "spent"
    if spent.is_dir():
        marker = spent / "tamper-probe-marker"
        try:
            handle = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        except OSError:
            failures.append(_fail("spent", "session_cannot_claim_marker"))
        else:
            os.close(handle)
            try:
                os.unlink(str(marker))
            except OSError:
                diagnostics.append("spent=marker_not_removable")
            else:
                failures.append(_fail("spent", "session_can_remove_marker"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_architecture_declaration(args):
    """The variant assessment and the declared own feature count must exist."""
    root = Path.cwd()
    failures = []
    document = root / "docs" / "governance" / "b0a-4-guard-architecture.md"
    if not document.is_file():
        return _report.emit(
            _report.FAILED, [_fail("architecture", "variant_assessment_missing")]
        )
    text = document.read_text(encoding="utf-8")
    for token in (
        "Variante A",
        "Variante B",
        "Variante C",
        "verworfen",
        "gewählt",
        "ACL",
        "sudo",
        "Restbefunde",
    ):
        if token not in text:
            failures.append(_fail(f"architecture.{token}", "assessment_incomplete"))
    manifest = _load(root, "config/gates/blocks/b0a-4-guard.json")
    declared = manifest["feature_lineage"]["own_expected"]
    if str(declared) not in text:
        failures.append(_fail("architecture", "declared_count_not_stated"))
    lineage = _load(root, manifest["feature_lineage"]["lineage_file"])
    own = [
        feature
        for feature in lineage["features"]
        if str(feature["feature_id"]).startswith(
            manifest["feature_lineage"]["own_prefix"]
        )
    ]
    if len(own) != declared:
        failures.append(_fail("architecture", "own_feature_count_mismatch"))
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED,
        failures,
        [f"declared_own_features={declared}"],
    )


# -- live matrix against the installed guard --------------------------------

AMEND_OPTION = "--am" + "end"

LIVE_BLOCKED = (
    ("amend_plain", "git commit " + AMEND_OPTION),
    ("amend_no_edit_after", "git commit " + AMEND_OPTION + " --no-edit"),
    ("amend_no_edit_before", "git commit --no-edit " + AMEND_OPTION),
    ("amend_dash_c", "git -C /tmp/other commit " + AMEND_OPTION),
    ("amend_git_dir", "git --git-dir=/tmp/other/.git commit " + AMEND_OPTION),
    ("amend_work_tree", "git --work-tree=/tmp/other commit " + AMEND_OPTION),
    ("amend_env", "env GIT_EDITOR=true git commit " + AMEND_OPTION),
    ("amend_env_prefix", "GIT_EDITOR=true git commit " + AMEND_OPTION),
    ("amend_chained", "true && git commit " + AMEND_OPTION),
    ("amend_subshell", "(git commit " + AMEND_OPTION + ")"),
    ("filter_branch", "git filter-branch --all"),
    ("update_ref", "git update-ref refs/heads/probe HEAD"),
    ("reflog_expire", "git reflog expire --expire=now --all"),
    ("stash_clear", "git stash clear"),
    ("branch_force", "git branch -f probe HEAD"),
    ("unparseable", "echo 'unterminated"),
)

LIVE_PERMITTED = (
    ("status", "git status --short"),
    ("log", "git log --oneline -n 3"),
    ("listing", "ls -la"),
)


def _invoke_installed_guard(wrapper, command, cwd, environment=None):
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(cwd),
        }
    ).encode("utf-8")
    env = dict(os.environ)
    if environment:
        env.update(environment)
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["/bin/bash", str(wrapper)],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=60,
        shell=False,
        check=False,
    )
    raw = completed.stdout.decode("utf-8", "replace").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"malformed": raw[:200]}


def _live_matrix(wrapper, cwd, failures, diagnostics, prefix):
    for name, command in LIVE_BLOCKED:
        response = _invoke_installed_guard(wrapper, command, cwd)
        specific = (response or {}).get("hookSpecificOutput") or {}
        if specific.get("permissionDecision") != "deny":
            failures.append(_fail(f"{prefix}.{name}", "forbidden_command_not_blocked"))
        else:
            diagnostics.append(f"{prefix}.{name}=deny")
    for name, command in LIVE_PERMITTED:
        response = _invoke_installed_guard(wrapper, command, cwd)
        specific = (response or {}).get("hookSpecificOutput") or {}
        if specific.get("permissionDecision") == "deny":
            failures.append(_fail(f"{prefix}.{name}", "permitted_command_blocked"))
        else:
            diagnostics.append(f"{prefix}.{name}=released")


def mode_live_current(args):
    root = Path(args.install_root or DEFAULT_INSTALL_ROOT)
    wrapper = root / "bootstrap.sh"
    if not wrapper.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail("wrapper", "active_guard_not_installed")]
        )
    failures = []
    diagnostics = []
    _live_matrix(wrapper, Path.cwd(), failures, diagnostics, "calendar")

    # An empty or manipulated project directory must change nothing.
    for label, value in (
        ("empty", ""),
        ("manipulated", "/nonexistent/elsewhere"),
        ("foreign", "/tmp"),
    ):
        response = _invoke_installed_guard(
            wrapper,
            "git commit " + AMEND_OPTION,
            Path.cwd(),
            {"CLAUDE_PROJECT_DIR": value},
        )
        specific = (response or {}).get("hookSpecificOutput") or {}
        if specific.get("permissionDecision") != "deny":
            failures.append(
                _fail(f"project_dir.{label}", "project_dir_changes_the_decision")
            )
        else:
            diagnostics.append(f"project_dir.{label}=deny")
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


def mode_live_plain(args):
    """The same protection must hold in a worktree without any tooling."""
    root = Path(args.install_root or DEFAULT_INSTALL_ROOT)
    wrapper = root / "bootstrap.sh"
    if not wrapper.is_file():
        return _report.emit(
            _report.BLOCKED, [_fail("wrapper", "active_guard_not_installed")]
        )
    failures = []
    diagnostics = []
    with tempfile.TemporaryDirectory(prefix="guard-plain-") as stage:
        plain = Path(stage) / "plain"
        plain.mkdir()
        subprocess.run(  # noqa: S603 - fixed argv
            ["git", "init", "--quiet", "-b", "main", str(plain)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            shell=False,
            check=False,
        )
        if (plain / "tools").exists():
            failures.append(_fail("plain", "plain_worktree_has_tooling"))
        diagnostics.append("plain_worktree_has_tools_gates=False")
        _live_matrix(wrapper, plain, failures, diagnostics, "plain")
    return _report.emit(
        _report.PASSED if not failures else _report.FAILED, failures, diagnostics
    )


MODES = {
    "active-guard": mode_active_guard,
    "architecture-declaration": mode_architecture_declaration,
    "live-current": mode_live_current,
    "live-plain": mode_live_plain,
    "exception-policy": mode_exception_policy,
    "fail-closed-paths": mode_fail_closed_paths,
    "history-matrix": mode_history_matrix,
    "no-worktree-fallback": mode_no_worktree_fallback,
    "owner-activation": mode_owner_activation,
    "package-determinism": mode_package_determinism,
    "rule-changes": mode_rule_changes,
    "tamper": mode_tamper,
    "violation-corpus": mode_violation_corpus,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--install-root", default="")
    parser.add_argument("--expect-hash", default="")
    parser.add_argument("--expect-version", default="")
    args = parser.parse_args(argv)
    try:
        return MODES[args.mode](args)
    except (OSError, ValueError) as exc:
        return _report.emit(
            _report.ERROR,
            [_fail(args.mode, "runner_error")],
            [re.sub(r"/[^\s]*", "<path>", str(exc))[:200]],
        )


if __name__ == "__main__":
    sys.exit(main())
