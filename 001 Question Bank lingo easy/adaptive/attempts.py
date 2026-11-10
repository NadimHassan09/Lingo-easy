"""Learner attempt records: one record per question per attempt, kept OUTSIDE the question bank.

Static question metadata (sub-skill, diagnostics) is joined in from the generated sidecars config/question_meta_v2.json and
config/distractor_diagnostics_v2.json. Nothing learner-specific is ever written back to the bank.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "1.0"
PROVENANCE = "qa-1.0 rule-based hypothesis (not validated on learner data)"


def load_sidecars(root=ROOT):
    meta = json.loads((Path(root) / "config" / "question_meta_v2.json").read_text(encoding="utf-8"))["questions"]
    diag_p = Path(root) / "config" / "distractor_diagnostics_v2.json"
    diag = json.loads(diag_p.read_text(encoding="utf-8"))["questions"] if diag_p.exists() else {}
    return meta, diag


def build_attempt_records(stored_exam, answers, meta, diag, learner_id, attempt_id, submitted_at, response_times_ms=None, started_at=None):
    """stored_exam: the exam JSON written by the assembler. answers: {question_id: shown option letter or None}."""
    response_times_ms = response_times_ms or {}
    recs = []
    bp = stored_exam.get("blueprint") or {}
    for qid, k in stored_exam["key"].items():
        sel = answers.get(qid) or None
        uuid_ = k.get("question_uuid")
        m = meta.get(uuid_, {})
        origin = (k.get("option_origin") or {}).get(sel) if sel else None
        correct = sel == k["answer"] if sel else False
        d = None
        if sel and not correct and origin:
            d0 = (diag.get(uuid_, {}).get("distractor_diagnostics") or {}).get(origin)
            if d0:
                d = {"error_tags": d0["error_tags"], "diagnostic_confidence": d0["diagnostic_confidence"], "evidence_class": d0["evidence_class"], "provenance": PROVENANCE}
        lvl = k["cefr"]
        prim = m.get("primary_subskill")
        recs.append({
            "schema_version": SCHEMA_VERSION,
            "attempt_record_id": f"{attempt_id}:{qid}",
            "assessment_id": stored_exam["exam_id"], "attempt_id": attempt_id, "learner_id": learner_id,
            "exam_type": bp.get("exam_type") or stored_exam.get("mode"), "level_target": stored_exam.get("level"),
            "blueprint_version": bp.get("version"), "seed": stored_exam.get("seed"),
            "started_at": started_at, "submitted_at": submitted_at,
            "question_id": qid, "question_uuid": uuid_, "question_version": k.get("part_content_hash"),
            "part_id": k["part_id"], "part_uuid": k.get("part_uuid"), "source_id": k["part_id"], "modality": k["skill"],
            "question_cefr": lvl,
            "answered": bool(sel), "selected_option": sel, "selected_option_bank_id": origin,
            "selected_option_text": (k.get("shown_options") or {}).get(sel) if sel else None,
            "is_correct": correct, "response_time_ms": response_times_ms.get(qid),
            "primary_subskill": prim, "secondary_subskills": m.get("secondary_subskills", []),
            "learning_objectives": [f"LO.{prim}.{lvl}"] if prim else [],
            "distractor_diagnostic": d,
        })
    return recs


def write_attempt(path, records):
    Path(path).write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
