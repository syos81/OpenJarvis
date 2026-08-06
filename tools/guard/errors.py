"""Machine readable guard error codes.

Every blocking outcome carries exactly one of these codes plus a short human
readable sentence. The codes are stable identifiers: reports, gates and the
audit log refer to them, never to prose.

Two families exist and they are never mixed:

``GUARD_*``
    integrity or bootstrap failures. The guard could not establish that it is
    running the version the owner activated. An owner command exception can
    never override one of these — the repair is an owner action outside the
    guarded session.

``DENY_*`` / ``ASK_*`` / ``ALLOW_*``
    ordinary decisions of an intact guard.
"""

from __future__ import annotations

# -- integrity and bootstrap (never overridable by an exception) ------------
GUARD_PROJECT_DIR_UNRESOLVED = "GUARD_PROJECT_DIR_UNRESOLVED"
GUARD_INSTALL_ROOT_MISSING = "GUARD_INSTALL_ROOT_MISSING"
GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED = "GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED"
GUARD_ACTIVE_MANIFEST_MISSING = "GUARD_ACTIVE_MANIFEST_MISSING"
GUARD_ACTIVE_MANIFEST_INVALID = "GUARD_ACTIVE_MANIFEST_INVALID"
GUARD_PACKAGE_MISSING = "GUARD_PACKAGE_MISSING"
GUARD_PACKAGE_HASH_MISMATCH = "GUARD_PACKAGE_HASH_MISMATCH"
GUARD_VERSION_UNSUPPORTED = "GUARD_VERSION_UNSUPPORTED"
GUARD_CONFIG_MISSING = "GUARD_CONFIG_MISSING"
GUARD_CONFIG_INVALID = "GUARD_CONFIG_INVALID"
GUARD_INTERPRETER_MISSING = "GUARD_INTERPRETER_MISSING"
GUARD_BOOTSTRAP_FAILED = "GUARD_BOOTSTRAP_FAILED"
GUARD_INPUT_MALFORMED = "GUARD_INPUT_MALFORMED"
GUARD_INTERNAL_ERROR = "GUARD_INTERNAL_ERROR"
GUARD_LOG_UNAVAILABLE = "GUARD_LOG_UNAVAILABLE"

INTEGRITY_CODES = (
    GUARD_ACTIVE_MANIFEST_INVALID,
    GUARD_ACTIVE_MANIFEST_MISSING,
    GUARD_BOOTSTRAP_FAILED,
    GUARD_CONFIG_INVALID,
    GUARD_CONFIG_MISSING,
    GUARD_INPUT_MALFORMED,
    GUARD_INSTALL_ROOT_MISSING,
    GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED,
    GUARD_INTERNAL_ERROR,
    GUARD_INTERPRETER_MISSING,
    GUARD_LOG_UNAVAILABLE,
    GUARD_PACKAGE_HASH_MISMATCH,
    GUARD_PACKAGE_MISSING,
    GUARD_PROJECT_DIR_UNRESOLVED,
    GUARD_VERSION_UNSUPPORTED,
)

# -- ordinary decisions -----------------------------------------------------
DENY_UNPARSEABLE_COMMAND = "DENY_UNPARSEABLE_COMMAND"
DENY_HIDDEN_FORBIDDEN_PATTERN = "DENY_HIDDEN_FORBIDDEN_PATTERN"
ASK_FOREIGN_WORKTREE = "ASK_FOREIGN_WORKTREE"
ASK_AMBIGUOUS_TARGET = "ASK_AMBIGUOUS_TARGET"
DENY_WORKTREE_UNDETERMINED = "DENY_WORKTREE_UNDETERMINED"

#: Short, non-secret sentences. No path, no nonce, no command text.
MESSAGES = {
    GUARD_PROJECT_DIR_UNRESOLVED: "the project directory could not be resolved",
    GUARD_INSTALL_ROOT_MISSING: "the active guard installation is missing",
    GUARD_INSTALL_ROOT_NOT_OWNER_CONTROLLED: (
        "the active guard installation is not owner controlled"
    ),
    GUARD_ACTIVE_MANIFEST_MISSING: "the active guard manifest is missing",
    GUARD_ACTIVE_MANIFEST_INVALID: "the active guard manifest is invalid",
    GUARD_PACKAGE_MISSING: "the active guard package is missing",
    GUARD_PACKAGE_HASH_MISMATCH: "the active guard package hash does not match",
    GUARD_VERSION_UNSUPPORTED: "the active guard version is not supported",
    GUARD_CONFIG_MISSING: "the active guard rule configuration is missing",
    GUARD_CONFIG_INVALID: "the active guard rule configuration is invalid",
    GUARD_INTERPRETER_MISSING: "no owner controlled interpreter is available",
    GUARD_BOOTSTRAP_FAILED: "the guard bootstrap could not produce a decision",
    GUARD_INPUT_MALFORMED: "the tool request could not be read",
    GUARD_INTERNAL_ERROR: "the guard hit an internal error",
    GUARD_LOG_UNAVAILABLE: "the protected guard log is not writable",
    DENY_UNPARSEABLE_COMMAND: "the command could not be parsed safely",
    DENY_HIDDEN_FORBIDDEN_PATTERN: (
        "the command may hide a forbidden operation"
    ),
    ASK_FOREIGN_WORKTREE: (
        "this would modify a different worktree of the same repository"
    ),
    ASK_AMBIGUOUS_TARGET: (
        "mutating command whose targets cannot be determined with confidence"
    ),
    DENY_WORKTREE_UNDETERMINED: (
        "mutating request in an undeterminable repository state"
    ),
}


def message(code, fallback=""):
    """Return the short sentence for ``code``.

    Unknown codes fall back to the code itself so a decision is never
    reported without an identifier.
    """
    return MESSAGES.get(code, fallback or str(code))
