#!/usr/bin/env python3
"""Deterministic guard package builder.

Turns a concrete committed state of ``tools/guard`` into an installable
package and reports its content hash. The hash is reproducible from the same
source on any machine: only relative paths and file contents enter it — no
timestamp, no build counter, no absolute worktree path, no generated file.

Usage::

    build.py --source <worktree> --out <stage-dir>
    build.py --digest <stage-dir>

The builder never installs anything and never touches the active guard.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import bootstrap  # noqa: E402

#: Files that are never part of the runtime package.
EXCLUDED_SUFFIXES = (".pyc", ".pyo")
EXCLUDED_NAMES = ("__pycache__", ".DS_Store")

#: Exactly the runtime modules. A file that is not listed here is not
#: shipped, so a development helper can never end up in the active guard.
PACKAGE_MEMBERS = (
    "__init__.py",
    "audit.py",
    "cmdparse.py",
    "decide.py",
    "entry.py",
    "errors.py",
    "owner_exception.py",
    "rules.json",
    "rules.py",
    "textnorm.py",
)


def stage(source_worktree, out_dir):
    """Copy the runtime package into ``out_dir/active/guard``."""
    source = os.path.join(source_worktree, "tools", "guard")
    if not os.path.isdir(source):
        raise SystemExit("guard source not found: tools/guard")
    target = os.path.join(out_dir, "active", "guard")
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)
    present = sorted(
        name
        for name in os.listdir(source)
        if name not in EXCLUDED_NAMES
        and not name.endswith(EXCLUDED_SUFFIXES)
    )
    if present != sorted(PACKAGE_MEMBERS):
        raise SystemExit(
            "guard source does not match the declared package members: "
            + ",".join(present)
        )
    for name in sorted(PACKAGE_MEMBERS):
        shutil.copyfile(
            os.path.join(source, name), os.path.join(target, name)
        )
        os.chmod(os.path.join(target, name), 0o444)
    return os.path.join(out_dir, "active")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--digest", default="")
    args = parser.parse_args(argv)

    if args.digest:
        active = args.digest
        if os.path.basename(os.path.normpath(active)) != "active":
            active = os.path.join(active, "active")
        sys.stdout.write(
            json.dumps(
                {
                    "package_sha256": bootstrap.package_digest(active),
                    "files": bootstrap.package_files(active),
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        return 0

    if not args.source or not args.out:
        parser.error("--source and --out are required")
    active = stage(args.source, args.out)
    sys.stdout.write(
        json.dumps(
            {
                "package_sha256": bootstrap.package_digest(active),
                "files": bootstrap.package_files(active),
                "members": list(PACKAGE_MEMBERS),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
