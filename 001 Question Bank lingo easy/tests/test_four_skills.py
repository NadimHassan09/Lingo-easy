"""Four-skill integration: unified question-bank layout, assembly of Reading+Listening+Writing+Speaking, API submission, storage and the UI contract."""
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assembler.assemble import assemble  # noqa: E402
from assembler.bank import load_bank  # noqa: E402
from assembler.demo import build_demo_bank  # noqa: E402
from assembler.layout import LEVELS, SKILLS, iter_scopes, scope_dir  # noqa: E402
from server import api  # noqa: E402
from server.dev_server import serve  # noqa: E402

BANK = ROOT / "question_bank"
STATUSES = ["validated", "reviewed", "approved"]
LEAK_KEYS = {"evaluation_blueprint", "difficulty", "classification", "diagnostics", "provenance", "uuid", "target_cefr", "expected_response", "derived", "qa", "meta",
             "level", "ielts_reference", "outline", "examples", "raw_spec"}


def find_keys(o, bad, path=""):
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in bad:
                out.append(path + "." + k)
            out += find_keys(v, bad, path + "." + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out += find_keys(v, bad, f"{path}[{i}]")
    return out


class LayoutTests(unittest.TestCase):
    def test_unified_structure_only(self):
        self.assertEqual(sorted(p.name for p in BANK.iterdir()), ["assessment_test", "placement_test"])
        self.assertEqual(sorted(p.name for p in (BANK / "assessment_test").iterdir()), list(LEVELS))
        for name, mode, level, d in iter_scopes(BANK):
            self.assertEqual(sorted(p.name for p in d.iterdir()), sorted(SKILLS), name)
        self.assertFalse((ROOT / "productive_bank").exists())

    def test_every_scope_has_ten_parts_per_skill_with_matching_ids_and_levels(self):
        for name, mode, level, d in iter_scopes(BANK):
            bank, skipped = load_bank(d, STATUSES)
            self.assertEqual(skipped, [], name)
            for skill in SKILLS:
                self.assertEqual(len(bank[skill]), 10, (name, skill))
                for p in bank[skill]:
                    self.assertTrue((d / skill / p["id"] / "part.json").exists())  # folder name = id
                    if mode == "assessment":
                        self.assertEqual(p["profile"], f"level_{level.lower()}")
                        if skill in ("writing", "speaking"):
                            self.assertEqual(p["target_cefr"], level)
        all_ids = [p["id"] for _, _, _, d in iter_scopes(BANK) for s in load_bank(d, STATUSES)[0].values() for p in s]
        self.assertEqual(len(all_ids), 280)
        self.assertEqual(len(set(all_ids)), 280)

    def test_productive_parts_share_lingo_easy_metadata(self):
        for _, mode, level, d in iter_scopes(BANK):
            for skill in ("writing", "speaking"):
                for p in load_bank(d, STATUSES)[0][skill]:
                    for k in ("id", "uuid", "skill", "part_type", "title", "topic", "profile", "level", "skill_tag", "meta", "derived", "ielts_reference"):
                        self.assertIn(k, p, (p["id"], k))
                    self.assertEqual(p["level"]["cefr"], p["target_cefr"])
                    lo, hi = p["ielts_reference"]["band_range"]
                    self.assertTrue(lo <= p["level"]["band"] <= hi)


class AssemblyTests(unittest.TestCase):
    def test_placement_has_all_four_skills_and_spread_levels(self):
        for seed in range(25):
            pub, st = assemble(scope_dir(BANK, "placement"), seed=seed)
            self.assertEqual([s["skill"] for s in pub["sections"]], list(SKILLS))
            self.assertEqual(st["requested"], {"listening": 4, "reading": 3, "writing": 3, "speaking": 3})
            self.assertEqual(st["blueprint"]["status"], "enforced")
            for sk in ("writing", "speaking"):
                lv = [t["target_cefr"] for t in st["tasks"].values() if t["skill"] == sk]
                self.assertEqual(len(lv), 3)
                self.assertGreaterEqual(len(set(lv)), 2)
                self.assertEqual(lv, sorted(lv))  # shown easiest first

    def test_each_assessment_level_uses_only_its_level_for_all_skills(self):
        for lv in LEVELS:
            pub, st = assemble(scope_dir(BANK, "assessment", lv), level=lv, seed=5)
            self.assertEqual([s["skill"] for s in pub["sections"]], list(SKILLS))
            self.assertTrue(all(p["profile"] == f"level_{lv.lower()}" for p in st["parts"]))
            self.assertTrue(all(t["target_cefr"] == lv for t in st["tasks"].values()))
            self.assertTrue(all(k["cefr"] == lv for k in st["key"].values()))

    def test_mcq_selection_for_a_seed_is_unchanged_by_writing_and_speaking(self):
        a = assemble(scope_dir(BANK, "placement"), seed=77, writing=0, speaking=0)[1]
        b = assemble(scope_dir(BANK, "placement"), seed=77)[1]
        self.assertEqual([p["part_id"] for p in a["parts"] if p["skill"] in ("listening", "reading")], [p["part_id"] for p in b["parts"] if p["skill"] in ("listening", "reading")])
        self.assertEqual(a["key"].keys(), b["key"].keys())

    def test_public_exam_never_leaks_internal_metadata(self):
        pub, st = assemble(scope_dir(BANK, "assessment", "C1"), level="C1", seed=1)
        for sec in pub["sections"]:
            if sec["skill"] in ("writing", "speaking"):
                for part in sec["parts"]:
                    self.assertEqual(find_keys(part, LEAK_KEYS), [], part["part_id"])
                    self.assertIn(part["kind"], ("writing_task", "speaking_task"))
        text = json.dumps(pub)
        self.assertNotIn("D_TENSE", text)
        self.assertNotIn("successful_performance", text)

    def test_explicit_counts_and_shortage(self):
        _, st = assemble(scope_dir(BANK, "placement"), seed=1, writing=1, speaking=0)
        self.assertEqual(sum(1 for p in st["parts"] if p["skill"] == "writing"), 1)
        self.assertEqual(sum(1 for p in st["parts"] if p["skill"] == "speaking"), 0)
        from assembler.assemble import ShortageError
        with self.assertRaises(ShortageError):
            assemble(scope_dir(BANK, "placement"), seed=1, writing=11)

    def test_banks_without_productive_parts_still_work(self):
        with tempfile.TemporaryDirectory() as d:
            root = build_demo_bank(Path(d) / "bank", n_each=6)
            pub, st = assemble(root / "placement_test", 4, 4, seed=3, enforce_blueprint=False)
            self.assertEqual([s["skill"] for s in pub["sections"]], ["listening", "reading"])
            self.assertTrue(any("section omitted" in n for n in st["selection_notes"]))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.exams = Path(self.tmp.name)
        self.s = api.Settings(bank_dir=BANK, exams_dir=self.exams, statuses=STATUSES)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, **kw):
        pub = api.start_exam(kw or {"mode": "placement"}, self.s)
        stored = json.loads((self.exams / f"{pub['exam_id']}.json").read_text(encoding="utf-8"))
        return pub, stored

    def test_stats_cover_all_scopes_and_skills(self):
        st = api.bank_stats(self.s)
        self.assertEqual(st["usable_parts"], {s: 10 for s in SKILLS})
        self.assertEqual(sorted(st["assessment_usable_parts"]), list(LEVELS))
        self.assertTrue(all(v == {s: 10 for s in SKILLS} for v in st["assessment_usable_parts"].values()))
        self.assertEqual(st["skipped"], [])

    def test_submission_stores_writing_and_speaking_responses(self):
        pub, stored = self.start(mode="assessment", level="B1")
        tasks = stored["tasks"]
        wr = next(p for p, t in tasks.items() if t["skill"] == "writing")
        sp = next(p for p, t in tasks.items() if t["skill"] == "speaking")
        answers = {k: v["answer"] for k, v in stored["key"].items()}
        res = api.submit_exam(pub["exam_id"], {"answers": answers, "learner_id": "learner-1",
                                               "responses": {wr: {"text": "I think working from home is good. First, ...", "input_method": "typed_text"},
                                                             sp: {"text": "Well, I want to talk about a trip.", "input_method": "manual_transcript"}}}, self.s)
        self.assertEqual(res["total"]["percent"], 100.0)  # MCQ scoring unchanged and not diluted by the open tasks
        self.assertEqual(res["productive"]["responses_received"], 2)
        self.assertEqual(res["productive"]["evaluation"], "not_evaluated")
        saved = json.loads((self.exams / f"{pub['exam_id']}.responses.json").read_text(encoding="utf-8"))["records"]
        by = {r["part_id"]: r for r in saved}
        self.assertEqual(set(by), set(tasks))
        self.assertEqual(by[wr]["response_text"], "I think working from home is good. First, ...")
        self.assertEqual(by[wr]["input_method"], "typed_text")
        self.assertEqual(by[sp]["input_method"], "manual_transcript")
        self.assertEqual(by[sp]["transcript_source"], "manual_entry")
        for r in saved:
            self.assertEqual(r["response_modality"], "typed_text")
            self.assertEqual(r["evaluation_status"], "not_evaluated")
            self.assertEqual(r["learner_id"], "learner-1")
            for forbidden in ("audio", "audio_asset_ref", "stt_provider", "stt_confidence", "pronunciation_evaluation", "evaluation"):
                self.assertNotIn(forbidden, r)  # nothing audio-related is fabricated
            self.assertEqual(r["part_content_hash"], tasks[r["part_id"]]["part_content_hash"])
        unanswered = [r for r in saved if r["part_id"] not in (wr, sp)]
        self.assertTrue(unanswered and all(r["response_text"] == "" and r["word_count"] == 0 for r in unanswered))
        result = json.loads((self.exams / f"{pub['exam_id']}.result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["responses"][wr]["text"], by[wr]["response_text"])

    def test_response_validation(self):
        pub, stored = self.start(mode="placement")
        wr = next(p for p, t in stored["tasks"].items() if t["skill"] == "writing")
        sp = next(p for p, t in stored["tasks"].items() if t["skill"] == "speaking")
        bad = [({"responses": {"WR999": {"text": "x"}}}, 422),
               ({"responses": {wr: {"text": "x" * 20001}}}, 422),
               ({"responses": {sp: {"text": "hello", "input_method": "stt_transcript"}}}, 422),  # reserved for the future audio pipeline
               ({"responses": {wr: {"text": "hello", "input_method": "manual_transcript"}}}, 422),
               ({"responses": {wr: {"text": 5}}}, 422),
               ({"responses": ["x"]}, 422)]
        for payload, status in bad:
            with self.assertRaises(api.ApiError) as cm:
                api.submit_exam(pub["exam_id"], dict(payload, answers={}), self.s)
            self.assertEqual(cm.exception.status, status, payload)
        self.assertFalse((self.exams / f"{pub['exam_id']}.result.json").exists())  # rejected submissions do not consume the exam
        api.submit_exam(pub["exam_id"], {"responses": {wr: "plain string is accepted"}}, self.s)
        with self.assertRaises(api.ApiError) as cm:
            api.submit_exam(pub["exam_id"], {"responses": {}}, self.s)
        self.assertEqual(cm.exception.status, 409)

    def test_old_clients_without_responses_still_work(self):
        pub, stored = self.start(mode="placement")
        res = api.submit_exam(pub["exam_id"], {"answers": {k: v["answer"] for k, v in stored["key"].items()}}, self.s)
        self.assertEqual(res["total"]["percent"], 100.0)
        self.assertEqual(res["productive"]["responses_received"], 0)

    def test_http_round_trip(self):
        srv = serve(0, self.s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        try:
            pub = call("/api/exam/start", {"mode": "assessment", "level": "A1"})
            self.assertEqual([s["skill"] for s in pub["sections"]], list(SKILLS))
            task = pub["sections"][2]["parts"][0]
            res = call(f"/api/exam/{pub['exam_id']}/submit", {"answers": {}, "responses": {task["part_id"]: {"text": "My name is Sam."}}})
            self.assertEqual(res["productive"]["responses_received"], 1)
            self.assertEqual(call("/api/bank/stats")["usable_parts"], {s: 10 for s in SKILLS})
        finally:
            srv.shutdown()
            srv.server_close()


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    def test_microphone_is_simulated_only(self):
        for banned in ("getUserMedia", "MediaRecorder", "SpeechRecognition", "webkitSpeechRecognition", "AudioContext", "enumerateDevices"):
            self.assertFalse(banned in self.html, banned)
        self.assertIn("coming soon", self.html)
        self.assertIn("no permission was requested", self.html)
        self.assertIn("speech-to-text will fill this box in a future version", self.html)
        self.assertIn("manual_transcript", self.html)
        self.assertFalse("stt_transcript" in self.html)  # the UI never labels typed text as speech recognition

    def test_task_views_and_submission_wiring(self):
        for needle in ("writing_task", "speaking_task", "responses", "textarea"):
            self.assertIn(needle, self.html)
        m = re.search(r"<script>([\s\S]*)</script>", self.html)
        self.assertTrue(m)


class SkillFilesTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / ".agent" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def test_both_skills_follow_the_existing_skill_conventions(self):
        for name, extra in (("lingoeasy-writing-generator", ["not an answer key", "not_penalised", "CC BY 4.0", "LuchoBazz"]),
                            ("lingoeasy-speaking-generator", ["S_PRON", "CURRENT MVP LIMITATION", "partial", "audio_extension", "not** part of LuchoBazz"])):
            t = self.read(name)
            self.assertTrue(t.startswith("---\nname: " + name + "\ndescription: "))
            for section in ("## Hard rules", "## Workflow", "### Step 1", "### Step 5", "## Quality self-check", "## Parameters"):
                self.assertIn(section, t, (name, section))
            for needle in ["placement_test", "assessment_test", "config/taxonomy.json", "productive/config/productive_taxonomy.json", "python -m productive.build", *extra]:
                self.assertIn(needle, t, (name, needle))
            self.assertIn("placement", t.lower())
            self.assertTrue((ROOT / ".agent" / "skills" / name / "references").is_dir())
        # existing generators untouched in name/location
        self.assertTrue((ROOT / ".agent" / "skills" / "lingoeasy-reading-generator" / "SKILL.md").exists())
        self.assertTrue((ROOT / ".agent" / "skills" / "lingoeasy-listening-generator" / "SKILL.md").exists())

    def test_generator_cli_produces_valid_part_from_spec_and_rejects_bad_spec(self):
        from productive.specs.registry import POOLS
        spec = dict(POOLS["speaking"]["B1"][1])
        spec["k"] = "B1-T1"
        spec["title"] = "Learning methods (CLI test)"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "ok.json").write_text(json.dumps(spec), encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "productive.generate", "--spec-file", str(d / "ok.json"), "--skill", "speaking", "--bank", "B1",
                                "--out", str(d / "qb"), "--spec-archive", str(d / "arch")], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            part = json.loads((d / "qb" / "assessment_test" / "B1" / "speaking" / "SP301" / "part.json").read_text(encoding="utf-8"))
            self.assertEqual(part["meta"]["status"], "validated")
            self.assertEqual(part["part_type"], spec["fmt"])
            spec["gram"] = ["not_a_rule"]
            (d / "bad.json").write_text(json.dumps(spec), encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "productive.generate", "--spec-file", str(d / "bad.json"), "--skill", "speaking", "--bank", "B1",
                                "--out", str(d / "qb2"), "--spec-archive", str(d / "arch2")], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(r.returncode, 1)
            self.assertFalse((d / "qb2").exists())


if __name__ == "__main__":
    unittest.main()
