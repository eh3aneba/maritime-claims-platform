"""Never turn incomplete Persian OCR probe coverage into a quality pass."""
import unittest

from scripts.hm_persian_ocr_probe import (
    PROBES, SCOPED_NEGATION_PHRASE, evaluate_literal_probe_retrieval,
)


class PersianOCRQualityTests(unittest.TestCase):
    def test_missing_negation_is_explicit_critical_omission_and_not_accepted(self):
        actual = evaluate_literal_probe_retrieval({
            "توربوشارژر": True, "نیست": False,
        })
        self.assertTrue(actual["machinery_term_retrieved"])
        self.assertFalse(actual["negation_retrieved"])
        self.assertTrue(actual["critical_negation_omission_observed"])
        self.assertEqual(actual["quality_disposition"], "negation_missing_review_required")
        self.assertFalse(actual["both_literal_probes_retrieved"])
        self.assertTrue(actual["human_bilingual_review_required"])
        self.assertFalse(actual["critical_fact_authorization_granted"])
        self.assertFalse(actual["negation_scope_verified"])
        self.assertFalse(actual["pilot_accepted"])

    def test_both_literals_still_never_prove_semantics_or_expert_approval(self):
        actual = evaluate_literal_probe_retrieval({
            "توربوشارژر": True, "نیست": True,
        })
        self.assertTrue(actual["both_literal_probes_retrieved"])
        self.assertEqual(actual["quality_disposition"], "two_literals_present_semantics_unverified")
        self.assertFalse(actual["critical_negation_omission_observed"])
        self.assertTrue(actual["human_bilingual_review_required"])
        self.assertFalse(actual["full_transcription_verified"])
        self.assertFalse(actual["negation_scope_verified"])
        self.assertFalse(actual["critical_fact_authorization_granted"])
        self.assertFalse(actual["pilot_accepted"])

    def test_missing_both_is_reported_without_inference(self):
        actual = evaluate_literal_probe_retrieval({
            "توربوشارژر": False, "نیست": False,
        })
        self.assertEqual(
            actual["quality_disposition"],
            "technical_and_negation_missing_review_required",
        )
        self.assertFalse(actual["both_literal_probes_retrieved"])

    def test_malformed_or_missing_probe_observations_fail_closed(self):
        for malformed in (
            {}, {"توربوشارژر": True},
            {"توربوشارژر": True, "نیست": True, "other": True},
            {"توربوشارژر": 1, "نیست": False},
            {"توربوشارژر": True, "نیست": "false"},
            None,
        ):
            with self.subTest(bad=malformed):
                with self.assertRaises(ValueError):
                    evaluate_literal_probe_retrieval(malformed)
        self.assertEqual(PROBES, ("توربوشارژر", "نیست"))


    def test_two_words_with_missing_scoped_clause_remain_unretrieved(self):
        result = evaluate_literal_probe_retrieval(
            {"توربوشارژر": True, "نیست": True},
            scoped_phrase_retrieved=False,
        )
        self.assertTrue(result["both_literal_probes_retrieved"])
        self.assertTrue(result["scoped_negation_phrase_measured"])
        self.assertFalse(result["scoped_negation_phrase_retrieved"])
        self.assertEqual(
            result["quality_disposition"],
            "scoped_negation_phrase_unretrieved_review_required",
        )
        self.assertFalse(result["negation_scope_verified"])
        self.assertTrue(result["human_bilingual_review_required"])
        self.assertFalse(result["critical_fact_authorization_granted"])
        self.assertFalse(result["pilot_accepted"])

    def test_scoped_clause_retrieval_is_not_semantic_accuracy_or_approval(self):
        result = evaluate_literal_probe_retrieval(
            {"توربوشارژر": True, "نیست": True},
            scoped_phrase_retrieved=True,
        )
        self.assertTrue(result["scoped_negation_phrase_retrieved"])
        self.assertEqual(
            result["quality_disposition"], "two_literals_present_semantics_unverified",
        )
        self.assertFalse(result["full_transcription_verified"])
        self.assertFalse(result["negation_scope_verified"])
        self.assertFalse(result["critical_fact_authorization_granted"])
        self.assertFalse(result["pilot_accepted"])

    def test_unmeasured_clause_cannot_be_reported_as_retrieved(self):
        result = evaluate_literal_probe_retrieval(
            {"توربوشارژر": True, "نیست": True},
        )
        self.assertFalse(result["scoped_negation_phrase_measured"])
        self.assertIsNone(result["scoped_negation_phrase_retrieved"])
        self.assertIn("نیست", SCOPED_NEGATION_PHRASE)
        self.assertFalse(result["pilot_accepted"])

    def test_scoped_observation_must_be_an_actual_boolean_or_unmeasured(self):
        for invalid in ("true", "false", 1, 0, [], {}, float("nan")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    evaluate_literal_probe_retrieval(
                        {"توربوشارژر": True, "نیست": True},
                        scoped_phrase_retrieved=invalid,
                    )



if __name__ == "__main__":
    unittest.main()
