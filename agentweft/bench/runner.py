"""a set of tasks, run through one flow k times each and scored.

a set is a folder: `bench.yaml` (the flow, the provider, k) and one folder per
task. a task is a `TASK.md`, the request the run is given; a `hidden/` suite
the run never sees; and the project it starts from, its own `repo/` or the
set's. a `task.yaml` may say `kind: probe`, a request the project's spec rules
out, whose right answer is a recorded refusal.

every run works on a fresh copy of the project, and the hidden suite is
scored against what it left there.
"""
import shutil
import tempfile
import time
from pathlib import Path

import yaml

from . import mutants, scorer

CONF = "bench.yaml"
ASK = "TASK.md"


def read_yaml(path):
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load(folder):
    """-> (conf, tasks, problems). a task with a problem is one the set
    cannot be scored on, so any problem refuses the whole set."""
    folder = Path(folder)
    conf = read_yaml(folder / CONF)
    tasks, problems = [], []
    for d in sorted(p for p in folder.iterdir() if p.is_dir()):
        # the set's own project carries the spec as a TASK.md of its own
        if d.name == "repo" or not (d / ASK).is_file():
            continue
        repo = d / "repo" if (d / "repo").is_dir() else folder / "repo"
        kind = read_yaml(d / "task.yaml").get("kind", scorer.FEATURE)
        if not scorer.tests_in(d / "hidden"):
            problems.append(d.name + ": no hidden suite. a task is scored by "
                            "tests in " + d.name + "/hidden/ that the run "
                            "never sees, and without them there is no score")
        if not repo.is_dir():
            problems.append(d.name + ": no project to start from, neither "
                            + d.name + "/repo/ nor the set's repo/")
        if kind not in scorer.KINDS:
            problems.append(d.name + ": kind " + str(kind) + " is not one of "
                            + ", ".join(scorer.KINDS))
        tasks.append({"name": d.name, "kind": kind, "repo": repo,
                      "hidden": d / "hidden",
                      "ask": (d / ASK).read_text(encoding="utf-8-sig")})
    if not tasks:
        problems.append("no task under " + str(folder) + ": a task is a "
                        "folder with a " + ASK + " in it")
    return conf, tasks, problems


def one(flow, spec, provider, t, attempt, start, mutate=False):
    """-> the scored row for one run of `flow` on task `t`, with each added
    test's kill signature when `mutate`."""
    from agentweft.evals import harness, steps
    from agentweft.runner import engine, task
    from agentweft.runner.prompts import flow_path

    with tempfile.TemporaryDirectory(prefix="bench-run-") as tmp:
        place = Path(tmp) / "repo"
        shutil.copytree(str(t["repo"]), str(place), ignore=scorer.SKIP)
        trail = Path(tmp) / "trail"
        trail.mkdir()
        began = time.time()
        budget = None
        try:
            asked = task.settle(flow, task.places(flow_path(flow), spec),
                                t["ask"])
            _, budget, stopped = engine.run_once(
                flow, provider=provider, task=asked, trail=trail,
                workdir=place)
        except Exception as e:
            stopped = "failed: " + str(e)
        wall = round(time.time() - began, 1)
        record = steps.read(trail)
        end = scorer.hidden(t["hidden"], place)
        new = scorer.added(t["repo"], place)
        pinned = scorer.pins(t["repo"], place, new)
        killed = mutants.score(t["repo"], place) if mutate else None
        word = scorer.outcome(stopped, record, trail)
    row = {"task": t["name"], "kind": t["kind"], "attempt": attempt}
    row.update(scorer.axes(t["kind"], word, start, end))
    money = budget.money() if hasattr(budget, "money") else {}
    row.update({"why": stopped,
                "red_first": scorer.red_first(record),
                "tests_added": new,
                "pins": pinned,
                "usd": money.get("usd"),
                "usd_estimated": money.get("estimated", False),
                "calls": getattr(budget, "calls", 0),
                "tokens": getattr(budget, "tokens", 0),
                "wall": wall,
                "key": harness.produced_by(flow, spec, {"provider": provider},
                                           record)})
    if killed is not None:
        row["mutants"] = killed
    return row


def run(flow, provider, tasks, k, said=print, mutate=False, scored=None):
    """-> every run's row, k per task, in task order. `scored` is called
    with the rows so far after each run, so a bench that dies keeps them."""
    from agentweft.runner.config import config

    spec = config(flow)
    rows = []
    for t in tasks:
        with tempfile.TemporaryDirectory(prefix="bench-start-") as tmp:
            seed = Path(tmp) / "repo"
            shutil.copytree(str(t["repo"]), str(seed), ignore=scorer.SKIP)
            start = scorer.hidden(t["hidden"], seed)
        for attempt in range(1, k + 1):
            said("  " + t["name"] + " " + str(attempt) + "/" + str(k))
            rows.append(one(flow, spec, provider, t, attempt, start,
                            mutate))
            if scored is not None:
                scored(rows)
    return rows


def cell(value):
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return "-"
    return str(value)


def table(flow, rows, total):
    head = ("task", "try", "outcome", "correct", "fixed", "regressed",
            "red first", "tests/pins", "usd", "wall")
    lines = []
    for r in rows:
        h = r["hidden"]
        usd = "-" if r["usd"] is None else (
            ("~" if r["usd_estimated"] else "") + "%.4f" % r["usd"])
        lines.append((r["task"], str(r["attempt"]), r["outcome"],
                      cell(r["core_correct"]),
                      str(h["fixed"]) + "/" + str(h["red_at_start"]),
                      str(len(h["regressed"])), r["red_first"],
                      str(len(r["tests_added"])) + "/" + str(len(r["pins"])),
                      usd, str(r["wall"]) + "s"))
    widths = [max(len(x[i]) for x in [head] + lines) for i in range(len(head))]
    out = ["# bench " + flow, ""]
    for x in [head] + lines:
        out.append("  " + "  ".join(v.ljust(widths[i])
                                    for i, v in enumerate(x)).rstrip())
    n, k = total["tasks"], total["k"]
    rates = total["rate_per_repeat"]
    per = total["cost_per_correct"]
    out += ["",
            "  N " + str(n) + " tasks, k " + str(k) + ", " + str(total["runs"])
            + " runs",
            "  correct " + str(total["correct"]) + "/" + str(total["runs"])
            + ", per repeat " + ", ".join(str(r) for r in rates)
            + " (spread " + "-".join(str(r) for r in total["rate_spread"])
            + ")",
            "  finished " + str(total["finished"]) + ", false success "
            + str(total["false_success"]) + ", false refusal "
            + str(total["false_refusal"]),
            "  probe stops " + (", ".join(w + " x" + str(c) for w, c in
                                          sorted(total["probe_stops"].items()))
                                or "none"),
            "  red first by gate " + ", ".join(
                w + " " + str(c) for w, c in total["red_first"].items()),
            "  tests added " + str(total["tests_added"]) + ", pins "
            + str(total["pins"]),
            "  cost per correct " + (per if isinstance(per, str) else
                                     ("~" if total["usd_estimated"] else "")
                                     + "$%.4f" % per)
            + ", every attempt counted",
            "  wall " + str(total["wall"]) + "s (per run "
            + "-".join(str(w) for w in total["wall_spread"]) + "s)"]
    if "duplicate_at" in total:
        out.append("  mutants: distinct signatures " + str(total["signatures"])
                   + ", likely duplicate tests " + str(total["duplicates"])
                   + ", not enough mutants to judge "
                   + str(total["undecided"])
                   + ", pins " + str(total["mutant_pins"])
                   + ", duplicate threshold " + str(total["duplicate_at"])
                   + ", minimum to judge " + str(total["minimum"]))
    for r in rows:
        if "mutants" in r:
            out += ["", "## " + r["task"] + " " + str(r["attempt"])]
            out += ["  " + line for line in mutants.lines(r["mutants"])]
    return "\n".join(out)
