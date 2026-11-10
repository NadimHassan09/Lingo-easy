"""Run the whole QA pipeline and record every command, exit status and test counts.

Usage: python -m qa.run_all [N_SEEDS]    (patches are applied separately and idempotently: python -m qa.apply_patches)
Outputs: reports/validation_commands.log, reports/test_results.json
"""
import datetime
import json
import re
import subprocess
import sys
import time

from .common import *  # noqa: F401,F403

N = sys.argv[1] if len(sys.argv) > 1 else "1000"
STEPS = [
    ["-m", "qa.stage1_inventory_integrity"],
    ["-m", "qa.apply_patches"],
    ["-m", "qa.stage3_semantic"],
    ["-m", "qa.stage4_cefr"],
    ["-m", "qa.stage5_taxonomy"],
    ["-m", "qa.stage6_diagnostics"],
    ["-m", "qa.stage7_blueprint"],
    ["-m", "qa.stage8_simulation", N],
    ["-m", "qa.stage9_adaptive_examples"],
    ["-m", "qa.stage10_review_queue"],
    ["scripts/validate_part.py", "--bank", "question_bank"],
]


def run(cmd, log):
    t0 = time.time()
    p = subprocess.run([sys.executable] + cmd, capture_output=True, text=True, cwd=ROOT)
    dt = time.time() - t0
    line = {"command": "python " + " ".join(cmd), "cwd": str(ROOT), "exit_status": p.returncode, "seconds": round(dt, 1),
            "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    log.append(line)
    tail = (p.stdout + p.stderr).strip().splitlines()[-6:]
    with open(REPORTS / "validation_commands.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
        for t in tail:
            f.write("    | " + t + "\n")
    return p


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "validation_commands.log").write_text(f"# QA pipeline run {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n", encoding="utf-8")
    log = []
    for s in STEPS:
        p = run(s, log)
        print(("OK  " if p.returncode == 0 else "FAIL"), " ".join(s))
        if p.returncode != 0:
            print((p.stdout + p.stderr)[-800:])
            break
    # tests: legacy + QA suites together, verbose to capture per-test outcome
    t0 = time.time()
    p = subprocess.run([sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest", "discover", "-s", "tests", "-v"], capture_output=True, text=True, cwd=ROOT)
    out = p.stderr + p.stdout
    results = re.findall(r"^(test\w+) \(([\w.]+)\) \.\.\. (ok|FAIL|ERROR|skipped.*)$", out, flags=re.M)
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", out)
    cmdline = {"command": "python -m unittest discover -s tests -v", "cwd": str(ROOT), "exit_status": p.returncode, "seconds": round(time.time() - t0, 1),
               "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    log.append(cmdline)
    with open(REPORTS / "validation_commands.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(cmdline) + "\n" + "\n".join("    | " + x for x in out.strip().splitlines()[-5:]) + "\n")
    per = [{"test": f"{c}.{n}", "outcome": o} for n, c, o in results]
    summary = {"command": cmdline["command"], "exit_status": p.returncode, "tests_run": int(ran.group(1)) if ran else None,
               "passed": sum(1 for r in per if r["outcome"] == "ok"), "failed": sum(1 for r in per if r["outcome"] == "FAIL"),
               "errors": sum(1 for r in per if r["outcome"] == "ERROR"), "tests": per,
               "executed_commands": log, "notes": ["Counts parsed from unittest -v output of the run above; nothing is carried over from earlier runs."]}
    write_json(REPORTS / "test_results.json", summary)
    print(f"tests run={summary['tests_run']} passed={summary['passed']} failed={summary['failed']} errors={summary['errors']} exit={p.returncode}")


if __name__ == "__main__":
    main()
