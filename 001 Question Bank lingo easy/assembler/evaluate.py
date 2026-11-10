"""
Score an exam attempt (pure multiple-choice matching). No dependencies.

  evaluate(stored_exam, answers)  ->  result dict

`answers` maps item id -> chosen option id ("A".."D"); missing/blank = unanswered (counts as wrong).
The answer key comes from the STORED exam, never from the bank, so results stay reproducible
even if the bank changes later.
"""
import json
from pathlib import Path

CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
ROOT = Path(__file__).resolve().parent.parent


def _threshold():
    with open(ROOT / "config" / "blueprint.json", encoding="utf-8") as f:
        return json.load(f)["scoring"]["indicative_level_threshold"]


def _bucket():
    return {"correct": 0, "total": 0}


def _finish(b):
    b["percent"] = round(100 * b["correct"] / b["total"], 1) if b["total"] else None
    return b


def indicative_level(by_level, threshold):
    """Prototype rule (see blueprint.scoring): last level passed before the first level below threshold."""
    reached = None
    for lvl in CEFR:
        b = by_level.get(lvl)
        if not b or b["total"] == 0:
            continue
        if b["correct"] / b["total"] >= threshold:
            reached = lvl
        else:
            break
    return reached or "Below A1"


def evaluate(stored, answers, include_review=False, threshold=None):
    key = stored["key"]
    threshold = _threshold() if threshold is None else threshold
    unknown = sorted(k for k in answers if k not in key)
    if unknown:
        raise ValueError(f"unknown item id(s): {', '.join(unknown[:5])}")

    total = _bucket()
    by_skill = {}
    by_level = {l: _bucket() for l in CEFR}
    by_skill_level = {}
    by_tag, by_focus, review = {}, {}, []
    answered = 0

    for item_id, k in key.items():
        given = answers.get(item_id) or None
        ok = given == k["answer"]
        if given:
            answered += 1
        targets = [total, by_level[k["cefr"]],
                   by_skill.setdefault(k["skill"], _bucket()),
                   by_skill_level.setdefault(k["skill"], {l: _bucket() for l in CEFR})[k["cefr"]]]
        if k.get("skill_tag"):
            targets.append(by_tag.setdefault(f"{k['skill']}:{k['skill_tag']}", _bucket()))
        lf = k.get("language_focus") or {"type": "none"}
        if lf.get("type") == "grammar":
            targets.append(by_focus.setdefault(f"grammar:{lf.get('rule')}", _bucket()))
        elif lf.get("type") == "vocabulary":
            targets.append(by_focus.setdefault(f"vocabulary:{lf.get('lexical_type')}", _bucket()))
        for t in targets:
            t["total"] += 1
            t["correct"] += 1 if ok else 0
        if include_review:
            review.append({"item_id": item_id, "your_answer": given, "correct_answer": k["answer"], "correct": ok})

    result = {
        "exam_id": stored["exam_id"],
        "total": {**_finish(total), "answered": answered},
        "by_skill": {s: _finish(b) for s, b in by_skill.items()},
        "by_level": {l: _finish(b) for l, b in by_level.items()},
        "by_skill_level": {s: {l: _finish(b) for l, b in lv.items()} for s, lv in by_skill_level.items()},
        "by_skill_tag": {k: _finish(b) for k, b in sorted(by_tag.items())},
        "by_language_focus": {k: _finish(b) for k, b in sorted(by_focus.items())},
        "indicative_level": {
            "overall": indicative_level(by_level, threshold),
            **{s: indicative_level({l: lv[l] for l in CEFR}, threshold) for s, lv in by_skill_level.items()},
            "rule": f"prototype: last CEFR level with >= {int(threshold * 100)}% correct before the first level below it",
        },
    }
    if include_review:
        result["review"] = review
    return result
