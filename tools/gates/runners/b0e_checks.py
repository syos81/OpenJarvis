"""B0e checks: the derived corpus and the R9/R10 disposition register.

Two modes, both bound to block B0e's subject — hardening the test corpus
against silently ineffective perturbations (rule R9) and against absence
that silently becomes emptiness (rule R10):

``corpus``
    derives the executable check corpus and fails when it cannot be derived
    or is empty. A withdrawn discovery input blocks; it never reads as a
    clean, empty sweep.
``dispositions``
    re-derives the corpus, re-runs both sweeps and proves that the detected
    candidate set and the committed disposition register describe each other
    exactly: no candidate without a disposition, no disposition without a
    candidate, no silently vanished binding, and every R9 ``mark_and_fix``
    declared under rule R9's effect evidence convention.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import astcorpus, astscan  # noqa: E402
from tools.gates.runners import _report  # noqa: E402


def _fail(identifier, code):
    return _report.failure(identifier, category="b0e", code=code)


def mode_corpus(args):
    root = Path.cwd()
    try:
        corpus = astcorpus.derive(root)
    except astcorpus.CorpusError as error:
        return _report.emit(
            _report.BLOCKED,
            [_fail(error.detail or "corpus", error.code)],
            reason_code="corpus_underivable",
        )
    sources = {}
    for record in corpus.files.values():
        for derivation in record.derivations:
            sources[derivation["source"]] = sources.get(derivation["source"], 0) + 1
    diagnostics = [f"{name}={value}" for name, value in sorted(corpus.counts.items())]
    diagnostics.extend(f"source_{name}={value}" for name, value in sorted(sources.items()))
    return _report.emit(_report.PASSED, (), diagnostics)


def mode_dispositions(args):
    root = Path.cwd()
    failures, diagnostics = astscan.validate(root)
    blocked = any(code.startswith("corpus_") for _, code in failures)
    if blocked:
        return _report.emit(
            _report.BLOCKED,
            [_fail(identifier, code) for identifier, code in failures],
            diagnostics,
            reason_code="corpus_underivable",
        )
    outcome = _report.PASSED if not failures else _report.FAILED
    return _report.emit(
        outcome, [_fail(identifier, code) for identifier, code in failures], diagnostics
    )


MODES = {
    "corpus": mode_corpus,
    "dispositions": mode_dispositions,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    args = parser.parse_args(argv)
    return MODES[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
