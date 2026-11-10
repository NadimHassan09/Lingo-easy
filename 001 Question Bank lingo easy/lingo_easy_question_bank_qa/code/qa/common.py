"""Shared helpers for the Lingo Easy question-bank QA pipeline (read-only access to the bank)."""
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "question_bank"
OUT = ROOT / "lingo_easy_question_bank_qa"
REPORTS = OUT / "reports"
AUDIT = OUT / "audit"
CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
REVIEW_VERSION = "qa-1.0"

STOP = set("""a an the of to in on at for from by with and or but if then than so as is are was were be been being it its this that these those
i you he she we they me him her us them my your his our their do does did done have has had not no yes can could will would shall should may might must
there here which who whom whose what when where why how about into over under out up down off more most some any each all both such very just only also""".split())


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text).lower().replace("'", ""))).strip()


def toks(text):
    return [w for w in norm(text).split() if w not in STOP and len(w) > 1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_parts():
    """Return a list of dicts: {path, rel, bank, level_dir, part}. Placement parts have bank='placement'."""
    out = []
    for p in sorted(BANK.glob("**/part.json")):
        rel = p.relative_to(ROOT).as_posix()
        parts = p.relative_to(BANK).parts
        bank = "placement" if parts[0] in ("listening", "reading") else "assessment_" + parts[1]
        out.append({"path": p, "rel": rel, "bank": bank, "part": json.loads(p.read_text(encoding="utf-8")), "sha256": sha(p)})
    return out


def source_units(part):
    """List of (label, text) source units: reading paragraphs or listening turns."""
    if part["skill"] == "reading":
        return [(x["label"], x["text"]) for x in part["passage"]["paragraphs"]]
    return [(f"turn{i + 1}", t["text"]) for i, t in enumerate(part["audio"]["transcript"])]


def source_text(part):
    return " ".join(t for _, t in source_units(part))


def items_of(part):
    for g in part["question_groups"]:
        for it in g["items"]:
            yield g, it


def write_csv(path, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def is_numeric_text(s):
    return bool(re.search(r"\d", s)) or bool(re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|half|quarter|third)\b", s.lower()))
