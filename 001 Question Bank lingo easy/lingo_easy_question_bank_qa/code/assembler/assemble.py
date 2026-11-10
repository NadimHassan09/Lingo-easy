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

from .bank import SKILLS, BankError, load_bank
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


def public_part(part):
    """What the learner may see. Deliberately drops answer, explanation, evidence, level, tags, uuids."""
    out = {"part_id": part["id"], "skill": part["skill"], "title": part["title"]}
    if part["skill"] == "listening":
        names = {s["id"]: _speaker_label(s) for s in part["audio"]["speakers"]}
        out["text"] = {
            "kind": "transcript",
            "audio_file": None,  # TTS step comes later; the transcript is shown as text for now
            "turns": [{"speaker": names.get(t["speaker"], t["speaker"]), "text": t["text"]}
                      for t in part["audio"]["transcript"]],
        }
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
             enforce_blueprint=True, blueprint_path=None, meta=None):
    """Return (public_exam, stored_exam). Writes the stored exam when exams_dir is given.

    level=None  -> placement test: parts of every profile, profile_cycle from the blueprint.
    level="B1"  -> assessment test: bank_dir must be the level folder (question_bank/assessment/B1);
                   only parts of profile level_b1 are used.
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
    statuses = allowed_statuses or bp["assembler"]["allowed_statuses"]
    cycle = bp["assembler"]["profile_cycle"]
    bank, skipped = load_bank(bank_dir, statuses)
    if level is not None:
        level_profile = f"level_{level.lower()}"
        cycle = [level_profile]
        bank = {s: [p for p in parts if p["profile"] == level_profile] for s, parts in bank.items()}

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
        if spec is None or n_by_skill != spec["parts"]:
            spec, bp_status = None, "skipped: custom part counts or unknown exam type"
        else:
            forbidden = [tuple(x) for x in bpv.get("forbidden_pairs", [])]
            max_attempts = bpv["assembly"]["max_attempts"]
            meta = meta if meta is not None else load_meta()
    chosen, notes, attempts, fail_counts = {}, [], 0, {}
    for k in range(max_attempts):
        attempts = k + 1
        rng = random.Random(seed) if k == 0 else random.Random(f"{seed}:{k}")
        chosen, notes = {}, []
        for skill in SKILLS:  # fixed order => same seed gives the same exam
            chosen[skill], n = select_parts(bank[skill], n_by_skill[skill], cycle, rng)
            notes += [f"{skill}: {x}" for x in n]
            rng.shuffle(chosen[skill])
        if spec is None:
            break
        viol = validate_exam([p for s in SKILLS for p in chosen[s]], spec, meta, forbidden)
        if not viol:
            bp_status = "enforced"
            break
        for v in viol:
            fail_counts[v["code"]] = fail_counts.get(v["code"], 0) + 1
    else:
        raise BlueprintError("no_valid_exam", f"No exam satisfying the '{exam_type_for(level)}' blueprint was found in {max_attempts} attempts.",
                             {"exam_type": exam_type_for(level), "seed": seed, "attempts": max_attempts, "violation_counts": fail_counts,
                              "last_violations": viol})
    for skill in SKILLS:
        chosen[skill] = [shuffle_options(p, rng) for p in chosen[skill]]

    ordered = [p for s in SKILLS for p in chosen[s]]
    exam_id = uuid.uuid4().hex  # unique per attempt; the seed only fixes WHICH parts are chosen
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")

    public = {
        "exam_id": exam_id,
        "created_at": created,
        "mode": "assessment" if level else "placement",
        "level": level,
        "sections": [{"skill": s, "parts": [public_part(p) for p in chosen[s]]} for s in SKILLS if chosen[s]],
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
                   "status": p["meta"]["status"]} for p in ordered],
        "key": answer_key(ordered),
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
