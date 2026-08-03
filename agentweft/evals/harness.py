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
            "provider": cfg.get("provider") or {},
            "expect": cfg.get("expect") or {}}


def run_flow_for(flow, case):
    """point the flow at the case's inputs and run it. -> (output, budget).

    the case says which provider, and it has to win: the cases have declared
    `provider: fake` since the day they were written and nothing read it, so
    every eval run was calling the flow's real provider and charging for it.
    """
    from agentweft.runner import engine

    old = {k: os.environ.get(k) for k in ("INBOX", "LOGS", "WATCH")}
    for k in old:
        os.environ[k] = str(case["inbox"])
    try:
        return engine.run_once(flow, provider=case.get("provider"))
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


LAST = ROOT / ".last.json"


def save_scores(flow, results):
    import json

    ROOT.mkdir(exist_ok=True)
    blob = {}
    if LAST.exists():
        blob = json.loads(LAST.read_text(encoding="utf-8"))
    blob[flow] = {name: {"passed": r["passed"], "checked": r["checked"],
                         "calls": r["calls"], "tokens": r["tokens"]}
                  for name, r in results}
    LAST.write_text(json.dumps(blob, indent=2), encoding="utf-8")


def previous(flow):
    import json

    if not LAST.exists():
        return {}
    return json.loads(LAST.read_text(encoding="utf-8")).get(flow, {})


def compare(flow, results):
    """what got worse since the last scored run. this is the whole point - a
    single score tells me nothing, a score against last time is a decision."""
    was = previous(flow)
    if not was:
        return ["  (no previous run to compare against)"]
    out = []
    for name, r in results:
        before = was.get(name)
        if not before:
            out.append("  " + name + "  new")
            continue
        d = r["passed"] - before["passed"]
        dt = r["tokens"] - before["tokens"]
        mark = "same" if d == 0 else ("BETTER +" + str(d) if d > 0 else "WORSE " + str(d))
        out.append("  " + name.ljust(20) + mark
                   + "  (" + str(before["passed"]) + "/" + str(before["checked"])
                   + " -> " + str(r["passed"]) + "/" + str(r["checked"]) + ")"
                   + ("  tokens " + ("+" if dt >= 0 else "") + str(dt) if dt else ""))
    return out


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
    out.append("")
    out.append("since the last scored run:")
    out.extend(compare(flow, results))
    return chr(10).join(out)
