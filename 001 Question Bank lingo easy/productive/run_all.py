"""Run the Writing/Speaking pipeline end to end and record every command, exit status and test count.

Usage: python -m productive.run_all
Outputs (lingo_easy_writing_speaking/reports): validation_commands.log, test_results.json (+ everything productive.build and productive.audit write)
"""
import datetime
import json
import re
import subprocess
import sys
import time

from .common import ROOT, write_json

REPORTS = ROOT / "lingo_easy_writing_speaking" / "reports"
STEPS = [
    ["-m", "productive.schemas_build"],
    ["-m", "productive.build"],
    ["-m", "productive.audit"],
    ["-m", "productive.validate"],
    ["scripts/validate_part.py", "--bank", "question_bank"],
]


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    log_path = REPORTS / "validation_commands.log"
    log_path.write_text(f"# productive pipeline run {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n", encoding="utf-8")
    log = []
    for step in STEPS:
        t0 = time.time()
        p = subprocess.run([sys.executable] + step, capture_output=True, text=True, cwd=ROOT)
        line = {"command": "python " + " ".join(step), "exit_status": p.returncode, "seconds": round(time.time() - t0, 1)}
        log.append(line)
        tail = (p.stdout + p.stderr).strip().splitlines()[-4:]
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n" + "".join("    | " + t + "\n" for t in tail))
        print(("OK  " if p.returncode == 0 else "FAIL"), " ".join(step))
        if p.returncode != 0:
            print((p.stdout + p.stderr)[-600:])
    t0 = time.time()
    p = subprocess.run([sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest", "discover", "-s", "tests", "-v"], capture_output=True, text=True, cwd=ROOT)
    out = p.stderr + p.stdout
    results = re.findall(r"^(test\w+) \(([\w.]+)\) \.\.\. (ok|FAIL|ERROR|skipped.*)$", out, flags=re.M)
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", out)
    cmd = {"command": "python -m unittest discover -s tests -v", "exit_status": p.returncode, "seconds": round(time.time() - t0, 1)}
    log.append(cmd)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(cmd) + "\n" + "".join("    | " + x + "\n" for x in out.strip().splitlines()[-4:]))
    per = [{"test": f"{c}.{n}", "outcome": o} for n, c, o in results]
    suites = {}
    for r in per:
        mod = r["test"].split(".")[0]
        suites.setdefault(mod, {"ok": 0, "other": 0})["ok" if r["outcome"] == "ok" else "other"] += 1
    summary = {"command": cmd["command"], "exit_status": p.returncode, "tests_run": int(ran.group(1)) if ran else None,
               "passed": sum(1 for r in per if r["outcome"] == "ok"), "failed": sum(1 for r in per if r["outcome"] == "FAIL"),
               "errors": sum(1 for r in per if r["outcome"] == "ERROR"), "skipped": sum(1 for r in per if r["outcome"].startswith("skipped")),
               "by_module": suites, "tests": per, "executed_commands": log,
               "not_run": ["FastAPI app (server/app.py) is exercised outside this suite with a TestClient in a throw-away venv, because fastapi is not a project test dependency",
                           "Browser end-to-end checks were driven manually through the in-app browser; they are not part of the automated suite"]}
    write_json(REPORTS / "test_results.json", summary)
    print(f"tests run={summary['tests_run']} passed={summary['passed']} failed={summary['failed']} errors={summary['errors']} skipped={summary['skipped']} exit={p.returncode}")
    return 0 if p.returncode == 0 and all(s["exit_status"] == 0 for s in log) else 1


if __name__ == "__main__":
    sys.exit(main())
