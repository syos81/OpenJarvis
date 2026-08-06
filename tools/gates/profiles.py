"""Is an additional acceptance profile layer justified at all?

Derived, never imported. No semantics is carried over from the earlier labels
``A/B/C`` or ``P/S/H``: those were prose in a prompt, never a repository
artifact, and reusing their names would smuggle in a meaning that was never
defined here.

The derivation asks one mechanical question, stated as a falsifiable
criterion:

    A profile layer is justified if and only if there exists a unit that
    carries an existing acceptance profile value *and* an obligation
    signature, such that two units sharing one profile value have different
    obligation signatures.

Both operands are computed, never asserted:

*obligation signature*
    per block manifest, from what the manifest already declares — which
    phases are applicable and required, and which runner kinds carry the
    checks of each phase. Two blocks with the same signature have the same
    gate obligations.

*acceptance profile value*
    from the delivery order, where the values really exist, plus an optional
    declarative attribution of a block to one of those values.

The attribution is a separate declaration on purpose. Acceptance profiles are
declared per delivery element and obligations per block manifest; nothing in
the repository joins the two. Inventing that join inside this module — by
reading a manifest field that does not exist, or by guessing from a name —
would be exactly the invented domain meaning the derivation must not produce.
When no attribution exists the comparable domain is empty, and that is a
computed fact with a consequence, not a shrug.

The result may be ``not_justified``, and that is a finding, not a failure.
What it may never be is a constant: if the collision set is not computed from
the manifests, the result carries nothing and must not appear in a gate
result or a report.
"""

from __future__ import annotations

import json
from pathlib import Path

BLOCKS_DIR = "config/gates/blocks"
DELIVERY_ORDER = "config/governance/delivery-order.json"
#: Optional. Absent today, which is itself part of the derivation.
ATTRIBUTION = "config/governance/acceptance-profile-attribution.json"

#: The permanent lock that follows from a ``not_justified`` derivation.
LOCK = "config/governance/acceptance-profile-lock.json"

JUSTIFIED = "justified"
NOT_JUSTIFIED = "not_justified"


def load_lock(root):
    """The declared lock. Raises when it is missing — absence is not open."""
    return json.loads((Path(root) / LOCK).read_text(encoding="utf-8"))


def lock_violations(root, lock=None):
    """Return ``(relative_path, label)`` for every use of a locked label.

    The scope is declared, not hard coded, and the declaration itself is the
    only exempt file: it has to name the labels in order to forbid them.
    """
    lock = load_lock(root) if lock is None else lock
    base = Path(root)
    exempt = {str(item) for item in lock["exempt_paths"]}
    hits = []
    for entry in lock["scanned_paths"]:
        candidate = base / str(entry)
        if candidate.is_file():
            files = [candidate]
        elif candidate.is_dir():
            files = sorted(item for item in candidate.rglob("*") if item.is_file())
        else:
            continue
        for path in files:
            relative = path.relative_to(base).as_posix()
            if any(relative == item or relative.startswith(item + "/") for item in exempt):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - defensive
                continue
            for label in lock["locked_labels"]:
                if str(label) in text:
                    hits.append((relative, str(label)))
    return sorted(set(hits))


def lock_is_consistent_with(derivation, lock):
    """The lock may never claim a result the derivation did not produce."""
    return str(lock.get("derivation_result")) == str(derivation.get("result"))


def obligation_signature(manifest):
    """What a block manifest already declares about its gate obligations."""
    phases = []
    for phase, definition in sorted(manifest["phase_definitions"].items()):
        applicable = bool(definition.get("applicable"))
        required = bool(definition.get("required"))
        kinds = sorted(
            {
                check["runner"].get("name")
                or Path(
                    next(
                        (
                            token
                            for token in check["runner"].get("argv", [])
                            if token.endswith(".py")
                        ),
                        check["runner"].get("argv", ["?"])[-1],
                    )
                ).name
                for check in manifest["checks"]
                if check["phase"] == phase
            }
        )
        phases.append((phase, applicable, required, tuple(kinds)))
    return tuple(phases)


def collect(root):
    """Obligation signature per block, computed from every block manifest."""
    blocks = {}
    directory = Path(root) / BLOCKS_DIR
    for path in sorted(directory.glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        blocks[manifest["block_id"]] = obligation_signature(manifest)
    return blocks


def declared_profiles(root):
    """The acceptance profile values that already exist, as data."""
    document = json.loads((Path(root) / DELIVERY_ORDER).read_text(encoding="utf-8"))
    return {
        element["canonical_name"]: element.get("acceptance_profile")
        for element in document.get("elements", [])
    }


def declared_attribution(root):
    """Block to acceptance profile value. ``{}`` when nothing declares it."""
    target = Path(root) / ATTRIBUTION
    if not target.is_file():
        return {}
    document = json.loads(target.read_text(encoding="utf-8"))
    return {
        str(key): str(value)
        for key, value in dict(document.get("attribution", {})).items()
    }


def collisions(signatures, attribution):
    """Profile values that cover blocks with differing obligation signatures.

    This is the whole criterion. An empty result means no existing profile
    value hides a difference that already exists.
    """
    grouped = {}
    for block_id, profile in sorted(attribution.items()):
        if block_id not in signatures:
            # An attribution to a block that has no manifest compares nothing.
            continue
        grouped.setdefault(profile, {}).setdefault(
            signatures[block_id], []
        ).append(block_id)

    found = []
    for profile, by_signature in sorted(grouped.items()):
        if len(by_signature) < 2:
            continue
        found.append(
            {
                "acceptance_profile": profile,
                "distinct_obligation_signatures": len(by_signature),
                "blocks": sorted(
                    block for members in by_signature.values() for block in members
                ),
            }
        )
    return found


def derive(root):
    """Return the machine readable derivation result."""
    signatures = collect(root)
    element_profiles = declared_profiles(root)
    attribution = declared_attribution(root)
    found = collisions(signatures, attribution)

    by_signature = {}
    for block_id, signature in sorted(signatures.items()):
        by_signature.setdefault(signature, []).append(block_id)

    comparable = sorted(set(attribution) & set(signatures))
    profile_values = sorted({value for value in element_profiles.values() if value})

    elements_by_profile = {}
    for name, value in sorted(element_profiles.items()):
        if value:
            elements_by_profile.setdefault(value, []).append(name)

    if found:
        result = JUSTIFIED
        reason = (
            "An existing acceptance profile value covers blocks with "
            "different obligation signatures, so the existing declaration "
            "fails to express a difference that already exists."
        )
    else:
        result = NOT_JUSTIFIED
        parts = []
        if not comparable:
            parts.append(
                "No unit carries both an acceptance profile value and an "
                "obligation signature: the profile values are declared per "
                "delivery element, the obligations per block manifest, and "
                "nothing in the repository joins the two. The collision "
                "criterion therefore has an empty comparable domain, so no "
                "observed collision can justify a layer."
            )
        else:
            parts.append(
                "Every comparable unit that shares an acceptance profile "
                "value also shares its obligation signature, so no existing "
                "profile value hides a difference."
            )
        if len(by_signature) == len(signatures):
            parts.append(
                "In addition, each of the "
                f"{len(signatures)} block manifests carries its own distinct "
                "obligation signature, so which phases are applicable and "
                "required and which runner kinds carry their checks is "
                "already individually machine readable per block. A profile "
                "layer would restate that under a second name."
            )
        else:
            parts.append(
                f"{len(by_signature)} distinct obligation signatures cover "
                f"{len(signatures)} blocks; blocks sharing a signature have "
                "identical obligations, which a profile layer would not "
                "distinguish either."
            )
        reason = " ".join(parts)

    return {
        "schema_version": 1,
        "kind": "acceptance_profile_derivation",
        "result": result,
        "reason": reason,
        "justification_criterion": (
            "Justified if and only if two units share an existing acceptance "
            "profile value while having different obligation signatures."
        ),
        "falsifiable_by": (
            "A declared attribution in "
            f"{ATTRIBUTION} that maps two block manifests with different "
            "obligation signatures onto one acceptance profile value flips "
            "the result to justified. The derivation is therefore not a "
            "constant and is falsifiable against the normative state."
        ),
        "method": (
            "Obligation signature per block manifest from phase "
            "applicability, phase requirement and the runner kinds of each "
            "phase; acceptance profile values read from the delivery order; "
            "the two joined only through a declared attribution, never "
            "through a guessed one; collisions computed over that join."
        ),
        "imported_semantics": [],
        "inputs": {
            "block_manifests": sorted(signatures),
            "existing_acceptance_profiles": profile_values,
            "attribution_source": ATTRIBUTION,
            "attribution_present": bool(attribution),
        },
        "observed": {
            "blocks": len(signatures),
            "distinct_obligation_signatures": len(by_signature),
            "signature_groups": [
                sorted(members)
                for _signature, members in sorted(
                    by_signature.items(), key=lambda item: sorted(item[1])
                )
            ],
            "delivery_elements_by_acceptance_profile": elements_by_profile,
            "comparable_units": comparable,
            "profiles_covering_differing_signatures": found,
        },
        "consequence": (
            "No profile artifact and no profile schema is created. The "
            "labels A/B/C and P/S/H stay permanently locked and the absence "
            "check stays in force."
            if result == NOT_JUSTIFIED
            else "A general machine readable profile schema is created."
        ),
    }
