"""Minimal, owner controlled guard bootstrap — the root of trust.

This file is installed into the owner controlled installation root and is the
only thing the registered hook executes. It is deliberately small and
self contained:

* it imports nothing from the repository and nothing from the guarded
  worktree,
* it derives the installation root from its own absolute location, never
  from ``CLAUDE_PROJECT_DIR``, ``PATH``, ``PYTHONPATH`` or the current
  working directory,
* it verifies owner, mode, version and package hash before a single line of
  rule code is imported,
* it has no fallback to a repository copy. There is no second source.

Every failure path ends in a deny with a machine readable code.

``--install-root`` exists so the bootstrap itself can be exercised against a
throwaway installation in the tests. It grants nothing: the authority of the
guard comes from Claude Code invoking the registered wrapper, and that
wrapper passes no arguments.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys

SCHEMA = "guard-active-1"
#: Both are accepted so an owner rollback to the previous package still
#: boots. The active manifest pins exactly one of them.
SUPPORTED_GUARD_VERSIONS = ("1.0.0", "1.1.0")

ACTIVE_MANIFEST_FIELDS = (
    "activated_at",
    "config_schema",
    "guard_version",
    "install_target",
    "interpreter",
    "package_sha256",
    "schema_version",
    "source_commit",
)

CODE_INSTALL_ROOT_MISSING = "GUARD_INSTALL_ROOT_MISSING"
CODE_NOT_OWNER_CONTROLLED = "GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED"
CODE_MANIFEST_MISSING = "GUARD_ACTIVE_MANIFEST_MISSING"
CODE_MANIFEST_INVALID = "GUARD_ACTIVE_MANIFEST_INVALID"
CODE_PACKAGE_MISSING = "GUARD_PACKAGE_MISSING"
CODE_PACKAGE_HASH_MISMATCH = "GUARD_PACKAGE_HASH_MISMATCH"
CODE_VERSION_UNSUPPORTED = "GUARD_VERSION_UNSUPPORTED"
CODE_INTERPRETER_MISSING = "GUARD_INTERPRETER_MISSING"
CODE_BOOTSTRAP_FAILED = "GUARD_BOOTSTRAP_FAILED"
CODE_INTERNAL_ERROR = "GUARD_INTERNAL_ERROR"

MESSAGES = {
    CODE_INSTALL_ROOT_MISSING: "the active guard installation is missing",
    CODE_NOT_OWNER_CONTROLLED: (
        "the active guard installation is not owner controlled"
    ),
    CODE_MANIFEST_MISSING: "the active guard manifest is missing",
    CODE_MANIFEST_INVALID: "the active guard manifest is invalid",
    CODE_PACKAGE_MISSING: "the active guard package is missing",
    CODE_PACKAGE_HASH_MISMATCH: "the active guard package hash does not match",
    CODE_VERSION_UNSUPPORTED: "the active guard version is not supported",
    CODE_INTERPRETER_MISSING: "no owner controlled interpreter is available",
    CODE_BOOTSTRAP_FAILED: "the guard bootstrap could not produce a decision",
    CODE_INTERNAL_ERROR: "the guard hit an internal error",
}


class BootstrapError(Exception):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(code)


def emit_deny(code, detail="", stream=None):
    """Write the blocking response for ``code``."""
    reason = MESSAGES.get(code, code)
    if detail:
        reason = reason + " (" + str(detail) + ")"
    document = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": code + ": " + reason,
        }
    }
    (stream or sys.stdout).write(json.dumps(document, sort_keys=True) + "\n")


# -- integrity primitives ---------------------------------------------------

def owner_controlled(path, *, expect_uid=0, allow_missing=False):
    """True when ``path`` is owned by ``expect_uid`` and not group/other writable.

    Symlinks are rejected outright: a link in the chain would let the guarded
    session point a protected name at content it controls.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return bool(allow_missing)
    if stat.S_ISLNK(info.st_mode):
        return False
    if info.st_uid != expect_uid:
        return False
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False
    return True


def chain_owner_controlled(path, *, expect_uid=0):
    """True when ``path`` **and every ancestor directory** is protected.

    A protected file below a writable directory is not protected: the
    directory owner can rename or replace it. This is not theoretical — on
    this platform ``/usr/bin/python3`` is a stub that resolves into a
    developer tools bundle whose ancestors may belong to the ordinary user,
    and ``/usr/local/lib`` is commonly re-owned by a package manager.

    Symlinks are followed here, but each link and each resolved component
    must itself satisfy the ownership rule.
    """
    seen = set()
    current = os.path.abspath(path)
    while True:
        if current in seen:  # pragma: no cover - loop guard
            return False
        seen.add(current)
        try:
            link_info = os.lstat(current)
        except OSError:
            return False
        # ``root`` is always acceptable in an ancestor chain; in production
        # ``expect_uid`` is ``0``, so this reduces to root only. The second
        # value exists so the throwaway installations of the test suite can
        # exercise the same code path.
        if link_info.st_uid not in (0, expect_uid):
            return False
        if link_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            # A shared directory is acceptable only with the sticky bit: it
            # then lets nobody but the entry owner, the directory owner or
            # root rename or remove an entry, so a protected component inside
            # it still cannot be replaced. ``/tmp`` is the canonical case.
            if not (
                stat.S_ISDIR(link_info.st_mode) and link_info.st_mode & stat.S_ISVTX
            ):
                return False
        if stat.S_ISLNK(link_info.st_mode):
            resolved = os.path.realpath(current)
            if not chain_owner_controlled(resolved, expect_uid=expect_uid):
                return False
        parent = os.path.dirname(current)
        if parent == current:
            return True
        current = parent


def package_files(active_dir):
    """Every file of the package, as sorted repository relative POSIX paths."""
    collected = []
    for root, directories, names in os.walk(active_dir):
        directories[:] = sorted(
            name for name in directories if name != "__pycache__"
        )
        for name in sorted(names):
            if name.endswith(".pyc") or name == ".DS_Store":
                continue
            absolute = os.path.join(root, name)
            relative = os.path.relpath(absolute, active_dir)
            collected.append(relative.replace(os.sep, "/"))
    return sorted(collected)


def package_digest(active_dir):
    """Deterministic content hash of a guard package.

    Only relative paths and file contents enter the hash — no timestamp, no
    mode, no absolute path, no build counter. The same committed source
    therefore always produces the same digest, on any machine.
    """
    accumulator = hashlib.sha256()
    for relative in package_files(active_dir):
        absolute = os.path.join(active_dir, relative.replace("/", os.sep))
        with open(absolute, "rb") as handle:
            content = handle.read()
        accumulator.update(str(len(relative)).encode("ascii"))
        accumulator.update(b"\x00")
        accumulator.update(relative.encode("utf-8"))
        accumulator.update(b"\x00")
        accumulator.update(str(len(content)).encode("ascii"))
        accumulator.update(b"\x00")
        accumulator.update(hashlib.sha256(content).digest())
        accumulator.update(b"\x00")
    return accumulator.hexdigest()


def load_active_manifest(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise BootstrapError(CODE_MANIFEST_MISSING) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BootstrapError(CODE_MANIFEST_INVALID, "not_json") from exc
    if not isinstance(payload, dict):
        raise BootstrapError(CODE_MANIFEST_INVALID, "not_object")
    if sorted(payload) != sorted(ACTIVE_MANIFEST_FIELDS):
        raise BootstrapError(CODE_MANIFEST_INVALID, "field_set")
    if payload.get("schema_version") != SCHEMA:
        raise BootstrapError(CODE_MANIFEST_INVALID, "schema")
    if not re.match(r"^[0-9a-f]{40}$", str(payload.get("source_commit", ""))):
        raise BootstrapError(CODE_MANIFEST_INVALID, "source_commit")
    if not re.match(r"^[0-9a-f]{64}$", str(payload.get("package_sha256", ""))):
        raise BootstrapError(CODE_MANIFEST_INVALID, "package_sha256")
    if not str(payload.get("install_target", "")).startswith("/"):
        raise BootstrapError(CODE_MANIFEST_INVALID, "install_target")
    if not str(payload.get("interpreter", "")).startswith("/"):
        raise BootstrapError(CODE_MANIFEST_INVALID, "interpreter")
    return payload


def verify_installation(root, *, expect_uid=0):
    """Verify the whole installation and return the active manifest."""
    if not os.path.isdir(root):
        raise BootstrapError(CODE_INSTALL_ROOT_MISSING, "root")
    protected = [
        root,
        os.path.join(root, "bootstrap.sh"),
        os.path.join(root, "bootstrap.py"),
        os.path.join(root, "active"),
    ]
    for path in protected:
        if not os.path.exists(path):
            raise BootstrapError(CODE_INSTALL_ROOT_MISSING, os.path.basename(path))
        if not owner_controlled(path, expect_uid=expect_uid):
            raise BootstrapError(CODE_NOT_OWNER_CONTROLLED, os.path.basename(path))

    # The installation root must not sit below a directory the guarded
    # session can rename or replace.
    if not chain_owner_controlled(root, expect_uid=expect_uid):
        raise BootstrapError(CODE_NOT_OWNER_CONTROLLED, "install_root_ancestor")

    manifest_path = os.path.join(root, "active.json")
    if os.path.exists(manifest_path) and not owner_controlled(
        manifest_path, expect_uid=expect_uid
    ):
        raise BootstrapError(CODE_NOT_OWNER_CONTROLLED, "active.json")
    manifest = load_active_manifest(manifest_path)

    if manifest["guard_version"] not in SUPPORTED_GUARD_VERSIONS:
        raise BootstrapError(CODE_VERSION_UNSUPPORTED, manifest["guard_version"])
    if os.path.realpath(manifest["install_target"]) != os.path.realpath(root):
        raise BootstrapError(CODE_MANIFEST_INVALID, "install_target_mismatch")

    interpreter = manifest["interpreter"]
    if not os.path.isfile(interpreter) or not os.access(interpreter, os.X_OK):
        raise BootstrapError(CODE_INTERPRETER_MISSING, "missing")
    if not chain_owner_controlled(interpreter, expect_uid=expect_uid):
        raise BootstrapError(CODE_INTERPRETER_MISSING, "not_owner_controlled")
    # What actually runs matters, not only what is declared. A stub that
    # resolves into a user writable bundle is rejected here.
    running = os.path.realpath(sys.executable or "")
    if not running:
        raise BootstrapError(CODE_INTERPRETER_MISSING, "unresolved")
    if not chain_owner_controlled(running, expect_uid=expect_uid):
        raise BootstrapError(CODE_INTERPRETER_MISSING, "running_not_owner_controlled")

    active_dir = os.path.join(root, "active")
    files = package_files(active_dir)
    if not files:
        raise BootstrapError(CODE_PACKAGE_MISSING, "empty")
    for relative in files:
        absolute = os.path.join(active_dir, relative.replace("/", os.sep))
        if not owner_controlled(absolute, expect_uid=expect_uid):
            raise BootstrapError(CODE_NOT_OWNER_CONTROLLED, relative)
    for directory, _names, _files in os.walk(active_dir):
        if not owner_controlled(directory, expect_uid=expect_uid):
            raise BootstrapError(CODE_NOT_OWNER_CONTROLLED, "package_directory")

    if "guard/rules.json" not in files:
        raise BootstrapError(CODE_PACKAGE_MISSING, "rules")
    if "guard/entry.py" not in files:
        raise BootstrapError(CODE_PACKAGE_MISSING, "entry")

    digest = package_digest(active_dir)
    if digest != manifest["package_sha256"]:
        raise BootstrapError(CODE_PACKAGE_HASH_MISMATCH)
    return manifest


def default_root():
    return os.path.dirname(os.path.realpath(__file__))


def main(argv=None, *, stdin=None, stdout=None, expect_uid=0):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = default_root()
    if len(argv) >= 2 and argv[0] == "--install-root":
        root = os.path.realpath(argv[1])
    stream_out = stdout if stdout is not None else sys.stdout
    try:
        manifest = verify_installation(root, expect_uid=expect_uid)
    except BootstrapError as exc:
        emit_deny(exc.code, exc.detail, stream=stream_out)
        return 0
    except Exception:  # noqa: BLE001 - nothing may release the request
        emit_deny(CODE_INTERNAL_ERROR, stream=stream_out)
        return 0

    active_dir = os.path.join(root, "active")
    try:
        if active_dir not in sys.path:
            sys.path.insert(0, active_dir)
        import guard  # noqa: PLC0415 - verified package, imported on purpose
        from guard import entry  # noqa: PLC0415

        if guard.GUARD_VERSION != manifest["guard_version"]:
            emit_deny(CODE_VERSION_UNSUPPORTED, "package", stream=stream_out)
            return 0
        if guard.CONFIG_SCHEMA != manifest["config_schema"]:
            emit_deny(CODE_MANIFEST_INVALID, "config_schema", stream=stream_out)
            return 0
        var = os.path.join(root, "var")
        return entry.main(
            rules_path=os.path.join(active_dir, "guard", "rules.json"),
            pending_dir=os.path.join(var, "exceptions", "pending"),
            spent_dir=os.path.join(var, "exceptions", "spent"),
            log_path=os.path.join(var, "guard.log"),
            stdin=stdin,
            stdout=stream_out,
            guard_version=manifest["guard_version"],
        )
    except Exception:  # noqa: BLE001 - nothing may release the request
        emit_deny(CODE_INTERNAL_ERROR, "dispatch", stream=stream_out)
        return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
