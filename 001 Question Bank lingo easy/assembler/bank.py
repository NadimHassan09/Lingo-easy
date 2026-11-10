"""Load parts from one question-bank scope (placement_test/ or assessment_test/<LEVEL>/); read-only."""
import json
from pathlib import Path

from .layout import SKILLS


class BankError(Exception):
    """The bank contains something the assembler cannot safely use."""


def load_bank(bank_dir, allowed_statuses):
    """Return ({skill: [part, ...]}, [(path, reason), ...] for skipped files). Missing skill folders give empty lists."""
    bank = Path(bank_dir)
    parts = {s: [] for s in SKILLS}
    skipped = []
    for skill in SKILLS:
        for path in sorted((bank / skill).glob("*/part.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    part = json.load(f)
            except (OSError, ValueError) as e:
                skipped.append((str(path), f"unreadable: {e}"))
                continue
            if part.get("skill") != skill:
                skipped.append((str(path), f"skill is '{part.get('skill')}', folder is '{skill}'"))
                continue
            status = (part.get("meta") or {}).get("status")
            if status not in allowed_statuses:
                skipped.append((str(path), f"status '{status}' not allowed"))
                continue
            problem = minimal_problem(part)
            if problem:
                skipped.append((str(path), problem))
                continue
            parts[skill].append(part)
    return parts, skipped


def minimal_problem(part):
    """Cheap structural sanity check so a corrupt file can never break an exam mid-way."""
    if part.get("skill") in ("writing", "speaking"):
        for key in ("id", "title", "part_type", "task", "target_cefr"):
            if key not in part:
                return f"missing '{key}'"
        if not (part["task"] or {}).get("prompt"):
            return "productive part without a task prompt"
        if part["skill"] == "speaking" and not part["task"].get("main_question"):
            return "speaking part without a main question"
        return None
    for key in ("id", "title", "profile", "part_type", "question_groups"):
        if key not in part:
            return f"missing '{key}'"
    if part["skill"] == "listening" and not (part.get("audio") or {}).get("transcript"):
        return "listening part without transcript"
    if part["skill"] == "reading" and not (part.get("passage") or {}).get("paragraphs"):
        return "reading part without passage"
    for g in part["question_groups"]:
        for it in g.get("items", []):
            ids = [o.get("id") for o in it.get("options", [])]
            if it.get("answer") not in ids or not it.get("id"):
                return f"item {it.get('id', '?')} has no valid answer/options"
    return None
