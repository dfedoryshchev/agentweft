"""run a flow against fixed inputs.

the reason i cannot tell whether a prompt change helped is that the input is
different every time - it is my actual inbox. same input, different prompt, is
a comparison. different input, different prompt, is a vibe.

a case is a folder: what goes in, and which promises have to hold. there is no
expected output, because the output is not deterministic and pretending it is
would make this useless within a week.
"""
import os
import tempfile
from pathlib import Path

import yaml

from . import recording, steps

ROOT = Path("evals")


def cases_for(flow):
    d = ROOT / flow / "cases"
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_dir())


def load_case(path):
    """a case's `task` is a `task:` line in case.yaml or, for anything longer,
    a task.md beside it, and None for a case whose flow takes none."""
    cfg = {}
    f = path / "case.yaml"
    if f.exists():
        cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    task = cfg.get("task")
    md = path / "task.md"
    if md.is_file():
        if task is not None:
            raise ValueError(path.name + " has a task.md and a task: in "
                             "case.yaml. keep one")
        task = md.read_bytes().decode("utf-8")
    kept = path / recording.FILE
    return {"name": path.name, "path": path,
            "recording": kept if kept.is_file() else None,
            "inbox": path / cfg.get("inbox", "inbox"),
            "provider": cfg.get("provider") or {},
            "expect": cfg.get("expect") or {},
            "task": task}


class Ran(tuple):
    """(output, budget, why it stopped short or ""), plus `steps`: the lines
    of the run's steps.jsonl."""

    def __new__(cls, out, budget, stopped, record=()):
        self = tuple.__new__(cls, (out, budget, stopped))
        self.steps = list(record)
        return self


def run_flow_for(flow, case, record=False):
    """point the flow at the case's inputs and run it.

    -> a Ran: (output, budget, why it stopped short or ""), and its steps.

    the case says which provider, and it has to win: the cases have declared
    `provider: fake` since the day they were written and nothing read it, so
    every eval run was calling the flow's real provider and charging for it.

    a case with a recording beside it is answered from that and calls
    nothing. `record` runs the case's provider and writes what it answered
    there, over whatever was recorded before.
    """
    from agentweft import providers
    from agentweft.runner import engine, task
    from agentweft.runner.config import config
    from agentweft.runner.prompts import flow_path

    # the same refusal run.py gives, as the reason the run did not finish:
    # a task-taking flow run without one would be scored on an empty ask
    try:
        asked = task.settle(flow, task.places(flow_path(flow), config(flow)),
                            case.get("task"))
    except ValueError as e:
        return Ran("", None, str(e))
    pinned = case.get("provider")
    replay = recorder = None
    if record:
        if not pinned:
            return Ran("", None, (case["name"] + " names no provider in "
                                  "case.yaml, so there is no one to record"))
        pinned = recorder = recording.Recorder(providers.build(pinned))
    elif case.get("recording"):
        pinned = replay = recording.Replay.load(case["recording"])
    old = {k: os.environ.get(k) for k in ("INBOX", "LOGS", "WATCH")}
    for k in old:
        # the path is in the prompt, and a recording made on Windows has to
        # hash the same on Linux
        os.environ[k] = Path(case["inbox"]).as_posix()
    with tempfile.TemporaryDirectory() as folder:
        try:
            out = engine.run_once(flow, provider=pinned, task=asked,
                                  trail=Path(folder))
        except recording.Mismatch as e:
            return Ran("", None, str(e), steps.read(Path(folder)))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        took = steps.read(Path(folder))
    if recorder is not None:
        recorder.save(case["path"] / recording.FILE)
    if replay is not None and replay.unused():
        return Ran(out[0], out[1], (recording.PREFIX + "has answers the run "
                                    "never asked for: "
                                    + ", ".join(replay.unused())), took)
    return Ran(out[0], out[1], out[2], took)


def score(spec, output, budget=None, stopped="", seconds=None, steps=(),
          expect=None):
    """a case does not have an expected output; it has promises that either
    held or did not, and a run that got to the end or did not.

    the second one is a row of its own because the text cannot say it: a gate
    on the last step leaves that step's text behind, and an empty text keeps
    every promise there is.

    a case can also expect the steps the run took and how many calls it
    made, held against `steps`, the run's own record of them."""
    from agentweft.guardrails import promises

    from . import steps as took

    rows = [{"invariant": "the run got to the end", "ok": not stopped,
             "detail": stopped or "every step ran"}]
    for inv, ok, detail in promises.check(output, spec.promises.invariants):
        rows.append({"invariant": inv, "ok": ok, "detail": detail})
    rows.extend(took.rows(expect or {}, steps,
                          getattr(budget, "calls", 0)))
    checked = [r for r in rows if r["ok"] is not None]
    passed = len([r for r in checked if r["ok"]])
    money = budget.money() if hasattr(budget, "money") else {}
    return {"rows": rows, "passed": passed, "checked": len(checked),
            "usd": money.get("usd"),
            "usd_estimated": money.get("estimated", False),
            "reported_usd": money.get("reported_usd"),
            "spent": budget.spent() if hasattr(budget, "spent") else "",
            "skipped": len(rows) - len(checked),
            "calls": getattr(budget, "calls", 0),
            "tokens": getattr(budget, "tokens", 0),
            "metered": budget.metered() if hasattr(budget, "metered")
            else "estimated",
            "seconds": int(seconds or 0)}


LAST = ROOT / ".last.json"


def save_scores(flow, results):
    import json

    ROOT.mkdir(exist_ok=True)
    blob = {}
    if LAST.exists():
        blob = json.loads(LAST.read_text(encoding="utf-8"))
    blob.setdefault(flow, {}).update(
        {name: {"passed": r["passed"], "checked": r["checked"],
                "calls": r["calls"], "tokens": r["tokens"],
                "usd": r.get("usd"),
                "usd_estimated": r.get("usd_estimated", False)}
         for name, r in results})
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
                   + " promises, " + str(r["calls"]) + " calls, "
                   + ("" if r.get("metered") == "counted" else "~")
                   + str(r["tokens"]) + " tokens "
                   + r.get("metered", "estimated")
                   + (", " + r["spent"] if r.get("spent") else "")
                   + (", replayed" if r.get("replayed") else ""))
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
