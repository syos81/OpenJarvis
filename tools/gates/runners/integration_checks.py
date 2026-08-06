#!/usr/bin/env python3
"""B0a-3 integration checks.

Modes:

``id-mapping``            the seven fixed renumberings are executed, titles are
                          unchanged and the canonical line keeps its ids
``collisions-closed``     zero open collisions remain
``reference-migration``   the declared reference list and a full repository
                          search agree; no stale contacts-line id survives and
                          no reference points at the wrong decision
``single-normative-source`` exactly one normative place for lines, merge base,
                          collision finding and mapping
``dart-removed``          no pending owner input for DART remains active
``bundle-id-pinned``      the bundle identifier is unchanged and its exception
                          stays value and path exact
``merge-topology``        exactly two expected parents, no rebase, squash or
                          cherry-pick
``no-identity-change``    schema, signing, TCC identity and migration logic are
                          untouched
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import governance  # noqa: E402
from tools.gates import gitutil  # noqa: E402
from tools.gates.runners import _report  # noqa: E402

MIGRATION = Path("config/governance/b0a-3-id-migration.json")
COLLISIONS = Path("config/governance/decision-collisions.json")
NORMATIVE = Path("config/governance/normative-sources.json")
SCOPE = Path("config/governance/generality-scope.json")
BASELINE = Path("docs/personal-jarvis/calendar-implementation-baseline-2026-08-04.md")

#: Paths whose identity, signing, TCC or schema meaning must not change.
IDENTITY_PATHS = (
    "src/personaljarvis/base/db/migrations/**",
    "native/contacts-bridge/**",
    "frontend/src-tauri/**",
)
BINARY = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".icns", ".zip",
          ".gz", ".so", ".dylib", ".woff", ".woff2", ".ttf", ".otf", ".lock")


def _fail(identifier, code):
    return _report.failure(identifier, category="integration", code=code)


def load(root, relative):
    return json.loads((root / relative).read_text(encoding="utf-8"))


def token_pattern(identifier):
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(identifier)}(?![0-9A-Za-z])")


def text_files(root):
    for relative in sorted(gitutil.tracked_files(cwd=root)):
        if relative.lower().endswith(BINARY):
            continue
        target = root / relative
        if not target.is_file():
            continue
        try:
            yield relative, target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


# --------------------------------------------------------------------------
def mode_id_mapping(root):
    migration = load(root, MIGRATION)
    failures, diagnostics = [], []
    local_dec = governance.register_titles(None, root)
    local_adr = governance.adr_entries(None, root) or {}
    canonical_commit = migration["lines"]["canonical_unchanged"]["commit"]
    canon_dec = governance.register_titles(canonical_commit, root) or {}
    canon_adr = governance.adr_entries(canonical_commit, root) or {}

    for entry in migration["mappings"]:
        old, new, kind = entry["old_id"], entry["new_id"], entry["kind"]
        if kind == "DEC":
            title = (local_dec or {}).get(new)
            if title is None:
                failures.append(_fail(new, "renumbered_decision_missing"))
            elif title != entry["title"]:
                failures.append(_fail(new, "renumbered_title_changed"))
            if local_dec and old in local_dec:
                failures.append(_fail(old, "old_id_still_assigned"))
        else:
            found = local_adr.get(new)
            if found is None:
                failures.append(_fail(new, "renumbered_adr_missing"))
            else:
                filename, h1 = found
                if governance.cited_adr_title(h1, new) != entry["title"]:
                    failures.append(_fail(new, "renumbered_title_changed"))
                if filename != Path(entry["new_path"]).name:
                    failures.append(_fail(new, "renumbered_filename_mismatch"))
                if not h1.startswith(f"{new}:"):
                    failures.append(_fail(new, "renumbered_heading_mismatch"))
            if old in local_adr:
                failures.append(_fail(old, "old_id_still_assigned"))
            if (root / entry["old_path"]).exists():
                failures.append(_fail(entry["old_path"], "old_adr_file_still_present"))

    for identifier in migration["canonical_ids_unchanged"]:
        source = canon_dec if identifier.startswith("DEC-") else canon_adr
        if identifier not in source:
            failures.append(_fail(identifier, "canonical_id_changed"))
    diagnostics.append(f"mappings={len(migration['mappings'])}")
    diagnostics.append(f"canonical_ids={len(migration['canonical_ids_unchanged'])}")
    return failures, diagnostics


def mode_collisions_closed(root):
    registry = load(root, COLLISIONS)
    failures = []
    if registry.get("status") != "resolved":
        failures.append(_fail("registry", "collision_registry_not_resolved"))
    if registry.get("open_collisions") != 0:
        failures.append(_fail("registry", "open_collision_count_not_zero"))
    detected, error = governance.detect_collisions(registry, root)
    if error:
        failures.append(_fail("detection", error))
    for identifier in sorted(detected):
        failures.append(_fail(identifier, "collision_still_open"))
    return failures, [f"open_collisions={len(detected)}",
                      f"historical_records={len(registry.get('historical_resolution', []))}"]


def mechanism_files(root):
    """Files that implement the rules rather than referencing decisions."""
    target = root / NORMATIVE
    if not target.is_file():
        return set()
    registry = json.loads(target.read_text(encoding="utf-8"))
    return {entry["path"] for entry in registry.get("mechanism_files", [])}


def mode_reference_migration(root):
    """Declared list plus full repository search must agree."""
    migration = load(root, MIGRATION)
    excluded = set(governance.normative_exclusions(root)) | mechanism_files(root)
    old_ids = [entry["old_id"] for entry in migration["mappings"]]
    new_ids = [entry["new_id"] for entry in migration["mappings"]]
    old_pats = {i: token_pattern(i) for i in old_ids}
    # Spelling variants the token pattern cannot see: separator forms, lower
    # case identifiers in test names, and bare number pairs such as
    # ``ADR-0025/0020``.
    # Lower case identifier forms only — the upper case ``DEC-04x``/``ADR-00xx``
    # tokens are already covered by the token patterns above.
    variant_pats = {
        "dec_variant": re.compile(r"dec[ _\-]0?4[4-8]\b"),
        "adr_variant": re.compile(r"adr[ _\-]00?(?:19|20)\b"),
        "bare_pair": re.compile(r"\bADR-\d{4}\s*/\s*00?(?:19|20)\b"),
    }
    new_pats = {i: token_pattern(i) for i in new_ids}
    # Canonical-line references are legitimate but must be qualified.
    canonical_marker = re.compile(r"jarvis/rebuild-v1|rebuild-v1-Linie|canonical")
    # Declared historical resolution records may carry the old ids as proof.
    normative = load(root, NORMATIVE)
    historical = {}
    for entry in normative.get("historical_resolution_records", []):
        target = root / entry["path"]
        if target.is_file() and entry["marker"] in target.read_text(
            encoding="utf-8", errors="ignore"
        ):
            historical[entry["path"]] = entry["marker"]

    stale, migrated_files, scanned, qualified = [], 0, 0, 0
    historical_hits = 0
    window = 6
    for relative, text in text_files(root):
        if relative in excluded:
            continue
        scanned += 1
        normalised = unicodedata.normalize("NFKD", text)
        if any(pattern.search(normalised) for pattern in new_pats.values()):
            migrated_files += 1
        if relative in historical:
            historical_hits += sum(
                len(pattern.findall(normalised)) for pattern in old_pats.values()
            )
            continue
        for name, pattern in variant_pats.items():
            for match in pattern.finditer(normalised):
                start = normalised.rfind("\n", 0, match.start()) + 1
                end = normalised.find("\n", match.end())
                line_text = normalised[start : end if end != -1 else len(normalised)]
                if canonical_marker.search(line_text) or "aufgelöst" in line_text:
                    qualified += 1
                else:
                    stale.append((relative, name))
        lines = normalised.splitlines()
        for index, line in enumerate(lines):
            for identifier, pattern in old_pats.items():
                if not pattern.search(line):
                    continue
                # A remaining old id is legitimate only when its context
                # qualifies it as the canonical rebuild-v1 line.
                context = "\n".join(
                    lines[max(0, index - window) : index + window + 1]
                )
                if canonical_marker.search(context):
                    qualified += 1
                else:
                    stale.append((relative, identifier))

    failures = [
        _fail(f"{relative}#{identifier}", "stale_contacts_line_reference")
        for relative, identifier in sorted(set(stale))
    ]
    diagnostics = [f"scanned_files={scanned}", f"files_with_new_ids={migrated_files}",
                   f"qualified_canonical_references={qualified}",
                   f"historical_record_references={historical_hits}",
                   f"historical_record_files={len(historical)}",
                   f"stale_references={len(set(stale))}"]
    return failures, diagnostics


def mode_single_normative_source(root):
    registry = load(root, NORMATIVE)
    failures, diagnostics = [], []
    normative = registry["collision_and_mapping"]["normative"]
    document, _, section = normative.partition("#")
    target = root / document
    if not target.is_file():
        failures.append(_fail(document, "normative_source_missing"))
        return failures, diagnostics
    text = target.read_text(encoding="utf-8")
    if f"## §{section} " not in text:
        failures.append(_fail(normative, "normative_section_missing"))
    if "einzige normative Stelle" not in text:
        failures.append(_fail(normative, "normative_claim_missing"))

    collisions = load(root, COLLISIONS)
    declared = collisions.get("normative_source", {})
    if declared.get("document") != document or str(declared.get("section")) != section:
        failures.append(_fail("projection", "projection_points_elsewhere"))
    # The machine projection must agree with the normative text.
    for entry in collisions.get("historical_resolution", []):
        if entry["new_id"] not in text or entry["old_id"] not in text:
            failures.append(_fail(entry["new_id"], "mapping_not_in_normative_text"))

    for excluded in registry.get("historical_non_normative", []):
        path = root / excluded["path"]
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        if excluded["marker"] not in content:
            failures.append(_fail(excluded["path"], "historical_marker_missing"))
        diagnostics.append(f"historical_excluded={excluded['path']}")
    diagnostics.append(f"normative_source={normative}")
    return failures, diagnostics


def mode_dart_removed(root):
    scope = load(root, SCOPE)
    failures, diagnostics = [], []
    for term in scope["organization_terms"]:
        if term.get("status") == "pending_owner_input":
            failures.append(_fail(term["term_id"], "pending_owner_input_still_active"))
        if term.get("term_id") == "dart_full_name":
            failures.append(_fail("dart_full_name", "dart_placeholder_still_active"))
        if term.get("canonical") is None:
            failures.append(_fail(term.get("term_id", "?"), "term_without_value"))
    excluded = set(governance.normative_exclusions(root)) | mechanism_files(root)
    for relative, text in text_files(root):
        if relative in excluded or relative.startswith("docs/governance/b0b-"):
            continue
        # The retired placeholder id itself must not survive anywhere that is
        # normative or executable.
        if "dart_full_name" in text:
            failures.append(_fail(relative, "dart_placeholder_reference"))
    diagnostics.append(f"active_terms={len(scope['organization_terms'])}")
    return failures, diagnostics


def mode_bundle_id_pinned(root):
    scope = load(root, SCOPE)
    failures, diagnostics = [], []
    declared = scope.get("declared_identifiers", [])
    if len(declared) != 1:
        failures.append(_fail("declared_identifiers", "unexpected_declaration_count"))
        return failures, diagnostics
    entry = declared[0]
    if entry["value"] != "de.kluender.jarvis.contacts-bridge":
        failures.append(_fail("bundle_identifier", "bundle_identifier_changed"))
    if len(entry.get("paths", [])) != 5:
        failures.append(_fail("bundle_identifier", "path_list_changed"))
    for path in entry.get("paths", []):
        if any(ch in path for ch in "*?["):
            failures.append(_fail(path, "path_exception_not_exact"))
        if not (root / path).is_file():
            failures.append(_fail(path, "declared_path_missing"))
        else:
            content = (root / path).read_text(encoding="utf-8", errors="ignore")
            if entry["value"] not in content:
                failures.append(_fail(path, "declared_identifier_stale"))
    if not entry.get("due"):
        failures.append(_fail("bundle_identifier", "due_date_missing"))
    reference = entry.get("owner_reference", "")
    document = reference.split(" ")[0] if reference else ""
    if not document or not (root / document).is_file():
        failures.append(_fail("bundle_identifier", "owner_reference_unresolved"))
    else:
        text = (root / document).read_text(encoding="utf-8")
        if "Kontakte M2" not in text or "signierten Freigabe" not in text:
            failures.append(_fail(document, "due_date_not_documented"))
    diagnostics.append(f"pinned_paths={len(entry.get('paths', []))}")
    diagnostics.append("bundle_identifier=unchanged")
    return failures, diagnostics


def mode_merge_topology(root):
    """Exactly two expected parents; no rebase, squash or cherry-pick."""
    migration = load(root, MIGRATION)
    expected_second = migration["lines"]["tooling_source"]["commit"]
    expected_first = migration["lines"]["calendar_target"]["commit"]
    failures, diagnostics = [], []

    code, out, _ = gitutil.run_git(["rev-list", "--parents", "-n", "1", "HEAD"], cwd=root)
    if code != 0:
        return [_fail("HEAD", "head_unreadable")], diagnostics
    parts = out.split()
    head, parents = parts[0], parts[1:]
    diagnostics.append(f"head={head[:12]}")
    diagnostics.append(f"parent_count={len(parents)}")
    if len(parents) != 2:
        failures.append(_fail("HEAD", "merge_parent_count_unexpected"))
        return failures, diagnostics
    diagnostics.append(f"parent1={parents[0][:12]}")
    diagnostics.append(f"parent2={parents[1][:12]}")
    if parents[0] != expected_first:
        failures.append(_fail("parent1", "first_parent_not_calendar_tip"))
    if parents[1] != expected_second:
        failures.append(_fail("parent2", "second_parent_not_tooling_tip"))
    # A rebase, squash or cherry-pick would not preserve both parents as
    # reachable ancestors with their original identity.
    for parent in parents:
        code, _, _ = gitutil.run_git(
            ["merge-base", "--is-ancestor", parent, "HEAD"], cwd=root
        )
        if code != 0:
            failures.append(_fail(parent[:12], "parent_not_ancestor_of_head"))
    return failures, diagnostics


def mode_no_identity_change(root):
    """Identity relevant paths changed only in comments and docstrings."""
    migration = load(root, MIGRATION)
    base = migration["lines"]["calendar_target"]["commit"]
    failures, diagnostics = [], []
    import fnmatch

    code, out, _ = gitutil.run_git(["diff", "--name-only", base], cwd=root)
    if code != 0:
        return [_fail("diff", "diff_unavailable")], diagnostics
    touched = [line.strip() for line in out.splitlines() if line.strip()]
    identity = [
        path for path in touched
        if any(fnmatch.fnmatch(path, pattern) for pattern in IDENTITY_PATHS)
    ]
    diagnostics.append(f"identity_paths_touched={len(identity)}")
    for path in identity:
        code, diff, _ = gitutil.run_git(
            ["diff", "--unified=0", base, "--", path], cwd=root
        )
        if code != 0:
            failures.append(_fail(path, "diff_unavailable"))
            continue
        for line in diff.splitlines():
            if not (line.startswith("+") or line.startswith("-")):
                continue
            if line.startswith("+++") or line.startswith("---"):
                continue
            body = line[1:].strip()
            if not body:
                continue
            # Only decision id references may have changed here.
            without_ids = body
            for entry in migration["mappings"]:
                without_ids = token_pattern(entry["old_id"]).sub("", without_ids)
                without_ids = token_pattern(entry["new_id"]).sub("", without_ids)
            paired = any(
                token_pattern(entry["old_id"]).search(body)
                or token_pattern(entry["new_id"]).search(body)
                for entry in migration["mappings"]
            )
            if not paired:
                failures.append(_fail(path, "identity_path_changed_beyond_ids"))
                break
    if "de.kluender.jarvis.contacts-bridge" not in (
        root / "src/personaljarvis/contacts/application/mutation_service.py"
    ).read_text(encoding="utf-8", errors="ignore"):
        failures.append(_fail("bundle_identifier", "bundle_identifier_changed"))
    return failures, diagnostics


def mode_guard_base(root):
    """The guard base is derived mechanically and only validated declaratively."""
    from tools.gates import guardbase

    migration = load(root, MIGRATION)
    failures, diagnostics = [], []
    try:
        derivation = guardbase.derive_for_repository(root)
    except guardbase.GuardBaseError as exc:
        return [_fail("guard_base", exc.reason_code)], diagnostics
    base = derivation["base_commit"]
    diagnostics.append(f"guard_base={base[:12]}")
    diagnostics.append(f"derivation={derivation['derivation']}")
    if migration["guard_base"] != base:
        failures.append(_fail("guard_base", "declared_guard_base_mismatch"))
    code, out, _ = gitutil.run_git(
        ["merge-base", "--all", derivation["canonical_line"],
         derivation["calendar_line"]], cwd=root
    )
    bases = [line.strip() for line in out.splitlines() if line.strip()]
    diagnostics.append(f"merge_base_count={len(bases)}")
    if code != 0 or len(bases) != 1 or bases[0] != base:
        failures.append(_fail("guard_base", "merge_base_not_unique_or_mismatched"))
    return failures, diagnostics


def mode_merge_diff(root):
    """Classify the integration diff against both parents.

    Against the calendar parent only tooling and migration paths may appear;
    against the tooling parent only calendar and migration paths. This is the
    meaningful product guard for a merge — a branch-wide path allowlist would
    flag the calendar line's own legitimate history.
    """
    import fnmatch

    migration = load(root, MIGRATION)
    calendar_parent = migration["lines"]["calendar_target"]["commit"]
    tooling_parent = migration["lines"]["tooling_source"]["commit"]
    tooling_paths = (".claude/*", ".gitignore", "CLAUDE.md", "config/gates/*",
                     "config/governance/*", "docs/governance/*", "docs/tooling/*",
                     "scripts/gate.sh", "tests/tooling/*", "tools/gates/*")
    failures, diagnostics = [], []

    code, out, _ = gitutil.run_git(
        ["diff", "--name-only", calendar_parent], cwd=root
    )
    if code != 0:
        return [_fail("diff", "diff_unavailable")], diagnostics
    against_calendar = [line.strip() for line in out.splitlines() if line.strip()]
    diagnostics.append(f"paths_vs_calendar_parent={len(against_calendar)}")

    migrated = set()
    for entry in migration["mappings"]:
        for key in ("old_path", "new_path"):
            if entry.get(key):
                migrated.add(entry[key])

    for path in against_calendar:
        if any(fnmatch.fnmatch(path, pattern) for pattern in tooling_paths):
            continue
        if path in migrated or path.startswith("docs/") or path.startswith("src/") \
                or path.startswith("tests/") or path.startswith("frontend/") \
                or path.startswith("native/"):
            # Reference migration reaches these; their semantics are guarded by
            # the id mapping and the identity check.
            continue
        failures.append(_fail(path, "unexpected_path_in_integration"))

    code, out, _ = gitutil.run_git(["diff", "--name-only", tooling_parent], cwd=root)
    if code == 0:
        diagnostics.append(
            f"paths_vs_tooling_parent={len([l for l in out.splitlines() if l.strip()])}"
        )
    code, out, _ = gitutil.run_git(
        ["rev-list", "--count", f"{calendar_parent}..HEAD"], cwd=root
    )
    if code == 0:
        diagnostics.append(f"commits_since_calendar_parent={out.strip()}")
    return failures, diagnostics


MODES = {
    "bundle-id-pinned": mode_bundle_id_pinned,
    "guard-base": mode_guard_base,
    "merge-diff": mode_merge_diff,
    "collisions-closed": mode_collisions_closed,
    "dart-removed": mode_dart_removed,
    "id-mapping": mode_id_mapping,
    "merge-topology": mode_merge_topology,
    "no-identity-change": mode_no_identity_change,
    "reference-migration": mode_reference_migration,
    "single-normative-source": mode_single_normative_source,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    root = Path.cwd()
    failures, diagnostics = MODES[args.mode](root)
    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(outcome, failures, diagnostics)


if __name__ == "__main__":
    sys.exit(main())
