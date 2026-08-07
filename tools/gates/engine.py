"""Phase orchestration, aggregation and result persistence.

The engine is the only place that turns check outcomes into one of the five
binding results. It never derives a status from free text, never defaults a
missing result to something green and never echoes raw tool output.

Progress goes to stderr (sanitized); stdout carries exactly one machine
readable overall result.
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

from . import CAUSE_SIGNATURE_VERSION
from . import ENGINE_VERSION
from . import RESULT_SCHEMA_VERSION
from . import baseline as baseline_module
from . import cache as cache_module
from . import emptyset
from . import evidence as evidence_module
from . import features as features_module
from . import gitutil
from . import manifest as manifest_module
from . import paths as gate_paths
from . import runner as runner_module
from . import sanitize
from . import statuses

PHASES = manifest_module.PHASES


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id():
    return hashlib.sha256(os.urandom(32)).hexdigest()[:32]


class GateEngine:
    def __init__(
        self,
        *,
        worktree,
        manifest,
        python_executable=None,
        progress=None,
    ):
        self.worktree = Path(worktree)
        self.manifest = manifest
        self.python_executable = python_executable or sys.executable
        self.tools_dir = self.worktree / "tools" / "gates"
        self._progress_stream = progress if progress is not None else sys.stderr
        self.run_id = new_run_id()
        self.platform_class = gate_paths.platform_class()
        self.common_git_dir = gitutil.common_dir(self.worktree)
        self.cache = cache_module.BaselineCache(
            gate_paths.baseline_cache_root(self.common_git_dir),
            enabled=self.manifest.cache_enabled,
        )
        self._baseline_worktree = None

    # -- helpers -----------------------------------------------------------
    def progress(self, message):
        if self._progress_stream is None:
            return
        self._progress_stream.write(f"[gate] {sanitize.scrub(message)}\n")
        self._progress_stream.flush()

    def head_commit(self):
        return gitutil.head_commit(cwd=self.worktree)

    def worktree_state_digest(self):
        entries = gitutil.status_porcelain(cwd=self.worktree)
        payload = json.dumps(
            {"head": self.head_commit(), "entries": entries}, sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def toolchain(self):
        code, out, _ = gitutil.run_git(["--version"])
        git_version = out.strip().split()[-1] if code == 0 else "unknown"
        return {
            "python": platform.python_version(),
            "git": git_version,
        }

    def dependency_lock_digests(self, commit):
        digests = {}
        policy = self.manifest.data["baseline_policy"]
        for rel_path in policy["dependency_lock_paths"]:
            code, out, _ = gitutil.run_git(
                ["rev-parse", f"{commit}:{rel_path}"], cwd=self.worktree
            )
            digests[rel_path] = out.strip() if code == 0 else "absent"
        return digests

    def config_digests(self):
        digests = {}
        policy = self.manifest.data["baseline_policy"]
        for rel_path in policy["config_digest_paths"]:
            target = self.worktree / rel_path
            if target.is_file():
                digests[rel_path] = evidence_module.sha256_file(target)
            else:
                digests[rel_path] = "absent"
        return digests

    # -- check selection ---------------------------------------------------
    def select_checks(self, phase):
        """Return ``(checks, selection_note)`` in deterministic order."""
        available = {
            check.check_id: check for check in self.manifest.checks_for_phase(phase)
        }
        if phase != "targeted":
            return (
                [available[key] for key in sorted(available)],
                "all_declared_checks",
            )
        selection = self.manifest.data["targeted_selection"]
        selected = set(selection["always"])
        changed, base_resolved = gitutil.changed_files(
            selection["base_ref"], cwd=self.worktree
        )
        for rule in selection["rules"]:
            for pattern in rule["paths"]:
                if any(fnmatch.fnmatch(path, pattern) for path in changed):
                    selected.update(rule["checks"])
                    break
        selected &= set(available)
        note = (
            "change_rules_with_base"
            if base_resolved
            else "change_rules_without_base_ref"
        )
        return [available[key] for key in sorted(selected)], note

    # -- baseline ----------------------------------------------------------
    def baseline_worktree(self):
        if self._baseline_worktree is None:
            worktree = baseline_module.BaselineWorktree(
                source_worktree=self.worktree,
                commit=self.manifest.baseline_commit,
                owner=self.manifest.data["baseline_policy"]["owner_marker"],
            )
            worktree.acquire_lock()
            worktree.prepare()
            self._baseline_worktree = worktree
        return self._baseline_worktree

    def release_baseline(self):
        if self._baseline_worktree is not None:
            self._baseline_worktree.release_lock()
            self._baseline_worktree = None

    def _baseline_structured(self, check, phase):
        """Baseline outcome for ``check``: cache first, then a real run."""
        worktree = self.baseline_worktree()
        key = baseline_module.build_cache_key(
            manifest=self.manifest,
            check=check,
            phase=phase,
            platform_class=self.platform_class,
            toolchain=self.toolchain(),
            dependency_lock_digests=self.dependency_lock_digests(worktree.commit),
            config_digests=self.config_digests(),
            baseline_commit=worktree.commit,
        )
        cached, cache_state = self.cache.load(key)
        if cache_state == cache_module.STATE_HIT:
            self.progress(f"baseline cache hit for {check.check_id}")
            return baseline_module.structured_from_cache(cached), cache_state
        self.progress(f"baseline run for {check.check_id} on {worktree.commit[:12]}")
        run = runner_module.execute(
            check,
            worktree=self.worktree,
            target_dir=worktree.path,
            tools_dir=self.tools_dir,
            python_executable=self.python_executable,
            raw_log_dir=gate_paths.raw_log_dir(self.worktree),
            run_id=self.run_id,
            label=f"baseline-{phase}",
        )
        signature = None
        if run.structured.get("outcome") != runner_module.OUTCOME_PASSED:
            from . import signature as signature_module

            signature = signature_module.build_cause_signature(
                block_id=self.manifest.block_id,
                check_id=check.check_id,
                runner_kind=check.runner.get("type", ""),
                parser=check.parser,
                structured=run.structured,
            )
        try:
            self.cache.store(
                key,
                baseline_module.cache_result_from_structured(
                    run.structured, run.exit_code, signature
                ),
            )
        except cache_module.CacheBusyError:
            self.progress("baseline cache busy, result not stored")
        return run.structured, cache_module.STATE_MISS

    # -- check execution ---------------------------------------------------
    def _internal_check(self, check, phase):
        name = check.runner["name"]
        if name == "module_final_phase_results":
            return self._internal_phase_results()
        if name == "module_final_evidence":
            return self._internal_evidence()
        return statuses.FAIL, "internal_runner_unknown", {}

    def _stored_results(self):
        directory = gate_paths.results_dir(self.worktree)
        stored = {}
        for phase in PHASES:
            target = directory / f"{self.manifest.block_id}.{phase}.json"
            if not target.is_file():
                continue
            try:
                stored[phase] = json.loads(target.read_text(encoding="utf-8"))
            except ValueError:
                stored[phase] = None
        return stored

    def _internal_phase_results(self):
        stored = self._stored_results()
        head = self.head_commit()
        state_digest = self.worktree_state_digest()
        required = [
            phase
            for phase in PHASES
            if phase != "module-final"
            and self.manifest.phase_definition(phase)["required"]
        ]
        details = []
        status = statuses.PASS
        reason = "phase_results_consistent"
        # Rule R10. A closing phase with nothing to aggregate establishes
        # nothing; there is no reading under which that emptiness is the
        # result. The required set is derived from the manifest, so this is a
        # configuration defect and blocks rather than passing silently.
        empty_status, empty_reason = emptyset.require_non_empty(len(required))
        if empty_status != statuses.PASS:
            return empty_status, empty_reason, {
                "phases": [],
                "phases_examined": 0,
                "phases_required": 0,
            }
        for phase in required:
            result = stored.get(phase)
            if result is None:
                details.append({"phase": phase, "issue": "phase_result_missing"})
                status = statuses.FAIL
                reason = "phase_result_missing"
                continue
            if (
                result.get("commit") != head
                or result.get("manifest_digest") != self.manifest.digest
                or result.get("engine_version") != ENGINE_VERSION
                or result.get("worktree_state_digest") != state_digest
                or result.get("block") != self.manifest.block_id
            ):
                details.append({"phase": phase, "issue": "phase_result_stale"})
                status = statuses.FAIL
                reason = "phase_result_stale"
                continue
            phase_status = result.get("status")
            if phase_status == statuses.FAIL:
                details.append({"phase": phase, "issue": "phase_failed"})
                status = statuses.FAIL
                reason = "previous_phase_failed"
            elif phase_status == statuses.BLOCKED:
                details.append({"phase": phase, "issue": "phase_blocked"})
                if status != statuses.FAIL:
                    status = statuses.BLOCKED
                    reason = "previous_phase_blocked"
            elif phase_status not in statuses.ALL_STATUSES:
                details.append({"phase": phase, "issue": "phase_status_invalid"})
                status = statuses.FAIL
                reason = "phase_result_invalid"
        # The counts are reported alongside the issue list, because an empty
        # issue list is what a vacuous run and a clean run have in common. A
        # reader — human or machine — must be able to tell them apart without
        # knowing which of the two lists this is.
        return status, reason, {
            "phases": details,
            "phases_examined": len(required),
            "phases_required": len(required),
        }

    def _internal_evidence(self):
        stored = self._stored_results()
        evidence_directory = gate_paths.evidence_dir(self.worktree)
        raw_dir = gate_paths.raw_log_dir(self.worktree)
        required = [
            phase
            for phase in PHASES
            if phase != "module-final"
            and self.manifest.phase_definition(phase)["required"]
        ]
        issues = []
        #: A defect that was found, as opposed to a walk that found nothing.
        #: The two must not be merged: a failure outranks a non evidence
        #: state, and a non evidence state outranks a pass.
        hard_issue = False
        status = statuses.PASS
        empty_status, empty_reason = emptyset.require_non_empty(len(required))
        if empty_status != statuses.PASS:
            return empty_status, empty_reason, {
                "evidence": [],
                "phases_examined": 0,
                "raw_logs_declared": 0,
                "raw_logs_verified": 0,
            }

        examined = 0
        declared_total = 0
        verified_total = 0
        for phase in required:
            target = evidence_directory / f"{self.manifest.block_id}.{phase}.json"
            if not target.is_file():
                issues.append({"phase": phase, "issue": "evidence_missing"})
                hard_issue = True
                continue
            try:
                record = json.loads(target.read_text(encoding="utf-8"))
                evidence_module.validate_evidence(record)
            except (ValueError, evidence_module.EvidenceSchemaError):
                issues.append({"phase": phase, "issue": "evidence_invalid"})
                hard_issue = True
                continue
            examined += 1
            # Rule R10. The expectation is derived from the evidence record
            # itself — it lists the raw log digests of its own run — and not
            # from the collection that is walked. Before this, a phase whose
            # stored result had gone missing verified zero raw logs and
            # contributed no issue, so the check reported evidence_complete
            # while establishing nothing about that phase. The walk lives in
            # evidence.phase_evidence_counts so the tests exercise this code
            # and not a second copy of it.
            counts = evidence_module.phase_evidence_counts(
                phase, record=record, result=stored.get(phase), raw_dir=raw_dir
            )
            declared_total += counts.declared
            verified_total += counts.verified
            for reason in counts.issues:
                issues.append({"phase": phase, "issue": reason})
                hard_issue = True
            phase_status, phase_reason = emptyset.verdict(
                counts.verified, counts.declared
            )
            if phase_status != statuses.PASS:
                # Not an issue in the sense of "something was found wrong" —
                # nothing was found at all, and that is the point.
                issues.append({"phase": phase, "issue": phase_reason})
                status = emptyset.worse(status, phase_status)

        detail = {
            "evidence": issues,
            "phases_examined": examined,
            "raw_logs_declared": declared_total,
            "raw_logs_verified": verified_total,
        }
        if hard_issue:
            # A found defect outranks a non evidence state, always.
            return statuses.FAIL, "evidence_incomplete", detail
        if status != statuses.PASS:
            return status, emptyset.AGGREGATION_SET_EMPTY, detail
        return statuses.PASS, "evidence_complete", detail

    def _run_check(self, check, phase):
        """Execute one check and return its result entry."""
        entry = {
            "check_id": check.check_id,
            "phase": check.phase,
            "required": check.required,
            "parser": check.parser,
            "runner_type": check.runner["type"],
            "baseline_eligible": check.baseline_eligible,
            "status": statuses.FAIL,
            "reason_code": "check_not_executed",
            "exit_code": None,
            "duration_ms": None,
            "timed_out": False,
            "raw_log_name": None,
            "raw_log_sha256": None,
            "cause_signature_digest": None,
            "baseline_state": "not_used",
            "cache_state": cache_module.STATE_DISABLED,
            "detail": "",
        }
        if check.runner["type"] == "internal":
            status, reason, detail = self._internal_check(check, phase)
            entry["status"] = status
            entry["reason_code"] = reason
            entry["detail"] = sanitize.scrub(json.dumps(detail, sort_keys=True))
            return entry

        run = runner_module.execute(
            check,
            worktree=self.worktree,
            target_dir=self.worktree,
            tools_dir=self.tools_dir,
            python_executable=self.python_executable,
            raw_log_dir=gate_paths.raw_log_dir(self.worktree),
            run_id=self.run_id,
            label=phase,
        )
        entry["exit_code"] = run.exit_code
        entry["duration_ms"] = run.duration_ms
        entry["timed_out"] = run.timed_out
        entry["raw_log_name"] = Path(run.raw_log_path).name
        entry["raw_log_sha256"] = run.raw_log_sha256
        diagnostics = run.structured.get("diagnostics") or []
        entry["detail"] = sanitize.scrub(
            ",".join(str(item) for item in diagnostics[:5])
        )

        if run.passed:
            entry["status"] = statuses.PASS
            entry["reason_code"] = "check_passed"
            return entry

        if run.structured.get("outcome") == runner_module.OUTCOME_BLOCKED:
            entry["status"] = statuses.BLOCKED
            entry["reason_code"] = (
                run.structured.get("reason_code") or "check_blocked"
            )
            return entry

        if run.structured.get("outcome") == runner_module.OUTCOME_TIMEOUT:
            entry["status"] = statuses.FAIL
            entry["reason_code"] = "check_timeout"
            return entry

        if not check.baseline_eligible:
            entry["status"] = statuses.FAIL
            entry["reason_code"] = (
                "check_failed"
                if run.structured.get("outcome") == runner_module.OUTCOME_FAILED
                else "check_error"
            )
            return entry

        try:
            baseline_structured, cache_state = self._baseline_structured(check, phase)
        except baseline_module.BaselineUnavailable as exc:
            entry["status"] = statuses.BLOCKED
            entry["reason_code"] = exc.reason_code
            entry["baseline_state"] = "unavailable"
            return entry
        entry["cache_state"] = cache_state
        status, reason, candidate_signature, _ = baseline_module.compare_runs(
            check,
            run.structured,
            baseline_structured,
            block_id=self.manifest.block_id,
        )
        entry["status"] = status
        entry["reason_code"] = reason
        entry["baseline_state"] = "compared"
        if candidate_signature:
            entry["cause_signature_digest"] = candidate_signature["digest"]
        return entry

    # -- phases ------------------------------------------------------------
    def run_phase(self, phase):
        if phase not in PHASES:
            raise ValueError(f"unknown phase: {phase}")
        started_at = utc_now()
        head = self.head_commit()
        branch = gitutil.current_branch(cwd=self.worktree)
        state_digest = self.worktree_state_digest()
        definition = self.manifest.phase_definition(phase)
        entries = []
        baseline_used = False

        if not definition["applicable"]:
            self.progress(f"{phase}: declared non-applicable by manifest")
            entries.append(
                {
                    "check_id": f"{phase}.declared",
                    "phase": phase,
                    "required": True,
                    "parser": "gate_json",
                    "runner_type": "internal",
                    "baseline_eligible": False,
                    "status": definition["declared_result"],
                    "reason_code": "phase_not_applicable_by_manifest",
                    "exit_code": None,
                    "duration_ms": 0,
                    "timed_out": False,
                    "raw_log_name": None,
                    "raw_log_sha256": None,
                    "cause_signature_digest": None,
                    "baseline_state": "not_used",
                    "cache_state": cache_module.STATE_DISABLED,
                    "detail": sanitize.scrub(definition["reason"]),
                }
            )
            selection_note = "phase_not_applicable"
        else:
            checks, selection_note = self.select_checks(phase)
            self.progress(f"{phase}: {len(checks)} check(s) selected")
            declared_required = set(self.manifest.required_check_ids(phase))
            executed = set()
            try:
                for check in checks:
                    self.progress(f"{phase}: running {check.check_id}")
                    entries.append(self._run_check(check, phase))
                    executed.add(check.check_id)
                    if check.baseline_eligible:
                        baseline_used = True
            finally:
                self.release_baseline()
            if phase != "targeted":
                for missing in sorted(declared_required - executed):
                    entries.append(
                        {
                            "check_id": missing,
                            "phase": phase,
                            "required": True,
                            "parser": "exit_only",
                            "runner_type": "internal",
                            "baseline_eligible": False,
                            "status": statuses.FAIL,
                            "reason_code": "required_check_missing",
                            "exit_code": None,
                            "duration_ms": None,
                            "timed_out": False,
                            "raw_log_name": None,
                            "raw_log_sha256": None,
                            "cause_signature_digest": None,
                            "baseline_state": "not_used",
                            "cache_state": cache_module.STATE_DISABLED,
                            "detail": "",
                        }
                    )

        entries.sort(key=lambda item: item["check_id"])
        check_statuses = [entry["status"] for entry in entries]
        if phase == "module-final":
            overall = statuses.aggregate_module_final(check_statuses)
        else:
            overall = statuses.aggregate(check_statuses)
        finished_at = utc_now()

        cache_states = {
            entry["cache_state"]
            for entry in entries
            if entry["cache_state"]
            in (cache_module.STATE_HIT, cache_module.STATE_MISS)
        }
        if not cache_states:
            cache_state = "not_used"
        elif len(cache_states) == 1:
            cache_state = cache_states.pop()
        else:
            cache_state = "mixed"

        evidence_record = evidence_module.build_evidence(
            run_id=self.run_id,
            block=self.manifest.block_id,
            phase=phase,
            commit=head,
            manifest_digest=self.manifest.digest,
            engine_version=ENGINE_VERSION,
            status=overall,
            check_ids=sorted({entry["check_id"] for entry in entries}),
            reason_codes=sorted({entry["reason_code"] for entry in entries}),
            baseline_commit=(
                gitutil.resolve_commit(self.manifest.baseline_commit, cwd=self.worktree)
                if baseline_used
                else None
            ),
            cause_signature_digest=sorted(
                {
                    entry["cause_signature_digest"]
                    for entry in entries
                    if entry["cause_signature_digest"]
                }
            ),
            cache_state=cache_state,
            platform_class=self.platform_class,
            raw_log_sha256=sorted(
                {
                    entry["raw_log_sha256"]
                    for entry in entries
                    if entry["raw_log_sha256"]
                }
            ),
            started_at=started_at,
            finished_at=finished_at,
        )

        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "block": self.manifest.block_id,
            "phase": phase,
            "status": overall,
            "checks": entries,
            "baseline": {
                "baseline_commit_declared": self.manifest.baseline_commit,
                "baseline_commit_resolved": evidence_record["baseline_commit"],
                "cause_signature_version": CAUSE_SIGNATURE_VERSION,
                "used": baseline_used,
                "cache_state": cache_state,
            },
            "evidence": evidence_record,
            "run_id": self.run_id,
            "commit": head,
            "branch": branch,
            "worktree_state_digest": state_digest,
            "manifest_digest": self.manifest.digest,
            "engine_version": ENGINE_VERSION,
            "platform_class": self.platform_class,
            "selection": selection_note,
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": statuses.exit_code(overall),
        }
        sanitize.assert_clean(result, "$result")
        self._persist(phase, result, evidence_record)
        return result

    def _persist(self, phase, result, evidence_record):
        results_directory = gate_paths.ensure_private_dir(
            gate_paths.results_dir(self.worktree)
        )
        evidence_directory = gate_paths.ensure_private_dir(
            gate_paths.evidence_dir(self.worktree)
        )
        name = f"{self.manifest.block_id}.{phase}.json"
        (results_directory / name).write_text(
            json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        (evidence_directory / name).write_text(
            evidence_module.dump_evidence(evidence_record) + "\n", encoding="utf-8"
        )


def feature_report(worktree, manifest):
    """Convenience wrapper used by the CLI's ``--features`` reporting."""
    lineage = manifest.data["feature_lineage"]
    return features_module.validate_lineage(
        lineage_path=Path(worktree) / lineage["lineage_file"],
        predecessor_path=Path(worktree) / lineage["predecessor_file"],
        worktree=worktree,
        manifest=manifest,
    )
