"""Detection and redaction must cover the same variants.

Rule change RC-008. Before it, a flattened user path was *detected* by the
canary logic and still written out verbatim by the outgoing scrubber. Every
value used here is invented; no real name, path or organisation appears.
"""

from __future__ import annotations

import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.gates import (
    canaries,  # noqa: E402
    sanitize,  # noqa: E402
)
from tools.guard import audit as guard_audit  # noqa: E402
from tools.guard import textnorm  # noqa: E402

#: Invented value in the same shape as the declared canary.
SYNTHETIC = "/Users/erfundenerpruefer/Documents/Musterakte-2026.pdf"

#: Harmless strings that must survive untouched.
HARMLESS = (
    "Users-of-the-system-Documents-overview.pdf",
    "homepage-Users-guide.txt",
    "das Feld users enthaelt eine Zahl",
    "tools/guard/textnorm.py",
    "config/gates/blocks/b0b-calendar-k1.json",
)

#: Ordinary calendar payloads must not be touched by the path redaction.
CALENDAR_LIKE = (
    "Teambesprechung Musterprojekt",
    "Kalender: Arbeit (erfunden)",
    "window 2026-08-01T00:00:00Z .. 2026-09-01T00:00:00Z",
    "provider_calendar_id=cal-erfunden-1",
    "attendee: Erfundene Person <keine.adresse@example.invalid>",
)


class TestSharedVariantSource(unittest.TestCase):
    def test_detection_and_redaction_use_one_source(self):
        self.assertIs(sanitize.VARIANT_KINDS, textnorm.VARIANT_KINDS)
        self.assertIs(canaries.VARIANT_KINDS, textnorm.VARIANT_KINDS)
        self.assertIs(sanitize._SEPARATORS_RE, textnorm.SEPARATORS_RE)

    def test_every_declared_spelling_is_detected_and_redacted(self):
        for kind, spelling in sorted(
            textnorm.user_path_spellings(SYNTHETIC).items()
        ):
            with self.subTest(kind=kind):
                self.assertTrue(
                    textnorm.contains(spelling, SYNTHETIC),
                    "spelling is not detected",
                )
                redacted = sanitize.scrub(spelling)
                self.assertFalse(
                    textnorm.contains(redacted, SYNTHETIC),
                    "detected spelling survives redaction",
                )


class TestPositiveRedaction(unittest.TestCase):
    def _assert_redacted(self, probe):
        redacted = sanitize.scrub(probe)
        self.assertIn("<home>", redacted)
        self.assertFalse(textnorm.contains(redacted, SYNTHETIC))

    def test_slash_path_is_redacted(self):
        # Counter test for RC-008: the originally repelled violation must
        # still be detected and redacted.
        self._assert_redacted(SYNTHETIC)

    def test_flattened_path_is_redacted(self):
        # Sharpening test for RC-008: this failed before the change.
        self._assert_redacted(SYNTHETIC.replace("/", "-"))

    def test_hyphen_form_inside_a_longer_path_is_redacted(self):
        # A flattened path nested in a temporary directory: the placeholder
        # may be <tmp> here, what matters is that the value is gone.
        probe = "/private/tmp/session/" + SYNTHETIC.replace("/", "-")
        redacted = sanitize.scrub(probe)
        self.assertFalse(textnorm.contains(redacted, SYNTHETIC))
        self.assertNotIn("erfundenerpruefer", redacted)

    def test_underscore_form_is_redacted(self):
        self._assert_redacted(SYNTHETIC.replace("/", "_"))

    def test_percent_encoding_is_redacted(self):
        self._assert_redacted(SYNTHETIC.replace("/", "%2F"))

    def test_backslash_form_is_redacted(self):
        self._assert_redacted(SYNTHETIC.replace("/", "\\"))

    def test_unicode_normalisation_variant_is_detected(self):
        decomposed = unicodedata.normalize("NFD", SYNTHETIC)
        self.assertTrue(textnorm.contains(decomposed, SYNTHETIC))

    def test_existing_base64_detection_is_preserved(self):
        import base64

        encoded = base64.b64encode(SYNTHETIC.encode("utf-8")).decode("ascii")
        self.assertTrue(textnorm.contains(encoded, SYNTHETIC))

    def test_canary_detected_and_output_redacted(self):
        value = canaries.CANARIES["absolute_user_path"]
        for spelling in textnorm.user_path_spellings(value).values():
            with self.subTest(spelling=spelling[:24]):
                self.assertTrue(sanitize.contains_canary(spelling, value))
                redacted = sanitize.scrub(spelling)
                self.assertFalse(sanitize.contains_canary(redacted, value))

    def test_outgoing_evidence_rejects_a_flattened_path(self):
        payload = {"detail": SYNTHETIC.replace("/", "-")}
        violations = sanitize.find_violations(payload)
        self.assertTrue(violations)
        self.assertIn(
            "pii_flattened_user_path", {item["code"] for item in violations}
        )
        with self.assertRaises(sanitize.EvidenceLeakError):
            sanitize.assert_clean(payload)

    def test_guard_protocol_redacts_the_same_spellings(self):
        for spelling in textnorm.user_path_spellings(SYNTHETIC).values():
            with self.subTest(spelling=spelling[:24]):
                scrubbed = guard_audit.scrub(spelling)
                self.assertFalse(textnorm.contains(scrubbed, SYNTHETIC))


class TestNegativeControls(unittest.TestCase):
    def test_harmless_lookalikes_are_untouched(self):
        for probe in HARMLESS:
            with self.subTest(probe=probe):
                self.assertEqual(textnorm.redact_user_paths(probe), probe)

    def test_no_over_broad_user_name_redaction(self):
        # A word that merely contains a user name fragment stays intact.
        probe = "erfundenerpruefer hat den Termin bestaetigt"
        self.assertEqual(textnorm.redact_user_paths(probe), probe)

    def test_normal_calendar_payloads_are_untouched(self):
        for probe in CALENDAR_LIKE:
            with self.subTest(probe=probe):
                self.assertEqual(textnorm.redact_user_paths(probe), probe)

    def test_relative_repository_paths_are_untouched(self):
        for probe in ("tools/gates/sanitize.py", "src/personaljarvis/calendar"):
            with self.subTest(probe=probe):
                self.assertEqual(textnorm.redact_user_paths(probe), probe)


class TestFixtureDiscipline(unittest.TestCase):
    """Abuse test outside the declared fixtures."""

    def test_no_second_variant_table_exists(self):
        root = Path(__file__).resolve().parents[3]
        offenders = []
        for relative in ("tools/gates/sanitize.py", "tools/guard/audit.py",
                         "tools/gates/canaries.py"):
            source = (root / relative).read_text(encoding="utf-8")
            if "textnorm" not in source:
                offenders.append(relative)
            # No module may keep its own home-path spelling table.
            if 'r"/(?:Users|home)/' in source:
                offenders.append(relative + ":own_pattern")
        self.assertEqual(offenders, [])

    def test_synthetic_values_only(self):
        """No fixture may carry the real account name.

        The name is assembled at runtime so this assertion does not itself
        put it into a tracked file.
        """
        import os

        source = Path(__file__).read_text(encoding="utf-8")
        real_account = os.path.basename(os.path.expanduser("~"))
        self.assertNotIn(real_account, source)
        self.assertNotIn(real_account, SYNTHETIC)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
