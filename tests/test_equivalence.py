"""
Pure-Python tests of the decision-field equivalence rule.

These do not require GenVM. They exist so reviewers can see which fields
are consensus-critical and which gates force UNRESOLVED, without running
Studio. Keep this file in lockstep with `_results_equivalent` and the
extractor overrides in TwoSourceClaimResolver.py.
"""

from __future__ import annotations

import unittest


VERDICT_TRUE = "TRUE"
VERDICT_FALSE = "FALSE"
VERDICT_UNRESOLVED = "UNRESOLVED"
SOURCE_OK = "ok"
SOURCE_FAIL = "fail"


def _normalize_verdict(raw) -> str:
    if raw is None:
        return VERDICT_UNRESOLVED
    v = str(raw).strip().upper()
    if v in (VERDICT_TRUE, VERDICT_FALSE, VERDICT_UNRESOLVED):
        return v
    return VERDICT_UNRESOLVED


def _normalize_source_status(raw) -> str:
    s = str(raw).strip().lower() if raw is not None else SOURCE_FAIL
    return SOURCE_OK if s == SOURCE_OK else SOURCE_FAIL


def results_equivalent(leader: dict, validator: dict) -> bool:
    if not isinstance(leader, dict) or not isinstance(validator, dict):
        return False
    lv = _normalize_verdict(leader.get("verdict"))
    vv = _normalize_verdict(validator.get("verdict"))
    if lv != vv:
        return False
    if _normalize_source_status(leader.get("source_a_status")) != _normalize_source_status(
        validator.get("source_a_status")
    ):
        return False
    if _normalize_source_status(leader.get("source_b_status")) != _normalize_source_status(
        validator.get("source_b_status")
    ):
        return False
    if lv in (VERDICT_TRUE, VERDICT_FALSE):
        if _normalize_source_status(validator.get("source_a_status")) != SOURCE_OK:
            return False
        if _normalize_source_status(validator.get("source_b_status")) != SOURCE_OK:
            return False
    return True


def apply_fetch_overrides(extracted: dict, source_a_ok: bool, source_b_ok: bool, sources_agree: bool) -> dict:
    """Mirrors the extractor safety overrides."""
    verdict = _normalize_verdict(extracted.get("verdict"))
    sa = SOURCE_OK if source_a_ok else SOURCE_FAIL
    sb = SOURCE_OK if source_b_ok else SOURCE_FAIL
    if not source_a_ok or not source_b_ok:
        verdict = VERDICT_UNRESOLVED
    if verdict in (VERDICT_TRUE, VERDICT_FALSE) and not sources_agree:
        verdict = VERDICT_UNRESOLVED
    quote_a = str(extracted.get("quote_a") or "")
    quote_b = str(extracted.get("quote_b") or "")
    if verdict == VERDICT_TRUE and (len(quote_a.strip()) < 8 or len(quote_b.strip()) < 8):
        verdict = VERDICT_UNRESOLVED
    return {
        "verdict": verdict,
        "source_a_status": sa,
        "source_b_status": sb,
        "quote_a": quote_a,
        "quote_b": quote_b,
        "reasoning": extracted.get("reasoning", ""),
    }


class EquivalenceTests(unittest.TestCase):
    def test_identical_true_accepted(self):
        leader = {
            "verdict": "TRUE",
            "source_a_status": "ok",
            "source_b_status": "ok",
            "reasoning": "leader prose",
            "quote_a": "cut of 500,000 bpd",
            "quote_b": "OPEC+ agreed a cut",
        }
        validator = {
            "verdict": "TRUE",
            "source_a_status": "ok",
            "source_b_status": "ok",
            "reasoning": "different wording, same call",
            "quote_a": "output cut of 0.5 million",
            "quote_b": "ministers agreed to reduce",
        }
        self.assertTrue(results_equivalent(leader, validator))

    def test_reasoning_and_quotes_are_not_consensus_keys(self):
        leader = {
            "verdict": "FALSE",
            "source_a_status": "ok",
            "source_b_status": "ok",
            "reasoning": "A",
            "quote_a": "aaaaaaaa",
            "quote_b": "bbbbbbbb",
        }
        validator = dict(leader)
        validator["reasoning"] = "Z"
        validator["quote_a"] = "xxxxxxxx"
        validator["quote_b"] = "yyyyyyyy"
        self.assertTrue(results_equivalent(leader, validator))

    def test_verdict_mismatch_rejected(self):
        leader = {"verdict": "TRUE", "source_a_status": "ok", "source_b_status": "ok"}
        validator = {"verdict": "FALSE", "source_a_status": "ok", "source_b_status": "ok"}
        self.assertFalse(results_equivalent(leader, validator))

    def test_true_vs_unresolved_rejected(self):
        leader = {"verdict": "TRUE", "source_a_status": "ok", "source_b_status": "ok"}
        validator = {"verdict": "UNRESOLVED", "source_a_status": "ok", "source_b_status": "ok"}
        self.assertFalse(results_equivalent(leader, validator))

    def test_source_status_mismatch_rejected(self):
        leader = {"verdict": "UNRESOLVED", "source_a_status": "ok", "source_b_status": "fail"}
        validator = {"verdict": "UNRESOLVED", "source_a_status": "fail", "source_b_status": "fail"}
        self.assertFalse(results_equivalent(leader, validator))

    def test_true_with_failed_validator_source_rejected(self):
        leader = {"verdict": "TRUE", "source_a_status": "ok", "source_b_status": "ok"}
        validator = {"verdict": "TRUE", "source_a_status": "fail", "source_b_status": "ok"}
        self.assertFalse(results_equivalent(leader, validator))

    def test_garbage_verdict_normalizes_to_unresolved(self):
        leader = {"verdict": "MAYBE", "source_a_status": "ok", "source_b_status": "ok"}
        validator = {"verdict": "UNRESOLVED", "source_a_status": "ok", "source_b_status": "ok"}
        self.assertTrue(results_equivalent(leader, validator))

    def test_non_dict_rejected(self):
        self.assertFalse(results_equivalent("TRUE", {"verdict": "TRUE"}))  # type: ignore
        self.assertFalse(results_equivalent({"verdict": "TRUE"}, None))  # type: ignore


class ExtractorOverrideTests(unittest.TestCase):
    def test_failed_source_forces_unresolved_even_if_model_says_true(self):
        extracted = {
            "verdict": "TRUE",
            "quote_a": "enough quote text",
            "quote_b": "enough quote text",
        }
        out = apply_fetch_overrides(extracted, source_a_ok=True, source_b_ok=False, sources_agree=True)
        self.assertEqual(out["verdict"], VERDICT_UNRESOLVED)
        self.assertEqual(out["source_b_status"], SOURCE_FAIL)

    def test_disagreement_forces_unresolved(self):
        extracted = {
            "verdict": "TRUE",
            "quote_a": "enough quote text",
            "quote_b": "enough quote text",
        }
        out = apply_fetch_overrides(extracted, True, True, sources_agree=False)
        self.assertEqual(out["verdict"], VERDICT_UNRESOLVED)

    def test_true_without_quotes_forced_unresolved(self):
        extracted = {"verdict": "TRUE", "quote_a": "short", "quote_b": ""}
        out = apply_fetch_overrides(extracted, True, True, sources_agree=True)
        self.assertEqual(out["verdict"], VERDICT_UNRESOLVED)

    def test_true_survives_when_both_sources_ok_agree_and_quoted(self):
        extracted = {
            "verdict": "TRUE",
            "quote_a": "OPEC+ agreed a cut",
            "quote_b": "output reduced by 500k bpd",
        }
        out = apply_fetch_overrides(extracted, True, True, sources_agree=True)
        self.assertEqual(out["verdict"], VERDICT_TRUE)


if __name__ == "__main__":
    unittest.main()
