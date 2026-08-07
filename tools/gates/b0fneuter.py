"""Pytest plugin: neutralise one injected disturbance at import time (B0f).

The ``r9_injection_load_bearing`` category claims a test cannot pass without
its injected exception. This plugin makes that claim executable: it rewrites
the target module's syntax tree while pytest imports it, removing exactly the
injection at the anchor bound by ``B0F_NEUTER_FINGERPRINT`` and
``B0F_NEUTER_OCCURRENCE`` inside ``B0F_NEUTER_FILE``, and the probe then
requires the test to fail.

Rule R9 applies to the neutering itself: a probe whose rewrite silently
missed its anchor would prove nothing while looking like proof. The plugin
therefore refuses to stay silent — when the rewrite matched it prints the
marker ``B0F-NEUTERED`` (which the validator requires to be present), and
when it did not match it prints ``B0F-NEUTER-MISS`` and the validator fails
the probe. The perturbation's occurrence is evidenced before the result is
interpreted.

The rewrite handles the two anchor shapes of the sweep's injection class:

* a call carrying ``side_effect=<exception>`` — the keyword is dropped,
* an assignment ``<target>.side_effect = <exception>`` — replaced by ``pass``.
"""

from __future__ import annotations

import ast
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys


def _fingerprint(node):
    import hashlib

    dump = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:24]


class _Neuterer(ast.NodeTransformer):
    def __init__(self, fingerprint, occurrence):
        self.fingerprint = fingerprint
        self.occurrence = occurrence
        self.seen = 0
        self.applied = False

    def _matches(self, node):
        if _fingerprint(node) != self.fingerprint:
            return False
        if self.seen == self.occurrence:
            self.seen += 1
            return True
        self.seen += 1
        return False

    def visit_Call(self, node):
        self.generic_visit(node)
        if not self.applied and self._matches(node):
            node.keywords = [k for k in node.keywords if k.arg != "side_effect"]
            self.applied = True
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)
        if not self.applied and self._matches(node):
            self.applied = True
            replacement = ast.Pass()
            return ast.copy_location(replacement, node)
        return node


class _Loader(importlib.abc.SourceLoader):
    def __init__(self, path, fingerprint, occurrence):
        self._path = path
        self._fingerprint = fingerprint
        self._occurrence = occurrence

    def get_filename(self, fullname):
        return self._path

    def get_data(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def source_to_code(self, data, path, *, _optimize=-1):
        tree = ast.parse(data)
        neuterer = _Neuterer(self._fingerprint, self._occurrence)
        tree = neuterer.visit(tree)
        ast.fix_missing_locations(tree)
        marker = os.environ.get("B0F_NEUTER_MARKER", "")
        if marker:
            # Rule R9 for the probe itself: the rewrite's occurrence is
            # recorded out of band, so a probe whose rewrite silently missed
            # can never read as proof.
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("applied" if neuterer.applied else "miss")
        # Compilation is delegated to the standard loader, which accepts a
        # syntax tree directly — the supported API for import-time rewrites.
        return super().source_to_code(tree, path)


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, target, fingerprint, occurrence):
        self._target = os.path.realpath(target)
        self._fingerprint = fingerprint
        self._occurrence = occurrence

    def find_spec(self, fullname, path, target=None):
        for finder in sys.meta_path:
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(fullname, path, target)
            if spec is None or spec.origin is None:
                continue
            if os.path.realpath(spec.origin) == self._target:
                loader = _Loader(spec.origin, self._fingerprint, self._occurrence)
                return importlib.util.spec_from_file_location(
                    fullname, spec.origin, loader=loader
                )
            return spec
        return None


def pytest_configure(config):
    target = os.environ.get("B0F_NEUTER_FILE", "")
    fingerprint = os.environ.get("B0F_NEUTER_FINGERPRINT", "")
    occurrence = int(os.environ.get("B0F_NEUTER_OCCURRENCE", "0"))
    if target and fingerprint:
        sys.meta_path.insert(0, _Finder(target, fingerprint, occurrence))
