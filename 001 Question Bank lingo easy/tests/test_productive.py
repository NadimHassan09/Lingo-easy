"""Tests for the Writing/Speaking generators, validators and their compatibility with the existing Reading/Listening project."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from productive import cefr as cefr_mod  # noqa: E402
from productive import validate as V  # noqa: E402
from productive.common import LEVELS, load_json, part_id, taxonomy  # noqa: E402
from productive.generate import SpecError, build_part, generate  # noqa: E402
from productive.minischema import validate as schema_validate  # noqa: E402
from productive.specs.registry import POOLS  # noqa: E402

TS = "2026-10-30T12:00:00+03:00"
SEED = 20261030


def all_parts(seed=SEED):
    parts = []
    for sk in ("writing", "speaking"):
        for b in POOLS[sk]:
            parts += generate(sk, b, None, seed, TS)
    return parts


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = all_parts()
        cls.by = {p["id"]: p for p in cls.parts}

    def test_exact_counts(self):
        self.assertEqual(sum(p["skill"] == "writing" for p in self.parts), 70)
        self.assertEqual(sum(p["skill"] == "speaking" for p in self.parts), 70)
        for sk in ("writing", "speaking"):
            for bank in ["placement"] + LEVELS:
                n = sum(1 for p in self.parts if p["skill"] == sk and ((p["assessment"]["type"] == "placement" and bank == "placement") or p["assessment"]["level"] == bank))
                self.assertEqual(n, 10, (sk, bank))

    def test_placement_covers_all_levels_assessment_is_level_pure(self):
        want = taxonomy()["placement_design"]["level_counts"]
        for sk in ("writing", "speaking"):
            pl = Counter(p["target_cefr"] for p in self.parts if p["skill"] == sk and p["assessment"]["type"] == "placement")
            self.assertEqual(dict(pl), want)
            self.assertEqual(set(pl), set(LEVELS))
        for p in self.parts:
            if p["assessment"]["type"] == "assessment":
                self.assertEqual(p["target_cefr"], p["assessment"]["level"])
            else:
                self.assertIsNone(p["assessment"]["level"])
                self.assertEqual(p["profile"], "placement")

    def test_ids_and_uuids_unique_and_stable(self):
        self.assertEqual(len({p["id"] for p in self.parts}), 140)
        self.assertEqual(len({p["uuid"] for p in self.parts}), 140)
        again = {p["id"]: p["uuid"] for p in all_parts(seed=1)}
        self.assertEqual(again, {p["id"]: p["uuid"] for p in self.parts})  # uuids do not depend on the seed
        self.assertEqual(part_id("writing", "placement", 1), "WR001")
        self.assertEqual(part_id("speaking", "C2", 10), "SP610")

    def test_schema_compliance_of_every_part(self):
        for p in self.parts:
            self.assertEqual(V.schema_errors(p), [], p["id"])

    def test_full_validation_has_no_errors_and_no_duplicates(self):
        res = V.validate_all(self.parts)
        self.assertEqual(res["bank_errors"], [])
        for pid, r in res["parts"].items():
            self.assertEqual(r["schema_errors"], [], pid)
            self.assertEqual([f for f in r["findings"] if f[0] == "error"], [], pid)
        self.assertEqual([d for d in res["duplicates"] if d["severity"] == "duplicate"], [])

    def test_required_metadata_and_blueprint_completeness(self):
        for p in self.parts:
            for k in ("task", "expected_response", "classification", "difficulty", "evaluation_blueprint", "diagnostics", "provenance", "version", "uuid"):
                self.assertIn(k, p)
            bp = p["evaluation_blueprint"]
            self.assertGreaterEqual(len(bp["criteria"]), 4, p["id"])
            self.assertTrue(bp["not_penalised"])
            self.assertTrue(bp["multiple_valid_responses"])
            for c in bp["criteria"]:
                for k in ("description", "successful_performance", "weak_performance", "expected_evidence", "common_error_patterns", "related_subskills", "evaluation_limitations"):
                    self.assertTrue(c[k], (p["id"], c["id"], k))
            self.assertAlmostEqual(sum(c["weight"] for c in bp["criteria"]), 1.0, delta=0.01)
            self.assertTrue(p["classification"]["learning_objectives"])
            self.assertTrue(p["diagnostics"]["targets"])

    def test_no_answer_key_and_examples_labelled(self):
        for p in self.parts:
            self.assertEqual(V.walk_keys({k: v for k, v in p.items() if k != "provenance"}), [], p["id"])
            for e in p["expected_response"]["examples"]:
                self.assertIn("not an answer key", e["label"])

    def test_criteria_match_task_demands(self):
        for p in self.parts:
            ids = {c["id"] for c in p["evaluation_blueprint"]["criteria"]}
            if p["skill"] == "writing" and p["target_cefr"] in ("A1", "A2"):
                self.assertNotIn("W_ORG", ids, p["id"])
            if p["skill"] == "writing" and p["target_cefr"] in ("B2", "C1", "C2") and p["task_category"] in ("argumentative_essay", "discussion_two_views"):
                self.assertIn("W_ORG", ids, p["id"])
            if p["task_category" if p["skill"] == "writing" else "task_format"] in ("email_formal", "register_transformation"):
                self.assertIn("W_REG", ids)

    def test_speaking_text_mvp_never_scores_pronunciation(self):
        for p in self.parts:
            if p["skill"] != "speaking":
                continue
            bp = p["evaluation_blueprint"]
            self.assertNotIn("S_PRON", {c["id"] for c in bp["criteria"]})
            self.assertIn("S_PRON", {c["id"] for c in bp["not_assessed_by_design"]})
            self.assertTrue(bp["text_mvp_limitations"])
            fc = next(c for c in bp["criteria"] if c["id"] == "S_FC")
            self.assertEqual(fc["assessable_in_current_modality"], "partial")
            self.assertIn("Pronunciation is not assessed", " ".join(p["task"]["instructions"]))
            self.assertEqual(p["modality"]["current"], "typed_text")

    def test_future_audio_fields_optional_and_never_fabricated(self):
        for p in self.parts:
            self.assertNotIn("audio_extension", p)
            self.assertEqual(V.schema_errors(p), [])
        p = copy.deepcopy(self.parts[-1])
        p["audio_extension"] = {"audio_asset_ref": "asset-1", "audio_duration_seconds": 61.5, "transcript": "...", "stt_provider": "x", "stt_confidence": 0.9}
        self.assertEqual(V.schema_errors(p), [])  # accepted when real audio exists
        p["audio_extension"]["invented_field"] = 1
        self.assertTrue(V.schema_errors(p))
        p["audio_extension"] = {"stt_confidence": 3}
        self.assertTrue(V.schema_errors(p))

    def test_seed_reproducibility_and_selection(self):
        a = json.dumps(all_parts(SEED), sort_keys=True)
        b = json.dumps(all_parts(SEED), sort_keys=True)
        self.assertEqual(a, b)
        s1 = [p["id"] for p in generate("writing", "B2", 5, 1, TS)]
        s1b = [p["id"] for p in generate("writing", "B2", 5, 1, TS)]
        self.assertEqual(s1, s1b)
        self.assertEqual(len(s1), 5)
        seen = {tuple(p["id"] for p in generate("writing", "B2", 5, sd, TS)) for sd in range(12)}
        self.assertGreater(len(seen), 1)  # the seed does change which parts are drawn
        for sd in range(12):
            ps = generate("writing", "B2", 5, sd, TS)
            self.assertEqual(len({p["topic"] for p in ps}), 5)  # diversity-aware selection

    def test_cefr_estimates_are_independent_of_the_stored_target(self):
        spec = copy.deepcopy(POOLS["writing"]["C1"][0])
        spec["lv"] = "A1"  # changing the label must not change the demand-based estimate
        self.assertEqual(cefr_mod.estimate(spec, "writing")["composite_index"], cefr_mod.estimate(POOLS["writing"]["C1"][0], "writing")["composite_index"])
        mean = lambda sk, lv: sum(cefr_mod.estimate(s, sk)["composite_index"] for s in POOLS[sk][lv]) / 10  # noqa: E731
        for sk in ("writing", "speaking"):
            means = [mean(sk, lv) for lv in LEVELS]
            self.assertEqual(means, sorted(means), sk)  # monotonic across levels
        for p in self.parts:
            self.assertTrue(p["difficulty"]["human_review_required"])
            self.assertFalse(p["difficulty"]["calibrated"])


class RejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = all_parts()
        cls.w = next(p for p in cls.parts if p["id"] == "WR403")
        cls.s = next(p for p in cls.parts if p["id"] == "SP403")

    def errors(self, part):
        se = V.schema_errors(part)
        if se:
            return se
        return [f"{c}: {d}" for s, c, d in V.part_findings(part, taxonomy(), V.shared_taxonomy()) if s == "error"]

    def test_baseline_fixtures_are_clean(self):
        self.assertEqual(self.errors(self.w), [])
        self.assertEqual(self.errors(self.s), [])

    def test_missing_metadata_rejected(self):
        for key in ("evaluation_blueprint", "classification", "difficulty", "diagnostics", "uuid", "task", "expected_response", "provenance"):
            p = copy.deepcopy(self.w)
            del p[key]
            self.assertTrue(self.errors(p), key)

    def test_incomplete_blueprint_rejected(self):
        p = copy.deepcopy(self.w)
        del p["evaluation_blueprint"]["criteria"][0]["weak_performance"]
        self.assertTrue(self.errors(p))
        p = copy.deepcopy(self.w)
        p["evaluation_blueprint"]["criteria"] = p["evaluation_blueprint"]["criteria"][:2]
        self.assertTrue(self.errors(p))
        p = copy.deepcopy(self.w)
        p["evaluation_blueprint"]["criteria"][0]["weight"] = 0.9
        self.assertTrue(any("criterion_weights_not_normalised" in e for e in self.errors(p)))

    def test_wrong_level_label_rejected(self):
        p = copy.deepcopy(self.w)
        p["assessment"]["level"] = "C1"
        self.assertTrue(any("assessment_level_mismatch" in e for e in self.errors(p)))
        p = copy.deepcopy(self.w)
        p["target_cefr"] = "XX"
        self.assertTrue(self.errors(p))

    def test_level_inappropriate_criteria_and_demands_rejected(self):
        a1 = copy.deepcopy(next(p for p in self.parts if p["id"] == "WR101"))
        org = copy.deepcopy(self.w["evaluation_blueprint"]["criteria"][-1] if self.w["evaluation_blueprint"]["criteria"][-1]["id"] == "W_ORG" else next(c for c in self.w["evaluation_blueprint"]["criteria"] if c["id"] == "W_ORG"))
        a1["evaluation_blueprint"]["criteria"].append(org)
        self.assertTrue(any("criterion_not_appropriate_for_level" in e for e in self.errors(a1)))
        p = copy.deepcopy(next(p for p in self.parts if p["id"] == "WR101"))
        p["expected_response"]["grammar_demands"].append({"id": "mixed_conditionals", "level": "C1", "extension": True})
        self.assertTrue(any("grammar_demand_above_level" in e for e in self.errors(p)))

    def test_pronunciation_score_in_text_mvp_rejected(self):
        p = copy.deepcopy(self.s)
        pr = {"id": "S_PRON", "name": "Pronunciation", "description": "x" * 12, "weight": 0.1, "assessable_in_current_modality": "no", "scored_in_text_mvp": False,
              "successful_performance": "x" * 12, "weak_performance": "x" * 12, "expected_evidence": "x" * 12, "common_error_patterns": [], "related_subskills": ["a"], "evaluation_limitations": "x" * 12}
        p["evaluation_blueprint"]["criteria"].append(pr)
        self.assertTrue(any("pronunciation_scored_in_text_mvp" in e for e in self.errors(p)))
        p = copy.deepcopy(self.s)
        p["evaluation_blueprint"]["not_assessed_by_design"] = []
        self.assertTrue(any("pronunciation_not_marked_unavailable" in e for e in self.errors(p)))

    def test_answer_key_field_rejected(self):
        p = copy.deepcopy(self.w)
        p["expected_response"]["model_answer"] = "The ideal text"
        self.assertTrue(any("answer_key_present" in e for e in self.errors(p)) or self.errors(p))

    def test_out_of_range_word_count_and_time_rejected(self):
        p = copy.deepcopy(self.w)
        p["task"]["word_count"]["suggested_max"] = 40
        self.assertTrue(self.errors(p))
        p = copy.deepcopy(self.w)
        p["task"]["suggested_minutes"] = 3
        self.assertTrue(self.errors(p))
        p = copy.deepcopy(self.s)
        p["task"]["suggested_speaking_seconds"] = 10
        self.assertTrue(self.errors(p))

    def test_unknown_taxonomy_values_rejected_by_generator_and_validator(self):
        spec = copy.deepcopy(POOLS["writing"]["B1"][0])
        spec["gram"] = ["not_a_rule"]
        with self.assertRaises(SpecError):
            build_part("writing", "B1", spec, "WR301", SEED, TS)
        spec = copy.deepcopy(POOLS["writing"]["B1"][0])
        del spec["pts"]
        with self.assertRaises(SpecError):
            build_part("writing", "B1", spec, "WR301", SEED, TS)
        p = copy.deepcopy(self.w)
        p["topic"] = "not_a_topic"
        self.assertTrue(any("unknown_topic" in e for e in self.errors(p)))

    def test_bank_level_checks(self):
        parts = copy.deepcopy(self.parts)
        res = V.validate_all(parts[:-1])
        self.assertTrue(any("expected 70" in e for e in res["bank_errors"]))
        parts = copy.deepcopy(self.parts)
        parts[1]["uuid"] = parts[0]["uuid"]
        self.assertTrue(any("duplicate uuid" in e for e in V.validate_all(parts)["bank_errors"]))

    def test_duplicate_and_near_duplicate_detection(self):
        a = copy.deepcopy(next(p for p in self.parts if p["id"] == "WR402"))
        b = copy.deepcopy(a)
        b["id"], b["uuid"] = "WR499", "00000000-0000-4000-8000-000000000499"
        rows = V.duplicate_scan([a, b])
        self.assertEqual(rows[0]["severity"], "duplicate")
        c = copy.deepcopy(a)
        c["id"] = "WR498"
        c["task"]["prompt"] = "Some people say online study works as well as lessons in a classroom. Others do not agree. Discuss both views and say which is more convincing."
        c["title"] = "Different title"
        c["topic"] = "technology"
        rows = V.duplicate_scan([a, c])
        self.assertTrue(rows and "prompt" in rows[0]["reasons"])  # a paraphrase of the prompt is caught
        self.assertEqual(V.duplicate_scan([self.w, self.s]), [])

    def test_sensitive_content_flagged(self):
        p = copy.deepcopy(self.w)
        p["task"]["scenario"] = "You are at a party and someone offers you wine."
        self.assertTrue(any(c == "sensitive_content_keyword" for s, c, d in V.part_findings(p, taxonomy(), V.shared_taxonomy())))


class CompatibilityTests(unittest.TestCase):
    def test_reading_listening_assembler_and_bank_untouched(self):
        from assembler import bank as bank_mod
        from assembler.layout import scope_dir
        self.assertEqual(bank_mod.SKILLS, ("listening", "reading", "writing", "speaking"))
        self.assertFalse((ROOT / "productive_bank").exists())  # no second copy of the Writing/Speaking content
        parts, skipped = bank_mod.load_bank(scope_dir(ROOT / "question_bank", "placement"), ("validated", "reviewed", "approved"))
        self.assertEqual({s: len(v) for s, v in parts.items()}, {"listening": 10, "reading": 10, "writing": 10, "speaking": 10})
        self.assertEqual(skipped, [])

    def test_existing_validator_still_passes(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_part.py"), "--bank", "question_bank"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-400:] + r.stderr[-400:])

    def test_existing_schema_and_config_not_modified_in_place(self):
        t = load_json(ROOT / "config" / "taxonomy.json")
        self.assertIn("present_simple", t["grammar_rules"])
        pt = taxonomy()
        shared = set(t["grammar_rules"])
        ext = set(pt["grammar_extensions"])
        for g in [k for k in pt["grammar_level"] if not k.startswith("_")]:
            self.assertTrue(g in shared or g in ext, g)  # every id is shared vocabulary or a declared extension
        self.assertTrue(set(POOLS) == {"writing", "speaking"})
        for sk in POOLS.values():
            for specs in sk.values():
                for s in specs:
                    self.assertIn(s["topic"], t["topics"])

    def test_productive_attempt_schema_is_separate_from_bank(self):
        sch = load_json(ROOT / "schemas" / "productive_attempt.schema.json")
        text_attempt = {"attempt_id": "a1", "learner_id": "l1", "part_id": "SP101", "part_uuid": "u", "part_version": "1.0.0", "part_content_hash": "h", "skill": "speaking",
                        "response_modality": "typed_text", "response_text": "My name is ...", "submitted_at": "2026-10-30T12:00:00Z"}
        self.assertEqual(schema_validate(text_attempt, sch), [])
        for p in all_parts():
            self.assertNotIn("response_text", json.dumps(p))  # learner responses never live in the bank


if __name__ == "__main__":
    unittest.main()
