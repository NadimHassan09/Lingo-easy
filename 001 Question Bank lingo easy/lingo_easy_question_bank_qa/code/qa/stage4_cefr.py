"""Stage 4: independent CEFR reassessment (heuristic, uncalibrated, separate source vs question difficulty).

IMPORTANT LIMITS (also written to every output row's method field):
- No learner-response data exists, so nothing here is empirical difficulty.
- The score is a hand-weighted composite of surface features (word/sentence length, abstraction suffixes, paraphrase distance,
  inference demand, distractor plausibility). The level cut-offs are the midpoints between the median scores of the six
  assessment banks, which were *authored* to be level-pure. This is circular by construction: the model can only say
  "this item looks easier/harder than other items labelled with this level", never "this item IS level X".
- Recommendations never overwrite level.cefr; low-confidence ones are explicitly recommendations only.
"""
import re
import statistics
from collections import Counter, defaultdict

from .common import *  # noqa: F401,F403
from .stage1_inventory_integrity import question_records
from .stage3_semantic import numbers_in, sentences

METHOD = "heuristic composite v1 (surface features; cut-offs from medians of authored level-pure banks; NOT empirically calibrated)"
ABSTRACT = re.compile(r"(tion|sion|ity|ment|ness|ism|ance|ence|ship|ology|ise|ize)s?$")
INFER_TAGS = {"inference", "speaker_attitude", "speaker_opinion", "writer_claim", "main_idea", "gist", "text_organisation", "organisation_signposting", "purpose"}
HEDGE = re.compile(r"\b(may|might|perhaps|arguably|seems|suggest|tend|largely|partly|rather|somewhat|probably|likely)\b", re.I)


def text_feats(text):
    ws = re.findall(r"[A-Za-z']+", text)
    if not ws:
        return {"n": 0, "awl": 0, "long": 0, "abs": 0, "asl": 0, "hedge": 0}
    sents = sentences(text) or [text]
    return {"n": len(ws), "awl": sum(len(w) for w in ws) / len(ws), "long": sum(1 for w in ws if len(w) >= 9) / len(ws),
            "abs": sum(1 for w in ws if ABSTRACT.search(w.lower()) and len(w) > 6) / len(ws),
            "asl": len(ws) / len(sents), "hedge": len(HEDGE.findall(text)) / len(ws)}


def evidence_sentence(part, ev):
    if not ev:
        return ""
    q = norm(ev["quote"])
    for _, text in source_units(part):
        for s in sentences(text):
            if q in norm(s):
                return s
        if q in norm(text):
            return text
    return ev["quote"]


def source_score(part):
    f = text_feats(source_text(part))
    return 2.2 * f["awl"] + 14 * f["long"] + 12 * f["abs"] + 0.12 * f["asl"] + 20 * f["hedge"]


def question_score(rec, part):
    ev_s = evidence_sentence(part, rec["evidence"])
    qf = text_feats(rec["prompt"] + " " + " ".join(rec["options"]))
    ef = text_feats(ev_s)
    ans = set(toks(rec["answer_text"] or ""))
    evt = set(toks(ev_s))
    para_dist = 1 - (len(ans & evt) / len(ans)) if ans and evt else 0.5
    infer = 1.0 if rec["skill_tag"] in INFER_TAGS else 0.0
    src_toks = set(toks(source_text(part)))
    wrong = [o for i, o in enumerate(rec["options"]) if i != "ABCD".index(rec["answer_id"])]
    plaus = 0.0
    if rec["question_type"] in ("multiple_choice", "sentence_completion"):
        vals = []
        for w in wrong:
            wt = set(toks(w))
            if wt:
                vals.append(len(wt & src_toks) / len(wt))
        plaus = sum(vals) / len(vals) if vals else 0
    tfng = 1.0 if rec["question_type"] in ("true_false_not_given", "yes_no_not_given") else 0.0
    ng = 1.0 if rec["answer_text"] == "Not Given" else 0.0
    matching = 1.0 if rec["question_type"].startswith("matching") else 0.0
    lang = 2.0 * qf["awl"] + 10 * qf["long"] + 10 * qf["abs"] + 0.10 * qf["asl"] + 1.6 * ef["awl"] + 8 * ef["long"] + 0.08 * ef["asl"] + 15 * ef["hedge"]
    cog = 4.0 * para_dist + 3.0 * infer + 2.0 * plaus + 1.5 * tfng + 1.5 * ng + 1.0 * matching
    return lang, cog, lang + cog, {"paraphrase_distance": round(para_dist, 2), "inference_tag": bool(infer), "distractor_plausibility": round(plaus, 2), "evidence_sentence_words": ef["n"]}


def run(out=None):
    out = out or REPORTS
    entries = load_parts()
    byid = {e["part"]["id"]: e["part"] for e in entries}
    recs = question_records(entries)
    scored = []
    for r in recs:
        lang, cog, tot, extra = question_score(r, byid[r["part_id"]])
        scored.append((r, lang, cog, tot, extra))
    # cut-offs from level-pure banks (circular, documented)
    by_level = defaultdict(list)
    for r, lang, cog, tot, _ in scored:
        if r["bank"].startswith("assessment_"):
            by_level[r["original_cefr"]].append(tot)
    med = {lv: statistics.median(by_level[lv]) for lv in CEFR}
    cuts = [(med[CEFR[i]] + med[CEFR[i + 1]]) / 2 for i in range(5)]
    sp = {lv: statistics.median(source_score(e["part"]) for e in entries if e["part"]["text_cefr"] == lv and e["bank"].startswith("assessment_")) for lv in CEFR}
    scuts = [(sp[CEFR[i]] + sp[CEFR[i + 1]]) / 2 for i in range(5)]

    def to_level(x, cs):
        return CEFR[sum(1 for c in cs if x > c)]
    all_tot = sorted(t for _, _, _, t, _ in scored)
    lang_sorted = sorted(l for _, l, _, _, _ in scored)
    cog_sorted = sorted(c for _, _, c, _, _ in scored)

    def pct(arr, v):
        import bisect
        return bisect.bisect_left(arr, v) / len(arr)

    def band(p):
        return "low" if p < 0.34 else "medium" if p < 0.67 else "high"
    rows = []
    before, after = Counter(), Counter()
    for r, lang, cog, tot, extra in scored:
        rec_lv = to_level(tot, cuts)
        o = CEFR.index(r["original_cefr"])
        d = CEFR.index(rec_lv) - o
        # confidence: distance of score to the nearest cut-off relative to level spacing; capped, never high
        dist = min(abs(tot - c) for c in cuts)
        spacing = statistics.mean(abs(cuts[i + 1] - cuts[i]) for i in range(4))
        conf = int(max(5, min(60, 20 + 60 * dist / spacing)))
        if d != 0:
            conf = max(5, conf - 10)
        src_lv = to_level(source_score(byid[r["part_id"]]), scuts)
        rationale = (f"score {tot:.1f} (language {lang:.1f}, cognitive {cog:.1f}); paraphrase distance {extra['paraphrase_distance']}, "
                     f"inference-type tag {extra['inference_tag']}, distractor plausibility {extra['distractor_plausibility']}; "
                     f"nearest-level reading {rec_lv} vs recorded {r['original_cefr']}")
        before[r["original_cefr"]] += 1
        after[rec_lv] += 1
        rows.append({
            "question_id": r["question_id"], "uuid": r["uuid"], "bank": r["bank"], "modality": r["modality"],
            "original_cefr": r["original_cefr"], "original_band": r["original_band"], "text_cefr_recorded": r["text_cefr"],
            "source_difficulty_cefr_heuristic": src_lv, "question_difficulty_cefr_heuristic": rec_lv, "recommended_cefr": rec_lv,
            "level_gap_steps": d, "change_recommended": d != 0, "cefr_confidence": conf, "cefr_rationale": rationale,
            "language_demand": band(pct(lang_sorted, lang)), "cognitive_demand": band(pct(cog_sorted, cog)),
            "difficulty_estimate": round(pct(all_tot, tot), 3), "difficulty_estimate_method": METHOD,
            "human_review_required": bool(abs(d) >= 2),
        })
    write_csv(out / "cefr_reassessment.csv", rows)

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return rk

    def spearman(a, b):
        ra, rb = ranks(a), ranks(b)
        ma, mb = statistics.mean(ra), statistics.mean(rb)
        num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
        return num / den if den else 0.0
    bands = [r["original_band"] for r, *_ in scored]
    scores = [t for _, _, _, t, _ in scored]
    agree = {"exact_agreement": sum(1 for x in rows if x["level_gap_steps"] == 0) / len(rows),
             "within_one_level": sum(1 for x in rows if abs(x["level_gap_steps"]) <= 1) / len(rows),
             "spearman_score_vs_recorded_band": round(spearman(scores, bands), 3),
             "spearman_by_modality": {m: round(spearman([t for (r, _, _, t, _) in scored if r["modality"] == m], [r["original_band"] for (r, *_ ) in scored if r["modality"] == m]), 3) for m in ("reading", "listening")}}
    bank_before = defaultdict(Counter)
    bank_after = defaultdict(Counter)
    for x in rows:
        bank_before[x["bank"]][x["original_cefr"]] += 1
        bank_after[x["bank"]][x["recommended_cefr"]] += 1
    changed = [x for x in rows if x["change_recommended"]]
    write_json(out / "cefr_distribution_before_after.json", {
        "method": METHOD, "status": "RECOMMENDATIONS ONLY: no level.cefr value was changed in the bank",
        "cutoffs_total_score": [round(c, 2) for c in cuts], "level_medians_total_score": {k: round(v, 2) for k, v in med.items()},
        "overall_before": {k: before.get(k, 0) for k in CEFR}, "overall_after_recommended": {k: after.get(k, 0) for k in CEFR},
        "by_bank_before": {b: {k: c.get(k, 0) for k in CEFR} for b, c in bank_before.items()},
        "by_bank_after_recommended": {b: {k: c.get(k, 0) for k in CEFR} for b, c in bank_after.items()},
        "heuristic_vs_recorded_agreement": agree, "n_questions": len(rows),
        "changes_recommended": len(changed), "human_review_required_gap_ge_2": sum(1 for x in rows if x["human_review_required"]), "changes_by_gap": dict(Counter(x["level_gap_steps"] for x in rows)),
        "changes_with_confidence_ge_40": sum(1 for x in changed if x["cefr_confidence"] >= 40),
        "confusion_original_to_recommended": {o: {r2: sum(1 for x in rows if x["original_cefr"] == o and x["recommended_cefr"] == r2) for r2 in CEFR} for o in CEFR},
        "caveat": "Circular calibration: cut-offs come from the same authored banks that are being assessed. Use only to surface outliers for human review.",
    })
    print(f"{len(rows)} questions; recommended change for {len(changed)}; gap distribution {dict(Counter(x['level_gap_steps'] for x in rows))}")
    return rows


if __name__ == "__main__":
    run()
