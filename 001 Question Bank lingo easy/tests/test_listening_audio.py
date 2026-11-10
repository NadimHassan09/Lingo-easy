"""Listening audio: generated files, voice plan, serving over HTTP (with Range), transcript hiding."""
import hashlib
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from assembler.assemble import assemble, audio_info  # noqa: E402
from assembler.demo import build_demo_bank  # noqa: E402
from assembler.layout import iter_scopes  # noqa: E402
from server import api  # noqa: E402
from server.dev_server import serve  # noqa: E402

import generate_listening_audio as gla  # noqa: E402

BANK = ROOT / "question_bank"
CFG = json.loads((ROOT / "config" / "blueprint.json").read_text(encoding="utf-8"))
FAKE = b"ID3" + bytes(range(256)) * 40  # not real audio: only the serving path is tested


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class GeneratedAudioTests(unittest.TestCase):
    """Acceptance: every listening part (placement + A1..C2) has its mp3 in its own folder under the name part.json already declares."""

    def test_every_listening_part_has_audio_and_a_consistent_manifest(self):
        n = 0
        for name, mode, level, d in iter_scopes(BANK):
            for p in sorted((d / "listening").glob("*/part.json")):
                part = json.loads(p.read_text(encoding="utf-8"))
                mp3 = p.parent / part["audio"]["file"]
                man = p.parent / "audio-manifest.json"
                self.assertTrue(mp3.is_file(), f"missing audio for {part['id']} ({name}): run scripts/generate_listening_audio.py")
                self.assertTrue(man.is_file(), part["id"])
                m = json.loads(man.read_text(encoding="utf-8"))
                data = mp3.read_bytes()
                self.assertEqual(m["audio_file"], part["audio"]["file"])
                self.assertEqual(m["part_uuid"], part["uuid"])
                self.assertEqual(m["transcript_sha256"], sha(part["audio"]["transcript"]), f"transcript of {part['id']} changed after the audio was made")
                self.assertEqual(m["audio_sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(m["size_bytes"], len(data))
                self.assertGreater(m["duration_seconds"], 20)
                self.assertEqual(len(m["turns"]), len(part["audio"]["transcript"]))
                self.assertTrue(all(a["end"] > a["start"] for a in m["turns"]))
                self.assertEqual([t["start"] for t in m["turns"]], sorted(t["start"] for t in m["turns"]))
                self.assertTrue(data[:3] == b"ID3" or data[0] == 0xFF, part["id"])  # mp3 header
                n += 1
        self.assertEqual(n, 70)


class VoicePlanTests(unittest.TestCase):
    def test_speakers_in_a_part_always_sound_different(self):
        for name, mode, level, d in iter_scopes(BANK):
            for p in sorted((d / "listening").glob("*/part.json")):
                part = json.loads(p.read_text(encoding="utf-8"))
                plan, preset, rate = gla.voice_plan(part, CFG)
                pairs = [(v["voice"], v["pitch"]) for v in plan.values()]
                self.assertEqual(len(pairs), len(set(pairs)), part["id"])
                self.assertEqual(set(plan), {s["id"] for s in part["audio"]["speakers"]})
                self.assertIn(preset, ("easy", "medium", "hard"))
                for s in part["audio"]["speakers"]:
                    self.assertTrue(plan[s["id"]]["voice"].startswith({"american": "en-US", "british": "en-GB", "australian": "en-AU", "new_zealand": "en-NZ"}[s["accent"]]))

    def test_pace_follows_level(self):
        rates = {}
        for lv in ("A1", "B2", "C2"):
            p = next((BANK / "assessment_test" / lv / "listening").glob("*/part.json"))
            rates[lv] = gla.voice_plan(json.loads(p.read_text(encoding="utf-8")), CFG)[2]
        self.assertEqual(rates, {"A1": "-12%", "B2": "-5%", "C2": "+0%"})


class ServingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = build_demo_bank(t / "bank", n_each=6)
        self.exams = t / "exams"
        scope = self.root / "placement_test" / "listening"
        self.with_audio = []
        for i, d in enumerate(sorted(scope.iterdir())):
            part = json.loads((d / "part.json").read_text(encoding="utf-8"))
            if i < 3:  # first three parts get audio, the rest do not
                (d / part["audio"]["file"]).write_bytes(FAKE)
                self.with_audio.append(part["id"])
        self.s = api.Settings(bank_dir=self.root, exams_dir=self.exams, statuses=["validated"], enforce_blueprint=False)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, settings=None, **kw):
        s = settings or self.s
        pub = api.start_exam(dict({"listening": 6, "reading": 1}, **kw), s)
        return pub, s

    def listening_parts(self, pub):
        return [p for sec in pub["sections"] if sec["skill"] == "listening" for p in sec["parts"]]

    def test_public_exam_marks_audio_and_offers_transcript_toggle(self):
        pub, _ = self.start()
        for p in self.listening_parts(pub):
            has = p["part_id"] in self.with_audio
            self.assertEqual(p["text"]["audio"]["available"], has)
            self.assertEqual(p["text"]["transcript_toggle"], has)
            self.assertIn("turns", p["text"])  # dev mode: the transcript travels with the part, the UI hides it
            self.assertNotIn(".mp3", json.dumps(p))  # no file name or path leaks

    def test_real_assessment_mode_never_sends_the_transcript_when_audio_exists(self):
        s = api.Settings(bank_dir=self.root, exams_dir=self.exams, statuses=["validated"], enforce_blueprint=False, transcript_toggle=False)
        pub, _ = self.start(s)
        for p in self.listening_parts(pub):
            if p["part_id"] in self.with_audio:
                self.assertNotIn("turns", p["text"])
                self.assertFalse(p["text"]["transcript_toggle"])
            else:
                self.assertIn("turns", p["text"])  # no audio -> transcript stays, otherwise the part could not be answered

    def test_audio_endpoint_only_serves_audio_of_parts_in_the_exam(self):
        pub, s = self.start()
        pid = next(p["part_id"] for p in self.listening_parts(pub) if p["part_id"] in self.with_audio)
        path, ctype = api.audio_file_for(pub["exam_id"], pid, s)
        self.assertEqual(ctype, "audio/mpeg")
        self.assertEqual(path.read_bytes(), FAKE)
        no_audio = next(p["part_id"] for p in self.listening_parts(pub) if p["part_id"] not in self.with_audio)
        for exam_id, part_id, status in [(pub["exam_id"], no_audio, 404), (pub["exam_id"], "LI999", 404), (pub["exam_id"], "../../part", 400),
                                         (pub["exam_id"], "RE101", 404), ("0" * 32, pid, 404), ("../x", pid, 400)]:
            with self.assertRaises(api.ApiError) as cm:
                api.audio_file_for(exam_id, part_id, s)
            self.assertEqual(cm.exception.status, status, (exam_id, part_id))

    def test_http_full_and_range_requests(self):
        pub, s = self.start()
        pid = next(p["part_id"] for p in self.listening_parts(pub) if p["part_id"] in self.with_audio)
        srv = serve(0, s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}/api/exam/{pub['exam_id']}/audio/{pid}"
        try:
            with urllib.request.urlopen(url) as r:
                self.assertEqual((r.status, r.headers["Content-Type"], r.headers["Accept-Ranges"]), (200, "audio/mpeg", "bytes"))
                self.assertEqual(r.read(), FAKE)
            req = urllib.request.Request(url, headers={"Range": "bytes=100-199"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(r.status, 206)
                self.assertEqual(r.headers["Content-Range"], f"bytes 100-199/{len(FAKE)}")
                self.assertEqual(r.read(), FAKE[100:200])
            req = urllib.request.Request(url, headers={"Range": "bytes=-50"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(r.read(), FAKE[-50:])
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=999999-"}))
            self.assertEqual(cm.exception.code, 416)
            bad = f"http://127.0.0.1:{srv.server_address[1]}/api/exam/{pub['exam_id']}/audio/LI999"
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(bad)
            self.assertEqual(cm.exception.code, 404)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_audio_info_requires_the_file_next_to_part_json(self):
        scope = self.root / "placement_test"
        p0 = json.loads(next((scope / "listening").glob("*/part.json")).read_text(encoding="utf-8"))
        self.assertTrue(audio_info(scope, p0)["available"])
        (scope / "listening" / p0["id"] / p0["audio"]["file"]).unlink()
        self.assertFalse(audio_info(scope, p0)["available"])


class ScriptTests(unittest.TestCase):
    def test_dry_run_and_cli_selection(self):
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_listening_audio.py"), "--dry-run", "--only", "LI001", "LI601"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("LI001", r.stdout)
        self.assertIn("LI601", r.stdout)
        self.assertNotIn("LI002", r.stdout)

    def test_part_json_untouched_by_audio_generation(self):
        # audio.file was the reference all along; the pattern is the one the schema demands
        import re
        for name, mode, level, d in iter_scopes(BANK):
            for p in (d / "listening").glob("*/part.json"):
                f = json.loads(p.read_text(encoding="utf-8"))["audio"]["file"]
                self.assertRegex(f, re.compile(r"^[a-z]{2}[0-9]{3,4}_[a-z0-9_]+\.mp3$"))


if __name__ == "__main__":
    unittest.main()
