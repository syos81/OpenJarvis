"""Rule R6 — an expectation value belongs to the commit it is claimed for.

Every expectation value handed to the owner for an owner action must be
reproducibly derivable from exactly the commit and the artifact the action
refers to, and that derivation belongs to the acceptance evidence.

The rule exists because of a real defect, not a hypothesis. A guard package
hash was derived once from an uncommitted worktree state, then carried forward
and published twice — for two different commits — without being derived again
from either of them. The owner's dry run refused it, which is exactly what
``--expect-hash`` is for: the owner checks against an independently derived
value, not against whatever the installer happens to build at that moment. An
expectation that is merely repeated is not an expectation.

The derivation here builds from the **commit object**, never from the
worktree, for the same reason the owner installer does: a worktree can carry
uncommitted state, and an expectation derived from it belongs to nothing that
can be checked later.

An artifact kind is a declared derivation, not a guess. There is exactly one
today, because there is exactly one owner action with an expectation value.
A declaration naming an unknown kind is rejected rather than skipped.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DECLARATION = "config/governance/owner-expectations.json"

#: The one artifact kind that exists today.
GUARD_RUNTIME_PACKAGE = "guard_runtime_package"
ARTIFACT_KINDS = (GUARD_RUNTIME_PACKAGE,)

EXPECTATION_FIELDS = (
    "artifact",
    "commit",
    "derivation",
    "expectation_id",
    "owner_action",
    "published_at_commit",
    "value",
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

TIMEOUT = 300


class ExpectationError(ValueError):
    """Raised with a machine readable code for an unusable declaration."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load(root, path=DECLARATION):
    """Load and validate the declaration itself."""
    target = Path(root) / path
    if not target.is_file():
        raise ExpectationError("declaration_missing", str(path))
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ExpectationError("declaration_not_json", str(exc)[:80]) from exc
    if not isinstance(document, dict):
        raise ExpectationError("declaration_not_an_object")
    entries = document.get("expectations")
    if not isinstance(entries, list):
        raise ExpectationError("expectations_not_a_list")

    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ExpectationError("expectation_not_an_object")
        missing = sorted(set(EXPECTATION_FIELDS) - set(entry))
        if missing:
            raise ExpectationError("expectation_missing_field", ",".join(missing))
        unknown = sorted(set(entry) - set(EXPECTATION_FIELDS))
        if unknown:
            raise ExpectationError("expectation_unknown_field", ",".join(unknown))
        if entry["expectation_id"] in seen:
            raise ExpectationError("expectation_id_duplicated", entry["expectation_id"])
        seen.add(entry["expectation_id"])
        if entry["artifact"] not in ARTIFACT_KINDS:
            # An unknown kind has no declared derivation, so it can never be
            # checked. That is a rejection, never a skip.
            raise ExpectationError("artifact_kind_unknown", str(entry["artifact"]))
        if not _COMMIT_RE.match(str(entry["commit"])):
            raise ExpectationError("commit_not_a_full_object_id", str(entry["commit"]))
        if not _DIGEST_RE.match(str(entry["value"])):
            raise ExpectationError("value_not_a_digest", str(entry["value"]))
        if not str(entry["owner_action"]).strip():
            raise ExpectationError("owner_action_missing", entry["expectation_id"])
        if not str(entry["derivation"]).strip():
            raise ExpectationError("derivation_not_stated", entry["expectation_id"])
    return document


def _extract(repository, commit, destination):
    """Materialise a commit's tree. Never the worktree."""
    archive = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(repository), "archive", str(commit)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=TIMEOUT, check=False, shell=False,
    )
    if archive.returncode != 0:
        return False
    unpack = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["tar", "-x", "-C", str(destination)],
        input=archive.stdout, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=False, shell=False,
    )
    return unpack.returncode == 0


def derive_guard_package(repository, commit):
    """Package digest of ``commit``, built from the commit object.

    Returns ``(digest, code)``. ``digest`` is ``None`` when it could not be
    derived, and then ``code`` says why.
    """
    with tempfile.TemporaryDirectory(prefix="expectation-") as scratch:
        tree = Path(scratch) / "tree"
        tree.mkdir()
        if not _extract(repository, commit, tree):
            return None, "commit_not_extractable"
        builder = tree / "tools" / "guardpkg" / "build.py"
        if not builder.is_file():
            return None, "builder_absent_at_that_commit"
        stage = Path(scratch) / "stage"
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(builder), "--source", str(tree),
             "--out", str(stage)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=TIMEOUT, check=False, shell=False,
        )
        if completed.returncode != 0:
            return None, "build_failed_at_that_commit"
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
        except ValueError:
            return None, "build_output_unreadable"
        digest = payload.get("package_sha256")
        if not _DIGEST_RE.match(str(digest)):
            return None, "derived_value_not_a_digest"
        return str(digest), ""


DERIVATIONS = {GUARD_RUNTIME_PACKAGE: derive_guard_package}


def verify(root, entry):
    """Re-derive one expectation. ``""`` means it holds."""
    derive = DERIVATIONS.get(entry["artifact"])
    if derive is None:  # pragma: no cover - load() rejects this first
        return "artifact_kind_unknown"
    derived, code = derive(root, entry["commit"])
    if derived is None:
        return code
    if derived != entry["value"]:
        # Exactly the R6 defect: the published value does not belong to the
        # commit it is claimed for.
        return "value_does_not_belong_to_the_declared_commit"
    return ""


def check(root, path=DECLARATION):
    """Full R6 check. Returns ``(failures, diagnostics)``."""
    try:
        document = load(root, path)
    except ExpectationError as error:
        return [(path, error.code)], []

    failures = []
    diagnostics = []
    for entry in document["expectations"]:
        code = verify(root, entry)
        if code:
            failures.append((entry["expectation_id"], code))
        else:
            diagnostics.append(
                f"{entry['expectation_id']}=derived_from_{entry['commit'][:7]}"
            )
    diagnostics.append(f"expectations={len(document['expectations'])}")
    return sorted(failures), sorted(diagnostics)
