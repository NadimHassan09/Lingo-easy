"""Run from the project root:  python -m unittest discover -s tests -v   (no extra packages needed)"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assembler.assemble import ShortageError, assemble  # noqa: E402
from assembler.demo import build_demo_bank  # noqa: E402
from assembler.evaluate import evaluate  # noqa: E402
from server import api  # noqa: E402
from server.dev_server import serve  # noqa: E402

LEAK_WORDS = ['"answer"', '"explanation"', '"evidence"', '"cefr"', '"band"', '"skill_tag"', '"language_focus"', '"uuid"']


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bank = build_demo_bank(self.root / "bank", n_each=6)
        self.exams = self.root / "exams"

    def tearDown(self):
        self.tmp.cleanup()


class AssembleTests(Base):
    def test_counts_and_no_repeats(self):
        pub, st = assemble(self.bank, 4, 4, exams_dir=self.exams)
        ids = [p["part_id"] for s in pub["sections"] for p in s["parts"]]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(len(st["key"]), 32)

    def test_public_exam_leaks_nothing(self):
        pub, _ = assemble(self.bank, 4, 4, exams_dir=self.exams)
        text = json.dumps(pub)
        for w in LEAK_WORDS:
            self.assertNotIn(w, text, f"public exam leaks {w}")

    def test_stored_exam_written(self):
        _, st = assemble(self.bank, 2, 2, exams_dir=self.exams)
        self.assertTrue((self.exams / f"{st['exam_id']}.json").exists())

    def test_same_seed_same_parts_different_exam_id(self):
        _, a = assemble(self.bank, 4, 4, seed=11)
        _, b = assemble(self.bank, 4, 4, seed=11)
        self.assertEqual([p["part_id"] for p in a["parts"]], [p["part_id"] for p in b["parts"]])
        self.assertNotEqual(a["exam_id"], b["exam_id"])

    def test_shortage_is_an_error_not_a_partial_exam(self):
        with self.assertRaises(ShortageError):
            assemble(self.bank, 7, 4)

    def test_status_filter(self):
        p = self.bank / "listening" / "LI101" / "part.json"
        d = json.loads(p.read_text())
        d["meta"]["status"] = "draft"
        p.write_text(json.dumps(d))
        with self.assertRaises(ShortageError):
            assemble(self.bank, 6, 1)  # only 5 listening parts remain usable
        pub, _ = assemble(self.bank, 5, 1)
        self.assertNotIn("LI101", [x["part_id"] for s in pub["sections"] for x in s["parts"]])

    def test_profile_and_type_variety(self):
        _, st = assemble(self.bank, 4, 4, seed=3)
        lis = [p for p in st["parts"] if p["skill"] == "listening"]
        self.assertEqual(len({p["part_type"] for p in lis}), 4)
        self.assertGreaterEqual(len({p["profile"] for p in lis}), 3)


class RandomisationAndAssessmentTests(Base):
    def test_options_and_part_order_vary_but_key_stays_correct(self):
        orders, option_orders = set(), set()
        for seed in range(12):
            pub, st = assemble(self.bank, 4, 4, seed=seed)
            orders.add(tuple(p["part_id"] for s in pub["sections"] for p in s["parts"]))
            first = pub["sections"][0]["parts"][0]["groups"][0]["items"][0]
            option_orders.add(tuple(o["text"] for o in first["options"]))
            # whatever the shuffle did, the stored key must still point at the right option text
            for s in pub["sections"]:
                for part in s["parts"]:
                    for g in part["groups"]:
                        for it in g["items"]:
                            self.assertIn(st["key"][it["id"]]["answer"], [o["id"] for o in it["options"]])
        self.assertGreater(len(orders), 3)
        self.assertGreater(len(option_orders), 1)

    def test_tfng_options_never_shuffled(self):
        for seed in range(6):
            pub, _ = assemble(self.bank, 2, 2, seed=seed)
            for s in pub["sections"]:
                for part in s["parts"]:
                    for g in part["groups"]:
                        if g["presentation"] == "true_false_not_given":
                            for it in g["items"]:
                                self.assertEqual([o["text"] for o in it["options"]], ["True", "False", "Not Given"])

    def test_assessment_uses_only_its_level(self):
        level_dir = self.bank / "assessment" / "B1"
        for skill in ("listening", "reading"):
            for p in sorted((self.bank / skill).glob("*/part.json"))[:5]:
                part = json.loads(p.read_text(encoding="utf-8"))
                part["profile"] = "level_b1"
                out = level_dir / skill / part["id"]
                out.mkdir(parents=True)
                (out / "part.json").write_text(json.dumps(part), encoding="utf-8")
        s = api.Settings(bank_dir=self.bank, exams_dir=self.exams, statuses=["validated"])
        pub = api.start_exam({"mode": "assessment", "level": "B1", "listening": 2, "reading": 2}, s)
        self.assertEqual((pub["mode"], pub["level"]), ("assessment", "B1"))
        key = json.loads((self.exams / f"{pub['exam_id']}.json").read_text())["key"]
        res = api.submit_exam(pub["exam_id"], {"answers": {k: v["answer"] for k, v in key.items()}}, s)
        self.assertTrue(res["assessment"]["passed"])
        with self.assertRaises(api.ApiError) as cm:
            api.start_exam({"mode": "assessment", "level": "C2"}, s)  # no C2 folder -> not enough parts
        self.assertIn(cm.exception.status, (409, 500))
        with self.assertRaises(api.ApiError) as cm:
            api.start_exam({"mode": "assessment", "level": "Z9"}, s)
        self.assertEqual(cm.exception.status, 422)


class EvaluateTests(Base):
    def setUp(self):
        super().setUp()
        _, self.st = assemble(self.bank, 4, 4)

    def test_all_correct(self):
        r = evaluate(self.st, {k: v["answer"] for k, v in self.st["key"].items()})
        self.assertEqual(r["total"]["correct"], 32)
        self.assertEqual(r["total"]["percent"], 100.0)

    def test_all_wrong_and_unanswered(self):
        wrong = {k: ("A" if v["answer"] != "A" else "B") for k, v in self.st["key"].items()}
        self.assertEqual(evaluate(self.st, wrong)["total"]["correct"], 0)
        r = evaluate(self.st, {})
        self.assertEqual((r["total"]["correct"], r["total"]["answered"], r["total"]["total"]), (0, 0, 32))

    def test_breakdowns_add_up(self):
        r = evaluate(self.st, {k: v["answer"] for k, v in self.st["key"].items()})
        self.assertEqual(sum(b["total"] for b in r["by_level"].values()), 32)
        self.assertEqual(sum(b["total"] for b in r["by_skill"].values()), 32)
        self.assertEqual(r["indicative_level"]["overall"], "C1")  # demo clones contain no C2 items
        self.assertIn("grammar:conditionals_unreal", r["by_language_focus"])

    def test_level_rule_stops_at_first_failure(self):
        # answer everything correctly except B1 items -> level must stop at A2
        ans = {k: (v["answer"] if v["cefr"] != "B1" else "D") for k, v in self.st["key"].items()}
        self.assertEqual(evaluate(self.st, ans)["indicative_level"]["overall"], "A2")

    def test_unknown_item_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(self.st, {"NOPE-Q01": "A"})


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        # demo bank = 4-item clones: cannot satisfy the production blueprint, so plumbing tests opt out explicitly (blueprint is tested in tests/test_qa.py)
        self.s = api.Settings(bank_dir=self.bank, exams_dir=self.exams, statuses=["validated", "reviewed", "approved"], enforce_blueprint=False)

    def test_flow_and_single_submission(self):
        pub = api.start_exam({"listening": 2, "reading": 1}, self.s)
        key = json.loads((self.exams / f"{pub['exam_id']}.json").read_text())["key"]
        res = api.submit_exam(pub["exam_id"], {"answers": {k: v["answer"] for k, v in key.items()}}, self.s)
        self.assertEqual(res["total"]["percent"], 100.0)
        with self.assertRaises(api.ApiError) as cm:
            api.submit_exam(pub["exam_id"], {"answers": {}}, self.s)
        self.assertEqual(cm.exception.status, 409)

    def test_validation_errors(self):
        pub = api.start_exam({}, self.s)
        for exam_id, payload, status in [
            ("../etc/passwd", {"answers": {}}, 400),
            ("0" * 32, {"answers": {}}, 404),
            (pub["exam_id"], {"answers": {"x": "Z"}}, 422),
            (pub["exam_id"], {"answers": {"UNKNOWN-Q01": "A"}}, 422),
            (pub["exam_id"], {"nope": 1}, 422),
        ]:
            with self.assertRaises(api.ApiError) as cm:
                api.submit_exam(exam_id, payload, self.s)
            self.assertEqual(cm.exception.status, status, (exam_id, payload))

    def test_start_validation(self):
        for bad in ({"listening": "4"}, {"listening": -1}, {"reading": 99}, {"reading": True}):
            with self.assertRaises(api.ApiError) as cm:
                api.start_exam(bad, self.s)
            self.assertEqual(cm.exception.status, 422)
        with self.assertRaises(api.ApiError) as cm:
            api.start_exam({"listening": 7}, self.s)
        self.assertEqual(cm.exception.status, 409)


class HttpTests(Base):
    """Real HTTP round trip against the stdlib server (same endpoints as the FastAPI app)."""

    def setUp(self):
        super().setUp()
        s = api.Settings(bank_dir=self.bank, exams_dir=self.exams, statuses=["validated", "reviewed", "approved"], enforce_blueprint=False)
        self.srv = serve(0, s)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_endpoints(self):
        code, body = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Placement test", body)
        self.assertEqual(self.call("/api/health")[0], 200)
        code, body = self.call("/api/exam/start", {})
        self.assertEqual(code, 200)
        pub = json.loads(body)
        key = json.loads((self.exams / f"{pub['exam_id']}.json").read_text())["key"]
        code, body = self.call(f"/api/exam/{pub['exam_id']}/submit", {"answers": {k: "A" for k in key}})
        self.assertEqual(code, 200)
        self.assertIn("by_level", json.loads(body))
        self.assertEqual(self.call(f"/api/exam/{pub['exam_id']}/submit", {"answers": {}})[0], 409)
        self.assertEqual(self.call("/api/nothing")[0], 404)


if __name__ == "__main__":
    unittest.main()
