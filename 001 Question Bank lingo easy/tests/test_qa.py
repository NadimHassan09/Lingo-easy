"""QA test-suite for the question-bank audit, blueprint-driven assembler, attempts and adaptive profile.

Run from the project root:  python -m unittest tests.test_qa -v      (needs the QA pipeline outputs: python -m qa.run_all)
Includes deliberately invalid fixtures to prove the validators detect known problems.
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adaptive.attempts import build_attempt_records, load_sidecars  # noqa: E402
from adaptive.profile import MIN_EVIDENCE, build_profile, wilson  # noqa: E402
from assembler.assemble import ShortageError, assemble  # noqa: E402
from assembler.blueprint import CEFR, BlueprintError, exam_metrics, load_blueprint, load_meta, validate_exam  # noqa: E402
from qa import stage1_inventory_integrity as S1  # noqa: E402
from qa import stage3_semantic as S3  # noqa: E402
from qa.common import AUDIT, BANK, OUT, PLACEMENT, assessment_dir, items_of, load_parts  # noqa: E402
from qa.minischema import validate  # noqa: E402

PARTS = load_parts()
BYID = {e["part"]["id"]: e["part"] for e in PARTS}
BP = load_blueprint()
META = load_meta()
TYPES = [("placement", None, PLACEMENT)] + [(f"assessment_{lv}", lv, assessment_dir(lv)) for lv in CEFR]


def part_fixture(pid="LI003"):
    e = next(x for x in PARTS if x["part"]["id"] == pid)
    return copy.deepcopy(e["part"]), e


def run_checks(part, entry):
    findings = []
    e = dict(entry)
    e["part"] = part
    S1.check_part(e, lambda *a: findings.append(a))
    for n, (g, it) in enumerate(items_of(part), start=1):
        S1.check_item(e, g, it, n, lambda *a: findings.append(a))
    return findings


class IntegrityTests(unittest.TestCase):
    def test_bank_has_no_hard_integrity_failures(self):
        bad = []
        for e in PARTS:
            f = run_checks(copy.deepcopy(e["part"]), e)
            bad += [x for x in f if x[2] == "hard"]
        self.assertEqual(bad, [])

    def test_question_and_part_ids_and_uuids_unique(self):
        qids, quuids, pids, puuids = [], [], [], []
        for e in PARTS:
            pids.append(e["part"]["id"])
            puuids.append(e["part"]["uuid"])
            for _, it in items_of(e["part"]):
                qids.append(it["id"])
                quuids.append(it["uuid"])
        for name, xs in (("qid", qids), ("quuid", quuids), ("pid", pids), ("puuid", puuids)):
            self.assertEqual(len(xs), len(set(xs)), name)

    def test_answer_membership_and_exactly_one_correct(self):
        for e in PARTS:
            for _, it in items_of(e["part"]):
                ids = [o["id"] for o in it["options"]]
                self.assertIn(it["answer"], ids, it["id"])
                self.assertEqual(ids.count(it["answer"]), 1, it["id"])

    def test_evidence_is_in_source(self):
        for e in PARTS:
            src = S1.norm(S1.source_text(e["part"]))
            for _, it in items_of(e["part"]):
                if it["evidence"]:
                    self.assertIn(S1.norm(it["evidence"]["quote"]), src, it["id"])

    def test_detects_known_problems_in_invalid_fixtures(self):
        p, e = part_fixture()
        it = p["question_groups"][0]["items"][0]
        it["answer"] = "D"                                  # answer not in options
        it["options"][1]["text"] = it["options"][0]["text"]  # duplicate options
        it["uuid"] = "not-a-uuid"
        it["evidence"] = {"quote": "this sentence never appears in the transcript"}
        p["derived"]["word_count"] += 5                      # stale derived statistic
        checks = {x[3] for x in run_checks(p, e)}
        for c in ("answer_not_in_options", "duplicate_options", "bad_item_uuid", "evidence_not_in_transcript", "derived_word_count"):
            self.assertIn(c, checks)

    def test_duplicate_identifiers_would_be_reported(self):
        p, e = part_fixture()
        findings = []
        seen = {"item_id:" + it["id"]: [e["rel"], e["rel"]] for _, it in items_of(p)}
        for k, v in seen.items():
            if len(v) > 1:
                findings.append(k)
        self.assertTrue(findings)  # fixture sanity: the duplicate rule keys on identical ids

    def test_asset_audit_reports_audio_state_truthfully(self):
        import copy
        ents = [e for e in PARTS if e["part"]["skill"] == "listening"][:3]
        rows = S1.asset_audit(ents)
        for r in (r for r in rows if r["asset_type"] == "audio"):
            e = next(x for x in ents if x["part"]["id"] == r["part_id"])
            self.assertEqual(r["exists"], (e["path"].parent / e["part"]["audio"]["file"]).exists())  # reflects the disk (mp3s were generated later)
        missing = copy.deepcopy(ents[0])
        missing["part"]["audio"]["file"] = "li999_does_not_exist.mp3"
        rows = S1.asset_audit([missing])
        self.assertTrue(all(r["exists"] is False for r in rows if r["asset_type"] == "audio"))
        self.assertTrue(any("not generated" in r["note"] for r in rows))

    def test_levels_and_tags_match_config(self):
        tax = S1.TAX
        for e in PARTS:
            for _, it in items_of(e["part"]):
                self.assertIn(it["level"]["cefr"], CEFR)
                self.assertIn(it["skill_tag"], tax["skill_tags"][e["part"]["skill"]])


class SemanticChecksTests(unittest.TestCase):
    def _review(self, options, answer, prompt="What did the lecturer say?", level="C1"):
        part, e = part_fixture("LI601")
        rec = {"question_id": "T-Q01", "uuid": "u", "modality": "listening", "options": options, "answer_id": answer, "answer_text": options["ABCD".index(answer)],
               "evidence": None, "explanation": "x" * 20, "question_type": "multiple_choice", "skill_tag": "inference", "original_cefr": level,
               "prompt": prompt, "part_id": "LI601", "source_file": "x", "bank": "t"}
        return S3.review(rec, part)

    def test_length_cue_and_extreme_wording_are_flagged(self):
        r = self._review(["A short wrong one", "It is completely useless to everyone", "The correct statement is much longer than both distractors put together"], "C")
        codes = {f["code"] for f in r["findings"]}
        self.assertIn("length_cue_correct_option_longest", codes)
        self.assertIn("extreme_wording_in_distractor", codes)
        self.assertEqual(r["semantic_status"], "human_review")

    def test_balanced_item_passes(self):
        r = self._review(["It is mainly about habits", "It is mainly about sleep", "It is mainly about memory"], "B")
        self.assertEqual(r["semantic_status"], "pass")

    def test_number_not_in_source_flagged(self):
        r = self._review(["A fall of 99 per cent", "A fall of 12 per cent", "A fall of 5 per cent"], "A", "How much?")
        self.assertIn("number_not_in_source", {f["code"] for f in r["findings"]})

    def test_number_parser(self):
        self.assertEqual(S3.numbers_in("three hundred and sixty pounds"), {360})
        self.assertEqual(S3.numbers_in("twenty-four pounds"), {24})
        self.assertIn(5800, S3.numbers_in("five thousand eight hundred"))


class SchemaAndMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((OUT / "schemas" / "question_schema_v2.json").read_text(encoding="utf-8"))
        cls.v2 = [json.loads(l) for l in open(OUT / "exports" / "question_records_v2.jsonl", encoding="utf-8")]

    def test_all_v2_records_valid(self):
        bad = [(r["question_id"], validate(r, self.schema)[:2]) for r in self.v2 if validate(r, self.schema)]
        self.assertEqual(bad, [])

    def test_invalid_v2_fixtures_rejected(self):
        r = copy.deepcopy(self.v2[0])
        del r["answer"]
        self.assertTrue(validate(r, self.schema))
        r = copy.deepcopy(self.v2[0])
        r["answer"] = "Z"
        self.assertTrue(validate(r, self.schema))
        r = copy.deepcopy(self.v2[0])
        r["learner_history"] = [1]  # learner data must never live in the question record
        self.assertTrue(validate(r, self.schema))

    def test_migration_preserves_ids_uuids_and_counts(self):
        v1 = {it["uuid"]: it["id"] for e in PARTS for _, it in items_of(e["part"])}
        self.assertEqual({r["uuid"]: r["question_id"] for r in self.v2}, v1)
        self.assertEqual(len(self.v2), 1610)

    def test_v1_bank_still_valid_for_existing_validator(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_part.py"), "--bank", str(BANK)], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-500:])

    def test_no_learner_data_in_bank(self):
        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for x in o:
                    yield from keys(x)
        for e in PARTS:
            ks = set(keys(e["part"]))
            self.assertFalse(ks & {"learner_id", "attempt_id", "response_time_ms", "selected_option", "attempts", "history"}, e["part"]["id"])

    def test_taxonomy_values_valid(self):
        tax = json.loads((OUT / "schemas" / "skill_taxonomy.json").read_text(encoding="utf-8"))
        subs = {s["id"] for s in tax["subskills"]}
        cog = {c["id"] for c in tax["cognitive_processes"]}
        for m in json.loads((ROOT / "config" / "question_meta_v2.json").read_text(encoding="utf-8"))["questions"].values():
            self.assertIn(m["primary_subskill"], subs)
            self.assertIn(m["recommended_primary_subskill"], subs)
            self.assertIn(m["cognitive_process"], cog)
        tags = {(m["modality"], m["tag"]) for m in tax["original_tag_mapping"]}
        for e in PARTS:
            for _, it in items_of(e["part"]):
                self.assertIn((e["part"]["skill"], it["skill_tag"]), tags)

    def test_cefr_recommendations_never_applied_to_bank(self):
        base = zipfile.ZipFile(OUT / "baseline" / "original_snapshot_before_qa.zip")
        for e in PARTS:
            old = json.loads(base.read(e["legacy_rel"]))
            for (_, a), (_, b) in zip(items_of(old), items_of(e["part"])):
                self.assertEqual(a["level"], b["level"], a["id"])
                self.assertEqual(a["skill_tag"], b["skill_tag"], a["id"])


class RegressionTests(unittest.TestCase):
    def test_unchanged_questions_identical_and_changed_only_in_distractors(self):
        base = zipfile.ZipFile(OUT / "baseline" / "original_snapshot_before_qa.zip")
        changed = {}
        for line in open(AUDIT / "question_change_log.jsonl", encoding="utf-8"):
            c = json.loads(line)
            changed.setdefault(c["question_id"], []).append(c)
        n_same = n_changed = 0
        for e in PARTS:
            old = json.loads(base.read(e["legacy_rel"]))
            self.assertEqual(old["uuid"], e["part"]["uuid"])
            self.assertEqual(old["passage"] if "passage" in old else old["audio"], e["part"]["passage"] if "passage" in e["part"] else e["part"]["audio"], "source text must not change: " + old["id"])
            for (_, a), (_, b) in zip(items_of(old), items_of(e["part"])):
                self.assertEqual((a["id"], a["uuid"], a["prompt"], a["answer"], a["evidence"], a["level"], a["skill_tag"]),
                                 (b["id"], b["uuid"], b["prompt"], b["answer"], b["evidence"], b["level"], b["skill_tag"]))
                ta = {o["id"]: o["text"] for o in a["options"]}
                tb = {o["id"]: o["text"] for o in b["options"]}
                self.assertEqual(ta[a["answer"]], tb[b["answer"]], "key text must be unchanged: " + a["id"])
                if a["id"] in changed:
                    n_changed += 1
                    self.assertNotEqual(ta, tb)
                else:
                    n_same += 1
                    self.assertEqual(ta, tb, a["id"])
        self.assertEqual(n_same + n_changed, 1610)
        self.assertGreater(n_changed, 400)

    def test_change_log_is_complete_and_traceable(self):
        for line in open(AUDIT / "question_change_log.jsonl", encoding="utf-8"):
            c = json.loads(line)
            for k in ("question_id", "uuid", "original", "revised", "fields_modified", "reason", "review_confidence", "human_review_still_required", "review_timestamp", "tool"):
                self.assertIn(k, c)
            self.assertFalse(c["answer_changed"])
            self.assertTrue(c["human_review_still_required"])
            self.assertEqual(c["original"]["answer"], c["revised"]["answer"])


class BlueprintAndAssemblerTests(unittest.TestCase):
    def test_blueprint_is_internally_consistent(self):
        for name, lv, _ in TYPES:
            s = BP["exam_types"][name]
            self.assertEqual(s["questions"]["total"], s["questions"]["listening"] + s["questions"]["reading"])
            for l, r in s["level_counts"].items():
                self.assertLessEqual(r["min"], r["max"])
            self.assertLessEqual(sum(r["min"] for r in s["level_counts"].values()), s["questions"]["total"])
            self.assertGreaterEqual(sum(r["max"] for r in s["level_counts"].values()), s["questions"]["total"])
            if lv:
                self.assertEqual(s["level_counts"][lv], {"min": 79, "max": 79})

    def test_determinism_same_seed(self):
        for name, lv, d in TYPES:
            for seed in (1, 7, 42):
                p1, s1 = assemble(d, seed=seed, level=lv)
                p2, s2 = assemble(d, seed=seed, level=lv)
                self.assertEqual(json.dumps(p1["sections"], sort_keys=True), json.dumps(p2["sections"], sort_keys=True), (name, seed))
                self.assertEqual(s1["key"], s2["key"])
                self.assertEqual([p["part_id"] for p in s1["parts"]], [p["part_id"] for p in s2["parts"]])

    def test_constraints_hold_across_many_seeds(self):
        by_bank = {}
        for name, lv, d in TYPES:
            from assembler.bank import load_bank
            bank, _ = load_bank(d, ["validated"])
            byid = {p["id"]: p for s in bank.values() for p in s}
            for seed in range(80):
                _, st = assemble(d, seed=seed, level=lv)
                parts = [byid[p["part_id"]] for p in st["parts"] if p["skill"] in ("listening", "reading")]
                v = validate_exam(parts, BP["exam_types"][name], META)
                self.assertEqual(v, [], (name, seed, v))
                ids = [it["id"] for p in parts for g in p["question_groups"] for it in g["items"]]
                self.assertEqual(len(ids), len(set(ids)))  # no duplicate questions in an exam
                m = exam_metrics(parts, META)
                self.assertEqual((m["total"], m["by_modality"]), (79, {"listening": 40, "reading": 39}))

    def test_key_remains_correct_after_option_shuffle(self):
        _, st = assemble(PLACEMENT, seed=3)
        for qid, k in st["key"].items():
            self.assertEqual(k["shown_options"][k["answer"]], BYID_ITEMS[qid]["correct_text"])
            self.assertEqual(k["option_origin"][k["answer"]], BYID_ITEMS[qid]["answer"])

    def test_blueprint_failure_is_structured_not_relaxed(self):
        bp = copy.deepcopy(BP)
        bp["exam_types"]["placement"]["level_counts"]["A1"] = {"min": 70, "max": 79}  # impossible with this bank
        bp["assembly"]["max_attempts"] = 15
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bp.json"
            p.write_text(json.dumps(bp), encoding="utf-8")
            with self.assertRaises(BlueprintError) as cm:
                assemble(PLACEMENT, seed=1, blueprint_path=p)
        d = cm.exception.to_dict()
        self.assertEqual(d["error"], "no_valid_exam")
        self.assertEqual(d["details"]["attempts"], 15)
        self.assertIn("level_count", d["details"]["violation_counts"])

    def test_insufficient_bank_coverage_raises_shortage(self):
        with tempfile.TemporaryDirectory() as td:
            for skill in ("listening", "reading"):
                src = next(e for e in PARTS if e["part"]["skill"] == skill and e["bank"] == "placement")
                dst = Path(td) / skill / src["part"]["id"]
                dst.mkdir(parents=True)
                (dst / "part.json").write_text(json.dumps(src["part"]), encoding="utf-8")
            with self.assertRaises(ShortageError):
                assemble(td, seed=1)

    def test_forbidden_pair_is_never_selected_together(self):
        bp = copy.deepcopy(BP)
        pair = ["LI001", "LI002"]
        bp["forbidden_pairs"] = [pair]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bp.json"
            p.write_text(json.dumps(bp), encoding="utf-8")
            hits = 0
            for seed in range(120):
                _, st = assemble(PLACEMENT, seed=seed, blueprint_path=p)
                ids = {x["part_id"] for x in st["parts"]}
                self.assertFalse(set(pair) <= ids)
                hits += 1
        self.assertEqual(hits, 120)

    def test_validate_exam_detects_violations(self):
        _, st = assemble(PLACEMENT, seed=2)
        parts = [BYID[p["part_id"]] for p in st["parts"] if p["skill"] in ("listening", "reading")]
        spec = copy.deepcopy(BP["exam_types"]["placement"])
        spec["max_parts_per_topic"] = 0
        spec["level_counts"]["B2"] = {"min": 0, "max": 1}
        codes = {v["code"] for v in validate_exam(parts, spec, META)}
        self.assertIn("topic_repetition", codes)
        self.assertIn("level_count", codes)
        dup = validate_exam(parts + [parts[0]], BP["exam_types"]["placement"], META)
        self.assertTrue({"duplicate_questions", "duplicate_sources"} <= {v["code"] for v in dup})

    def test_distribution_summary_numbers_match_manifests(self):
        s = json.loads((OUT / "reports" / "assembly_simulation_summary.json").read_text(encoding="utf-8"))
        for name, res in s["results"].items():
            e = res["enforced"]
            self.assertEqual(e["exams_generated"] + e["generation_failures"], s["seeds_per_exam_type_and_mode"])
            mf = (OUT / "exam_manifests" / f"manifest_{name}.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(mf) - 1, s["seeds_per_exam_type_and_mode"])


BYID_ITEMS = {}
for _e in PARTS:
    for _g, _it in items_of(_e["part"]):
        BYID_ITEMS[_it["id"]] = {"answer": _it["answer"], "correct_text": next(o["text"] for o in _it["options"] if o["id"] == _it["answer"])}


class AttemptAndProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, cls.diag = load_sidecars()
        _, cls.st = assemble(PLACEMENT, seed=11)

    def _answers(self, n_correct, n_wrong):
        keys = list(self.st["key"].items())
        ans = {k: v["answer"] for k, v in keys[:n_correct]}
        ans.update({k: next(c for c in "ABC" if c != v["answer"]) for k, v in keys[n_correct:n_correct + n_wrong]})
        return ans

    def test_attempt_records_complete_and_schema_valid(self):
        sch = json.loads((OUT / "schemas" / "learner_attempt_schema.json").read_text(encoding="utf-8"))
        recs = build_attempt_records(self.st, self._answers(30, 20), self.meta, self.diag, "synthetic-x", "att1", "2026-01-01T00:00:00+00:00", {k: 4000 for k in self.st["key"]})
        self.assertEqual(len(recs), 79)
        self.assertEqual(sum(r["answered"] for r in recs), 50)
        self.assertEqual(sum(r["is_correct"] for r in recs), 30)
        for r in recs:
            self.assertEqual(validate(r, sch), [], r["attempt_record_id"])
        wrong = [r for r in recs if r["answered"] and not r["is_correct"]]
        self.assertTrue(all(r["distractor_diagnostic"] for r in wrong))
        self.assertTrue(all(r["distractor_diagnostic"] is None for r in recs if r["is_correct"]))

    def test_diagnostic_traceability_to_source(self):
        rows = [json.loads(l) for l in open(OUT / "exports" / "question_records_v2.jsonl", encoding="utf-8")]
        by_part = {e["part"]["id"]: S1.norm(S1.source_text(e["part"])) for e in PARTS}
        checked = 0
        for r in rows:
            for d in r["distractor_diagnostics"]:
                self.assertIn(d["option_id"], [o["id"] for o in r["options"]])
                if d["evidence_class"] == "text_grounded" and not d["is_correct"]:
                    self.assertTrue(d["evidence_basis"])
                    self.assertIn(S1.norm(d["evidence_basis"]), by_part[r["part_id"]])
                    checked += 1
        self.assertGreater(checked, 500)

    def test_profile_single_wrong_answer_is_not_a_weakness(self):
        recs = build_attempt_records(self.st, self._answers(0, 1), self.meta, self.diag, "synthetic-y", "a1", "t")
        prof = build_profile("synthetic-y", {"a1": recs}, now="t")
        self.assertEqual(prof["status"], "insufficient_evidence")
        self.assertTrue(all(s["status"] == "insufficient_evidence" for s in prof["subskills"].values()))
        self.assertEqual(prof["recommended_next_objectives"], [])

    def test_profile_from_multiple_attempts_is_traceable(self):
        _, st2 = assemble(PLACEMENT, seed=12)
        r1 = build_attempt_records(self.st, {k: v["answer"] for k, v in self.st["key"].items()}, self.meta, self.diag, "synthetic-z", "a1", "t")
        keys2 = list(st2["key"].items())
        a2 = {k: (v["answer"] if i % 2 else next(c for c in "ABC" if c != v["answer"])) for i, (k, v) in enumerate(keys2)}
        r2 = build_attempt_records(st2, a2, self.meta, self.diag, "synthetic-z", "a2", "t")
        prof = build_profile("synthetic-z", {"a1": r1, "a2": r2}, now="t")
        sch = json.loads((OUT / "schemas" / "adaptive_profile_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(prof, sch), [])
        self.assertEqual(prof["consistency"]["status"], "inconsistent")
        all_ids = {r["attempt_record_id"] for r in r1 + r2}
        for s in prof["subskills"].values():
            self.assertTrue(set(s["supporting_attempt_record_ids"]) <= all_ids)
        self.assertEqual(prof["attempts_included"], ["a1", "a2"])

    def test_wilson_interval_sane(self):
        lo, hi = wilson(3, 6)
        self.assertTrue(0 < lo < 0.5 < hi < 1)
        self.assertEqual(wilson(0, 0), (0.0, 1.0))
        self.assertGreaterEqual(MIN_EVIDENCE, 5)


class MiniSchemaTests(unittest.TestCase):
    def test_basic_rules(self):
        s = {"type": "object", "required": ["a"], "additionalProperties": False, "properties": {"a": {"type": "integer", "minimum": 1}, "b": {"enum": ["x", "y"]}}}
        self.assertEqual(validate({"a": 2, "b": "x"}, s), [])
        self.assertTrue(validate({"a": 0}, s))
        self.assertTrue(validate({}, s))
        self.assertTrue(validate({"a": 1, "c": 1}, s))
        self.assertTrue(validate({"a": True}, s))


if __name__ == "__main__":
    unittest.main()
