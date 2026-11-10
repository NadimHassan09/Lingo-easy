"""
Framework-free API logic. Both server/app.py (FastAPI) and server/dev_server.py (stdlib) call these.

Settings come from environment variables (all optional):
  LINGO_BANK_DIR        default: <root>/question_bank
  LINGO_EXAMS_DIR       default: <root>/exams
  LINGO_STATUSES        comma list overriding blueprint.assembler.allowed_statuses, e.g. "reviewed,approved"
  LINGO_REVEAL_ANSWERS  "1" to include the per-item review (correct answers) in submit results (dev only)
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
        )


def health(settings):
    return {"status": "ok", "bank_dir": str(settings.bank_dir), "allowed_statuses": settings.statuses}


def _assessment_dir(settings, level):
    return settings.bank_dir / "assessment" / level


def bank_stats(settings):
    bank, skipped = load_bank(settings.bank_dir, settings.statuses)
    assessment = {}
    for level in LEVELS:
        if _assessment_dir(settings, level).is_dir():
            lb, _ = load_bank(_assessment_dir(settings, level), settings.statuses)
            assessment[level] = {s: len(p) for s, p in lb.items()}
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
              "listening": n, "reading": n}   (all optional; default is a placement test)
    """
    listening, reading = _count_param(payload, "listening"), _count_param(payload, "reading")
    mode = (payload or {}).get("mode") or "placement"
    if mode not in ("placement", "assessment"):
        raise ApiError(422, "'mode' must be 'placement' or 'assessment'")
    level = (payload or {}).get("level")
    bank_dir = settings.bank_dir
    if mode == "assessment":
        if level not in LEVELS:
            raise ApiError(422, f"assessment needs 'level' to be one of {', '.join(LEVELS)}")
        bank_dir = _assessment_dir(settings, level)
    else:
        level = None
    try:
        public, _ = assemble(bank_dir, listening, reading, allowed_statuses=settings.statuses,
                             exams_dir=settings.exams_dir, level=level, enforce_blueprint=settings.enforce_blueprint)
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


def submit_exam(exam_id, payload, settings):
    path = _exam_path(exam_id, settings)
    if not path.exists():
        raise ApiError(404, "exam not found")
    result_path = path.with_name(f"{exam_id}.result.json")
    if result_path.exists():
        raise ApiError(409, "this exam was already submitted")

    answers = (payload or {}).get("answers")
    if not isinstance(answers, dict):
        raise ApiError(422, "body must be {\"answers\": {\"<item_id>\": \"A\"}}")
    clean = {}
    for item_id, choice in answers.items():
        if choice in (None, ""):
            continue
        if choice not in ("A", "B", "C", "D"):
            raise ApiError(422, f"invalid choice for {item_id}: must be A, B, C or D")
        clean[item_id] = choice

    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
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
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({**result, "answers": clean}, f, ensure_ascii=False, indent=2)
    try:  # attempt records are separate from the bank and must never break scoring
        meta, diag = _sidecars()
        learner = str((payload or {}).get("learner_id") or "anonymous")[:64]
        recs = build_attempt_records(stored, clean, meta, diag, learner_id=learner, attempt_id=exam_id, submitted_at=result["submitted_at"])
        write_attempt(path.with_name(f"{exam_id}.attempt.json"), recs)
    except Exception:  # noqa: BLE001
        pass
    return result
