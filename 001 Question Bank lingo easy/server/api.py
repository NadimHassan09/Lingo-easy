"""
Framework-free API logic. Both server/app.py (FastAPI) and server/dev_server.py (stdlib) call these.

Settings come from environment variables (all optional):
  LINGO_BANK_DIR        default: <root>/question_bank   (contains placement_test/ and assessment_test/<LEVEL>/, see assembler/layout.py)
  LINGO_EXAMS_DIR       default: <root>/exams
  LINGO_STATUSES        comma list overriding blueprint.assembler.allowed_statuses, e.g. "reviewed,approved"
  LINGO_REVEAL_ANSWERS  "1" to include the per-item review (correct answers) in submit results (dev only)
  LINGO_TRANSCRIPT_TOGGLE  "0" = never send the listening transcript when the part has audio (use for real assessments); default "1" = dev toggle button
"""
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from assembler.assemble import ShortageError, assemble, load_blueprint
from assembler.blueprint import BlueprintError
from adaptive.attempts import build_attempt_records, load_sidecars, write_attempt
from assembler.bank import BankError, load_bank
from assembler.evaluate import evaluate
from assembler.layout import scope_dir

ROOT = Path(__file__).resolve().parent.parent
EXAM_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_PARTS_PER_SKILL = 8
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
ASSESSMENT_PASS_MARK = 60.0  # percent correct; prototype value


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Settings:
    bank_dir: Path
    exams_dir: Path
    statuses: list
    reveal_answers: bool = False
    enforce_blueprint: bool = True  # False only for plumbing tests that use tiny demo banks
    transcript_toggle: bool = True  # dev/review aid: send the listening transcript behind a show/hide button; False = never sent when audio exists (real assessment)

    @classmethod
    def from_env(cls):
        statuses = os.environ.get("LINGO_STATUSES")
        return cls(
            bank_dir=Path(os.environ.get("LINGO_BANK_DIR", ROOT / "question_bank")),
            exams_dir=Path(os.environ.get("LINGO_EXAMS_DIR", ROOT / "exams")),
            statuses=[s.strip() for s in statuses.split(",") if s.strip()] if statuses
            else load_blueprint()["assembler"]["allowed_statuses"],
            reveal_answers=os.environ.get("LINGO_REVEAL_ANSWERS") == "1",
            enforce_blueprint=os.environ.get("LINGO_ENFORCE_BLUEPRINT", "1") != "0",
            transcript_toggle=os.environ.get("LINGO_TRANSCRIPT_TOGGLE", "1") != "0",
        )


def health(settings):
    return {"status": "ok", "bank_dir": str(settings.bank_dir), "allowed_statuses": settings.statuses}


def _assessment_dir(settings, level):
    return scope_dir(settings.bank_dir, "assessment", level)


def _placement_dir(settings):
    return scope_dir(settings.bank_dir, "placement")


def bank_stats(settings):
    bank, skipped = load_bank(_placement_dir(settings), settings.statuses)
    assessment = {}
    for level in LEVELS:
        if _assessment_dir(settings, level).is_dir():
            lb, sk = load_bank(_assessment_dir(settings, level), settings.statuses)
            assessment[level] = {s: len(p) for s, p in lb.items()}
            skipped += sk
    return {
        "assessment_usable_parts": assessment,
        "usable_parts": {s: len(p) for s, p in bank.items()},
        "by_profile": {s: _count(p["profile"] for p in parts) for s, parts in bank.items()},
        "skipped": [{"file": f, "reason": r} for f, r in skipped],
    }


def _count(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _count_param(payload, name):
    v = (payload or {}).get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not (0 <= v <= MAX_PARTS_PER_SKILL):
        raise ApiError(422, f"'{name}' must be an integer between 0 and {MAX_PARTS_PER_SKILL}")
    return v


def start_exam(payload, settings):
    """Assemble + store a new exam; return the PUBLIC version (no answers).

    payload: {"mode": "placement" | "assessment", "level": "A1".."C2" (assessment only),
              "listening": n, "reading": n, "writing": n, "speaking": n}   (all optional; default is a placement test with all four skills)
    """
    listening, reading = _count_param(payload, "listening"), _count_param(payload, "reading")
    writing, speaking = _count_param(payload, "writing"), _count_param(payload, "speaking")
    mode = (payload or {}).get("mode") or "placement"
    if mode not in ("placement", "assessment"):
        raise ApiError(422, "'mode' must be 'placement' or 'assessment'")
    level = (payload or {}).get("level")
    bank_dir = _placement_dir(settings)
    if mode == "assessment":
        if level not in LEVELS:
            raise ApiError(422, f"assessment needs 'level' to be one of {', '.join(LEVELS)}")
        bank_dir = _assessment_dir(settings, level)
    else:
        level = None
    try:
        public, _ = assemble(bank_dir, listening, reading, allowed_statuses=settings.statuses,
                             exams_dir=settings.exams_dir, level=level, enforce_blueprint=settings.enforce_blueprint,
                             writing=writing, speaking=speaking, include_transcript=settings.transcript_toggle)
    except ShortageError as e:
        raise ApiError(409, str(e))
    except BlueprintError as e:
        raise ApiError(409, e.to_dict())
    except BankError as e:
        raise ApiError(500, f"question bank problem: {e}")
    return public


def _exam_path(exam_id, settings):
    if not isinstance(exam_id, str) or not EXAM_ID_RE.match(exam_id):
        raise ApiError(400, "invalid exam id")
    return settings.exams_dir / f"{exam_id}.json"


_SIDE = {}


def _sidecars():
    if "v" not in _SIDE:
        _SIDE["v"] = load_sidecars(ROOT)
    return _SIDE["v"]


MAX_RESPONSE_CHARS = 20000
INPUT_METHODS = {"writing": ("typed_text",), "speaking": ("manual_transcript",)}  # "stt_transcript" is reserved for the future audio pipeline


def _clean_responses(raw, stored):
    """Validate Writing/Speaking responses: {"<part_id>": {"text": str, "input_method": optional}} (a bare string is accepted as text)."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ApiError(422, "'responses' must be an object keyed by part id")
    tasks = stored.get("tasks") or {}
    clean = {}
    for pid, r in raw.items():
        if pid not in tasks:
            raise ApiError(422, f"unknown writing/speaking part: {str(pid)[:20]}")
        text = r.get("text") if isinstance(r, dict) else r
        if text is None:
            continue
        if not isinstance(text, str) or len(text) > MAX_RESPONSE_CHARS:
            raise ApiError(422, f"response for {pid} must be text of at most {MAX_RESPONSE_CHARS} characters")
        skill = tasks[pid]["skill"]
        method = (r.get("input_method") if isinstance(r, dict) else None) or INPUT_METHODS[skill][0]
        if method not in INPUT_METHODS[skill]:
            raise ApiError(422, f"input_method '{str(method)[:30]}' is not available for {skill} in this version (allowed: {', '.join(INPUT_METHODS[skill])})")
        clean[pid] = {"text": text, "input_method": method}
    return clean


def build_productive_records(stored, responses, learner_id, submitted_at):
    """One record per Writing/Speaking task of the exam, matching schemas/productive_attempt.schema.json (stored outside the bank).

    Unanswered tasks are recorded with empty text so a later evaluator can tell skipped from missing. No audio, STT or evaluation data is fabricated:
    speaking text is labelled transcript_source 'manual_entry'; 'stt' is reserved for the future audio pipeline.
    """
    records = []
    for pid, t in (stored.get("tasks") or {}).items():
        r = responses.get(pid, {"text": "", "input_method": INPUT_METHODS[t["skill"]][0]})
        rec = {"attempt_id": stored["exam_id"] + ":" + pid, "learner_id": learner_id, "exam_id": stored["exam_id"], "part_id": pid, "part_uuid": t["part_uuid"],
               "part_version": t["part_version"], "part_content_hash": t["part_content_hash"], "skill": t["skill"], "target_cefr": t["target_cefr"],
               "task_type": t["task_type"], "primary_subskill": t["primary_subskill"], "mode": stored.get("mode"), "level": stored.get("level"),
               "response_modality": "typed_text", "response_text": r["text"], "word_count": len(r["text"].split()), "input_method": r["input_method"],
               "submitted_at": submitted_at, "evaluation_status": "not_evaluated"}
        if t["skill"] == "speaking":
            rec["transcript_source"] = "manual_entry"
        records.append(rec)
    return records


PART_ID_RE = re.compile(r"^[A-Z]{2}[0-9]{3,4}$")


def audio_file_for(exam_id, part_id, settings):
    """Resolve the mp3 of a listening part that belongs to this exam. Returns (Path, content_type). Clients only name exam and part; the file name comes from the stored exam."""
    path = _exam_path(exam_id, settings)
    if not path.exists():
        raise ApiError(404, "exam not found")
    if not isinstance(part_id, str) or not PART_ID_RE.match(part_id):
        raise ApiError(400, "invalid part id")
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    entry = next((p for p in stored["parts"] if p["part_id"] == part_id and p["skill"] == "listening"), None)
    audio = (entry or {}).get("audio") or {}
    if not entry or not audio.get("available") or not audio.get("file"):
        raise ApiError(404, "no audio for this part")
    folder = (scope_dir(settings.bank_dir, stored["mode"], stored.get("level")) / "listening" / part_id).resolve()
    target = (folder / audio["file"]).resolve()
    if folder not in target.parents or not target.is_file():
        raise ApiError(404, "audio file not found")
    return target, "audio/mpeg"


def submit_exam(exam_id, payload, settings):
    path = _exam_path(exam_id, settings)
    if not path.exists():
        raise ApiError(404, "exam not found")
    result_path = path.with_name(f"{exam_id}.result.json")
    if result_path.exists():
        raise ApiError(409, "this exam was already submitted")

    answers = (payload or {}).get("answers")
    if answers is None and (payload or {}).get("responses") is not None:
        answers = {}
    if not isinstance(answers, dict):
        raise ApiError(422, "body must be {\"answers\": {\"<item_id>\": \"A\"}, \"responses\": {\"<part_id>\": {\"text\": \"...\"}}}")
    clean = {}
    for item_id, choice in answers.items():
        if choice in (None, ""):
            continue
        if choice not in ("A", "B", "C", "D"):
            raise ApiError(422, f"invalid choice for {item_id}: must be A, B, C or D")
        clean[item_id] = choice

    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    responses = _clean_responses((payload or {}).get("responses"), stored)
    try:
        result = evaluate(stored, clean, include_review=settings.reveal_answers)
    except ValueError as e:
        raise ApiError(422, str(e))
    result["mode"] = stored.get("mode", "placement")
    if result["mode"] == "assessment":
        pct = result["total"]["percent"] or 0.0
        result["assessment"] = {"level": stored.get("level"), "percent": pct,
                                "pass_mark": ASSESSMENT_PASS_MARK, "passed": pct >= ASSESSMENT_PASS_MARK}
    result["submitted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = build_productive_records(stored, responses, learner_id=str((payload or {}).get("learner_id") or "anonymous")[:64], submitted_at=result["submitted_at"])
    result["productive"] = {
        "tasks": len(stored.get("tasks") or {}),
        "responses_received": sum(1 for r in records if r["response_text"].strip()),
        "evaluation": "not_evaluated",
        "note": "Writing and Speaking responses are stored for a future evaluation pipeline. They are not scored in this version, "
                "and Speaking responses are typed text (no audio was recorded or analysed).",
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({**result, "answers": clean, "responses": {r["part_id"]: {"text": r["response_text"], "input_method": r["input_method"]} for r in records}},
                  f, ensure_ascii=False, indent=2)
    if records:
        try:
            with open(path.with_name(f"{exam_id}.responses.json"), "w", encoding="utf-8") as f:
                json.dump({"exam_id": exam_id, "records": records}, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
    try:  # attempt records are separate from the bank and must never break scoring
        meta, diag = _sidecars()
        learner = str((payload or {}).get("learner_id") or "anonymous")[:64]
        recs = build_attempt_records(stored, clean, meta, diag, learner_id=learner, attempt_id=exam_id, submitted_at=result["submitted_at"])
        write_attempt(path.with_name(f"{exam_id}.attempt.json"), recs)
    except Exception:  # noqa: BLE001
        pass
    return result
