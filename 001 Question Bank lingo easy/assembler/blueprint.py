"""Blueprint (exam specification) loading, exam metrics and constraint checking.

The blueprint (blueprints/exam_blueprint_v1.json in the QA deliverable, copied to config/exam_blueprint_v1.json) is the
contract that an assembled exam must satisfy. validate_exam() is pure and deterministic: same parts in -> same violations out.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
DEFAULT_BLUEPRINT = ROOT / "config" / "exam_blueprint_v1.json"
DEFAULT_META = ROOT / "config" / "question_meta_v2.json"


class BlueprintError(Exception):
    """No exam satisfying the blueprint could be assembled (structured, never a silently relaxed exam)."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    def to_dict(self):
        return {"error": self.code, "message": self.message, "details": self.details}


def load_blueprint(path=None):
    return json.loads(Path(path or DEFAULT_BLUEPRINT).read_text(encoding="utf-8"))


def load_meta(path=None):
    p = Path(path or DEFAULT_META)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("questions", {})


def exam_type_for(level):
    return "placement" if not level else f"assessment_{level}"


def exam_metrics(parts, meta):
    """parts: list of full part dicts (as selected). meta: uuid -> question metadata (sub-skill etc.).
    Only multiple-choice parts (Reading/Listening) carry questions; Writing/Speaking tasks are ignored here."""
    parts = [p for p in parts if p.get("skill") in ("listening", "reading")]
    levels, modal, sub = Counter(), Counter(), defaultdict(Counter)
    topics, ptypes, profiles = Counter(), defaultdict(Counter), defaultdict(Counter)
    item_ids, sources = [], []
    for p in parts:
        sk = p["skill"]
        topics[p.get("topic")] += 1
        ptypes[sk][p["part_type"]] += 1
        profiles[sk][p["profile"]] += 1
        sources.append(p["id"])
        for g in p["question_groups"]:
            for it in g["items"]:
                levels[it["level"]["cefr"]] += 1
                modal[sk] += 1
                item_ids.append(it["id"])
                m = meta.get(it.get("uuid"), {})
                sub[sk][m.get("primary_subskill", "unknown")] += 1
    return {"total": sum(modal.values()), "by_modality": dict(modal), "by_level": {k: levels.get(k, 0) for k in CEFR},
            "by_subskill": {sk: dict(c) for sk, c in sub.items()}, "topics": dict(topics),
            "part_types": {sk: dict(c) for sk, c in ptypes.items()}, "profiles": {sk: dict(c) for sk, c in profiles.items()},
            "duplicate_item_ids": len(item_ids) - len(set(item_ids)), "sources": sources,
            "duplicate_sources": len(sources) - len(set(sources)), "parts_per_skill": {sk: sum(profiles[sk].values()) for sk in profiles}}


def validate_exam(parts, spec, meta, forbidden_pairs=()):
    """Return a list of violation dicts (empty = exam satisfies the blueprint)."""
    m = exam_metrics(parts, meta)
    v = []

    def bad(code, constraint, observed, required):
        v.append({"code": code, "constraint": constraint, "observed": observed, "required": required})
    q = spec["questions"]
    for key, need in (("total", q["total"]), ("listening", q["listening"]), ("reading", q["reading"])):
        got = m["total"] if key == "total" else m["by_modality"].get(key, 0)
        if got != need:
            bad("question_count", key, got, need)
    for sk, need in spec["parts"].items():
        if m["parts_per_skill"].get(sk, 0) != need:
            bad("part_count", sk, m["parts_per_skill"].get(sk, 0), need)
    for lv in CEFR:
        rng = spec["level_counts"].get(lv, {"min": 0, "max": q["total"]})
        got = m["by_level"][lv]
        if not rng["min"] <= got <= rng["max"]:
            bad("level_count", lv, got, rng)
    tl = spec.get("target_level")
    if tl:
        share = m["by_level"][tl] / max(1, m["total"])
        if share < spec.get("min_target_level_share", 1.0) - 1e-9:
            bad("target_level_share", tl, round(share, 3), spec.get("min_target_level_share", 1.0))
    if m["duplicate_item_ids"]:
        bad("duplicate_questions", "items", m["duplicate_item_ids"], 0)
    if m["duplicate_sources"]:
        bad("duplicate_sources", "parts", m["duplicate_sources"], 0)
    for sk, need in spec.get("min_distinct_subskills", {}).items():
        got = len([s for s in m["by_subskill"].get(sk, {}) if s != "unknown"])
        if got < need:
            bad("subskill_coverage", sk, got, need)
    mx = spec.get("max_subskill_share")
    if mx:
        for sk, c in m["by_subskill"].items():
            tot = sum(c.values())
            if tot and max(c.values()) / tot > mx + 1e-9:
                bad("subskill_dominance", sk, round(max(c.values()) / tot, 3), mx)
    mt = spec.get("max_parts_per_topic")
    if mt is not None:
        for t, n in m["topics"].items():
            if n > mt:
                bad("topic_repetition", t, n, mt)
    for sk, need in spec.get("min_distinct_part_types", {}).items():
        got = len(m["part_types"].get(sk, {}))
        if got < need:
            bad("part_type_variety", sk, got, need)
    if spec.get("require_each_profile_per_skill"):
        for sk in spec["parts"]:
            if len(m["profiles"].get(sk, {})) < 3:
                bad("profile_variety", sk, sorted(m["profiles"].get(sk, {})), "foundation+intermediate+advanced")
    ids = set(m["sources"])
    for a, b in forbidden_pairs:
        if a in ids and b in ids:
            bad("forbidden_pair", f"{a}+{b}", "both selected", "never together")
    return v
