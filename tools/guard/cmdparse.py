"""Argument based parsing of Bash command lines.

The guard never decides from a raw substring comparison. It tokenises the
command line, splits it into segments at shell operators, strips environment
prefixes and known wrappers and then inspects *arguments*.

Everything that cannot be tokenised or that hides its real argument vector
behind an expansion is reported as unparseable. The caller blocks in that
case — an unparseable construction is never released.

Heredoc bodies are removed before tokenisation. A heredoc carries data, not
commands; leaving it in would make every document that merely mentions a
forbidden command line look like an execution of it.
"""

from __future__ import annotations

import re
import shlex

#: Tokens that end one command segment and start the next.
OPERATORS = (";", "&&", "||", "|", "&", "(", ")", "\n", "|&")

#: Redirection operators. They mark a segment as mutating but never carry the
#: command name.
REDIRECTIONS = (">", ">>", "<", "<<", "<<<", ">|", "2>", "2>>", "&>", ">&")

#: Constructs whose expansion is unknown at parse time.
_OPAQUE = ("$(", "`", "<(", ">(", "${")

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


class UnparseableCommand(Exception):
    """Raised when the real argument vector cannot be established."""

    def __init__(self, detail="unparseable"):
        self.detail = detail
        super().__init__(detail)


def strip_heredocs(command):
    """Return ``(command_without_heredoc_bodies, had_heredoc)``.

    A heredoc body is data. It is cut out so its content is never mistaken
    for an executed command. The introducing ``<<DELIM`` stays in place, so
    the redirection itself is still visible to the tokeniser.
    """
    match = _HEREDOC.search(command)
    if not match:
        return command, False
    lines = command.split("\n")
    kept = []
    pending = []
    index = 0
    while index < len(lines):
        line = lines[index]
        found = _HEREDOC.search(line)
        kept.append(line)
        index += 1
        if not found:
            continue
        delimiter = found.group(2)
        while index < len(lines):
            body = lines[index]
            index += 1
            if body.strip() == delimiter:
                break
            pending.append(body)
    return "\n".join(kept), True


def tokenise(command):
    """Tokenise a command line. Raises :class:`UnparseableCommand`."""
    text = str(command)
    stripped, _ = strip_heredocs(text)
    lexer = shlex.shlex(stripped, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError as exc:
        raise UnparseableCommand(f"tokenise:{exc.__class__.__name__}") from exc


def has_opaque_expansion(command):
    """True when the command contains a construct with unknown expansion."""
    stripped, _ = strip_heredocs(str(command))
    return any(marker in stripped for marker in _OPAQUE)


def segments(command):
    """Split a command line into argument vectors.

    Returns a list of ``(argv, redirects)`` tuples. ``redirects`` is ``True``
    when the segment writes through a shell redirection.
    """
    tokens = tokenise(command)
    result = []
    current = []
    redirects = False
    for token in tokens:
        if token in OPERATORS:
            if current:
                result.append((current, redirects))
            current = []
            redirects = False
            continue
        if token in REDIRECTIONS or (
            token
            and token[0] in ("<", ">")
            and set(token) <= set("<>&|012")
        ):
            redirects = True
            continue
        current.append(token)
    if current:
        result.append((current, redirects))
    return result


def strip_prefixes(argv, wrappers):
    """Remove environment assignments and known wrappers from ``argv``.

    ``wrappers`` maps a wrapper name to the number of its own leading option
    arguments that carry a value (``{"nice": 1}`` for ``nice -n 10 cmd``).
    Returns ``(argv, elevated)``. ``elevated`` is ``True`` when the command
    was wrapped in a privilege escalation.
    """
    tokens = list(argv)
    elevated = False
    seen = 0
    while tokens and seen < 8:
        head = tokens[0]
        if _ENV_ASSIGNMENT.match(head):
            tokens = tokens[1:]
            seen += 1
            continue
        name = basename(head)
        if name not in wrappers:
            break
        if name in ("sudo", "doas", "su"):
            elevated = True
        tokens = tokens[1:]
        seen += 1
        value_options = int(wrappers[name])
        while tokens:
            candidate = tokens[0]
            if _ENV_ASSIGNMENT.match(candidate):
                tokens = tokens[1:]
                continue
            if not candidate.startswith("-"):
                break
            tokens = tokens[1:]
            if value_options and tokens and not tokens[0].startswith("-"):
                # A wrapper option that takes a value, e.g. ``nice -n 10``.
                tokens = tokens[1:]
            break
    return tokens, elevated


def basename(token):
    """Last path component of a token, without quoting artefacts."""
    text = str(token)
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text


class GitCommand:
    """A parsed ``git`` invocation."""

    __slots__ = ("subcommand", "args", "directories", "global_options")

    def __init__(self, subcommand, args, directories, global_options):
        self.subcommand = subcommand
        self.args = list(args)
        self.directories = list(directories)
        self.global_options = list(global_options)

    def has_option(self, *names):
        """True when one of ``names`` appears as an argument option.

        ``--amend`` also matches ``--amend=…`` so an option with an attached
        value cannot slip past.
        """
        for argument in self.args:
            for name in names:
                if argument == name or argument.startswith(name + "="):
                    return True
        return False

    def positional(self):
        return [item for item in self.args if not item.startswith("-")]


#: git global options that consume the following token as a value.
_GIT_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace",
                      "--exec-path", "--super-prefix", "--config-env")
#: git global options that name a directory.
_GIT_DIRECTORY_OPTIONS = ("-C", "--git-dir", "--work-tree")


def parse_git(argv):
    """Parse ``argv`` of a git invocation.

    Returns a :class:`GitCommand`. Raises :class:`UnparseableCommand` when
    the subcommand cannot be determined.
    """
    tokens = list(argv[1:])
    global_options = []
    directories = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            break
        global_options.append(token)
        name, sep, value = token.partition("=")
        if sep:
            if name in _GIT_DIRECTORY_OPTIONS:
                directories.append(value)
            index += 1
            continue
        if name in _GIT_VALUE_OPTIONS:
            if index + 1 >= len(tokens):
                raise UnparseableCommand("git:option_without_value")
            value = tokens[index + 1]
            if name in _GIT_DIRECTORY_OPTIONS:
                directories.append(value)
            global_options.append(value)
            index += 2
            continue
        index += 1
    if index >= len(tokens):
        raise UnparseableCommand("git:no_subcommand")
    subcommand = tokens[index]
    if any(marker in subcommand for marker in ("$", "`")):
        raise UnparseableCommand("git:opaque_subcommand")
    return GitCommand(subcommand, tokens[index + 1:], directories, global_options)
