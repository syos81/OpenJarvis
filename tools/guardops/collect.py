#!/usr/bin/env python3
"""Owner tool for the exception objects the running guard decided to ignore.

Background. An expired or version foreign exception object no longer touches
the decision — that was settled in the first B0d position: such an object is
classified, recorded and otherwise left completely alone. Leaving it alone is
correct for a *watchman*, and insufficient for an *installation*: the objects
stay in the protected pending area forever, and only the owner may move them.
This tool is the owner's side of that, and nothing more.

Four subcommands, and the separation between them is the point:

``status``        what is in the areas, and how the active guard qualifies it
``verify``        re-derive every digest and binding of every object
``plan-collect``  print the exact owner command; run nothing
``collect``       move non candidates out of ``pending``; root only

``status``, ``verify`` and ``plan-collect`` open no file for writing at all.
That is not a promise about intent, it is the structure of this module: every
write in it happens inside :func:`collect`, and :func:`collect` refuses before
its first write unless the effective user is root. A guarded session can
therefore run the first three and can never run the fourth.

Two further properties matter as much:

*it qualifies with the guard that is actually running*
    The classification comes from the installed package under
    ``<target>/active``, imported and asked, not from a reimplementation here
    and not from the repository copy. A tool that judged these objects by the
    candidate's rules would describe a guard that is not deciding anything
    today. ``--guard-source worktree`` exists for the gate, states itself in
    every report, and is never the default.

*it never destroys and never rewrites*
    ``collect`` moves an object byte identically into ``collected`` and
    verifies the digest at the destination before removing the source. It
    never deletes an object, never edits one, never touches a candidate, and
    never overwrites an existing collected object. Everything about an object
    that made the guard ignore it stays readable afterwards.

Reports are JSON on stdout with sorted keys. They are PII poor by
construction: a report carries nonces, digests, classifications, ages and
counts — never a command text, never a reason text, never a path outside the
declared areas.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ is None:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.guardops import REPORT_SCHEMA  # noqa: E402

#: Default owner controlled installation root. Not a user path, and never
#: read from the environment: an installation this tool is pointed at by an
#: environment variable would be an installation the session chose.
DEFAULT_TARGET = "/usr/local/jarvis-guard"

#: The declared areas of an installation, relative to the target.
AREAS = {
    "pending": ("var", "exceptions", "pending"),
    "collected": ("var", "exceptions", "collected"),
    "observed": ("var", "observed"),
}

#: Where ``collect`` moves a non candidate to.
COLLECTION_AREA = "collected"

#: Sources the qualification may come from.
SOURCE_ACTIVE = "active"
SOURCE_WORKTREE = "worktree"
SOURCES = (SOURCE_ACTIVE, SOURCE_WORKTREE)

#: Object level outcomes reported by ``status`` and ``verify``.
STRUCTURALLY_SOUND = "structurally_sound"
STRUCTURALLY_CORRUPT = "structurally_corrupt"

#: Exit codes. Distinct, so a caller never has to parse prose.
EXIT_OK = 0
EXIT_FINDING = 1
EXIT_UNUSABLE = 2
EXIT_REFUSED = 3


class ToolError(Exception):
    """Raised with a machine readable code when the tool cannot proceed."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


# -- loading the guard that is actually running -----------------------------


#: What a guard implementation must expose before this tool will speak in its
#: name. The three question separation — can it be read, does it apply here,
#: does it match — is what every report below is phrased in. A guard that does
#: not have it cannot be described in those words, so the tool refuses instead
#: of reimplementing the missing part or quietly answering with another
#: guard's rules. Guard 1.2.0 is exactly such a guard, and until the candidate
#: is activated ``--guard-source active`` refuses here rather than mislead.
REQUIRED_API = (
    "ExceptionCorrupt",
    "classify",
    "command_digest",
    "integrity_digest",
    "structural_parse",
    "worktree_id",
)

#: Deliberately separate from a missing installation: an installation that is
#: present but older is a different situation from none at all.
LACKS_API = "guard_source_lacks_qualification_api"


def _require_api(module, version):
    missing = sorted(name for name in REQUIRED_API if not hasattr(module, name))
    if missing:
        raise ToolError(LACKS_API, f"{version}: {','.join(missing)}")


class GuardUnderTest:
    """The guard implementation a report is spoken in the name of."""

    __slots__ = ("source", "root", "version", "schema", "policy", "module")

    def __init__(self, source, root, version, schema, policy, module):
        self.source = source
        self.root = root
        self.version = version
        self.schema = schema
        self.policy = policy
        self.module = module

    def describe(self):
        return {
            "guard_source": self.source,
            "guard_version": self.version,
            "exception_schema": self.schema,
            "max_ttl_seconds": int(self.policy["max_ttl_seconds"]),
        }


def _load_active(target):
    """Import the installed package. Never falls back to anything else."""
    root = Path(target) / "active"
    if not (root / "guard" / "owner_exception.py").is_file():
        raise ToolError("active_guard_absent", str(root))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for stale in ("guard", "guard.owner_exception", "guard.rules"):
        sys.modules.pop(stale, None)
    import guard  # noqa: PLC0415 - deliberately late and path bound
    from guard import owner_exception  # noqa: PLC0415
    from guard import rules as rules_module  # noqa: PLC0415

    rules = rules_module.load_rules(str(root / "guard" / "rules.json"))
    _require_api(owner_exception, guard.GUARD_VERSION)
    return GuardUnderTest(
        SOURCE_ACTIVE,
        root,
        guard.GUARD_VERSION,
        guard.EXCEPTION_SCHEMA,
        dict(rules.exception_policy),
        owner_exception,
    )


def _load_worktree(_worktree):
    """The repository copy — the candidate, not the guard that is running.

    Deliberately resolved from this module's own location and not from the
    ``--worktree`` argument: that argument names the worktree an exception
    object is bound to, which is a different thing from the repository the
    candidate source lives in. Conflating the two would let a report claim to
    describe a guard that is not the one it read.
    """
    from tools.guard import EXCEPTION_SCHEMA  # noqa: PLC0415
    from tools.guard import GUARD_VERSION  # noqa: PLC0415
    from tools.guard import owner_exception  # noqa: PLC0415
    from tools.guard import rules as rules_module  # noqa: PLC0415

    root = Path(__file__).resolve().parents[1] / "guard"
    rules = rules_module.load_rules(str(root / "rules.json"))
    _require_api(owner_exception, GUARD_VERSION)
    return GuardUnderTest(
        SOURCE_WORKTREE,
        root,
        GUARD_VERSION,
        EXCEPTION_SCHEMA,
        dict(rules.exception_policy),
        owner_exception,
    )


def load_guard(source, *, target, worktree):
    if source == SOURCE_ACTIVE:
        return _load_active(target)
    if source == SOURCE_WORKTREE:
        return _load_worktree(worktree)
    raise ToolError("guard_source_unknown", str(source))


# -- reading an area, without writing to it ---------------------------------


def area_path(target, name):
    if name not in AREAS:
        raise ToolError("area_unknown", str(name))
    return Path(target).joinpath(*AREAS[name])


def _objects_in(directory):
    """Every ``*.json`` in ``directory``, sorted. Opens nothing for writing."""
    path = Path(directory)
    if not path.is_dir():
        return None
    try:
        return sorted(item for item in path.glob("*.json") if item.is_file())
    except OSError as exc:
        raise ToolError("area_unreadable", str(exc)[:80]) from exc


def inspect_object(path, guard, *, now, worktree_id=""):
    """Everything this tool knows about one object. Read only.

    A structural failure is reported, never raised past here: the point of
    the tool is to describe an area the guard may already be blocking on, and
    a describing tool that dies on the first unusable object describes
    nothing.
    """
    raw = Path(path).read_bytes()
    record = {
        "object_id": Path(path).stem,
        "object_sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    module = guard.module
    try:
        payload = module.structural_parse(
            raw.decode("utf-8", "replace"), policy=guard.policy
        )
    except module.ExceptionCorrupt as exc:
        record["structure"] = STRUCTURALLY_CORRUPT
        record["corruption_code"] = exc.args[0] if exc.args else "unknown"
        record["classification"] = ""
        record["decision_effect_possible"] = False
        return record

    record["structure"] = STRUCTURALLY_SOUND
    record["corruption_code"] = ""
    qualification = module.classify(
        payload,
        now=now,
        policy=guard.policy,
        guard_version=guard.version,
        schema=guard.schema,
    )
    record["classification"] = qualification.primary
    record["qualifications"] = sorted(qualification.applying)
    record["age_seconds"] = int(qualification.age_seconds)
    record["version_mismatches"] = [
        {"field": field, "expected": expected, "found": found}
        for field, expected, found in sorted(qualification.version_mismatches)
    ]
    record["nonce_matches_filename"] = str(payload["nonce"]) == Path(path).stem
    record["worktree_binding"] = (
        "this_worktree"
        if worktree_id and payload["worktree_id"] == worktree_id
        else "other_worktree"
    )
    # Only a candidate can ever reach the decision, and only in the worktree
    # it names. Anything else is diagnosis, and this field says so rather
    # than leaving the reader to infer it.
    record["decision_effect_possible"] = bool(
        qualification.is_candidate and record["worktree_binding"] == "this_worktree"
    )
    return record


def _survey(target, guard, *, now, worktree_id):
    """Every declared area, described. Writes nothing anywhere."""
    areas = {}
    for name in sorted(AREAS):
        directory = area_path(target, name)
        entries = _objects_in(directory)
        if entries is None:
            areas[name] = {"present": False, "count": 0, "objects": []}
            continue
        if name == "observed":
            areas[name] = {
                "present": True,
                "count": len(entries),
                "objects": sorted(item.stem for item in entries),
            }
            continue
        areas[name] = {
            "present": True,
            "count": len(entries),
            "objects": [
                inspect_object(item, guard, now=now, worktree_id=worktree_id)
                for item in entries
            ],
        }
    return areas


def collectable(objects):
    """The objects ``collect`` would move: sound, and not a candidate.

    A corrupt object is deliberately **not** collectable. It is the one kind
    of object that still blocks every decision, so moving it would silently
    repair a block the owner has not looked at yet. It is reported instead.
    """
    return sorted(
        item["object_id"]
        for item in objects
        if item["structure"] == STRUCTURALLY_SOUND
        and item["classification"] != "candidate"
    )


# -- the four subcommands ---------------------------------------------------


def command_status(args, guard, *, now, worktree_id):
    areas = _survey(args.target, guard, now=now, worktree_id=worktree_id)
    pending = areas["pending"]["objects"]
    report = {
        "schema": REPORT_SCHEMA,
        "subcommand": "status",
        "target": str(args.target),
        "wrote_anything": False,
        "areas": areas,
        "collectable": collectable(pending),
        "corrupt_present": sorted(
            item["object_id"]
            for item in pending
            if item["structure"] == STRUCTURALLY_CORRUPT
        ),
        "candidates_present": sorted(
            item["object_id"]
            for item in pending
            if item["classification"] == "candidate"
        ),
    }
    report.update(guard.describe())
    # A corrupt object in the pending area is a finding: it blocks every
    # decision until the owner looks at it. Nothing else here is.
    return report, EXIT_FINDING if report["corrupt_present"] else EXIT_OK


def command_verify(args, guard, *, now, worktree_id):
    """Re-derive every digest and binding of every object in one area.

    Not a comparison against a remembered value: the integrity digest and the
    command digest are recomputed from the object's own fields with the
    active guard's own functions, so an object that was edited after it was
    written cannot pass here.
    """
    if args.path:
        directory = Path(args.path)
        area_name = "path"
    else:
        directory = area_path(args.target, args.area)
        area_name = args.area
    entries = _objects_in(directory)
    module = guard.module
    findings = []
    objects = []
    if entries is None:
        report = {
            "schema": REPORT_SCHEMA,
            "subcommand": "verify",
            "area": area_name,
            "area_present": False,
            "wrote_anything": False,
            "objects": [],
            "findings": [{"object_id": "", "code": "area_absent"}],
        }
        report.update(guard.describe())
        return report, EXIT_FINDING

    for item in entries:
        record = inspect_object(item, guard, now=now, worktree_id=worktree_id)
        if record["structure"] == STRUCTURALLY_CORRUPT:
            findings.append(
                {"object_id": record["object_id"], "code": record["corruption_code"]}
            )
            objects.append(record)
            continue
        payload = json.loads(item.read_text(encoding="utf-8"))
        derived_integrity = module.integrity_digest(payload)
        derived_command = module.command_digest(payload["command_canonical"])
        record["integrity_rederived"] = derived_integrity == payload["integrity_sha256"]
        record["command_digest_rederived"] = (
            derived_command == payload["command_sha256"]
        )
        if not record["integrity_rederived"]:
            findings.append(
                {"object_id": record["object_id"], "code": "integrity_digest_mismatch"}
            )
        if not record["command_digest_rederived"]:
            findings.append(
                {"object_id": record["object_id"], "code": "command_digest_mismatch"}
            )
        if not record["nonce_matches_filename"]:
            findings.append(
                {"object_id": record["object_id"], "code": "nonce_filename_mismatch"}
            )
        objects.append(record)

    report = {
        "schema": REPORT_SCHEMA,
        "subcommand": "verify",
        "area": area_name,
        "area_present": True,
        "wrote_anything": False,
        "objects": objects,
        "findings": sorted(
            findings, key=lambda entry: (entry["object_id"], entry["code"])
        ),
        "decision_effect_possible": sorted(
            item["object_id"] for item in objects if item["decision_effect_possible"]
        ),
    }
    report.update(guard.describe())
    return report, EXIT_FINDING if findings else EXIT_OK


def owner_command(target):
    """The exact command the owner runs. One line, no substitution left."""
    return (
        "sudo /bin/bash scripts/guard-collect.sh collect "
        "--target " + str(target) + " --confirm"
    )


def command_plan_collect(args, guard, *, now, worktree_id):
    """Say exactly what would move, print the owner's command, run nothing."""
    areas = _survey(args.target, guard, now=now, worktree_id=worktree_id)
    pending = areas["pending"]["objects"]
    would_move = collectable(pending)
    report = {
        "schema": REPORT_SCHEMA,
        "subcommand": "plan-collect",
        "target": str(args.target),
        "executed": False,
        "wrote_anything": False,
        "would_move": would_move,
        "would_move_count": len(would_move),
        "would_stay": sorted(
            item["object_id"]
            for item in pending
            if item["object_id"] not in set(would_move)
        ),
        "destination_area": COLLECTION_AREA,
        "destination_present": areas[COLLECTION_AREA]["present"],
        "owner_command": owner_command(args.target),
        "owner_action": True,
        "note": (
            "This tool has not run that command and cannot run it: collect "
            "refuses before its first write unless the effective user is root."
        ),
    }
    report.update(guard.describe())
    return report, EXIT_OK


def _move_object(source, destination):
    """Move one object byte identically. Returns ``(ok, code)``.

    Copy, verify the digest at the destination, only then unlink the source.
    The destination is created with ``O_CREAT | O_EXCL``, so an object that is
    already collected is never overwritten.
    """
    raw = Path(source).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        handle = os.open(str(destination), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return False, "already_collected"
        return False, "destination_not_writable"
    try:
        os.write(handle, raw)
    except OSError:
        os.close(handle)
        return False, "write_failed"
    os.close(handle)
    written = Path(destination).read_bytes()
    if hashlib.sha256(written).hexdigest() != digest:
        # The copy is not byte identical. Leave both in place and report; a
        # tool that removed the source here would destroy the original on the
        # strength of a copy it just found wrong.
        return False, "copy_not_byte_identical"
    try:
        shutil.chown(str(destination), user="root", group="wheel")
    except (OSError, LookupError):
        pass
    os.unlink(str(source))
    return True, ""


def command_collect(args, guard, *, now, worktree_id):
    """Move every non candidate out of ``pending``. Root only.

    The refusal below is the first statement in the only writing function of
    this module. Everything a guarded session can reach is above it.
    """
    if os.geteuid() != 0:
        return {
            "schema": REPORT_SCHEMA,
            "subcommand": "collect",
            "executed": False,
            "wrote_anything": False,
            "refused": True,
            "reason_code": "collect_requires_root",
            "owner_command": owner_command(args.target),
        }, EXIT_REFUSED
    if not args.confirm:
        return {
            "schema": REPORT_SCHEMA,
            "subcommand": "collect",
            "executed": False,
            "wrote_anything": False,
            "refused": True,
            "reason_code": "confirmation_missing",
            "owner_command": owner_command(args.target),
        }, EXIT_REFUSED

    pending_dir = area_path(args.target, "pending")
    destination_dir = area_path(args.target, COLLECTION_AREA)
    if not destination_dir.is_dir():
        return {
            "schema": REPORT_SCHEMA,
            "subcommand": "collect",
            "executed": False,
            "wrote_anything": False,
            "refused": True,
            "reason_code": "collection_area_absent",
            "detail": str(destination_dir),
        }, EXIT_UNUSABLE

    areas = _survey(args.target, guard, now=now, worktree_id=worktree_id)
    pending = areas["pending"]["objects"]
    wanted = set(collectable(pending))
    moved = []
    failures = []
    for record in pending:
        if record["object_id"] not in wanted:
            continue
        source = pending_dir / (record["object_id"] + ".json")
        destination = destination_dir / (record["object_id"] + ".json")
        ok, code = _move_object(source, destination)
        if ok:
            moved.append(
                {
                    "object_id": record["object_id"],
                    "object_sha256": record["object_sha256"],
                    "classification": record["classification"],
                }
            )
        else:
            failures.append({"object_id": record["object_id"], "code": code})

    log_path = Path(args.target) / "var" / "activation.log"
    try:
        with open(str(log_path), "a", encoding="utf-8") as handle:
            for entry in moved:
                handle.write(
                    "%s exception_collected object_sha256=%s classification=%s\n"
                    % (
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        entry["object_sha256"],
                        entry["classification"],
                    )
                )
    except OSError:
        failures.append({"object_id": "", "code": "activation_log_unwritable"})

    report = {
        "schema": REPORT_SCHEMA,
        "subcommand": "collect",
        "executed": True,
        "wrote_anything": bool(moved),
        "refused": False,
        "moved": sorted(moved, key=lambda entry: entry["object_id"]),
        "moved_count": len(moved),
        "failures": sorted(
            failures, key=lambda entry: (entry["object_id"], entry["code"])
        ),
        "left_in_place": sorted(
            record["object_id"] for record in pending if record["object_id"] not in wanted
        ),
    }
    report.update(guard.describe())
    return report, EXIT_FINDING if failures else EXIT_OK


COMMANDS = {
    "status": command_status,
    "verify": command_verify,
    "plan-collect": command_plan_collect,
    "collect": command_collect,
}

#: The subcommands that must never open a file for writing.
READ_ONLY_COMMANDS = ("status", "verify", "plan-collect")

#: Rule R7. ``REPORT_SCHEMA`` names the report format, so it is bound to that
#: format rather than merely carried along: these are the top level keys each
#: subcommand's report has, and a gate compares the emitted reports against
#: them. A key added or dropped without a schema change fails there. Without
#: this the schema field would be a version that is compared to nothing —
#: exactly the defect R7 exists for.
REPORT_KEYS = {
    "status": (
        "areas", "candidates_present", "collectable", "corrupt_present",
        "exception_schema", "guard_source", "guard_version", "max_ttl_seconds",
        "schema", "subcommand", "target", "wrote_anything",
    ),
    "verify": (
        "area", "area_present", "decision_effect_possible", "exception_schema",
        "findings", "guard_source", "guard_version", "max_ttl_seconds",
        "objects", "schema", "subcommand", "wrote_anything",
    ),
    "plan-collect": (
        "destination_area", "destination_present", "exception_schema", "executed",
        "guard_source", "guard_version", "max_ttl_seconds", "note",
        "owner_action", "owner_command", "schema", "subcommand", "target",
        "would_move", "would_move_count", "would_stay", "wrote_anything",
    ),
}


def build_parser():
    parser = argparse.ArgumentParser(description="Owner tool for ignored exception objects.")
    parser.add_argument("subcommand", choices=sorted(COMMANDS))
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--worktree", default="")
    parser.add_argument("--area", default="pending", choices=sorted(AREAS))
    parser.add_argument("--path", default="")
    parser.add_argument("--guard-source", default=SOURCE_ACTIVE, choices=list(SOURCES))
    parser.add_argument("--now", type=int, default=0)
    parser.add_argument("--confirm", action="store_true")
    return parser


def main(argv=None, stdout=None):
    args = build_parser().parse_args(argv)
    stream = stdout or sys.stdout
    worktree = args.worktree or os.getcwd()
    now = args.now if args.now else int(time.time())

    try:
        guard = load_guard(args.guard_source, target=args.target, worktree=worktree)
    except ToolError as error:
        stream.write(
            json.dumps(
                {
                    "schema": REPORT_SCHEMA,
                    "subcommand": args.subcommand,
                    "wrote_anything": False,
                    "error": True,
                    "reason_code": error.code,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        return EXIT_UNUSABLE
    except Exception:  # noqa: BLE001 - an unusable guard is never a silent pass
        stream.write(
            json.dumps(
                {
                    "schema": REPORT_SCHEMA,
                    "subcommand": args.subcommand,
                    "wrote_anything": False,
                    "error": True,
                    "reason_code": "guard_source_unusable",
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        return EXIT_UNUSABLE

    worktree_id = guard.module.worktree_id(worktree)
    try:
        report, code = COMMANDS[args.subcommand](
            args, guard, now=now, worktree_id=worktree_id
        )
    except ToolError as error:
        report = {
            "schema": REPORT_SCHEMA,
            "subcommand": args.subcommand,
            "wrote_anything": False,
            "error": True,
            "reason_code": error.code,
        }
        code = EXIT_UNUSABLE
    stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
