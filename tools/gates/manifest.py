"""Strict, declarative block manifests.

The manifest is the only place where blocks, phases, checks, baseline policy,
platform requirements, evidence policy and feature lineage are declared. The
parser is deliberately unforgiving:

* unknown fields are rejected, never silently ignored,
* only the five phases and the five results exist,
* success results may not be pre-declared (only a non-applicable phase may
  declare ``not_applicable`` together with a reason),
* argv declarations must be safe: no shell strings, no ``eval``, no absolute
  or user specific paths,
* contradictory baseline declarations are rejected,
* ordering is deterministic and enforced.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import MANIFEST_SCHEMA_VERSION
from . import sanitize
from . import statuses

PHASES = (
    "preflight",
    "targeted",
    "offline-final",
    "platform-live",
    "module-final",
)
PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}

PARSERS = ("gate_json", "unittest", "exit_only")
BASELINE_CAPABLE_PARSERS = ("gate_json", "unittest")
RUNNER_TYPES = ("argv", "internal")
EVIDENCE_PROFILES = ("tooling",)
INTERNAL_RUNNERS = ("module_final_phase_results", "module_final_evidence")

ALLOWED_PLACEHOLDERS = (
    "${GATE_PYTHON}",
    "${GATE_TOOLS}",
    "${GATE_WORKTREE}",
    "${GATE_REPORT}",
)
ALLOWED_COMMANDS = ("git",)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHELL_METACHARS = (";", "|", "&", "$(", "`", ">", "<", "\n", "*", "?", "~")
_ABS_PATH_HINTS = ("/Users/", "/home/", "$HOME", "${HOME}")  # gate-allow: absolute_user_path

TOP_LEVEL_FIELDS = {
    "schema_version": int,
    "block_id": str,
    "title": str,
    "engine_min_version": str,
    "required_phases": list,
    "phase_definitions": dict,
    "targeted_selection": dict,
    "checks": list,
    "baseline_policy": dict,
    "platform_requirements": dict,
    "evidence_policy": dict,
    "feature_lineage": dict,
    "product_guard": dict,
}

PHASE_DEF_REQUIRED = ("applicable", "required", "reason")
PHASE_DEF_OPTIONAL = ("declared_result",)
CHECK_REQUIRED = (
    "check_id",
    "phase",
    "required",
    "description",
    "runner",
    "parser",
    "timeout_seconds",
    "baseline_eligible",
    "evidence_profile",
)
RUNNER_REQUIRED = ("type",)
RUNNER_OPTIONAL = ("argv", "name", "cwd")
BASELINE_POLICY_FIELDS = (
    "baseline_commit",
    "cause_signature_version",
    "owner_marker",
    "cache_enabled",
    "dependency_lock_paths",
    "config_digest_paths",
)
PLATFORM_FIELDS = ("systems", "architectures", "min_python")
EVIDENCE_POLICY_FIELDS = ("sanitized_evidence", "raw_log_area")
FEATURE_LINEAGE_FIELDS = ("lineage_file", "predecessor_file")
PRODUCT_GUARD_FIELDS = ("allowed_paths", "block_base_commit", "forbidden_paths")
TARGETED_FIELDS = ("base_ref", "always", "rules")
TARGETED_RULE_FIELDS = ("rule_id", "paths", "checks")


class ManifestError(ValueError):
    """Raised with every violation found in a manifest."""

    def __init__(self, issues):
        self.issues = list(issues)
        joined = "; ".join(f"{code}: {message}" for code, message in self.issues)
        super().__init__(f"invalid manifest ({joined})")


class _Validator:
    def __init__(self):
        self.issues = []

    def fail(self, code, message):
        self.issues.append((code, message))

    def require(self, condition, code, message):
        if not condition:
            self.fail(code, message)
        return condition


class Check:
    __slots__ = (
        "check_id",
        "phase",
        "required",
        "description",
        "runner",
        "parser",
        "timeout_seconds",
        "baseline_eligible",
        "evidence_profile",
    )

    def __init__(self, raw):
        for name in self.__slots__:
            setattr(self, name, raw[name])

    def as_definition(self):
        """Normalised definition used inside the baseline cache key."""
        return {
            "check_id": self.check_id,
            "phase": self.phase,
            "required": self.required,
            "runner": self.runner,
            "parser": self.parser,
            "timeout_seconds": self.timeout_seconds,
            "baseline_eligible": self.baseline_eligible,
            "evidence_profile": self.evidence_profile,
        }


class Manifest:
    def __init__(self, data, digest, path=None):
        self.data = data
        self.digest = digest
        self.path = Path(path) if path else None
        self.block_id = data["block_id"]
        self.checks = [Check(raw) for raw in data["checks"]]
        self.checks_by_id = {check.check_id: check for check in self.checks}

    # -- accessors ---------------------------------------------------------
    def phase_definition(self, phase):
        return self.data["phase_definitions"][phase]

    def is_applicable(self, phase):
        return bool(self.phase_definition(phase)["applicable"])

    def checks_for_phase(self, phase):
        return [check for check in self.checks if check.phase == phase]

    def required_check_ids(self, phase):
        return sorted(
            check.check_id
            for check in self.checks_for_phase(phase)
            if check.required
        )

    @property
    def baseline_commit(self):
        return self.data["baseline_policy"]["baseline_commit"]

    @property
    def cache_enabled(self):
        return bool(self.data["baseline_policy"]["cache_enabled"])


def _validate_argv(validator, check_id, argv):
    if not validator.require(
        isinstance(argv, list) and argv,
        "runner_argv_invalid",
        f"{check_id}: argv must be a non-empty list",
    ):
        return
    for token in argv:
        if not isinstance(token, str):
            validator.fail(
                "runner_argv_invalid", f"{check_id}: argv entries must be strings"
            )
            continue
        stripped = token
        for placeholder in ALLOWED_PLACEHOLDERS:
            stripped = stripped.replace(placeholder, "")
        if any(meta in stripped for meta in _SHELL_METACHARS):
            validator.fail(
                "runner_unsafe_shell_string",
                f"{check_id}: argv token contains shell metacharacters: {token}",
            )
        if re.search(r"\beval\b", stripped):
            validator.fail(
                "runner_unsafe_shell_string", f"{check_id}: eval is not allowed"
            )
        if token.startswith("/") or any(hint in token for hint in _ABS_PATH_HINTS):
            validator.fail(
                "absolute_user_path",
                f"{check_id}: absolute or user specific path in argv: {token}",
            )
        if "$" in stripped:
            validator.fail(
                "runner_unknown_placeholder",
                f"{check_id}: unknown placeholder in argv token: {token}",
            )
    head = argv[0]
    if head not in ALLOWED_PLACEHOLDERS and head not in ALLOWED_COMMANDS:
        validator.fail(
            "runner_command_not_allowed",
            f"{check_id}: argv[0] must be a placeholder or one of "
            f"{ALLOWED_COMMANDS}, got {head}",
        )
    if head in ("bash", "sh", "zsh") or "-c" in argv:
        validator.fail(
            "runner_unsafe_shell_string",
            f"{check_id}: composed shell strings are not allowed",
        )


def _validate_check(validator, raw, seen_ids):
    if not isinstance(raw, dict):
        validator.fail("check_invalid", "check entries must be objects")
        return
    check_id = raw.get("check_id", "<unnamed>")
    unknown = sorted(set(raw) - set(CHECK_REQUIRED))
    if unknown:
        validator.fail(
            "unknown_field", f"{check_id}: unknown check field(s): {unknown}"
        )
    missing = sorted(set(CHECK_REQUIRED) - set(raw))
    if missing:
        validator.fail(
            "missing_field", f"{check_id}: missing check field(s): {missing}"
        )
        return

    if not _ID_RE.match(str(check_id)):
        validator.fail("invalid_id", f"invalid check_id: {check_id}")
    if check_id in seen_ids:
        validator.fail("duplicate_check_id", f"duplicate check_id: {check_id}")
    seen_ids.add(check_id)

    if raw["phase"] not in PHASES:
        validator.fail(
            "invalid_phase", f"{check_id}: unknown phase: {raw['phase']}"
        )
    if not isinstance(raw["required"], bool):
        validator.fail("invalid_type", f"{check_id}: required must be boolean")
    if not isinstance(raw["description"], str) or not raw["description"].strip():
        validator.fail(
            "invalid_type", f"{check_id}: description must be a non-empty string"
        )
    if raw["parser"] not in PARSERS:
        validator.fail(
            "invalid_parser", f"{check_id}: unknown parser: {raw['parser']}"
        )
    if raw["evidence_profile"] not in EVIDENCE_PROFILES:
        validator.fail(
            "invalid_evidence_profile",
            f"{check_id}: unknown evidence_profile: {raw['evidence_profile']}",
        )
    timeout = raw["timeout_seconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        validator.fail("invalid_timeout", f"{check_id}: timeout must be an int")
    elif not 1 <= timeout <= 3600:
        validator.fail(
            "invalid_timeout", f"{check_id}: timeout out of range: {timeout}"
        )
    if not isinstance(raw["baseline_eligible"], bool):
        validator.fail(
            "invalid_type", f"{check_id}: baseline_eligible must be boolean"
        )

    runner = raw["runner"]
    if not isinstance(runner, dict):
        validator.fail("runner_invalid", f"{check_id}: runner must be an object")
        return
    unknown_runner = sorted(set(runner) - set(RUNNER_REQUIRED + RUNNER_OPTIONAL))
    if unknown_runner:
        validator.fail(
            "unknown_field", f"{check_id}: unknown runner field(s): {unknown_runner}"
        )
    runner_type = runner.get("type")
    if runner_type not in RUNNER_TYPES:
        validator.fail(
            "runner_invalid", f"{check_id}: unknown runner type: {runner_type}"
        )
    elif runner_type == "argv":
        _validate_argv(validator, check_id, runner.get("argv"))
        if runner.get("cwd") not in (None, "worktree", "target"):
            validator.fail(
                "runner_invalid", f"{check_id}: unknown runner cwd: {runner['cwd']}"
            )
        if "name" in runner:
            validator.fail(
                "runner_invalid", f"{check_id}: argv runner must not declare a name"
            )
    else:
        if runner.get("name") not in INTERNAL_RUNNERS:
            validator.fail(
                "runner_invalid",
                f"{check_id}: unknown internal runner: {runner.get('name')}",
            )
        if "argv" in runner:
            validator.fail(
                "runner_invalid",
                f"{check_id}: internal runner must not declare argv",
            )
        if raw["parser"] != "gate_json":
            validator.fail(
                "invalid_parser",
                f"{check_id}: internal runners must use the gate_json parser",
            )

    if raw["baseline_eligible"]:
        if raw["parser"] not in BASELINE_CAPABLE_PARSERS:
            validator.fail(
                "baseline_contradiction",
                f"{check_id}: baseline_eligible requires a structured parser "
                f"(one of {BASELINE_CAPABLE_PARSERS})",
            )
        if runner_type == "internal":
            validator.fail(
                "baseline_contradiction",
                f"{check_id}: internal runners cannot be baseline eligible",
            )
        if runner.get("cwd") != "target":
            validator.fail(
                "baseline_contradiction",
                f"{check_id}: baseline eligible checks must run with cwd=target",
            )


def _validate_phase_definitions(validator, data):
    definitions = data.get("phase_definitions")
    if not isinstance(definitions, dict):
        validator.fail("invalid_type", "phase_definitions must be an object")
        return
    unknown = sorted(set(definitions) - set(PHASES))
    if unknown:
        validator.fail("invalid_phase", f"unknown phase definition(s): {unknown}")
    missing = sorted(set(PHASES) - set(definitions))
    if missing:
        validator.fail("missing_field", f"missing phase definition(s): {missing}")
    for phase in sorted(set(definitions) & set(PHASES)):
        definition = definitions[phase]
        if not isinstance(definition, dict):
            validator.fail("invalid_type", f"{phase}: definition must be an object")
            continue
        unknown_fields = sorted(
            set(definition) - set(PHASE_DEF_REQUIRED + PHASE_DEF_OPTIONAL)
        )
        if unknown_fields:
            validator.fail(
                "unknown_field", f"{phase}: unknown field(s): {unknown_fields}"
            )
        for field in PHASE_DEF_REQUIRED:
            if field not in definition:
                validator.fail("missing_field", f"{phase}: missing {field}")
        applicable = definition.get("applicable")
        if not isinstance(applicable, bool):
            validator.fail("invalid_type", f"{phase}: applicable must be boolean")
        if not isinstance(definition.get("required"), bool):
            validator.fail("invalid_type", f"{phase}: required must be boolean")
        reason = definition.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            validator.fail(
                "missing_reason", f"{phase}: a non-empty reason is mandatory"
            )
        declared = definition.get("declared_result")
        if declared is not None:
            if applicable is not False:
                validator.fail(
                    "declared_result_not_allowed",
                    f"{phase}: only a non-applicable phase may declare a result",
                )
            if declared != statuses.NOT_APPLICABLE:
                validator.fail(
                    "declared_result_not_allowed",
                    f"{phase}: only '{statuses.NOT_APPLICABLE}' may be declared",
                )
        if applicable is False and declared != statuses.NOT_APPLICABLE:
            validator.fail(
                "missing_field",
                f"{phase}: a non-applicable phase must declare "
                f"'{statuses.NOT_APPLICABLE}'",
            )
        if phase == "module-final" and applicable is False:
            validator.fail(
                "invalid_phase", "module-final must be applicable"
            )


def _validate_no_predeclared_results(validator, data):
    """No success result may be baked into the manifest."""
    forbidden = set(statuses.ALL_STATUSES) - {statuses.NOT_APPLICABLE}

    def walk(node, pointer):
        if isinstance(node, dict):
            for key in sorted(node, key=str):
                walk(node[key], f"{pointer}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{pointer}[{index}]")
        elif isinstance(node, str) and node in forbidden:
            validator.fail(
                "predeclared_result",
                f"{pointer}: manifests must not pre-declare '{node}'",
            )

    walk(data, "$")


def _validate_sections(validator, data):
    baseline = data.get("baseline_policy", {})
    if isinstance(baseline, dict):
        unknown = sorted(set(baseline) - set(BASELINE_POLICY_FIELDS))
        if unknown:
            validator.fail("unknown_field", f"baseline_policy: unknown {unknown}")
        missing = sorted(set(BASELINE_POLICY_FIELDS) - set(baseline))
        if missing:
            validator.fail("missing_field", f"baseline_policy: missing {missing}")
        commit = baseline.get("baseline_commit", "")
        if not isinstance(commit, str) or not re.match(r"^[0-9a-f]{7,40}$", commit):
            validator.fail(
                "invalid_baseline_commit",
                f"baseline_policy: invalid baseline commit: {commit!r}",
            )
        if not isinstance(baseline.get("cache_enabled"), bool):
            validator.fail("invalid_type", "baseline_policy: cache_enabled bool")
        for field in ("dependency_lock_paths", "config_digest_paths"):
            value = baseline.get(field)
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                validator.fail("invalid_type", f"baseline_policy: {field} list[str]")
            elif value != sorted(value):
                validator.fail("unstable_order", f"baseline_policy: {field} sorted")
    else:
        validator.fail("invalid_type", "baseline_policy must be an object")

    platform_requirements = data.get("platform_requirements", {})
    if isinstance(platform_requirements, dict):
        unknown = sorted(set(platform_requirements) - set(PLATFORM_FIELDS))
        if unknown:
            validator.fail("unknown_field", f"platform_requirements: {unknown}")
        missing = sorted(set(PLATFORM_FIELDS) - set(platform_requirements))
        if missing:
            validator.fail("missing_field", f"platform_requirements: {missing}")
    else:
        validator.fail("invalid_type", "platform_requirements must be an object")

    for section, fields in (
        ("evidence_policy", EVIDENCE_POLICY_FIELDS),
        ("feature_lineage", FEATURE_LINEAGE_FIELDS),
        ("product_guard", PRODUCT_GUARD_FIELDS),
    ):
        value = data.get(section, {})
        if not isinstance(value, dict):
            validator.fail("invalid_type", f"{section} must be an object")
            continue
        unknown = sorted(set(value) - set(fields))
        if unknown:
            validator.fail("unknown_field", f"{section}: unknown {unknown}")
        missing = sorted(set(fields) - set(value))
        if missing:
            validator.fail("missing_field", f"{section}: missing {missing}")

    guard = data.get("product_guard") or {}
    if isinstance(guard, dict):
        base_commit = guard.get("block_base_commit", "")
        if not isinstance(base_commit, str) or not re.match(
            r"^[0-9a-f]{7,40}$", base_commit
        ):
            validator.fail(
                "invalid_block_base_commit",
                f"product_guard: invalid block base commit: {base_commit!r}",
            )

    for section in ("feature_lineage", "product_guard"):
        for key, value in sorted((data.get(section) or {}).items()):
            if key == "block_base_commit":
                continue
            paths_list = value if isinstance(value, list) else [value]
            for item in paths_list:
                if isinstance(item, str) and (
                    item.startswith("/")
                    or any(hint in item for hint in _ABS_PATH_HINTS)
                ):
                    validator.fail(
                        "absolute_user_path",
                        f"{section}.{key}: absolute path not allowed: {item}",
                    )


def _validate_targeted(validator, data, check_ids):
    selection = data.get("targeted_selection", {})
    if not isinstance(selection, dict):
        validator.fail("invalid_type", "targeted_selection must be an object")
        return
    unknown = sorted(set(selection) - set(TARGETED_FIELDS))
    if unknown:
        validator.fail("unknown_field", f"targeted_selection: unknown {unknown}")
    missing = sorted(set(TARGETED_FIELDS) - set(selection))
    if missing:
        validator.fail("missing_field", f"targeted_selection: missing {missing}")
        return
    always = selection.get("always")
    if not isinstance(always, list) or not always:
        validator.fail(
            "invalid_type", "targeted_selection.always must be a non-empty list"
        )
    else:
        if always != sorted(always):
            validator.fail("unstable_order", "targeted_selection.always sorted")
        for check_id in always:
            if check_id not in check_ids:
                validator.fail(
                    "unknown_check_reference",
                    f"targeted_selection.always references unknown {check_id}",
                )
    rules = selection.get("rules")
    if not isinstance(rules, list):
        validator.fail("invalid_type", "targeted_selection.rules must be a list")
        return
    rule_ids = set()
    for rule in rules:
        if not isinstance(rule, dict):
            validator.fail("invalid_type", "targeted rule must be an object")
            continue
        unknown_rule = sorted(set(rule) - set(TARGETED_RULE_FIELDS))
        if unknown_rule:
            validator.fail("unknown_field", f"targeted rule: unknown {unknown_rule}")
        missing_rule = sorted(set(TARGETED_RULE_FIELDS) - set(rule))
        if missing_rule:
            validator.fail("missing_field", f"targeted rule: missing {missing_rule}")
            continue
        if rule["rule_id"] in rule_ids:
            validator.fail("duplicate_rule_id", f"duplicate rule: {rule['rule_id']}")
        rule_ids.add(rule["rule_id"])
        for check_id in rule["checks"]:
            if check_id not in check_ids:
                validator.fail(
                    "unknown_check_reference",
                    f"rule {rule['rule_id']} references unknown check {check_id}",
                )
        for pattern in rule["paths"]:
            if not isinstance(pattern, str) or pattern.startswith("/"):
                validator.fail(
                    "absolute_user_path",
                    f"rule {rule['rule_id']}: path must be repository relative",
                )


def validate(data, *, digest=None, path=None):
    """Validate a parsed manifest and return a :class:`Manifest`."""
    validator = _Validator()
    if not isinstance(data, dict):
        raise ManifestError([("invalid_type", "manifest must be an object")])

    unknown = sorted(set(data) - set(TOP_LEVEL_FIELDS))
    if unknown:
        validator.fail("unknown_field", f"unknown top level field(s): {unknown}")
    missing = sorted(set(TOP_LEVEL_FIELDS) - set(data))
    if missing:
        validator.fail("missing_field", f"missing top level field(s): {missing}")

    for field, expected_type in sorted(TOP_LEVEL_FIELDS.items()):
        if field in data and not isinstance(data[field], expected_type):
            validator.fail(
                "invalid_type", f"{field} must be {expected_type.__name__}"
            )
        if field in data and expected_type is bool:  # pragma: no cover
            pass

    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        validator.fail(
            "unsupported_schema_version",
            f"schema_version must be {MANIFEST_SCHEMA_VERSION}",
        )
    block_id = data.get("block_id", "")
    if not isinstance(block_id, str) or not _ID_RE.match(block_id):
        validator.fail("invalid_id", f"invalid block_id: {block_id!r}")

    required_phases = data.get("required_phases")
    if required_phases != list(PHASES):
        validator.fail(
            "invalid_phase",
            "required_phases must list exactly the five phases in order",
        )

    _validate_phase_definitions(validator, data)
    _validate_no_predeclared_results(validator, data)
    _validate_sections(validator, data)

    raw_checks = data.get("checks") or []
    seen_ids = set()
    for raw in raw_checks:
        _validate_check(validator, raw, seen_ids)

    ordering_key = []
    for raw in raw_checks:
        if isinstance(raw, dict):
            ordering_key.append(
                (PHASE_INDEX.get(raw.get("phase"), 99), str(raw.get("check_id")))
            )
    if ordering_key != sorted(ordering_key):
        validator.fail(
            "unstable_order", "checks must be sorted by phase, then check_id"
        )

    definitions = data.get("phase_definitions")
    if isinstance(definitions, dict):
        for phase in PHASES:
            definition = definitions.get(phase)
            if not isinstance(definition, dict):
                continue
            phase_checks = [
                raw
                for raw in raw_checks
                if isinstance(raw, dict) and raw.get("phase") == phase
            ]
            if definition.get("applicable") is False and phase_checks:
                validator.fail(
                    "phase_contradiction",
                    f"{phase}: a non-applicable phase must not declare checks",
                )
            if (
                definition.get("applicable") is True
                and definition.get("required") is True
                and not phase_checks
            ):
                validator.fail(
                    "missing_required_check",
                    f"{phase}: an applicable required phase needs at least one check",
                )
            if (
                definition.get("applicable") is True
                and phase_checks
                and not any(raw.get("required") for raw in phase_checks)
            ):
                validator.fail(
                    "missing_required_check",
                    f"{phase}: at least one check must be required",
                )

    _validate_targeted(validator, data, seen_ids)

    leaks = sanitize.find_violations(data, "$manifest")
    for leak in leaks:
        validator.fail(
            "manifest_leak", f"{leak['path']}: rejected content ({leak['code']})"
        )

    if validator.issues:
        raise ManifestError(sorted(set(validator.issues)))
    return Manifest(data, digest=digest, path=path)


def load(path):
    """Load, digest and validate a manifest file."""
    manifest_path = Path(path)
    raw_bytes = manifest_path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError([("invalid_json", str(exc))]) from exc
    return validate(data, digest=digest, path=manifest_path)


def manifest_path_for(worktree, block_id):
    return Path(worktree) / "config" / "gates" / "blocks" / f"{block_id}.json"


def known_block_ids(worktree):
    directory = Path(worktree) / "config" / "gates" / "blocks"
    if not directory.is_dir():
        return []
    return sorted(item.stem for item in directory.glob("*.json"))
