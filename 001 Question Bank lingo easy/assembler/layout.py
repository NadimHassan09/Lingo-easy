"""Single source of truth for the question-bank directory layout (all four skills).

question_bank/
  placement_test/<skill>/<PART_ID>/part.json
  assessment_test/<LEVEL>/<skill>/<PART_ID>/part.json

A "scope" is one directory that directly contains the skill folders (placement_test/, or assessment_test/<LEVEL>/).
assemble() and load_bank() work on a scope; everything else should go through the helpers below instead of hard-coding paths.
"""
from pathlib import Path

MCQ_SKILLS = ("listening", "reading")
PRODUCTIVE_SKILLS = ("writing", "speaking")
SKILLS = MCQ_SKILLS + PRODUCTIVE_SKILLS
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
PLACEMENT_DIR = "placement_test"
ASSESSMENT_DIR = "assessment_test"


def scope_dir(bank_root, mode, level=None):
    root = Path(bank_root)
    if mode == "placement":
        return root / PLACEMENT_DIR
    if mode == "assessment":
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        return root / ASSESSMENT_DIR / level
    raise ValueError(f"unknown mode {mode!r}")


def skill_dir(bank_root, mode, level, skill):
    return scope_dir(bank_root, mode, level) / skill


def iter_scopes(bank_root):
    """Yield (name, mode, level, directory) for the placement scope and the six assessment scopes."""
    yield "placement", "placement", None, scope_dir(bank_root, "placement")
    for lv in LEVELS:
        yield f"assessment_{lv}", "assessment", lv, scope_dir(bank_root, "assessment", lv)


def scope_of_path(bank_root, path):
    """('placement'|'assessment', level|None, skill) for a part.json path inside the bank."""
    rel = Path(path).resolve().relative_to(Path(bank_root).resolve()).parts
    if rel[0] == PLACEMENT_DIR:
        return "placement", None, rel[1]
    if rel[0] == ASSESSMENT_DIR:
        return "assessment", rel[1], rel[2]
    raise ValueError(f"not inside a known scope: {path}")
