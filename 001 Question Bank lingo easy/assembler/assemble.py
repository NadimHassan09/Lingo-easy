"""
Assemble a placement exam from the question bank.

  python -m assembler.assemble --listening 4 --reading 4 [--bank question_bank] [--seed 123]

Rules
- Only parts whose meta.status is in blueprint.assembler.allowed_statuses are eligible.
- Never invents content. If the bank cannot satisfy the request -> ShortageError (no partial exam).
- Parts are picked without repeats, preferring the profile in blueprint.assembler.profile_cycle,
  then a part_type and topic not used yet in the same skill.
- The PUBLIC exam (sent to the learner) contains no answers, explanations, evidence or level metadata.
- The STORED exam (exams/<exam_id>.json) holds the answer key + the exact parts used, so every
  attempt can be reproduced and audited.
"""
import argparse
import copy
import json
import os
import random
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .bank import BankError, load_bank
from .layout import MCQ_SKILLS, PRODUCTIVE_SKILLS, SKILLS
from .blueprint import BlueprintError, exam_type_for, load_blueprint as load_exam_blueprint, load_meta, validate_exam, DEFAULT_BLUEPRINT

ROOT = Path(__file__).resolve().parent.parent


class ShortageError(Exception):
    """The bank cannot satisfy the requested blueprint."""


def load_blueprint():
    with open(ROOT / "config" / "blueprint.json", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------- selection
def select_parts(candidates, n, profile_cycle, rng):
    chosen, notes = [], []
    used_types, used_topics = set(), set()
    for i in range(n):
        want = profile_cycle[i % len(profile_cycle)]
        pool = [p for p in candidates if p["id"] not in {c["id"] for c in chosen}]

        def score(p):
            return (4 if p["profile"] == want else 0) + (2 if p["part_type"] not in used_types else 0) \
                + (1 if p.get("topic") not in used_topics else 0)

        best = max(score(p) for p in pool)
        pick = rng.choice([p for p in pool if score(p) == best])
        if pick["profile"] != want:
            notes.append(f"slot {i + 1}: wanted profile '{want}', used '{pick['profile']}' (none left)")
        chosen.append(pick)
        used_types.add(pick["part_type"])
        used_topics.add(pick.get("topic"))
    return chosen, notes


# ----------------------------------------------------------------------------- views
def _speaker_label(sp):
    return f"{sp['name']} ({sp['role']})" if sp.get("role") else sp["name"]


PUBLIC_TASK_KEYS = {
    "writing": ("title", "scenario", "prompt", "instructions", "required_points", "audience", "register", "word_count", "suggested_minutes", "stimulus"),
    "speaking": ("title", "format", "scenario", "prompt", "instructions", "main_question", "follow_up_questions", "cue_card", "preparation_seconds",
                 "suggested_speaking_seconds", "typed_response_words"),
}


def public_productive_part(part):
    """Learner-facing view of a Writing/Speaking task. Drops CEFR level, rubric, diagnostics, outlines, provenance and uuids."""
    task = {k: part["task"][k] for k in PUBLIC_TASK_KEYS[part["skill"]] if k in part["task"]}
    return {"part_id": part["id"], "skill": part["skill"], "title": part["title"], "kind": part["skill"] + "_task", "task": task, "groups": [],
            "response": {"type": "text", "modality": "typed_text", "future": ["audio", "stt_transcript"]}}


def select_productive(candidates, n, rng, mode):
    """Placement: one task from each of n contiguous level strata (spreads evidence over A1-C2), shown easiest first.
    Assessment: n random tasks with distinct topics where possible (all candidates already share the target level)."""
    if n <= 0:
        return []
    order = ["A1", "A2", "B1", "B2", "C1", "C2"]
    pool = sorted(candidates, key=lambda p: (order.index(p["target_cefr"]), p["id"]))
    if mode == "placement":
        size = len(pool) / n
        chosen, topics = [], set()
        for i in range(n):
            stratum = pool[int(round(i * size)):int(round((i + 1) * size))]
            fresh = [p for p in stratum if p.get("topic") not in topics] or stratum
            pick = rng.choice(fresh)
            chosen.append(pick)
            topics.add(pick.get("topic"))
        return chosen
    chosen, topics = [], set()
    for _ in range(n):
        rest = [p for p in pool if p not in chosen]
        fresh = [p for p in rest if p.get("topic") not in topics] or rest
        pick = rng.choice(fresh)
        chosen.append(pick)
        topics.add(pick.get("topic"))
    return chosen


def productive_problems(parts, mode, level, n_by_skill):
    """Hard checks on the selected Writing/Speaking tasks (the productive part of the blueprint)."""
    bad = []
    for sk in PRODUCTIVE_SKILLS:
        ps = [p for p in parts if p["skill"] == sk]
        if len(ps) != n_by_skill.get(sk, 0):
            bad.append({"code": "part_count", "constraint": sk, "observed": len(ps), "required": n_by_skill.get(sk, 0)})
        if len({p["id"] for p in ps}) != len(ps):
            bad.append({"code": "duplicate_sources", "constraint": sk, "observed": len(ps), "required": "unique"})
        if mode == "assessment" and any(p["target_cefr"] != level for p in ps):
            bad.append({"code": "target_level", "constraint": sk, "observed": [p["target_cefr"] for p in ps], "required": level})
        if mode == "placement" and len(ps) >= 2 and len({p["target_cefr"] for p in ps}) < 2:
            bad.append({"code": "placement_level_spread", "constraint": sk, "observed": [p["target_cefr"] for p in ps], "required": ">= 2 distinct levels"})
    return bad


def audio_info(scope_dir, part):
    """Does the listening part have its mp3 (named by audio.file) in its own folder? Returns {file, available, duration_seconds}."""
    f = (part.get("audio") or {}).get("file")
    folder = Path(scope_dir) / "listening" / part["id"]
    ok = bool(f) and (folder / f).is_file()
    dur = None
    if ok and (folder / "audio-manifest.json").is_file():
        try:
            dur = json.loads((folder / "audio-manifest.json").read_text(encoding="utf-8")).get("duration_seconds")
        except (OSError, ValueError):
            dur = None
    return {"file": f, "available": ok, "duration_seconds": dur}


def public_part(part, audio=None, exam_id=None, include_transcript=True):
    """What the learner may see. Deliberately drops answer, explanation, evidence, level, tags, uuids.

    Listening: when the mp3 exists the part carries an audio url and (only if include_transcript) the transcript turns, which the UI hides behind a
    show/hide button. Without audio the transcript is always included so the part stays answerable."""
    if part["skill"] in PRODUCTIVE_SKILLS:
        return public_productive_part(part)
    out = {"part_id": part["id"], "skill": part["skill"], "title": part["title"]}
    if part["skill"] == "listening":
        names = {s["id"]: _speaker_label(s) for s in part["audio"]["speakers"]}
        has_audio = bool(audio and audio.get("available") and exam_id)
        text = {"kind": "transcript",
                "audio": {"available": has_audio,  # the client fetches GET /api/exam/<exam_id>/audio/<part_id>
                          "duration_seconds": audio.get("duration_seconds") if audio else None},
                "transcript_toggle": bool(has_audio and include_transcript)}
        if not has_audio or include_transcript:
            text["turns"] = [{"speaker": names.get(t["speaker"], t["speaker"]), "text": t["text"]} for t in part["audio"]["transcript"]]
        out["text"] = text
    else:
        out["text"] = {"kind": "passage", "title": part["passage"].get("title", part["title"]),
                       "paragraphs": [{"label": p["label"], "text": p["text"]} for p in part["passage"]["paragraphs"]]}
    out["groups"] = []
    for g in part["question_groups"]:
        out["groups"].append({
            "id": g["id"],
            "presentation": g["presentation"],
            "instruction": g["instruction"],
            "context": g.get("context", ""),
            "items": [{"id": it["id"], "number": it["number"], "prompt": it["prompt"],
                       "options": [{"id": o["id"], "text": o["text"]} for o in it["options"]]}
                      for it in g["items"]],
        })
    return out


def answer_key(parts):
    key = {}
    for part in parts:
        for g in part["question_groups"]:
            for it in g["items"]:
                if it["id"] in key:
                    raise BankError(f"duplicate item id {it['id']} across selected parts")
                key[it["id"]] = {
                    "answer": it["answer"],
                    "part_id": part["id"],
                    "skill": part["skill"],
                    "cefr": it["level"]["cefr"],
                    "band": it["level"]["band"],
                    "skill_tag": it.get("skill_tag"),
                    "question_uuid": it.get("uuid"),
                    "part_uuid": part.get("uuid"),
                    "part_content_hash": (part.get("derived") or {}).get("content_hash"),
                    "option_origin": it.get("option_origin") or {o["id"]: o["id"] for o in it["options"]},
                    "shown_options": {o["id"]: o["text"] for o in it["options"]},
                    "language_focus": it.get("language_focus", {"type": "none"}),
                }
    return key


# ----------------------------------------------------------------------------- main entry
SHUFFLE_OPTIONS = ("multiple_choice", "sentence_completion", "summary_completion")


def shuffle_options(part, rng):
    """Copy of the part with the option order of plain choice items shuffled and re-lettered A, B, C...

    True/False/Not Given, Yes/No/Not Given and matching groups keep their natural order.
    """
    part = copy.deepcopy(part)
    for g in part["question_groups"]:
        if g["presentation"] not in SHUFFLE_OPTIONS:
            continue
        for it in g["items"]:
            right = next(o["text"] for o in it["options"] if o["id"] == it["answer"])
            origin = {o["text"]: o["id"] for o in it["options"]}
            texts = [o["text"] for o in it["options"]]
            rng.shuffle(texts)
            it["options"] = [{"id": "ABCD"[k], "text": x} for k, x in enumerate(texts)]
            it["answer"] = "ABCD"[texts.index(right)]
            it["option_origin"] = {"ABCD"[k]: origin[x] for k, x in enumerate(texts)}  # shown letter -> bank letter (for diagnostics)
    return part


def assemble(bank_dir, listening=None, reading=None, allowed_statuses=None, seed=None, exams_dir=None, level=None,
             enforce_blueprint=True, blueprint_path=None, meta=None, writing=None, speaking=None, include_transcript=True):
    """Return (public_exam, stored_exam). Writes the stored exam when exams_dir is given.

    bank_dir is one SCOPE (see assembler/layout.py): question_bank/placement_test, or question_bank/assessment_test/<LEVEL>.
    level=None  -> placement test: parts of every profile, profile_cycle from the blueprint.
    level="B1"  -> assessment test: bank_dir must be the level folder (question_bank/assessment_test/B1);
                   only parts of profile level_b1 are used.
    Writing/Speaking: n tasks per skill (blueprint skills.<skill>.parts_per_test when None). If the scope has no part of that skill at
    all and the count was not requested explicitly, the section is omitted and a selection note says so (keeps old MCQ-only banks working).
    Random per attempt: which parts, the order of parts inside each skill, and the option order of choice items.

    Blueprint: when enforce_blueprint is true, the standard part counts are requested and config/exam_blueprint_v1.json exists,
    every candidate exam is checked against the blueprint of its exam type (placement / assessment_<LEVEL>). Candidates that
    violate a hard constraint are discarded and re-drawn deterministically (attempt k uses Random(f"{seed}:{k}")). If no
    valid exam is found within max_attempts a BlueprintError (structured violation counts) is raised; constraints are never relaxed.
    """
    bp = load_blueprint()
    n_by_skill = {
        "listening": bp["skills"]["listening"]["parts_per_test"] if listening is None else listening,
        "reading": bp["skills"]["reading"]["parts_per_test"] if reading is None else reading,
    }
    explicit_productive = {"writing": writing, "speaking": speaking}
    statuses = allowed_statuses or bp["assembler"]["allowed_statuses"]
    cycle = bp["assembler"]["profile_cycle"]
    bank, skipped = load_bank(bank_dir, statuses)
    if level is not None:
        level_profile = f"level_{level.lower()}"
        cycle = [level_profile]
        bank = {s: [p for p in parts if p["profile"] == level_profile] for s, parts in bank.items()}

    dropped_notes = []
    for skill in PRODUCTIVE_SKILLS:
        want = explicit_productive[skill]
        default_n = bp.get("productive", {}).get(skill, {}).get("parts_per_test", 0)
        if isinstance(default_n, dict):
            default_n = default_n.get("assessment" if level else "placement", 0)
        n_by_skill[skill] = default_n if want is None else want
        if want is None and not bank[skill]:
            if n_by_skill[skill]:
                dropped_notes.append(f"{skill}: no {skill} parts in this bank scope, section omitted")
            n_by_skill[skill] = 0
    for skill in SKILLS:
        have, need = len(bank[skill]), n_by_skill[skill]
        if have < need:
            raise ShortageError(
                f"Bank has {have} usable {skill} part(s) but {need} are required "
                f"(allowed statuses: {', '.join(statuses)}; skipped files: {len(skipped)}).")
    if sum(n_by_skill.values()) == 0:
        raise ShortageError("Nothing requested: both counts are 0.")

    seed = secrets.randbits(32) if seed is None else int(seed)
    spec, bp_status, forbidden, max_attempts, bp_version = None, "not_enforced", [], 1, None
    bp_file = Path(blueprint_path) if blueprint_path else DEFAULT_BLUEPRINT
    if enforce_blueprint and bp_file.exists():
        bpv = load_exam_blueprint(bp_file)
        spec = bpv["exam_types"].get(exam_type_for(level))
        bp_version = bpv.get("version")
        if spec is None or {k: n_by_skill[k] for k in MCQ_SKILLS} != spec["parts"]:
            spec, bp_status = None, "skipped: custom part counts or unknown exam type"
        else:
            forbidden = [tuple(x) for x in bpv.get("forbidden_pairs", [])]
            max_attempts = bpv["assembly"]["max_attempts"]
            meta = meta if meta is not None else load_meta()
    chosen, notes, attempts, fail_counts = {}, [], 0, {}
    for k in range(max_attempts):
        attempts = k + 1
        rng = random.Random(seed) if k == 0 else random.Random(f"{seed}:{k}")
        chosen, notes = {}, list(dropped_notes)
        for skill in MCQ_SKILLS:  # fixed order => same seed gives the same exam
            chosen[skill], n = select_parts(bank[skill], n_by_skill[skill], cycle, rng)
            notes += [f"{skill}: {x}" for x in n]
            rng.shuffle(chosen[skill])
        prng = random.Random(f"{seed}:productive:{k}")  # separate stream: MCQ selection for a given seed is unchanged by Writing/Speaking
        for skill in PRODUCTIVE_SKILLS:
            chosen[skill] = select_productive(bank[skill], n_by_skill[skill], prng, "assessment" if level else "placement")
        pviol = productive_problems([p for s in PRODUCTIVE_SKILLS for p in chosen[s]], "assessment" if level else "placement", level, n_by_skill)
        if spec is None and not pviol:
            break
        viol = (validate_exam([p for s in MCQ_SKILLS for p in chosen[s]], spec, meta, forbidden) if spec is not None else []) + pviol
        if not viol:
            bp_status = "enforced"
            break
        for v in viol:
            fail_counts[v["code"]] = fail_counts.get(v["code"], 0) + 1
    else:
        raise BlueprintError("no_valid_exam", f"No exam satisfying the '{exam_type_for(level)}' blueprint was found in {max_attempts} attempts.",
                             {"exam_type": exam_type_for(level), "seed": seed, "attempts": max_attempts, "violation_counts": fail_counts,
                              "last_violations": viol})
    for skill in MCQ_SKILLS:
        chosen[skill] = [shuffle_options(p, rng) for p in chosen[skill]]

    ordered = [p for s in SKILLS for p in chosen[s]]
    mcq_ordered = [p for s in MCQ_SKILLS for p in chosen[s]]
    exam_id = uuid.uuid4().hex  # unique per attempt; the seed only fixes WHICH parts are chosen
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")

    audio_by_part = {p["id"]: audio_info(bank_dir, p) for p in chosen["listening"]}
    public = {
        "exam_id": exam_id,
        "created_at": created,
        "mode": "assessment" if level else "placement",
        "level": level,
        "sections": [{"skill": s, "parts": [public_part(p, audio_by_part.get(p["id"]), exam_id, include_transcript) for p in chosen[s]]} for s in SKILLS if chosen[s]],
    }
    stored = {
        "exam_id": exam_id,
        "created_at": created,
        "mode": "assessment" if level else "placement",
        "level": level,
        "seed": seed,
        "requested": n_by_skill,
        "allowed_statuses": statuses,
        "selection_notes": notes,
        "blueprint": {"exam_type": exam_type_for(level), "version": bp_version, "status": bp_status, "selection_attempts": attempts},
        "parts": [{"part_id": p["id"], "skill": p["skill"], "uuid": p.get("uuid"),
                   "content_hash": (p.get("derived") or {}).get("content_hash"),
                   "profile": p["profile"], "part_type": p["part_type"], "title": p["title"],
                   "status": p["meta"]["status"],
                   **({"audio": audio_by_part[p["id"]]} if p["skill"] == "listening" else {})} for p in ordered],
        "key": answer_key(mcq_ordered),
        "tasks": {p["id"]: {"skill": p["skill"], "part_uuid": p.get("uuid"), "part_version": p.get("version"),
                            "part_content_hash": (p.get("derived") or {}).get("content_hash"), "target_cefr": p["target_cefr"],
                            "task_type": p["part_type"], "primary_subskill": (p.get("classification") or {}).get("primary_subskill"),
                            "evaluation_status": "not_evaluated"}
                  for s in PRODUCTIVE_SKILLS for p in chosen[s]},
    }
    if exams_dir is not None:
        d = Path(exams_dir)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{exam_id}.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stored, f, ensure_ascii=False, indent=2)
        os.replace(tmp, d / f"{exam_id}.json")
    return public, stored


def main():
    ap = argparse.ArgumentParser(description="Assemble an exam from the question bank")
    ap.add_argument("--bank", default=str(ROOT / "question_bank"))
    ap.add_argument("--exams-dir", default=str(ROOT / "exams"))
    ap.add_argument("--listening", type=int)
    ap.add_argument("--reading", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--public", action="store_true", help="print the public exam JSON")
    args = ap.parse_args()
    try:
        public, stored = assemble(args.bank, args.listening, args.reading, seed=args.seed, exams_dir=args.exams_dir)
    except ShortageError as e:
        raise SystemExit(f"SHORTAGE: {e}")
    print(f"exam {stored['exam_id']} (seed {stored['seed']}), {len(stored['key'])} items")
    for p in stored["parts"]:
        print(f"  {p['part_id']:<7} {p['profile']:<13} {p['part_type']:<20} {p['title']}")
    for n in stored["selection_notes"]:
        print("  note:", n)
    if args.public:
        print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
