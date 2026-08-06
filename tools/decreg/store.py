"""Reading and writing the register on a git ref, through plumbing only.

The register is a single append-only file on one canonical ref. It never
lives in a working branch, so no working copy can hold a second, diverging
version of it.

Two properties matter here and both are enforced by git itself rather than by
this module trusting its own bookkeeping:

*compare and swap*
    every ref update states the value it expects to replace. A concurrent
    update therefore fails the write instead of silently winning it.
*content addressing*
    the new state is written as a blob, a tree and a commit before the ref
    moves. A failed ref update leaves unreferenced objects, never a half
    written register.

Nothing here decides anything about numbers. Validity is the model's job and
is re-checked on every read, so a register that was damaged outside this tool
is rejected on the next read rather than extended.
"""

from __future__ import annotations

import subprocess

from . import CANONICAL_REF, REGISTER_FILENAME
from . import model

GIT = "git"
TIMEOUT = 60


class StoreError(RuntimeError):
    """Raised with a machine readable code for every refused operation."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _git(repo, arguments, *, stdin=None, check=True):
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [GIT, "-C", str(repo), *[str(item) for item in arguments]],
        input=stdin.encode("utf-8") if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT,
        shell=False,
        check=False,
    )
    if check and completed.returncode != 0:
        raise StoreError(
            "git_command_failed",
            completed.stderr.decode("utf-8", "replace").strip()[:200],
        )
    return completed.returncode, completed.stdout.decode("utf-8", "replace")


def ref_oid(repo, ref=CANONICAL_REF):
    """Current object id of the ref, or ``None`` when it does not exist."""
    code, out = _git(repo, ["rev-parse", "--verify", "--quiet", ref], check=False)
    value = out.strip()
    return value if code == 0 and value else None


def read(repo, ref=CANONICAL_REF, filename=REGISTER_FILENAME):
    """Return ``(text, ref_oid)``. An absent ref is an empty register."""
    oid = ref_oid(repo, ref)
    if oid is None:
        return "", None
    code, out = _git(repo, ["cat-file", "blob", f"{oid}:{filename}"], check=False)
    if code != 0:
        raise StoreError("register_file_missing_on_ref", filename)
    return out, oid


def state(repo, ref=CANONICAL_REF, filename=REGISTER_FILENAME):
    """Parsed state of the register. Raises on any integrity failure."""
    text, oid = read(repo, ref, filename)
    events, current, digest = model.parse(text)
    return {
        "text": text,
        "ref_oid": oid,
        "events": events,
        "state": current,
        "digest": digest,
    }


def write(repo, text, *, expected_oid, message, ref=CANONICAL_REF,
          filename=REGISTER_FILENAME):
    """Write ``text`` as the new register state. Compare and swap on the ref.

    ``expected_oid`` is the ref value the caller read. ``None`` means the
    caller expects the ref not to exist yet.
    """
    model.parse(text)  # never write a state that does not read back

    _code, out = _git(repo, ["hash-object", "-w", "--stdin"], stdin=text)
    blob = out.strip()
    if not blob:
        raise StoreError("blob_not_written")

    _code, out = _git(
        repo, ["mktree"], stdin=f"100644 blob {blob}\t{filename}\n"
    )
    tree = out.strip()
    if not tree:
        raise StoreError("tree_not_written")

    arguments = ["commit-tree", tree, "-m", str(message)]
    if expected_oid is not None:
        arguments[2:2] = ["-p", expected_oid]
    _code, out = _git(repo, arguments)
    commit = out.strip()
    if not commit:
        raise StoreError("commit_not_written")

    update = ["update-ref", ref, commit]
    # The empty object id means: this ref must not exist yet.
    update.append(expected_oid if expected_oid is not None else "")
    code, _out = _git(repo, update, check=False)
    if code != 0:
        raise StoreError("ref_moved_concurrently", ref)
    return commit
