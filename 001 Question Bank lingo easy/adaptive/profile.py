"""Adaptive learner profile built from attempt records (see docs/adaptive_learning_diagnostic_spec.md).

Design rules enforced here:
- A sub-skill is only called a strength/weakness with >= MIN_EVIDENCE answered questions AND a Wilson interval that excludes the
  reference accuracy (0.6); otherwise it is 'insufficient_evidence' or 'typical'.
- CEFR estimation is separate from sub-skill mastery and is labelled indicative.
- Error patterns need >= MIN_ERRORS occurrences and are reported as hypotheses with their evidence class.
- Every claim lists the attempt_record_ids that support it. Confidence labels are NOT calibrated probabilities.
"""
import datetime
import math
from collections import Counter, defaultdict

CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
MIN_EVIDENCE = 6        # answered questions needed for a sub-skill claim
MIN_ERRORS = 3          # occurrences needed to report an error pattern
REFERENCE = 0.60        # reference accuracy used for strength/weakness decisions
GENERATOR = "adaptive/profile.py v1.0"


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def _stat(recs):
    ans = [r for r in recs if r["answered"]]
    k = sum(1 for r in ans if r["is_correct"])
    lo, hi = wilson(k, len(ans))
    return {"n_answered": len(ans), "n_correct": k, "accuracy": round(k / len(ans), 3) if ans else None,
            "wilson_low": round(lo, 3), "wilson_high": round(hi, 3), "supporting_attempt_record_ids": [r["attempt_record_id"] for r in ans]}


def classify(stat):
    n = stat["n_answered"]
    if n < MIN_EVIDENCE:
        return "insufficient_evidence"
    if stat["wilson_high"] < REFERENCE:
        return "weakness"
    if stat["wilson_low"] > REFERENCE:
        return "strength"
    return "typical_or_unclear"


def cefr_estimate(records):
    by = defaultdict(list)
    for r in records:
        if r["answered"]:
            by[r["question_cefr"]].append(r)
    per = {lv: {"n": len(by[lv]), "correct": sum(1 for r in by[lv] if r["is_correct"])} for lv in CEFR if by.get(lv)}
    reached, basis = None, []
    for lv in CEFR:
        if lv not in per:
            continue
        if per[lv]["n"] < 4:
            continue  # too few items at this level to use
        if per[lv]["correct"] / per[lv]["n"] >= REFERENCE:
            reached = lv
            basis.append(lv)
        else:
            break
    n_used = sum(per[lv]["n"] for lv in basis)
    total = sum(v["n"] for v in per.values())
    label = "insufficient_evidence" if reached is None else ("low" if n_used < 20 else "moderate")
    return {"level": reached, "status": "indicative", "method": "last level with >=60% correct on >=4 items before the first level below that threshold; levels with <4 items are skipped",
            "per_level": per, "items_used": n_used, "items_total": total, "confidence_label": label,
            "caveat": "Not a calibrated placement. Provisional until learner-response data exists to calibrate items."}


def build_profile(learner_id, attempts, now=None):
    """attempts: dict attempt_id -> list of attempt records (all for one learner)."""
    now = now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    allrec = [r for recs in attempts.values() for r in recs]
    answered = [r for r in allrec if r["answered"]]
    prof = {"schema_version": "1.0", "profile_id": f"{learner_id}:{now}", "learner_id": learner_id, "generated_at": now, "generator_version": GENERATOR,
            "attempts_included": sorted(attempts), "synthetic": False}
    if len(answered) < MIN_EVIDENCE:
        prof["status"] = "insufficient_evidence"
    elif len(attempts) < 2 or len(answered) < 40:
        prof["status"] = "provisional"
    else:
        prof["status"] = "established_for_this_instrument"
    prof["status_reason"] = {"answered_questions": len(answered), "attempts": len(attempts),
                             "rule": "insufficient_evidence <6 answered; provisional if <2 attempts or <40 answered; otherwise established (still uncalibrated)"}
    prof["observed_performance"] = {"overall": _stat(allrec),
                                    "by_modality": {m: _stat([r for r in allrec if r["modality"] == m]) for m in ("reading", "listening")}}
    prof["cefr_estimate"] = cefr_estimate(allrec)
    subs = {}
    for s in sorted({r["primary_subskill"] for r in allrec if r["primary_subskill"]}):
        st = _stat([r for r in allrec if r["primary_subskill"] == s])
        st["status"] = classify(st)
        subs[s] = st
    prof["subskills"] = subs
    # consistency across attempts
    accs = []
    for aid, recs in attempts.items():
        a = [r for r in recs if r["answered"]]
        if len(a) >= 10:
            accs.append((aid, sum(1 for r in a if r["is_correct"]) / len(a)))
    if len(accs) < 2:
        prof["consistency"] = {"status": "not_assessable", "reason": "needs >=2 attempts with >=10 answered questions"}
    else:
        spread = max(a for _, a in accs) - min(a for _, a in accs)
        prof["consistency"] = {"status": "consistent" if spread <= 0.15 else "inconsistent", "accuracy_by_attempt": {k: round(v, 3) for k, v in accs}, "spread": round(spread, 3)}
    # error patterns (hypotheses)
    wrong = [r for r in answered if not r["is_correct"] and r.get("distractor_diagnostic")]
    tags = Counter()
    grounded = Counter()
    refs = defaultdict(list)
    for r in wrong:
        d = r["distractor_diagnostic"]
        for t in d["error_tags"]:
            tags[t] += 1
            refs[t].append(r["attempt_record_id"])
            if d["evidence_class"] == "text_grounded":
                grounded[t] += 1
    pats = []
    for t, n in tags.most_common():
        if t == "insufficient_evidence_to_classify" or n < MIN_ERRORS:
            continue
        pats.append({"error_tag": t, "occurrences": n, "of_incorrect_answers": len(wrong), "text_grounded_occurrences": grounded[t],
                     "claim_strength": "hypothesis_supported_by_repetition" if grounded[t] >= MIN_ERRORS else "weak_hypothesis",
                     "supporting_attempt_record_ids": refs[t]})
    prof["error_patterns"] = pats
    # next objectives: weakest sub-skills at the learner's current/next level
    cur = prof["cefr_estimate"]["level"]
    nxt = CEFR[min(CEFR.index(cur) + 1, 5)] if cur else "A1"
    recs_out = []
    for s, st in subs.items():
        if st["status"] == "weakness":
            recs_out.append({"objective_id": f"LO.{s}.{cur or 'A1'}", "subskill": s, "target_cefr": cur or "A1", "priority": 1,
                             "reason": f"accuracy {st['accuracy']} (95% interval {st['wilson_low']}-{st['wilson_high']}) on {st['n_answered']} questions is below the {REFERENCE} reference",
                             "evidence_refs": st["supporting_attempt_record_ids"], "lesson_ref": None})
    for s, st in subs.items():
        if st["status"] == "strength" and cur:
            recs_out.append({"objective_id": f"LO.{s}.{nxt}", "subskill": s, "target_cefr": nxt, "priority": 2,
                             "reason": "consistent strength; extend to the next level", "evidence_refs": st["supporting_attempt_record_ids"], "lesson_ref": None})
    prof["recommended_next_objectives"] = recs_out
    prof["lesson_mapping_note"] = "lesson_ref is null: no lesson/exercise bank was found in the project, so objectives cannot yet be mapped to concrete lessons."
    prof["uncertainty"] = [
        "Item difficulty is unvalidated (no learner-response calibration); accuracy against the 0.6 reference is a screening rule, not a measurement of mastery.",
        "Sub-skill tags are rule-validated only; many items in the bank test detail retrieval, so other sub-skills have few observations.",
        "Error patterns are hypotheses about reasoning; one wrong answer never establishes a misconception.",
    ]
    return prof
