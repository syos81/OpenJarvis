"""Rule evaluation on parsed arguments.

Two detection layers, in this order:

1. **argument based** — the command line is tokenised, split into segments,
   freed from environment prefixes and wrappers, and every segment is matched
   against the declared rule set. ``git`` aliases are resolved, because an
   alias is defined in session writable configuration and would otherwise
   hide a forbidden operation.
2. **backstop** — the *raw* command text is matched against the declared
   backstop expressions. This layer exists so a construction the tokeniser
   cannot see through can never release a forbidden operation. It only ever
   adds detections; it never removes one.

Both layers only ever produce denies. Nothing here can turn a deny into an
allow.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import CONFIG_SCHEMA
from . import cmdparse
from .cmdparse import UnparseableCommand

#: Non-git binaries that mutate the file system when they run.
MUTATING_COMMANDS = frozenset(
    {
        "chmod",
        "chown",
        "cp",
        "dd",
        "install",
        "ln",
        "mkdir",
        "mv",
        "rm",
        "rmdir",
        "tee",
        "touch",
        "truncate",
    }
)

#: git subcommands that mutate a worktree or the repository.
MUTATING_GIT_SUBCOMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "branch",
        "checkout",
        "cherry-pick",
        "commit",
        "merge",
        "mv",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "switch",
        "update-ref",
        "worktree",
    }
)

#: Raw markers that make a command line ambiguous for target extraction.
SHELL_CONTROL_TOKENS = (";", "&&", "||", "|", "$(", "`", ">", ">>")

_SHORT_RECURSIVE = re.compile(r"^-[a-zA-Z]*[rR][a-zA-Z]*$")


class ConfigError(ValueError):
    """Raised when the rule configuration cannot be used."""


class RuleSet:
    """The validated, active rule configuration."""

    __slots__ = (
        "raw",
        "wrappers",
        "git_denies",
        "binary_denies",
        "env_file_readers",
        "env_file_pattern",
        "backstops",
        "alias_resolution",
        "exception_policy",
        "fixture_targets",
        "reason_text",
    )

    def __init__(self, raw):
        self.raw = raw
        self.wrappers = dict(raw["wrappers"])
        self.git_denies = list(raw["git_denies"])
        self.binary_denies = list(raw["binary_denies"])
        self.env_file_readers = frozenset(raw["env_file_readers"])
        self.env_file_pattern = re.compile(raw["env_file_pattern"])
        self.backstops = [
            (entry["code"], re.compile(entry["regex"]))
            for entry in raw["backstop_patterns"]
        ]
        self.alias_resolution = dict(raw["alias_resolution"])
        self.exception_policy = dict(raw["exception_policy"])
        # Optional by design. An absent block means no fixture release at
        # all, which is the fail closed default; a present block is fully
        # validated by ``fixture.configuration``.
        self.fixture_targets = dict(raw.get("fixture_targets") or {})
        self.reason_text = dict(raw["reason_text"])

    def codes(self):
        """Every deny code the rule set can produce, sorted."""
        codes = {entry["code"] for entry in self.git_denies}
        codes.update(entry["code"] for entry in self.binary_denies)
        codes.update(code for code, _ in self.backstops)
        codes.add("env_file_access")
        return sorted(codes)

    def rewrite_classes(self):
        """Mapping code -> declared rewrite class, sorted by code."""
        return {
            entry["code"]: entry.get("rewrite_class", "")
            for entry in sorted(self.git_denies, key=lambda item: item["code"])
        }

    def message(self, code):
        return self.reason_text.get(code, code)


_REQUIRED_CONFIG_FIELDS = (
    "alias_resolution",
    "backstop_patterns",
    "binary_denies",
    "config_schema",
    "config_version",
    "env_file_pattern",
    "env_file_readers",
    "exception_policy",
    "git_denies",
    "reason_text",
    "wrappers",
)

#: Fields the loader accepts but does not require. Rule R4: the accepting
#: reader is effective before the data exists, never after it.
_OPTIONAL_CONFIG_FIELDS = (
    "fixture_targets",
)


def load_rules(path):
    """Load and validate ``rules.json``. Raises :class:`ConfigError`."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError("rules_unreadable") from exc
    except ValueError as exc:
        raise ConfigError("rules_not_json") from exc
    if not isinstance(raw, dict):
        raise ConfigError("rules_not_object")
    missing = sorted(set(_REQUIRED_CONFIG_FIELDS) - set(raw))
    if missing:
        raise ConfigError("rules_missing_fields:" + ",".join(missing))
    unknown = sorted(set(raw) - set(_REQUIRED_CONFIG_FIELDS) - set(_OPTIONAL_CONFIG_FIELDS))
    if unknown:
        raise ConfigError("rules_unknown_fields:" + ",".join(unknown))
    if raw.get("config_schema") != CONFIG_SCHEMA:
        raise ConfigError("rules_schema_mismatch")
    try:
        rules = RuleSet(raw)
    except (KeyError, TypeError, re.error) as exc:
        raise ConfigError("rules_malformed") from exc
    for entry in rules.git_denies:
        if not entry.get("code") or not entry.get("subcommand"):
            raise ConfigError("rules_git_deny_incomplete")
    for entry in rules.binary_denies:
        if not entry.get("code") or not entry.get("binary"):
            raise ConfigError("rules_binary_deny_incomplete")
    policy = rules.exception_policy
    if int(policy.get("max_ttl_seconds", 0)) <= 0:
        raise ConfigError("rules_exception_ttl_invalid")
    if int(policy.get("max_ttl_seconds")) > 600:
        raise ConfigError("rules_exception_ttl_too_long")
    return rules


def _resolve_alias(rules, name, cwd):
    """Return the expansion of a git alias, or ``None``."""
    settings = rules.alias_resolution
    if not settings.get("enabled"):
        return None
    binary = str(settings.get("git_binary", ""))
    if not binary.startswith("/"):
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [binary, "config", "--get", "alias." + name],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=int(settings.get("timeout_seconds", 5)),
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.decode("utf-8", "replace").strip()
    return value or None


def _git_deny_code(rules, git, argv, cwd, depth=0):
    """Return a deny code for a parsed git command, or ``None``."""
    for entry in rules.git_denies:
        if entry["subcommand"] != git.subcommand:
            continue
        required_options = entry.get("require_any_option")
        if required_options and not git.has_option(*required_options):
            continue
        required_positional = entry.get("require_any_positional")
        if required_positional:
            positional = git.positional()
            if not positional or positional[0] not in required_positional:
                continue
        allow_only = entry.get("allow_only_options")
        if allow_only and git.has_option(*allow_only):
            continue
        return entry["code"]

    known = {item["subcommand"] for item in rules.git_denies}
    if git.subcommand in known:
        return None
    max_depth = int(rules.alias_resolution.get("max_depth", 0))
    if depth >= max_depth:
        return None
    expansion = _resolve_alias(rules, git.subcommand, cwd)
    if expansion is None:
        return None
    if expansion.startswith("!"):
        # A shell alias hides its real argument vector.
        raise UnparseableCommand("git:shell_alias")
    try:
        expanded_tokens = cmdparse.tokenise(expansion)
    except UnparseableCommand:
        raise UnparseableCommand("git:alias_unparseable")
    if not expanded_tokens:
        return None
    rebuilt = ["git"] + git.global_options + expanded_tokens + git.args
    try:
        nested = cmdparse.parse_git(rebuilt)
    except UnparseableCommand:
        raise
    return _git_deny_code(rules, nested, rebuilt, cwd, depth=depth + 1)


def _binary_deny_code(rules, argv):
    head = cmdparse.basename(argv[0])
    for entry in rules.binary_denies:
        if entry["binary"] != head:
            continue
        if entry.get("require_recursive_flag"):
            recursive = any(
                token == "--recursive" or _SHORT_RECURSIVE.match(token)
                for token in argv[1:]
            )
            if not recursive:
                continue
        return entry["code"]
    return None


def _env_file_deny(rules, argv):
    head = cmdparse.basename(argv[0])
    if head not in rules.env_file_readers:
        return None
    for token in argv[1:]:
        if rules.env_file_pattern.search(token):
            return "env_file_access"
    return None


def backstop_code(rules, command):
    """Deny code from the raw text backstop layer, or ``None``.

    The *raw* command text is used deliberately, including any heredoc body:
    the backstop must never detect less than the previous purely textual
    rule set did.
    """
    text = str(command)
    env_hit = False
    for code, pattern in rules.backstops:
        if not pattern.search(text):
            continue
        if code == "env_file_access":
            env_hit = True
            continue
        return code
    if env_hit:
        for token in re.findall(r"[^\s;&|<>]+", text):
            if rules.env_file_pattern.search(token):
                return "env_file_access"
    return None


def evaluate_command(rules, command, cwd=None):
    """Evaluate a Bash command line.

    Returns ``(code, layer)``. ``code`` is ``None`` when no rule matched.
    ``layer`` is ``"argv"``, ``"backstop"`` or ``"unparseable"``.
    """
    text = str(command)
    try:
        parsed = cmdparse.segments(text)
    except UnparseableCommand:
        code = backstop_code(rules, text)
        return (code or None, "backstop" if code else "unparseable")

    for argv, _redirects in parsed:
        tokens, _elevated = cmdparse.strip_prefixes(argv, rules.wrappers)
        if not tokens:
            continue
        head = cmdparse.basename(tokens[0])
        if head == "git":
            try:
                git = cmdparse.parse_git(tokens)
            except UnparseableCommand:
                code = backstop_code(rules, text)
                return (code or None, "backstop" if code else "unparseable")
            try:
                code = _git_deny_code(rules, git, tokens, cwd)
            except UnparseableCommand:
                code = backstop_code(rules, text)
                return (code or "git_unparseable", "backstop" if code else "unparseable")
            if code:
                return code, "argv"
            continue
        code = _binary_deny_code(rules, tokens)
        if code:
            return code, "argv"
        code = _env_file_deny(rules, tokens)
        if code:
            return code, "argv"

    code = backstop_code(rules, text)
    if code:
        return code, "backstop"
    return None, "argv"


def evaluate_path(rules, target):
    """Deny code for a file tool target, or ``None``."""
    if target and rules.env_file_pattern.search(str(target)):
        return "env_file_access"
    return None


def command_targets(rules, command):
    """Return ``(targets, ambiguous, mutating)`` for a Bash command line.

    Used by the worktree protection layer. Unchanged in substance from the
    B0a-1 behaviour; it is expressed on parsed segments instead of a single
    ``shlex.split`` so wrappers and operators no longer hide a target.
    """
    text = str(command)
    ambiguous = any(token in text for token in SHELL_CONTROL_TOKENS)
    try:
        parsed = cmdparse.segments(text)
    except UnparseableCommand:
        return [], True, True
    if not parsed:
        return [], False, False
    mutating = False
    targets = []
    for argv, redirects in parsed:
        tokens, _elevated = cmdparse.strip_prefixes(argv, rules.wrappers)
        if not tokens:
            continue
        if redirects:
            mutating = True
        head = cmdparse.basename(tokens[0])
        if head in MUTATING_COMMANDS:
            mutating = True
        if head == "git":
            try:
                git = cmdparse.parse_git(tokens)
            except UnparseableCommand:
                return targets, True, True
            targets.extend(git.directories)
            if git.subcommand in MUTATING_GIT_SUBCOMMANDS:
                mutating = True
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            if "/" in token or token in (".", ".."):
                targets.append(token)
    return targets, ambiguous, mutating
