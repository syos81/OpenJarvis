"""Machine readable interface of the decision number reservation register.

Every subcommand writes exactly one JSON document to stdout and nothing else.
No subcommand is interactive, none has a silent default and none invents a
number: ``next-free`` reports what the history says is free, and reserving it
is a separate, explicit act.

The register itself lives on one canonical ref. Reading it here never touches
a working tree; writing it moves that ref with a compare and swap. Pushing it
anywhere is an owner action and is only ever *printed*, never performed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import CANONICAL_REF, REGISTER_FILENAME, SCHEMA_VERSION
from . import model
from . import remote as remote_rules
from . import scan
from . import store

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_BLOCKED = 3


def emit(payload, stream=None):
    (stream or sys.stdout).write(
        json.dumps(payload, sort_keys=True, indent=2) + "\n"
    )


def refused(code, detail="", **extra):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "reason_code": code,
        "detail": str(detail),
    }
    payload.update(extra)
    emit(payload)
    return EXIT_REFUSED


def _head_commit(repo):
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=30, shell=False, check=False,
    )
    return completed.stdout.decode("utf-8", "replace").strip()


def _state(args):
    return store.state(args.repo, args.ref)


def command_verify(args):
    """Full integrity check of the register, from the ref alone."""
    current = _state(args)
    emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": "verify",
        "ref": args.ref,
        "ref_oid": current["ref_oid"],
        "events": len(current["events"]),
        "chain_digest": current["digest"],
        "numbers": len(current["state"]),
        "statement": (
            "Every line parsed, every line is canonical, every line binds to "
            "the complete preceding state, and every transition is allowed."
        ),
    })
    return EXIT_OK


def command_status(args):
    current = _state(args)
    by_action = {}
    for dec_id, action in sorted(current["state"].items()):
        by_action.setdefault(action, []).append(dec_id)
    emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": "status",
        "ref": args.ref,
        "ref_oid": current["ref_oid"],
        "events": len(current["events"]),
        "chain_digest": current["digest"],
        "by_action": by_action,
    })
    return EXIT_OK


def command_next_free(args):
    """What the history says is free. Reporting is not reserving."""
    current = _state(args)
    emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": "next-free",
        "prefix": args.prefix,
        "width": args.width,
        "next_free": model.next_free(current["state"], args.prefix, args.width),
        "note": (
            "Derived from the full register history. Reporting a number free "
            "neither reserves nor allocates it."
        ),
    })
    return EXIT_OK


def command_scan(args):
    """Allocation state of one or more lines, from register table rows."""
    union, per_ref = scan.scan_lines(args.repo, args.refs, args.register_path)
    unreadable = sorted(ref for ref, found in per_ref.items() if found is None)
    used, gaps, first_unused = scan.series_state(union, args.prefix, args.width)
    emit({
        "schema_version": SCHEMA_VERSION,
        "ok": not unreadable,
        "command": "scan",
        "refs": list(args.refs),
        "unreadable_refs": unreadable,
        "register_path": args.register_path,
        "allocations_per_ref": {
            ref: (None if found is None else len(found))
            for ref, found in sorted(per_ref.items())
        },
        "prefix": args.prefix,
        "used": used,
        "gaps": gaps,
        "first_unused": first_unused,
        "method": (
            "An allocation is a register table row whose first cell is the "
            "decision id. A mention in prose is not an allocation."
        ),
    })
    return EXIT_OK if not unreadable else EXIT_REFUSED


def _append(args, action):
    wants_import_marking = (
        getattr(args, "import_note", None) is not None
        or getattr(args, "original_file", None) is not None
    )
    if wants_import_marking and not bool(getattr(args, "genesis", False)):
        # The model would silently drop the fields on a normal event; a
        # writer that discards what the caller stated is worse than one
        # that refuses, so the refusal happens loudly here.
        return refused(
            "genesis_field_on_normal_event",
            "import marking requires --genesis",
            dec_id=args.dec_id,
            action=action,
        )
    current = _state(args)
    previous_event_id = (
        current["events"][-1]["event_id"] if current["events"] else None
    )
    source_commit = args.source_commit or _head_commit(args.repo)
    try:
        event = model.build_event(
            dec_id=args.dec_id,
            action=action,
            owner_ref=args.owner_ref,
            origin_line=args.origin_line,
            recorded_at_utc=args.recorded_at_utc,
            source_commit=source_commit,
            previous_digest=current["digest"],
            previous_event_id=previous_event_id,
            genesis=bool(getattr(args, "genesis", False)),
            original_file=getattr(args, "original_file", None),
            import_note=getattr(args, "import_note", None),
        )
        text = model.append(current["text"], event)
    except model.RegisterError as error:
        return refused(error.code, error.detail, dec_id=args.dec_id, action=action)

    if args.dry_run:
        emit({
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "command": action,
            "dry_run": True,
            "dec_id": args.dec_id,
            "event_id": event["event_id"],
            "would_bind_to": current["digest"],
            "resulting_events": len(current["events"]) + 1,
        })
        return EXIT_OK

    try:
        commit = store.write(
            args.repo,
            text,
            expected_oid=current["ref_oid"],
            message=f"{action} {args.dec_id}",
            ref=args.ref,
        )
    except store.StoreError as error:
        return refused(error.code, error.detail, dec_id=args.dec_id, action=action)

    emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": action,
        "dec_id": args.dec_id,
        "event_id": event["event_id"],
        "ref": args.ref,
        "ref_oid": commit,
        "previous_ref_oid": current["ref_oid"],
    })
    return EXIT_OK


def command_reserve(args):
    return _append(args, model.ACTION_RESERVED)


def command_assign(args):
    return _append(args, model.ACTION_ASSIGNED)


def command_release(args):
    return _append(args, model.ACTION_RELEASED)


def command_plan_push(args):
    """Print the exact owner push command. Never perform it."""
    local = store.ref_oid(args.repo, args.ref)
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(args.repo), "ls-remote", args.remote, args.ref],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=60, shell=False, check=False,
    )
    line = completed.stdout.decode("utf-8", "replace").strip()
    remote_oid = line.split()[0] if line else None

    base = args.base_oid or None
    if base is None and remote_oid is not None and local is not None:
        ancestor = subprocess.run(  # noqa: S603 - fixed argv
            ["git", "-C", str(args.repo), "merge-base", "--is-ancestor",
             remote_oid, local],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, shell=False, check=False,
        )
        base = remote_oid if ancestor.returncode == 0 else None

    is_ancestor = False
    if remote_oid and local:
        ancestor = subprocess.run(  # noqa: S603 - fixed argv
            ["git", "-C", str(args.repo), "merge-base", "--is-ancestor",
             remote_oid, local],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, shell=False, check=False,
        )
        is_ancestor = ancestor.returncode == 0

    observed = remote_rules.RemoteState(remote_oid, local, base, is_ancestor)
    outcome = (
        remote_rules.classify_initial(observed)
        if remote_oid is None
        else remote_rules.classify_update(observed)
    )
    ready = outcome == remote_rules.READY
    emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": "plan-push",
        "outcome": outcome,
        "description": remote_rules.describe(outcome),
        "ready": ready,
        "local_oid": local,
        "remote_oid": remote_oid,
        "owner_command": (
            remote_rules.push_command(args.remote, args.ref) if ready else ""
        ),
        "push_status": "not_performed_owner_action",
        "statement": (
            "This tool never pushes. The command above, if any, is the only "
            "permitted form and is executed by the owner."
        ),
    })
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="dec-reservations", add_help=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--ref", default=CANONICAL_REF)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("verify").set_defaults(handler=command_verify)
    subparsers.add_parser("status").set_defaults(handler=command_status)

    free = subparsers.add_parser("next-free")
    free.add_argument("--prefix", default="DEC-")
    free.add_argument("--width", type=int, default=3)
    free.set_defaults(handler=command_next_free)

    scanner = subparsers.add_parser("scan")
    scanner.add_argument("--ref", dest="refs", action="append", required=True)
    scanner.add_argument("--register-path", default=scan.REGISTER_PATH)
    scanner.add_argument("--prefix", default="DEC-")
    scanner.add_argument("--width", type=int, default=3)
    scanner.set_defaults(handler=command_scan)

    for name, handler in (
        ("reserve", command_reserve),
        ("assign", command_assign),
        ("release", command_release),
    ):
        sub = subparsers.add_parser(name)
        sub.add_argument("--dec-id", required=True)
        sub.add_argument("--owner-ref", required=True)
        sub.add_argument("--origin-line", required=True)
        sub.add_argument("--recorded-at-utc", required=True)
        sub.add_argument("--source-commit", default="")
        sub.add_argument("--dry-run", action="store_true")
        if name == "assign":
            sub.add_argument("--genesis", action="store_true")
            # Genesis import contract (B0g): unprovable historical metadata
            # is marked on the event itself. The model already carries and
            # validates both fields and rejects them on non-genesis events;
            # the arguments only close the gap that the writer could not
            # emit what its own reader demands.
            sub.add_argument("--import-note", default=None)
            sub.add_argument("--original-file", default=None)
        sub.set_defaults(handler=handler)

    push = subparsers.add_parser("plan-push")
    push.add_argument("--remote", default="origin")
    push.add_argument("--base-oid", default="")
    push.set_defaults(handler=command_plan_push)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except model.RegisterError as error:
        return refused(error.code, error.detail)
    except store.StoreError as error:
        return refused(error.code, error.detail)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
