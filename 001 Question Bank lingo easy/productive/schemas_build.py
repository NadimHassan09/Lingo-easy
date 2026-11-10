"""Builds the JSON Schemas in schemas/ from one set of shared definitions (so Writing and Speaking cannot drift apart).

Run: python -m productive.schemas_build
Files: productive_task_base, writing_part, speaking_part, evaluation_blueprint, generation_metadata, productive_attempt (.schema.json)
"""
from .common import LEVELS, ROOT, taxonomy, write_json

S = lambda **kw: dict(type="string", **kw)  # noqa: E731
STR = {"type": "string", "minLength": 1}
STRS = {"type": "array", "items": STR}
CEFR = {"type": "string", "enum": LEVELS}


def defs():
    t = taxonomy()
    diag = sorted(t["diagnostics"]["categories"])
    return {
        "cefr": CEFR, "str": STR, "strs": STRS,
        "assessment": {"type": "object", "required": ["type", "level"], "additionalProperties": False,
                       "properties": {"type": {"enum": ["placement", "assessment"]}, "level": {"type": ["string", "null"], "enum": LEVELS + [None]}}},
        "modality": {"type": "object", "required": ["current", "planned"], "additionalProperties": False,
                     "properties": {"current": {"const": "typed_text"}, "planned": {"type": "array", "items": {"enum": ["audio", "typed_text"]}}, "note": STR}},
        "criterion": {"type": "object",
                      "required": ["id", "name", "description", "weight", "assessable_in_current_modality", "scored_in_text_mvp", "successful_performance",
                                   "weak_performance", "expected_evidence", "common_error_patterns", "related_subskills", "evaluation_limitations"],
                      "properties": {"id": {"type": "string", "pattern": "^[WS]_[A-Z]+$"}, "name": STR, "description": STR, "weight": {"type": "number", "minimum": 0, "maximum": 1},
                                     "assessable_in_current_modality": {"enum": ["yes", "partial", "no"]}, "scored_in_text_mvp": {"type": "boolean"},
                                     "successful_performance": STR, "weak_performance": STR, "expected_evidence": STR, "common_error_patterns": {"type": "array", "items": STR},
                                     "related_subskills": STRS, "evaluation_limitations": STR, "diagnostic_categories": {"type": "array", "items": {"enum": diag}},
                                     "l1_transfer_hypotheses": {"type": "object"}}},
        "blueprint": {"type": "object",
                      "required": ["blueprint_version", "response_modality", "target_cefr", "criteria", "not_assessed_by_design", "required_demonstrations",
                                   "optional_demonstrations", "not_penalised", "scale", "evaluator_output_contract", "multiple_valid_responses"],
                      "properties": {"blueprint_version": STR, "response_modality": {"const": "typed_text"}, "target_cefr": CEFR,
                                     "criteria": {"type": "array", "minItems": 3, "items": {"$ref": "#/$defs/criterion"}},
                                     "not_assessed_by_design": {"type": "array", "items": {"type": "object", "required": ["id", "name", "reason"]}},
                                     "required_demonstrations": {"type": "array", "minItems": 1, "items": STR}, "optional_demonstrations": {"type": "array", "items": STR},
                                     "not_penalised": {"type": "array", "minItems": 1, "items": STR}, "scale": {"type": "object"},
                                     "evaluator_output_contract": {"type": "array", "minItems": 5, "items": STR}, "multiple_valid_responses": {"const": True},
                                     "notes": STR, "text_mvp_limitations": STRS}},
        "difficulty": {"type": "object",
                       "required": ["original_target_cefr", "recommended_cefr", "cefr_confidence", "level_gap_steps", "difficulty_index", "language_demand", "cognitive_demand",
                                    "expected_performance", "rationale", "method", "calibrated", "human_review_required"],
                       "properties": {"original_target_cefr": CEFR, "recommended_cefr": CEFR, "cefr_confidence": {"enum": ["low", "medium", "high"]},
                                      "level_gap_steps": {"type": "integer", "minimum": 0}, "difficulty_index": {"type": "number", "minimum": 0, "maximum": 1},
                                      "language_demand": STR, "cognitive_demand": STR, "expected_performance": {"type": "array", "minItems": 1, "items": STR}, "rationale": STR,
                                      "method": STR, "calibrated": {"const": False}, "human_review_required": {"type": "boolean"}, "review_priority": {"enum": ["P1", "P2", "P3"]},
                                      "components": {"type": "object"}, "prompt_readability": {"type": "object"}}},
        "classification": {"type": "object", "required": ["primary_subskill", "secondary_subskills", "cognitive_processes", "learning_objectives"],
                           "properties": {"primary_subskill": STR, "secondary_subskills": STRS, "cognitive_processes": {"type": "array", "minItems": 1, "items": STR},
                                          "learning_objectives": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "text", "measurable_verb", "criteria"],
                                                                                                           "properties": {"id": STR, "text": STR, "measurable_verb": STR, "criteria": STRS}}}}},
        "diagnostics": {"type": "object", "required": ["targets", "policy", "observed_vs_inferred"],
                        "properties": {"targets": {"type": "array", "minItems": 1, "items": {"enum": diag}}, "policy": {"type": "object"}, "observed_vs_inferred": STR}},
        "grammar": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "level"], "properties": {"id": STR, "level": CEFR, "extension": {"type": "boolean"}}}},
        "expected": {"type": "object",
                     "required": ["content_points", "required_elements", "optional_elements", "organisation", "vocabulary_demands", "grammar_demands", "discourse_complexity",
                                  "linguistic_demand", "cognitive_demand", "examples"],
                     "properties": {"content_points": {"type": "array", "minItems": 1, "items": STR}, "required_elements": {"type": "array", "minItems": 1, "items": STR},
                                    "optional_elements": STRS, "organisation": {"type": "array", "minItems": 1, "items": STR}, "vocabulary_demands": {"type": "array", "minItems": 1, "items": STR},
                                    "grammar_demands": {"$ref": "#/$defs/grammar"}, "discourse_complexity": STR, "linguistic_demand": STR, "cognitive_demand": STR,
                                    "examples": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["label", "outline"],
                                                                                         "properties": {"label": {"type": "string", "pattern": "not an answer key"}, "outline": {"type": "array", "minItems": 1, "items": STR}}}}}},
        "qa": {"type": "object", "required": ["structural_validation", "semantic_rule_review", "llm_review", "human_review", "findings"],
               "properties": {"structural_validation": {"enum": ["not_run", "pass", "fail"]}, "semantic_rule_review": {"enum": ["not_run", "pass", "flagged"]},
                              "llm_review": {"enum": ["not_performed", "performed"]}, "human_review": {"enum": ["not_reviewed", "reviewed", "approved"]},
                              "findings": {"type": "array"}}},
        "provenance": {"$ref": "generation_metadata"},
    }


def generation_metadata():
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "lingoeasy/generation_metadata.schema.json", "title": "Generation provenance", "type": "object",
            "required": ["generator", "generator_version", "assembly", "seed", "generated_at", "spec_source", "spec_sha256", "authoring", "raw_spec"],
            "properties": {"generator": STR, "generator_version": STR, "assembly": {"const": "deterministic"}, "seed": {"type": "integer"}, "generated_at": STR, "spec_source": STR,
                           "spec_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                           "authoring": {"type": "object", "required": ["method", "provider", "model", "runtime_llm_calls"],
                                         "properties": {"method": STR, "provider": STR, "model": STR, "generation_parameters": STR, "runtime_llm_calls": {"type": "integer", "minimum": 0}}},
                           "raw_spec": {"type": "object"}}}


def part_schema(skill):
    d = defs()
    d["provenance"] = generation_metadata()
    d["provenance"].pop("$schema"); d["provenance"].pop("$id"); d["provenance"].pop("title")  # noqa: E702
    base_required = ["schema_version", "id", "uuid", "version", "skill", "assessment", "target_cefr", "level", "ielts_reference", "part_type", "skill_tag", "profile", "topic", "context", "title", "modality", "task",
                     "expected_response", "classification", "difficulty", "evaluation_blueprint", "diagnostics", "qa", "provenance", "meta", "derived"]
    props = {"schema_version": {"const": "1.0"}, "id": {"type": "string", "pattern": "^(WR|SP)[0-9]{3}$"},
             "uuid": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
             "version": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"}, "skill": {"const": skill}, "assessment": {"$ref": "#/$defs/assessment"},
             "target_cefr": {"$ref": "#/$defs/cefr"}, "level": {"type": "object", "required": ["cefr", "band"], "properties": {"cefr": CEFR, "band": {"type": "number", "minimum": 1, "maximum": 9}}},
             "ielts_reference": {"type": "object", "required": ["band_range", "note"]}, "part_type": STR, "skill_tag": STR, "profile": {"type": "string", "pattern": "^(placement|level_[a-c][12])$"}, "topic": STR, "context": STR, "title": STR,
             "modality": {"$ref": "#/$defs/modality"}, "expected_response": {"$ref": "#/$defs/expected"}, "classification": {"$ref": "#/$defs/classification"},
             "difficulty": {"$ref": "#/$defs/difficulty"}, "evaluation_blueprint": {"$ref": "#/$defs/blueprint"}, "diagnostics": {"$ref": "#/$defs/diagnostics"},
             "qa": {"$ref": "#/$defs/qa"}, "provenance": {"$ref": "#/$defs/provenance"},
             "meta": {"type": "object", "required": ["status", "source"], "properties": {"status": {"enum": ["draft", "validated", "reviewed", "approved", "rejected"]}, "source": STR, "generator": STR, "model": STR, "notes": STR}},
             "derived": {"type": "object", "required": ["content_hash"], "properties": {"content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}},
             "audio_extension": {"$ref": "#/$defs/audio_extension"}}
    d["audio_extension"] = {"type": "object", "additionalProperties": False,
                            "description": "OPTIONAL and RESERVED. Present only when real audio exists; never fabricated for text-only attempts. Defined here so adding audio later does not change the Part contract.",
                            "properties": {"audio_asset_ref": STR, "audio_duration_seconds": {"type": "number", "minimum": 0}, "transcript": STR, "stt_provider": STR,
                                           "stt_confidence": {"type": "number", "minimum": 0, "maximum": 1}, "pronunciation_evaluation": {"type": "object"},
                                           "fluency_evaluation": {"type": "object"}, "audio_evaluation_evidence": {"type": "array"}}}
    if skill == "writing":
        props["task_category"] = {"type": "string", "enum": sorted(taxonomy()["writing"]["categories"])}
        props["task"] = {"type": "object", "required": ["title", "scenario", "prompt", "instructions", "required_points", "audience", "register", "response_type", "word_count", "suggested_minutes"],
                         "properties": {"title": STR, "scenario": STR, "prompt": STR, "instructions": {"type": "array", "minItems": 2, "items": STR}, "required_points": {"type": "array", "minItems": 1, "items": STR},
                                        "audience": STR, "register": STR, "response_type": STR, "suggested_minutes": {"type": "integer", "minimum": 1},
                                        "word_count": {"type": "object", "required": ["minimum", "suggested_min", "suggested_max", "maximum"],
                                                       "properties": {k: {"type": "integer", "minimum": 1} for k in ["minimum", "suggested_min", "suggested_max", "maximum"]}},
                                        "stimulus": {"type": "object", "required": ["type", "content"]}}}
        req = base_required + ["task_category"]
    else:
        props["task_format"] = {"type": "string", "enum": sorted(taxonomy()["speaking"]["formats"])}
        props["task"] = {"type": "object", "required": ["title", "format", "scenario", "prompt", "instructions", "main_question", "follow_up_questions", "preparation_seconds", "suggested_speaking_seconds", "typed_response_words"],
                         "properties": {"title": STR, "format": STR, "scenario": STR, "prompt": STR, "instructions": {"type": "array", "minItems": 2, "items": STR}, "main_question": STR,
                                        "follow_up_questions": {"type": "array", "items": STR}, "preparation_seconds": {"type": "integer", "minimum": 0}, "suggested_speaking_seconds": {"type": "integer", "minimum": 10},
                                        "typed_response_words": {"type": "object", "required": ["minimum", "suggested_min", "suggested_max"], "properties": {k: {"type": "integer", "minimum": 1} for k in ["minimum", "suggested_min", "suggested_max"]}},
                                        "cue_card": {"type": "object", "required": ["topic", "points"]}}}
        req = base_required + ["task_format"]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"lingoeasy/{skill}_part.schema.json",
            "title": f"Lingo Easy {skill.capitalize()} Part (productive-task schema v1.0; shares its structure with the other productive skill)",
            "type": "object", "required": req, "additionalProperties": False, "properties": props, "$defs": d}


def attempt_schema():
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "lingoeasy/productive_attempt.schema.json",
            "title": "Learner attempt for a Writing or Speaking Part (stored outside the question bank)", "type": "object",
            "required": ["attempt_id", "learner_id", "part_id", "part_uuid", "part_version", "part_content_hash", "skill", "response_modality", "response_text", "submitted_at"],
            "properties": {"attempt_id": STR, "learner_id": STR, "part_id": STR, "part_uuid": STR, "part_version": STR, "part_content_hash": STR,
                           "skill": {"enum": ["writing", "speaking"]}, "response_modality": {"enum": ["typed_text", "audio"]},
                           "response_text": {"type": "string"}, "word_count": {"type": "integer", "minimum": 0}, "time_spent_seconds": {"type": "number", "minimum": 0},
                           "submitted_at": STR,
                           "audio": {"type": "object", "description": "Optional. Present only for real audio attempts.",
                                     "properties": {"audio_asset_ref": STR, "audio_duration_seconds": {"type": "number"}, "transcript": STR, "stt_provider": STR, "stt_confidence": {"type": "number", "minimum": 0, "maximum": 1}}},
                           "evaluation": {"type": "object", "description": "Written later by the evaluation pipeline (not implemented in this task); follows evaluation_blueprint.evaluator_output_contract."}}}


def main():
    out = ROOT / "schemas"
    for skill in ("writing", "speaking"):
        write_json(out / f"{skill}_part.schema.json", part_schema(skill))
    d = defs()
    write_json(out / "evaluation_blueprint.schema.json", dict({"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "lingoeasy/evaluation_blueprint.schema.json", "title": "Evaluation blueprint"}, **d["blueprint"], **{"$defs": d}))
    write_json(out / "generation_metadata.schema.json", generation_metadata())
    write_json(out / "productive_attempt.schema.json", attempt_schema())
    base = part_schema("writing")
    base["$id"] = "lingoeasy/productive_task_base.schema.json"
    base["title"] = "Shared productive-task base (see writing_part / speaking_part for the concrete skills)"
    base["properties"]["skill"] = {"enum": ["writing", "speaking"]}
    base["required"] = [r for r in base["required"] if r != "task_category"]
    base["properties"].pop("task_category", None)
    base["properties"]["task"] = {"type": "object"}
    write_json(out / "productive_task_base.schema.json", base)
    print("schemas written:", sorted(p.name for p in out.glob("*.schema.json")))


if __name__ == "__main__":
    main()
