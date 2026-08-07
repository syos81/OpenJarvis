"""The derived corpus of executable check paths (block B0e).

The R9 and R10 sweeps must not run over a hand picked directory list: a check
path that exists but is not looked at would silently fall out of every
statement the sweep makes. This module therefore *derives* which files are
actually executable as tests, validators, gate checkers or evidence checkers,
and it records for every file why it is in the corpus.

Sources of executability, each recorded per file:

``pytest_testpaths``
    ``pyproject.toml`` declares ``[tool.pytest.ini_options] testpaths``; the
    project does not override ``python_files``, so pytest's documented
    default discovery patterns apply (``test_*.py`` and ``*_test.py``).
``unittest_discovery``
    a block manifest runs ``-m unittest discover -s <dir>``; unittest's
    default pattern ``test*.py`` applies below that start directory.
``unittest_module``
    a block manifest runs ``-m unittest -v <module> ...`` with an explicit
    dotted module list.
``manifest_runner``
    a block manifest executes ``${GATE_TOOLS}/runners/<name>.py`` directly.
``entry_script``
    a shell entry point (``scripts/*.sh``, ``.claude/hooks/*.sh``,
    ``tools/guardpkg/*.sh``) executes a repository Python module or file.
    Shell has no Python syntax tree; the reference extraction from these
    wrappers is the single, documented exception to the AST-only rule, and
    it only ever *adds* files to the corpus.
``import_closure``
    a module below ``tools/`` imported, transitively, from any file already
    in the corpus via one of the sources above. Resolved over the syntax
    tree of each importer, never over text.

Rule R10 applies to the derivation itself: a missing source (no
``pyproject.toml``, no block manifests, no scripts directory) is an error,
never an empty corpus, and an empty corpus is an error too. ``derive`` never
returns a corpus with zero files, zero units or zero syntax tree nodes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: pytest's default discovery patterns; pyproject.toml does not override
#: ``python_files``, which is asserted during derivation.
PYTEST_FILE_PATTERNS = ("test_*.py", "*_test.py")

#: unittest's default discovery pattern for ``discover``.
UNITTEST_DISCOVER_PATTERN = "test*.py"

#: Shell entry point areas that may execute repository Python.
ENTRY_SCRIPT_AREAS = ("scripts", ".claude/hooks", "tools/guardpkg")

#: Only modules below these roots belong to the import closure: they are the
#: check tooling. Product code under ``src/`` is a *subject* of checks, not a
#: check path.
CLOSURE_ROOTS = ("tools",)

SOURCE_KINDS = (
    "pytest_testpaths",
    "unittest_discovery",
    "unittest_module",
    "manifest_runner",
    "entry_script",
    "import_closure",
)

_MODULE_RE = re.compile(r"-m[ \t]+([A-Za-z_][A-Za-z0-9_.]*)")
_PYFILE_RE = re.compile(r"((?:tools|scripts)/[A-Za-z0-9_./-]+\.py)\b")


class CorpusError(ValueError):
    """Raised with a machine readable code when the corpus cannot be derived.

    Missing inputs raise; they never shrink the corpus to an empty set that
    could later read as a clean sweep.
    """

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class CorpusFile:
    """One executable file and the evidence for its executability."""

    __slots__ = ("path", "derivations")

    def __init__(self, path):
        self.path = path
        self.derivations = []

    def add(self, source, detail):
        entry = {"source": source, "detail": detail}
        if entry not in self.derivations:
            self.derivations.append(entry)


class Unit:
    """One function or method in a corpus file."""

    __slots__ = ("qualname", "node", "is_test_named")

    def __init__(self, qualname, node):
        self.qualname = qualname
        self.node = node
        self.is_test_named = qualname.rsplit(".", 1)[-1].startswith("test")


class _UnitCollector(ast.NodeVisitor):
    def __init__(self):
        self.units = []
        self._stack = []

    def visit_ClassDef(self, node):
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def _function(self, node):
        self.units.append(Unit(".".join(self._stack + [node.name]), node))
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function


class Corpus:
    """The derived corpus: files, parsed trees, units and counts."""

    __slots__ = ("files", "trees", "units", "counts")

    def __init__(self, files, trees, units, counts):
        self.files = files
        self.trees = trees
        self.units = units
        self.counts = counts


def collect_units(tree):
    """All function and method units of a parsed module, in source order."""
    collector = _UnitCollector()
    collector.visit(tree)
    return collector.units


def _read_pytest_testpaths(worktree):
    target = worktree / "pyproject.toml"
    if not target.is_file():
        raise CorpusError("corpus_source_missing", "pyproject.toml")
    try:
        import tomllib
    except ImportError as exc:  # pragma: no cover - interpreter floor
        raise CorpusError("corpus_reader_unavailable", "tomllib") from exc
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorpusError("corpus_source_unreadable", "pyproject.toml") from exc
    options = data.get("tool", {}).get("pytest", {}).get("ini_options")
    if not isinstance(options, dict) or not options.get("testpaths"):
        raise CorpusError("corpus_source_missing", "tool.pytest.ini_options.testpaths")
    if "python_files" in options:
        # The derivation would silently diverge from the real discovery.
        raise CorpusError("corpus_convention_overridden", "python_files")
    testpaths = options["testpaths"]
    if not isinstance(testpaths, list) or not all(isinstance(p, str) for p in testpaths):
        raise CorpusError("corpus_source_unreadable", "testpaths")
    return testpaths


def _block_manifests(worktree):
    blocks_dir = worktree / "config" / "gates" / "blocks"
    if not blocks_dir.is_dir():
        raise CorpusError("corpus_source_missing", "config/gates/blocks")
    from . import manifest as manifest_module

    manifests = []
    for path in sorted(blocks_dir.glob("*.json")):
        try:
            manifests.append(manifest_module.load(path))
        except manifest_module.ManifestError as exc:
            raise CorpusError("corpus_manifest_invalid", path.name) from exc
    if not manifests:
        raise CorpusError("corpus_source_missing", "config/gates/blocks/*.json")
    return manifests


def _module_to_path(worktree, dotted):
    relative = Path(*dotted.split("."))
    for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
        if (worktree / candidate).is_file():
            return candidate
    return None


def _add(files, worktree, relative, source, detail):
    relative = Path(relative)
    if not (worktree / relative).is_file():
        return None
    key = relative.as_posix()
    record = files.get(key)
    if record is None:
        record = files[key] = CorpusFile(key)
    record.add(source, detail)
    return record


def _from_manifests(files, worktree, manifests):
    for manifest in manifests:
        for check in manifest.checks:
            argv = list(check.runner.get("argv") or [])
            label = f"{manifest.block_id}:{check.check_id}"
            if "-m" in argv and "unittest" in argv:
                if "discover" in argv:
                    if "-s" in argv:
                        start = argv[argv.index("-s") + 1]
                        base = worktree / start
                        if not base.is_dir():
                            raise CorpusError("corpus_source_missing", start)
                        for found in sorted(base.rglob(UNITTEST_DISCOVER_PATTERN)):
                            if "__pycache__" in found.parts:
                                continue
                            _add(
                                files,
                                worktree,
                                found.relative_to(worktree),
                                "unittest_discovery",
                                f"{label} -s {start}",
                            )
                else:
                    for argument in argv[argv.index("unittest") + 1 :]:
                        if argument.startswith("-"):
                            continue
                        module_path = _module_to_path(worktree, argument)
                        if module_path is None:
                            raise CorpusError("corpus_module_unresolved", argument)
                        _add(files, worktree, module_path, "unittest_module", label)
            for argument in argv:
                if argument.startswith("${GATE_TOOLS}/"):
                    relative = Path("tools/gates") / argument[len("${GATE_TOOLS}/") :]
                    if relative.suffix == ".py":
                        if not (worktree / relative).is_file():
                            raise CorpusError("corpus_runner_missing", str(relative))
                        _add(files, worktree, relative, "manifest_runner", label)


def _from_entry_scripts(files, worktree):
    seen_area = False
    for area in ENTRY_SCRIPT_AREAS:
        base = worktree / area
        if not base.is_dir():
            continue
        seen_area = True
        for script in sorted(base.glob("*.sh")):
            try:
                text = script.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise CorpusError("corpus_source_unreadable", script.name) from exc
            label = script.relative_to(worktree).as_posix()
            for match in _MODULE_RE.finditer(text):
                module_path = _module_to_path(worktree, match.group(1))
                if module_path is not None:
                    _add(files, worktree, module_path, "entry_script", label)
            for match in _PYFILE_RE.finditer(text):
                _add(files, worktree, match.group(1), "entry_script", label)
    if not seen_area:
        raise CorpusError("corpus_source_missing", "entry script areas")


def _imports_of(tree, importer_relative):
    """Dotted module names imported by ``tree``, resolved for relative form."""
    package_parts = list(Path(importer_relative).parent.parts)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                prefix = ".".join(base)
                module = f"{prefix}.{node.module}" if node.module else prefix
            else:
                module = node.module or ""
            if module:
                names.add(module)
                for alias in node.names:
                    names.add(f"{module}.{alias.name}")
    return names


def _closure(files, trees, worktree):
    pending = [key for key in files if key.split("/", 1)[0] in CLOSURE_ROOTS]
    # Test files import the check tooling too; their imports seed the closure
    # exactly like the entry points' do.
    pending.extend(key for key in files if key.split("/", 1)[0] not in CLOSURE_ROOTS)
    visited = set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        tree = _parse_into(trees, worktree, key)
        for dotted in sorted(_imports_of(tree, key)):
            if dotted.split(".", 1)[0] not in CLOSURE_ROOTS:
                continue
            module_path = _module_to_path(worktree, dotted)
            if module_path is None:
                continue
            record = _add(files, worktree, module_path, "import_closure", key)
            if record is not None and record.path not in visited:
                pending.append(record.path)


def _parse_into(trees, worktree, key):
    if key not in trees:
        try:
            source = (worktree / key).read_text(encoding="utf-8")
            trees[key] = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            raise CorpusError("corpus_file_unparseable", key) from exc
    return trees[key]


def derive(worktree):
    """Derive the executable corpus. Raises :class:`CorpusError`, never
    returns an empty corpus."""
    worktree = Path(worktree)
    files = {}

    for testpath in _read_pytest_testpaths(worktree):
        base = worktree / testpath
        if not base.is_dir():
            raise CorpusError("corpus_source_missing", testpath)
        for pattern in PYTEST_FILE_PATTERNS:
            for found in sorted(base.rglob(pattern)):
                if "__pycache__" in found.parts:
                    continue
                _add(
                    files,
                    worktree,
                    found.relative_to(worktree),
                    "pytest_testpaths",
                    f"testpaths {testpath} pattern {pattern}",
                )

    _from_manifests(files, worktree, _block_manifests(worktree))
    _from_entry_scripts(files, worktree)

    trees = {}
    _closure(files, trees, worktree)

    units = {}
    node_count = 0
    test_units = 0
    validator_units = 0
    for key in sorted(files):
        tree = _parse_into(trees, worktree, key)
        node_count += sum(1 for _ in ast.walk(tree))
        found = collect_units(tree)
        units[key] = found
        in_tools = key.split("/", 1)[0] in CLOSURE_ROOTS
        for unit in found:
            if in_tools:
                validator_units += 1
            elif unit.is_test_named:
                test_units += 1

    counts = {
        "files": len(files),
        "ast_nodes": node_count,
        "units": sum(len(found) for found in units.values()),
        "test_units": test_units,
        "validator_units": validator_units,
    }
    for field in ("files", "ast_nodes", "units"):
        if counts[field] <= 0:
            raise CorpusError("corpus_empty", field)
    return Corpus(files, trees, units, counts)
