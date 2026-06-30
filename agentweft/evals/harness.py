"""run a flow against fixed inputs.

the reason i cannot tell whether a prompt change helped is that the input is
different every time - it is my actual inbox. same input, different prompt, is
a comparison. different input, different prompt, is a vibe.

a case is a folder: what goes in, and which promises have to hold. there is no
expected output, because the output is not deterministic and pretending it is
would make this useless within a week.
"""
import os
from pathlib import Path

import yaml

ROOT = Path("evals")


def cases_for(flow):
    d = ROOT / flow / "cases"
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_dir())


def load_case(path):
    cfg = {}
    f = path / "case.yaml"
    if f.exists():
        cfg = yaml.safe_load(f.read_text()) or {}
    return {"name": path.name, "path": path,
            "inbox": path / cfg.get("inbox", "inbox"),
            "expect": cfg.get("expect") or {}}


def run_flow_for(flow, case):
    """point the flow at the case's inputs and run it. -> (output, budget)."""
    from agentweft.runner import engine

    old = {k: os.environ.get(k) for k in ("INBOX", "LOGS", "WATCH")}
    for k in old:
        os.environ[k] = str(case["inbox"])
    try:
        return engine.run_once(flow)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def score(spec, output, budget=None, seconds=None):
    """a case does not have an expected output; it has promises that either
    held or did not."""
    from agentweft.guardrails import promises

    rows = []
    for inv, ok, detail in promises.check(output, spec.promises.invariants):
        rows.append({"invariant": inv, "ok": ok, "detail": detail})
    checked = [r for r in rows if r["ok"] is not None]
    passed = len([r for r in checked if r["ok"]])
    return {"rows": rows, "passed": passed, "checked": len(checked),
            "skipped": len(rows) - len(checked),
            "calls": getattr(budget, "calls", 0),
            "tokens": getattr(budget, "tokens", 0),
            "seconds": int(seconds or 0)}


def table(flow, results):
    out = ["# " + flow, ""]
    total_p = total_c = 0
    for name, r in results:
        total_p = total_p + r["passed"]
        total_c = total_c + r["checked"]
        out.append("  " + name.ljust(20) + str(r["passed"]) + "/" + str(r["checked"])
                   + " promises, " + str(r["calls"]) + " calls, ~"
                   + str(r["tokens"]) + " tokens")
        for row in r["rows"]:
            if row["ok"] is False:
                out.append("      FAIL " + row["invariant"] + " - " + row["detail"])
            elif row["ok"] is None:
                out.append("      skip " + row["invariant"])
    out.append("")
    out.append("  total " + str(total_p) + "/" + str(total_c))
    return chr(10).join(out)
