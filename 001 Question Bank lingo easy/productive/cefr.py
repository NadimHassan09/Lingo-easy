"""Heuristic, independent CEFR alignment estimate for a productive task spec.

NOT empirically calibrated. It looks at the demands the task places on the learner (structures invited, cognitive operations, expected length,
abstractness, language of the prompt itself), not at the level the author intended. It is a consistency check and an outlier detector.
Weights and reference points were fixed a priori (see WEIGHTS / CENTRES) and are documented in GENERATOR_ARCHITECTURE.md.
"""
import math

from .common import LEVELS, LV, readability, taxonomy

WEIGHTS = {"grammar": 0.35, "cognition": 0.25, "length": 0.20, "abstractness": 0.10, "prompt_language": 0.10}
ABSTRACT_IDX = [0.5, 2.0, 3.2, 4.2]
# reference centres (log scale) for suggested length: writing = words, speaking = suggested seconds
CENTRES = {"writing": [45, 90, 165, 250, 310, 370], "speaking": [70, 100, 145, 200, 270, 320]}


def _top2(vals):
    v = sorted(vals, reverse=True)[:2]
    return sum(v) / len(v)


def _interp(x, centres):
    lx = math.log(max(x, 1))
    lc = [math.log(c) for c in centres]
    if lx <= lc[0]:
        return 0.0
    if lx >= lc[-1]:
        return 5.0
    for i in range(len(lc) - 1):
        if lc[i] <= lx <= lc[i + 1]:
            return i + (lx - lc[i]) / (lc[i + 1] - lc[i])
    return 5.0


def components(spec, skill):
    t = taxonomy()
    g = [LV[t["grammar_level"][x]] for x in spec["gram"]]
    c = [LV[t["cognitive_processes"][x]["level"]] for x in spec["cog"]]
    if skill == "writing":
        size = (spec["w"][1] + spec["w"][2]) / 2
        learner_text = ". ".join([spec["prompt"]] + spec["pts"])
    else:
        size = spec["dur"]
        learner_text = ". ".join([spec["prompt"], spec["main"]] + spec["cue"] + spec["follow"])
    asl, lw = readability(learner_text)
    prompt_idx = min(5.0, max(0.0, 0.15 * (asl - 5) + 9 * lw))
    return {"grammar": _top2(g), "cognition": _top2(c), "length": _interp(size, CENTRES[skill]),
            "abstractness": ABSTRACT_IDX[spec["abs"]], "prompt_language": prompt_idx,
            "_prompt_avg_sentence_len": round(asl, 1), "_prompt_long_word_ratio": round(lw, 3)}


def estimate(spec, skill):
    comp = components(spec, skill)
    score = sum(WEIGHTS[k] * comp[k] for k in WEIGHTS)
    rec = LEVELS[min(5, max(0, int(round(score))))]
    vals = [comp[k] for k in WEIGHTS]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    distance = abs(score - round(score))
    confidence = "medium" if sd <= 1.0 and distance <= 0.3 else "low"
    return {"composite_index": round(score, 2), "recommended_cefr": rec, "components": {k: round(comp[k], 2) for k in WEIGHTS},
            "component_spread_sd": round(sd, 2), "cefr_confidence": confidence,
            "prompt_readability": {"avg_sentence_words": comp["_prompt_avg_sentence_len"], "long_word_ratio": comp["_prompt_long_word_ratio"]}}
