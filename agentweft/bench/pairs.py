"""a second run on the same repo: what the facts the first run left save the
run after it.

a pair set is a folder: `bench.yaml` (the flow, the provider, k) and one
folder per pair:

    first.md        the task that leaves facts behind (run 1)
    second.md       a related task on the same files (run 2)
    hidden/         the suite run 2 is scored on, never seen by a run
    repo/           the project both runs start from, or the set's repo/
    gold.yaml       what run 1 should leave, and what run 2 is held to

gold.yaml, written before anything runs:

    trail:                    the facts a careful retro keeps after run 1
      - scope: [pkg/]
        kind: convention
    false:                    a fact on one of these scopes whose claim holds
      - scope: [pkg/cli.py]   every word is one the record does not back
        words: [prints]
    convention:               the project's documented way run 2 must follow
      scope: [pkg/]
      check: [python, check.py]

the check runs in the pair's folder with TASK_REPO naming the place, the way
the hidden suite does, so it is never in the project a run sees; exit 0 is
the convention held.

each repeat runs run 1 on a fresh copy of the project, then run 2 on what run
1 left: the `lane` arm, handed the facts run 1 kept. with `twin`, run 2 also
runs on a copy of what run 1 left, without its facts/ folder, with the flow's
`lane: off`: the `twin` arm, the same run with no fact handed or on disk, so
the two differ in the facts alone.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from agentweft.orchestrate import facts

from . import runner, scorer

GOLD = "gold.yaml"
FIRST = "first.md"
SECOND = "second.md"
LANE = "lane"
TWIN = "twin"
# the probation rules, set before any pair ran: more new facts than this in
# one run is spam, and fewer than one in this many attached facts used is a
# lane that hands steps what they never touch
MOST_FACTS = 3
ONE_IN = 4
HONOURED = "honoured"
CONTRADICTED = "contradicted"
UNTOUCHED = "untouched"
UNCHECKED = "not checked"
VERDICTS = (HONOURED, CONTRADICTED, UNTOUCHED, UNCHECKED)
# what a run writes that is not its change to the project
NOT_THE_CHANGE = (".git", facts.FOLDER, "__pycache__", ".pytest_cache")


def load(folder):
    """-> (conf, pairs, problems). a pair with a problem cannot be scored,
    so any problem refuses the whole set."""
    folder = Path(folder)
    conf = runner.read_yaml(folder / runner.CONF)
    pairs, problems = [], []
    for d in sorted(p for p in folder.iterdir() if p.is_dir()):
        if d.name == "repo" or not (d / FIRST).is_file():
            continue
        repo = d / "repo" if (d / "repo").is_dir() else folder / "repo"
        gold = runner.read_yaml(d / GOLD)
        if not (d / SECOND).is_file():
            problems.append(d.name + ": no " + SECOND + ", the task run 2 is"
                            " given")
        if not scorer.tests_in(d / "hidden"):
            problems.append(d.name + ": no hidden suite in " + d.name
                            + "/hidden/ to score run 2 on")
        if not repo.is_dir():
            problems.append(d.name + ": no project to start from, neither "
                            + d.name + "/repo/ nor the set's repo/")
        said = gold.get("convention") or {}
        if not said.get("scope") or not said.get("check"):
            problems.append(d.name + ": " + GOLD + " names no convention with"
                            " a scope and a check, so run 2 holds to nothing")
        pairs.append({"name": d.name, "folder": d, "repo": repo, "gold": gold,
                      "hidden": d / "hidden",
                      "first": read(d / FIRST), "second": read(d / SECOND)})
    if not pairs:
        problems.append("no pair under " + str(folder) + ": a pair is a folder"
                        " with a " + FIRST + " in it")
    return conf, pairs, problems


def read(path):
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def files_of(place):
    """-> {path: sha256} of the project's own files in `place`."""
    place = Path(place)
    out = {}
    for p in place.rglob("*"):
        rel = p.relative_to(place)
        if p.is_file() and not set(rel.parts) & set(NOT_THE_CHANGE):
            out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def changed(before, after):
    """-> the paths added, removed or changed between two `files_of`."""
    return sorted(p for p in set(before) | set(after)
                  if before.get(p) != after.get(p))


def touches(scopes, paths):
    return any(facts.rank(facts.norm(s), facts.norm(p)) is not None
               for s in scopes for p in paths)


def check(pair, place, said):
    """-> the exit code of the convention's check on `place`, None when it
    could not run or ran past the hidden suite's limit."""
    argv = [str(a) for a in said]
    if argv and argv[0] in ("python", "python3", "py"):
        argv[0] = sys.executable
    env = dict(os.environ, TASK_REPO=str(Path(place).resolve()),
               PYTHONDONTWRITEBYTECODE="1")
    try:
        return scorer.bounded(argv, pair["folder"], env, scorer.TIMEOUT)
    except OSError:
        return None


def convention(pair, place, paths):
    """-> how run 2 stood to the pair's convention: honoured or contradicted
    when its change reached the convention's scope, untouched when it did
    not, not checked when the check could not say."""
    said = pair["gold"].get("convention") or {}
    if not touches(said.get("scope") or [], paths):
        return UNTOUCHED
    code = check(pair, place, said.get("check") or [])
    if code is None:
        return UNCHECKED
    return HONOURED if code == 0 else CONTRADICTED


def kept(record):
    """-> the ids of the facts the run's retro had the runner write."""
    out = []
    for line in record:
        for id in ((line.get("facts") or {}).get("written") or []):
            if id not in out:
                out.append(id)
    return out


def scope_set(scopes):
    return set(facts.norm(s).rstrip("/").lower() for s in scopes or [])


def against_gold(written, gold):
    """-> (the gold trail entries a written fact matches by scope and kind,
    the ids of the written facts the gold names false)."""
    found = []
    for n, want in enumerate(gold.get("trail") or []):
        if any(scope_set(f.scopes) & scope_set(want.get("scope"))
               and f.kind == want.get("kind") for f in written):
            found.append(n)
    false = []
    for f in written:
        claim = f.claim.lower()
        if any(scope_set(f.scopes) & scope_set(bad.get("scope"))
               and all(str(w).lower() in claim
                       for w in bad.get("words") or [])
               for bad in gold.get("false") or []):
            false.append(f.id)
    return found, false


def handed(record):
    """-> [step, fact id] for every fact a step of the run was handed."""
    return [[line.get("step"), id] for line in record
            for id in line.get("facts_attached") or []]


def used(given, found, paths):
    """-> the [step, id] pairs whose fact holds for a path the run changed,
    read from the whole run's diff: a step's own diff is not kept."""
    by_id = dict((f.id, f) for f in found)
    return [[step, id] for step, id in given
            if id in by_id and touches(by_id[id].scopes, paths)]


def steps_of(record):
    return [{"step": l.get("step"), "seconds": l.get("seconds"),
             "tokens": l.get("tokens"), "cost": l.get("cost")}
            for l in record]


def once(flow, spec, provider, asked, place, trail):
    """-> (what the run returned or why it stopped, its budget, seconds)."""
    from agentweft.runner import engine, task
    from agentweft.runner.prompts import flow_path

    began = time.time()
    budget = None
    try:
        settled = task.settle(flow, task.places(flow_path(flow), spec), asked)
        _, budget, stopped = engine.run_once(flow, provider=provider,
                                             task=settled, trail=trail,
                                             workdir=place)
    except Exception as e:
        stopped = "failed: " + str(e)
    return stopped, budget, round(time.time() - began, 1)


def lane_off(flow, where):
    """-> a flows folder holding a copy of `flow` that says `lane: off`."""
    from agentweft.runner.prompts import flow_path

    copy = Path(where) / "flows" / flow
    shutil.copytree(str(flow_path(flow)), str(copy))
    yml = copy / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8").rstrip("\n")
                   + "\nlane: off\n", encoding="utf-8")
    return copy.parent


def money_of(budget):
    return budget.money() if hasattr(budget, "money") else {}


def second(flow, spec, provider, pair, place, start, tmp, arm):
    """-> run 2 of one arm in `place`, scored."""
    from agentweft.evals import steps

    trail = Path(tmp) / ("trail-" + arm)
    trail.mkdir()
    before = files_of(place)
    stopped, budget, wall = once(flow, spec, provider, pair["second"], place,
                                 trail)
    record = steps.read(trail)
    paths = changed(before, files_of(place))
    end = scorer.hidden(pair["hidden"], place)
    given = handed(record)
    money = money_of(budget)
    out = {"arm": arm, "why": stopped, "changed": paths,
           "convention": convention(pair, place, paths),
           "facts_attached": given,
           "facts_used": used(given, facts.read(place), paths),
           "facts_written": len(kept(record)),
           "usd": money.get("usd"),
           "usd_estimated": money.get("estimated", False),
           "calls": getattr(budget, "calls", 0),
           "tokens": getattr(budget, "tokens", 0),
           "wall": wall, "steps": steps_of(record)}
    out.update(scorer.axes(scorer.FEATURE,
                           scorer.outcome(stopped, record, trail, place),
                           start, end))
    return out


def first(flow, spec, provider, pair, place, tmp):
    """-> run 1 in `place`, scored on the facts it left against the gold."""
    from agentweft.evals import steps

    trail = Path(tmp) / "trail-first"
    trail.mkdir()
    stopped, budget, wall = once(flow, spec, provider, pair["first"], place,
                                 trail)
    record = steps.read(trail)
    ids = kept(record)
    found, false = against_gold([f for f in facts.read(place) if f.id in ids],
                                pair["gold"])
    return {"why": stopped,
            "outcome": scorer.outcome(stopped, record, trail, place),
            "facts_written": len(ids),
            "trail": len(pair["gold"].get("trail") or []),
            "trail_found": len(found), "false_facts": false,
            "usd": money_of(budget).get("usd"), "wall": wall,
            "steps": steps_of(record)}


def without_facts(place):
    """-> a copytree ignore that leaves out the store run 1 left at the top
    of `place`, and nothing else: a project's own folder named facts deeper
    down is the project's."""
    top = Path(place).resolve()

    def ignore(where, names):
        if Path(where).resolve() == top and facts.FOLDER in names:
            return [facts.FOLDER]
        return []

    return ignore


def one(flow, spec, provider, pair, attempt, twin=False):
    """-> one repeat of a pair: run 1, then run 2 in each arm."""
    from agentweft.runner import prompts

    with tempfile.TemporaryDirectory(prefix="bench-pair-",
                                     ignore_cleanup_errors=True) as tmp:
        place = Path(tmp) / "repo"
        shutil.copytree(str(pair["repo"]), str(place), ignore=scorer.SKIP)
        ran = first(flow, spec, provider, pair, place, tmp)
        start = scorer.hidden(pair["hidden"], place)
        if twin:
            off = Path(tmp) / "repo-twin"
            shutil.copytree(str(place), str(off), ignore=without_facts(place))
            if facts.folder(off).exists():
                raise RuntimeError("the twin's copy still holds "
                                   + facts.FOLDER + "/, so the arms would not"
                                   " differ in the facts alone")
        arms = {LANE: second(flow, spec, provider, pair, place, start, tmp,
                             LANE)}
        if twin:
            was = list(prompts.FLOW_ROOT)
            prompts.FLOW_ROOT[:0] = [str(lane_off(flow, tmp))]
            try:
                arms[TWIN] = second(flow, spec, provider, pair, off, start,
                                    tmp, TWIN)
            finally:
                prompts.FLOW_ROOT[:] = was
    return {"pair": pair["name"], "attempt": attempt, "first": ran,
            "second": arms}


def run(flow, provider, pairs, k, twin=False, said=print, scored=None):
    """-> every repeat's row, k per pair. `scored` is called with the rows
    so far after each, so a bench that dies keeps them."""
    from agentweft.runner.config import config

    spec = config(flow)
    rows = []
    for pair in pairs:
        for attempt in range(1, k + 1):
            said("  " + pair["name"] + " " + str(attempt) + "/" + str(k))
            rows.append(one(flow, spec, provider, pair, attempt, twin))
            if scored is not None:
                scored(rows)
    return rows


def probation(rows):
    """-> the probation rules over `rows`: no run writes more than
    MOST_FACTS new facts, at least one in ONE_IN attached facts is used by
    the run it was handed to, and no fact the gold names false is written.
    a false fact kills the write path until it is fixed and measured
    again. the twin keeps no fact and is handed none, so it is not read."""
    lanes = [r["second"][LANE] for r in rows if LANE in r["second"]]
    counts = [r["first"]["facts_written"] for r in rows] + [
        s["facts_written"] for s in lanes]
    spam = len([n for n in counts if n > MOST_FACTS])
    attached = sum(len(s["facts_attached"]) for s in lanes)
    usedn = sum(len(s["facts_used"]) for s in lanes)
    false = [id for r in rows for id in r["first"]["false_facts"]]
    used_ok = None if not attached else usedn * ONE_IN >= attached
    return {"facts_per_run": counts, "most": max(counts) if counts else 0,
            "spam": spam, "attached": attached, "used": usedn,
            "used_ok": used_ok, "false_facts": false, "kill": bool(false),
            "holds": not spam and used_ok is not False and not false}


def summary(rows, k):
    out = {"pairs": len({r["pair"] for r in rows}), "k": k,
           "probation": probation(rows)}
    for arm in (LANE, TWIN):
        ran = [r["second"][arm] for r in rows if arm in r["second"]]
        if not ran:
            continue
        priced = [s["usd"] for s in ran if s["usd"] is not None]
        out[arm] = {"runs": len(ran),
                    "correct": len([s for s in ran if s["core_correct"]]),
                    "finished": len([s for s in ran if s["finished"]]),
                    "conventions": dict(
                        (w, len([s for s in ran if s["convention"] == w]))
                        for w in VERDICTS),
                    "usd": round(sum(priced), 6) if priced else None,
                    "unpriced": len(ran) - len(priced),
                    "wall": round(sum(s["wall"] for s in ran), 1)}
    return out


def lines(total):
    """-> what the command prints for the totals."""
    out = ["  N " + str(total["pairs"]) + " pairs, k " + str(total["k"])]
    for arm in (LANE, TWIN):
        a = total.get(arm)
        if a is None:
            continue
        c = a["conventions"]
        out.append("  " + arm + ": correct " + str(a["correct"]) + "/"
                   + str(a["runs"]) + ", finished " + str(a["finished"])
                   + ", convention " + ", ".join(
                       w + " " + str(c[w]) for w in VERDICTS)
                   + ", usd " + ("-" if a["usd"] is None
                                 else "%.4f" % a["usd"])
                   + (" (" + str(a["unpriced"]) + " unpriced)"
                      if a["unpriced"] else "")
                   + ", wall " + str(a["wall"]) + "s")
    p = total["probation"]
    out.append("  probation: most new facts in a run " + str(p["most"])
               + " (runs over " + str(MOST_FACTS) + ": " + str(p["spam"])
               + "), attached facts used " + str(p["used"]) + " of "
               + str(p["attached"]) + " ("
               + ("none attached" if p["used_ok"] is None else
                  "holds" if p["used_ok"] else "under one in " + str(ONE_IN))
               + "), false facts " + str(len(p["false_facts"]))
               + (": the write path is killed until fixed" if p["kill"]
                  else ""))
    out.append("  probation " + ("holds" if p["holds"] else "fails"))
    return out


def main(argv, valued, live_flag="--live", fake="fake"):
    """-> 0 when every pair ran and was scored."""
    import datetime
    import json

    from agentweft.runner import state
    from agentweft.runner.config import config

    folder = Path(valued(argv, "--pairs") or "")
    if not folder.is_dir():
        print(str(folder) + ": no such folder")
        return 1
    conf, pairs, problems = load(folder)
    if problems:
        print("the set is not scored, nothing ran:")
        for p in problems:
            print("  " + p)
        return 1
    flow = valued(argv, "--flow") or conf.get("flow")
    if not flow:
        print("no flow: name one in " + runner.CONF + " or with --flow")
        return 1
    try:
        k = int(valued(argv, "--k") or conf.get("k") or 1)
    except ValueError:
        k = 0
    if k < 1:
        print("--k is at least 1")
        return 1
    try:
        spec = config(flow)
    except (FileNotFoundError, ValueError) as e:
        print("no flow " + flow + " to bench: " + str(e))
        return 1
    provider = conf.get("provider") or spec.get("provider") or {}
    if provider.get("provider") != fake and live_flag not in argv:
        print("the set runs on " + str(provider.get("provider") or "the "
              "flow's own provider") + ", which calls a real model. "
              + live_flag + " runs it, and it is charged")
        return 1
    twin = "--twin" in argv
    print("pairs " + flow + " over " + str(len(pairs)) + " pairs, k "
          + str(k) + (", with the twin" if twin else ""))
    date = datetime.datetime.now()
    out = valued(argv, "--out")
    path = Path(out) if out else (Path(state.RUNS) / "bench" / (
        "pairs-" + folder.name + "-" + date.strftime("%Y%m%d-%H%M%S")
        + ".json"))
    path.parent.mkdir(parents=True, exist_ok=True)

    def scored(rows):
        path.write_text(json.dumps(
            {"flow": flow, "set": folder.name, "k": k, "twin": twin,
             "date": date.isoformat(timespec="seconds"),
             "summary": summary(rows, k), "runs": rows}, indent=2),
            encoding="utf-8")

    rows = run(flow, provider, pairs, k, twin=twin, scored=scored)
    print("")
    print("\n".join(lines(summary(rows, k))))
    print("scores: " + str(path))
    return 0
