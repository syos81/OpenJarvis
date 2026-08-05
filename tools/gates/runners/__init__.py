"""Check runners executed by the gate engine.

Every runner writes a structured report to the file named by ``GATE_REPORT``
and exits 0 only when the check passed. Runners never print personal data and
never emit absolute paths into their report.
"""
