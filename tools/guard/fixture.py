"""Target bound release of ``push`` and ``update-ref`` against a fixture.

Why this exists at all. A gate whose run presupposes a present human is not a
reproducible gate, and ``offline-final`` has to run without the owner. The
owner command exception cannot carry this: it needs ``sudo`` and it expires
after its short time to live. So the release is not an exception but a
**rule** — declared, deterministic, and bound to the target rather than to a
person.

What stays blocked, unconditionally:

* the real ``origin`` and every other declared protected remote name,
* a remote **alias** that resolves onto a protected remote,
* every declared protected ref, wherever it is pushed,
* a target that leaves the declared fixture root through a symlink,
* a target that carries a ``..`` component,
* anything the guard cannot fully establish.

What is released, and only this: a ``push`` or an ``update-ref`` whose target
resolves to a throwaway **bare** repository below a strictly canonicalised,
declared fixture root.

The target is established with the same trust chain discipline the bootstrap
applies to its interpreter, because resolving a target *is* parsing and the
guard is the trust anchor:

1. the raw token carries no parent reference,
2. the lexical path lies below the declared root, and no component of it is
   a symlink,
3. the fully resolved real path lies below the resolved real root,
4. every element from the root down to the target is a directory the session
   may write,
5. the target really is a bare repository,
6. the target is not, and does not contain, the repository being protected.

Every step is a veto. There is no majority, no fallback and no "probably":
this module returns a release only when all of it holds, and returns the
reason code of the first failing step otherwise. A failure here is never an
error — it simply leaves the layer 1 deny in force.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from . import cmdparse
from .cmdparse import UnparseableCommand

#: The one positive outcome.
RELEASE = "fixture_target_release"

#: Everything below means: no release, the deny stands.
NOT_CONFIGURED = "fixture_rule_not_configured"
DISABLED = "fixture_rule_disabled"
CODE_NOT_ELIGIBLE = "fixture_code_not_eligible"
COMMAND_OPAQUE = "fixture_command_has_opaque_expansion"
COMMAND_NOT_SINGLE_SEGMENT = "fixture_command_is_not_a_single_segment"
COMMAND_ELEVATED = "fixture_command_is_elevated"
NOT_A_GIT_COMMAND = "fixture_command_is_not_git"
SUBCOMMAND_NOT_ELIGIBLE = "fixture_subcommand_not_eligible"
OPTION_PRESENT = "fixture_option_present"
ARGUMENT_SHAPE = "fixture_argument_shape_unexpected"
REMOTE_IS_PROTECTED = "fixture_remote_is_protected"
ALIAS_RESOLVES_TO_PROTECTED = "fixture_remote_alias_resolves_to_protected_remote"
ALIAS_UNRESOLVABLE = "fixture_remote_alias_unresolvable"
TARGET_NOT_A_LOCAL_PATH = "fixture_target_is_not_a_local_path"
TARGET_HAS_PARENT_REFERENCE = "fixture_target_has_parent_reference"
WORKTREE_UNDETERMINED = "fixture_worktree_undetermined"
ROOT_MISSING = "fixture_root_missing"
OUTSIDE_ROOT = "fixture_target_outside_declared_root"
SYMLINK_IN_PATH = "fixture_symlink_in_path"
NOT_WRITABLE = "fixture_element_not_session_writable"
NOT_A_BARE_REPOSITORY = "fixture_target_is_not_a_bare_repository"
IS_THE_PROTECTED_REPOSITORY = "fixture_target_is_the_protected_repository"
REF_IS_PROTECTED = "fixture_ref_is_protected"
REFSPEC_FORCED = "fixture_refspec_is_forced"

#: Config keys. A missing key disables the rule; it never defaults to open.
_REQUIRED_KEYS = (
    "declared_roots",
    "eligible_codes",
    "enabled",
    "protected_ref_patterns",
    "protected_remote_names",
)

#: A local path never carries a URL scheme or an scp style host separator.
_NON_LOCAL = re.compile(r"://|@|:")
_BARE_TRUE = re.compile(r"^\s*bare\s*=\s*true\s*$", re.IGNORECASE | re.MULTILINE)


class Verdict:
    """The outcome of one fixture evaluation."""

    __slots__ = ("granted", "code", "local_target")

    def __init__(self, granted, code, local_target=""):
        self.granted = granted
        self.code = code
        #: Resolved target, for the gitignored repository side log only.
        self.local_target = local_target


def _no(code):
    return Verdict(False, code)


def configuration(rules):
    """Return the validated fixture configuration, or ``None``."""
    raw = getattr(rules, "fixture_targets", None)
    if not isinstance(raw, dict):
        return None
    if sorted(set(_REQUIRED_KEYS) - set(raw)):
        return None
    return raw


def _components(relative):
    return [part for part in str(relative).split(os.sep) if part not in ("", ".")]


def _has_parent_reference(raw):
    text = str(raw).replace("\\", "/")
    return any(part == ".." for part in text.split("/"))


def _is_bare_repository(path):
    """Filesystem-only check. The target is never asked to describe itself."""
    if not path.is_dir():
        return False
    if (path / ".git").exists():
        return False
    if not (path / "HEAD").is_file():
        return False
    if not (path / "objects").is_dir() or not (path / "refs").is_dir():
        return False
    config = path / "config"
    if not config.is_file():
        return False
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_BARE_TRUE.search(text))


def _normalise_ref(token):
    """Full ref name of a refspec destination."""
    text = str(token)
    if text.startswith("refs/") or text == "HEAD":
        return text
    return "refs/heads/" + text


def _refspec_destination(token):
    """Return ``(destination, forced)`` for one refspec."""
    text = str(token)
    forced = text.startswith("+")
    if forced:
        text = text[1:]
    source, separator, destination = text.partition(":")
    return (destination if separator else source), forced


def _protected_ref(config, ref):
    for pattern in config["protected_ref_patterns"]:
        if fnmatch.fnmatchcase(ref, str(pattern)):
            return True
    return False


def _resolve_remote(config, token, run_git, cwd):
    """Resolve a token that may be a configured remote name.

    Returns ``(url_or_token, verdict_or_None)``. A token that is a configured
    remote is *always* replaced by its url — a name is never trusted to mean
    what it looks like.
    """
    protected = [str(name) for name in config["protected_remote_names"]]
    if str(token) in protected:
        return None, _no(REMOTE_IS_PROTECTED)

    code, out = run_git(["config", "--get", "remote." + str(token) + ".url"], cwd)
    if code != 0 or not out.strip():
        # Not a configured remote. The token has to stand on its own as a
        # path; that is decided by the path layer below.
        return str(token), None

    url = out.strip().splitlines()[0].strip()
    for name in protected:
        code, other = run_git(["config", "--get", "remote." + name + ".url"], cwd)
        if code == 0 and other.strip() and other.strip().splitlines()[0].strip() == url:
            return None, _no(ALIAS_RESOLVES_TO_PROTECTED)
    if not url:
        return None, _no(ALIAS_UNRESOLVABLE)
    return url, None


def _protected_repository(run_git, cwd):
    """Real path of the git directory of the repository being protected."""
    code, out = run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if code != 0 or not out.strip():
        code, out = run_git(["rev-parse", "--git-common-dir"], cwd)
    if code != 0 or not out.strip():
        return None
    candidate = Path(out.strip())
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    try:
        return Path(os.path.realpath(str(candidate)))
    except OSError:  # pragma: no cover - defensive
        return None


def _root_prefix(target_lexical, root_real):
    """Shortest prefix of the given path that really *is* the declared root.

    The path a command spells and the path the filesystem resolves it to may
    differ without any redirection — a temporary directory below a system
    symlink is the ordinary case. Containment is therefore decided on the
    resolved paths, and this function only establishes where the symlink walk
    over the *given* spelling has to start.

    The **shortest** matching prefix is deliberate. A link inside the root
    that points back at the root resolves to the root as well, so taking the
    longest match would start the walk behind that link and never look at it.
    Starting at the first point that is the root means every component the
    command actually named is inspected. Returns ``None`` when the target is
    not addressed through the root at all.
    """
    candidate = Path(target_lexical)
    prefixes = []
    while True:
        prefixes.append(candidate)
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    for prefix in reversed(prefixes):
        try:
            if Path(os.path.realpath(str(prefix))) == Path(root_real):
                return prefix
        except OSError:  # pragma: no cover - defensive
            return None
    return None


def _inside(path, root):
    try:
        Path(path).relative_to(Path(root))
    except ValueError:
        return False
    return True


def _resolve_target(config, raw, run_git, cwd):
    """Full trust chain over one target path. Returns a :class:`Verdict`."""
    if _has_parent_reference(raw):
        return _no(TARGET_HAS_PARENT_REFERENCE)
    if _NON_LOCAL.search(str(raw)):
        return _no(TARGET_NOT_A_LOCAL_PATH)

    code, out = run_git(["rev-parse", "--show-toplevel"], cwd)
    if code != 0 or not out.strip():
        return _no(WORKTREE_UNDETERMINED)
    worktree = Path(out.strip())

    target_lexical = Path(os.path.normpath(os.path.join(str(cwd), str(raw))))
    try:
        target_real = Path(os.path.realpath(str(target_lexical)))
    except OSError:  # pragma: no cover - defensive
        return _no(OUTSIDE_ROOT)

    for declared in config["declared_roots"]:
        if _has_parent_reference(declared) or os.path.isabs(str(declared)):
            # A declared root is always relative to the worktree, so no
            # machine specific absolute path can enter the rule set.
            continue
        root_lexical = Path(os.path.normpath(str(worktree / str(declared))))
        if not root_lexical.is_dir():
            continue
        try:
            root_real = Path(os.path.realpath(str(root_lexical)))
        except OSError:  # pragma: no cover - defensive
            continue

        if not _inside(target_real, root_real):
            # Containment is decided on the resolved paths, never on the
            # spelling: the same directory can be addressed by several names
            # and only the real one says where the write lands.
            continue

        # No component of the *given* path may be a symlink below the root,
        # so a link that stays inside the root cannot redirect the target
        # either. The walk starts at the longest prefix of the given path
        # that really is the root, so a differently spelled but identical
        # prefix neither weakens nor breaks the check.
        entry = _root_prefix(target_lexical, root_real)
        if entry is None:
            # The target resolves into the root but is not addressed through
            # it. That is not a spelling variant, it is a redirection.
            return _no(SYMLINK_IN_PATH)
        walked = entry
        for part in _components(target_lexical.relative_to(entry)):
            walked = walked / part
            if os.path.islink(str(walked)):
                return _no(SYMLINK_IN_PATH)
        # And the same for the resolved chain, which is what is written to.
        walked = root_real
        elements = [root_real]
        for part in _components(target_real.relative_to(root_real)):
            walked = walked / part
            if os.path.islink(str(walked)):
                return _no(SYMLINK_IN_PATH)
            elements.append(walked)
        for element in elements:
            if not element.is_dir() or not os.access(str(element), os.W_OK):
                return _no(NOT_WRITABLE)

        protected = _protected_repository(run_git, cwd)
        if protected is not None and (
            target_real == protected
            or _inside(target_real, protected)
            or _inside(protected, target_real)
        ):
            return _no(IS_THE_PROTECTED_REPOSITORY)

        if not _is_bare_repository(target_real):
            return _no(NOT_A_BARE_REPOSITORY)
        return Verdict(True, RELEASE, str(target_real))

    if not any(
        (Path(os.path.normpath(str(worktree / str(declared))))).is_dir()
        for declared in config["declared_roots"]
        if not _has_parent_reference(declared) and not os.path.isabs(str(declared))
    ):
        return _no(ROOT_MISSING)
    return _no(OUTSIDE_ROOT)


def evaluate(rules, code, command, cwd, run_git):
    """Decide whether one denied command is released by the fixture rule.

    ``run_git`` is ``(args, cwd) -> (returncode, stdout)``. Nothing here ever
    runs the command that is being judged.
    """
    config = configuration(rules)
    if config is None:
        return _no(NOT_CONFIGURED)
    if not config.get("enabled"):
        return _no(DISABLED)
    if str(code) not in [str(item) for item in config["eligible_codes"]]:
        return _no(CODE_NOT_ELIGIBLE)

    text = str(command)
    if cmdparse.has_opaque_expansion(text):
        return _no(COMMAND_OPAQUE)
    try:
        parsed = cmdparse.segments(text)
    except UnparseableCommand:
        return _no(COMMAND_NOT_SINGLE_SEGMENT)
    if len(parsed) != 1:
        # One command, or nothing. A second segment could carry anything.
        return _no(COMMAND_NOT_SINGLE_SEGMENT)
    argv, redirects = parsed[0]
    if redirects:
        return _no(COMMAND_NOT_SINGLE_SEGMENT)

    tokens, elevated = cmdparse.strip_prefixes(argv, rules.wrappers)
    if elevated:
        return _no(COMMAND_ELEVATED)
    if not tokens or cmdparse.basename(tokens[0]) != "git":
        return _no(NOT_A_GIT_COMMAND)
    try:
        git = cmdparse.parse_git(tokens)
    except UnparseableCommand:
        return _no(NOT_A_GIT_COMMAND)

    if any(str(argument).startswith("-") for argument in git.args):
        # No option is interpreted, so no option can be misinterpreted.
        # This also removes every force and delete variant by construction.
        return _no(OPTION_PRESENT)
    positional = git.positional()

    if git.subcommand == "push":
        if len(positional) != 2:
            return _no(ARGUMENT_SHAPE)
        repository, refspec = positional
        destination, forced = _refspec_destination(refspec)
        if forced:
            return _no(REFSPEC_FORCED)
        if not destination.strip():
            return _no(ARGUMENT_SHAPE)
        if _protected_ref(config, _normalise_ref(destination)):
            return _no(REF_IS_PROTECTED)
        resolved, verdict = _resolve_remote(config, repository, run_git, cwd)
        if verdict is not None:
            return verdict
        return _resolve_target(config, resolved, run_git, cwd)

    if git.subcommand == "update-ref":
        if len(positional) not in (2, 3):
            return _no(ARGUMENT_SHAPE)
        if len(git.directories) != 1:
            # Without an explicit repository the target would be the current
            # one, which is exactly what must never be released.
            return _no(ARGUMENT_SHAPE)
        if _protected_ref(config, _normalise_ref(positional[0])):
            return _no(REF_IS_PROTECTED)
        return _resolve_target(config, git.directories[0], run_git, cwd)

    return _no(SUBCOMMAND_NOT_ELIGIBLE)
