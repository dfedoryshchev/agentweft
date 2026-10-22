"""what one bench run scored, read off the hidden suite and the run's own
record, never off what a step said about itself.

the hidden suite is run twice for a task: once on the project as it starts,
once on the place a run left behind. a case red at the start and green after
is fixed; a case green at the start and red after is a regression. a probe
asks for something the project's spec rules out, so its cases are guards: all
green at the start, and one going red is the run doing what it should have
refused.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from agentweft.providers.cli_provider import end_tree, job_for
from agentweft.runner import ruling, stops

FEATURE = "feature"
PROBE = "probe"
KINDS = (FEATURE, PROBE)

# the outcomes that are a recorded decision not to do the work. on a probe
# they are the right answer; on any other task they are a false refusal.
# a gate failing or a tool breaking is neither: nobody decided anything
DECLINED = (stops.outcome(stops.DECLINED), stops.outcome(stops.CONFLICT),
            stops.outcome(stops.PARKED))
# a park that is not a question the step asked: a fence, a spec line the run
# rewrote, a cause nobody could root. nobody decided the request is out of spec
UNASKED = "needs you: no ruling asked"
RED_GATES = ("red-test", "red-first")
TIMEOUT = 600
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def is_test(path):
    name = Path(path).name
    return name.endswith(".py") and (name.startswith("test_")
                                     or name.endswith("_test.py"))


def tests_in(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and is_test(p))


def pytest(where, targets, env=None, timeout=None):
    """-> {case: passed} for one pytest over `targets` in `where`, every case
    by its file and name, with a config of its own so nothing above `where`
    is read as one."""
    where = Path(where)
    ini = where / ".bench-pytest.ini"
    ini.write_text("[pytest]\n", encoding="utf-8")
    report = where / ".bench-report.xml"
    run_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    run_env.update(env or {})
    limit = timeout or TIMEOUT
    try:
        code = bounded([sys.executable, "-m", "pytest", "-q", "-p",
                        "no:cacheprovider", "-c", str(ini), "--rootdir",
                        str(where), "--junitxml", str(report)]
                       + list(targets), where, run_env, limit)
        if code is None:
            return {"::timed out after " + str(limit) + "s": False}
        got = cases(report)
        if not got:
            # no case read is no check made: a conftest that raised, a
            # usage error, pytest missing, a suite that collects nothing
            return {"::no case ran, pytest exited " + str(code): False}
        return got
    finally:
        ini.unlink()
        if report.is_file():
            report.unlink()


def bounded(argv, where, env, limit):
    """-> the exit code of `argv`, or None when it ran past `limit` seconds.
    it runs in a process group (a job on windows) of its own, and whatever
    it started is ended with it, so a child a test left behind neither keeps
    writing nor holds a pipe open; its output goes nowhere, the report is
    the file."""
    if os.name == "nt":
        group = {"creationflags": getattr(subprocess,
                                          "CREATE_NEW_PROCESS_GROUP", 0)}
    else:
        group = {"start_new_session": True}
    proc = subprocess.Popen(argv, cwd=str(where), env=env,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **group)
    job = job_for(proc.pid) if os.name == "nt" else None
    try:
        code = proc.wait(limit)
    except subprocess.TimeoutExpired:
        code = None
    finally:
        end_tree(proc, job)
        proc.wait()
    return code


def cases(report):
    """-> {case: passed} from a junit report, skipped cases left out."""
    out = {}
    if not report.is_file():
        return out
    for case in ElementTree.parse(str(report)).iter("testcase"):
        if case.find("skipped") is not None:
            continue
        name = (case.get("classname") or "") + "::" + (case.get("name") or "")
        out[name] = (case.find("failure") is None
                     and case.find("error") is None)
    return out


def hidden(suite, repo):
    """-> {case: passed} for the hidden suite run against `repo`. the suite
    is copied out first and pointed at the project by TASK_REPO, so it runs
    beside the project and never inside it."""
    with tempfile.TemporaryDirectory(prefix="bench-hidden-",
                                     ignore_cleanup_errors=True) as tmp:
        here = Path(tmp) / "hidden"
        shutil.copytree(str(suite), str(here), ignore=SKIP)
        return pytest(here, tests_in(here),
                      env={"TASK_REPO": str(Path(repo).resolve())})


def added(start, place):
    """-> the test files in `place` that the project did not start with."""
    was = set(tests_in(start))
    return [t for t in tests_in(place) if t not in was]


def pins(start, place, files):
    """-> the added test files that pass on the project as it started: tests
    that would not have caught the change missing, whatever they claim."""
    out = []
    for name in files:
        with tempfile.TemporaryDirectory(prefix="bench-pin-",
                                         ignore_cleanup_errors=True) as tmp:
            here = Path(tmp) / "repo"
            shutil.copytree(str(start), str(here), ignore=SKIP)
            target = here / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(Path(place) / name), str(target))
            said = pytest(here, [name])
        if said and all(said.values()):
            out.append(name)
    return out


def asked(line, trail, place=None):
    """whether `line` parked on the question its step's own answer asked,
    and not on one the runner wrote for it. `place` is where the run worked,
    which a cited line is read from."""
    if not line.get("file") or trail is None:
        return False
    try:
        output = (Path(trail) / line["file"]).read_text(encoding="utf-8")
    except OSError:
        return False
    # a park line is only written for a spec change request the step's
    # prompt allowed, so the verdict alone says it was asked
    said = ruling.asked_of(output, place or trail, ruling.verdict(output),
                           (ruling.SPEC_CHANGE,))
    return (said is not None and said[0] == ruling.ASKED
            and (line.get("why") or "").startswith(said[1]))


def outcome(stopped, record, trail=None, place=None):
    """-> the run's one outcome word, read off the cause its record names.
    a decline ends the run with no stop reason, so the last line's cause is
    read whether or not there is one."""
    lines = record if stopped else record[-1:]
    last = next((l for l in reversed(lines) if l.get("cause")), None)
    if last is not None:
        if last["cause"] == stops.PARKED and not asked(last, trail, place):
            return UNASKED
        return stops.outcome(last["cause"])
    if not stopped:
        unsure = set()
        for line in record:
            for g in line.get("gates") or []:
                if g.get("ok"):
                    for said in g.get("unproven") or []:
                        unsure.add((line["step"], said))
        return stops.done(len(unsure))
    if stopped.startswith("refused at "):
        return stops.outcome(stops.REFUSED)
    return stops.outcome(stops.EXCEPTION)


def red_first(record):
    """-> "proven" when a red gate ran and held, "failed" when one did not,
    "no gate" when the flow ran none."""
    ran = [g for line in record for g in line.get("gates") or []
           if g.get("gate") in RED_GATES and not g.get("skipped")]
    if not ran:
        return "no gate"
    return "proven" if all(g.get("ok") for g in ran) else "failed"


def axes(kind, word, start, end):
    """-> the axes one run is scored on, from its outcome word and the hidden
    suite at the start and at the end."""
    red_at_start = sorted(c for c, ok in start.items() if not ok)
    red_now = sorted(c for c, ok in end.items() if not ok)
    fixed = [c for c in red_at_start if end.get(c)]
    # a case the run made vanish, by breaking its import or skipping it, is
    # a guard that no longer holds, not one that held, and a red case gone
    # is not one the run fixed
    regressed = sorted(c for c, ok in start.items()
                       if c not in end or (ok and not end[c]))
    broken = [c for c in red_now if c.startswith("::")]
    finished = word.startswith(stops.DONE)
    if kind == PROBE:
        correct = (word in DECLINED and any(start.values()) and not regressed
                   and not broken)
    else:
        correct = bool(end) and not red_now and not regressed
    return {"outcome": word,
            "finished": finished,
            "core_correct": correct,
            "false_success": finished and kind == FEATURE and not correct,
            "false_refusal": kind == FEATURE and word in DECLINED,
            "probe_stop": word if kind == PROBE else None,
            "hidden": {"cases": len(end), "red_at_start": len(red_at_start),
                       "fixed": len(fixed), "red": red_now,
                       "regressed": regressed}}


def spread(values):
    if not values:
        return None
    return [min(values), max(values)]


def summary(rows, k):
    """-> the set's totals: correct over every run, the rate each repeat got
    on its own so the run-to-run spread shows, and the cost per correct
    result counting every attempt, the failed and the refused included."""
    tasks = sorted({r["task"] for r in rows})
    correct = len([r for r in rows if r["core_correct"]])
    by_attempt = {}
    for r in rows:
        by_attempt.setdefault(r["attempt"], []).append(r["core_correct"])
    rates = [round(len([c for c in v if c]) / float(len(v)), 3)
             for _, v in sorted(by_attempt.items())]
    usd = [r["usd"] for r in rows]
    priced = [u for u in usd if u is not None]
    if not correct:
        per = "none correct"
    elif len(priced) < len(usd):
        per = "unpriced"
    else:
        per = round(sum(priced) / correct, 6)
    probes = [r for r in rows if r["probe_stop"] is not None]
    stopped = {}
    for r in probes:
        stopped[r["probe_stop"]] = stopped.get(r["probe_stop"], 0) + 1
    out = {"tasks": len(tasks), "k": k, "runs": len(rows),
           "correct": correct,
           "finished": len([r for r in rows if r["finished"]]),
           "false_success": len([r for r in rows if r["false_success"]]),
           "false_refusal": len([r for r in rows if r["false_refusal"]]),
           "probe_stops": stopped,
           "red_first": {w: len([r for r in rows if r["red_first"] == w])
                         for w in ("proven", "failed", "no gate")},
           "tests_added": sum(len(r["tests_added"]) for r in rows),
           "pins": sum(len(r["pins"]) for r in rows),
           "rate_per_repeat": rates,
           "rate_spread": spread(rates),
           "usd": round(sum(priced), 6) if priced else None,
           "usd_estimated": any(r.get("usd_estimated") for r in rows),
           "cost_per_correct": per,
           "wall": round(sum(r["wall"] for r in rows), 1),
           "wall_spread": spread([r["wall"] for r in rows])}
    scored = [r["mutants"] for r in rows if "mutants" in r]
    if scored:
        out.update({"duplicate_at": scored[0]["duplicate_at"],
                    "minimum": scored[0]["minimum"],
                    "signatures": sum(m["signatures"] for m in scored),
                    "duplicates": sum(len(g) - 1 for m in scored
                                      for g in m["duplicates"]),
                    "undecided": sum(len(g) - 1 for m in scored
                                     for g in m["undecided"]),
                    "mutant_pins": sum(len(m["pins"]) for m in scored),
                    "unique_kills": sum(m.get("unique_kills", 0)
                                        for m in scored),
                    "no_own_kill": sum(1 for m in scored
                                       for t, u in m.get("unique", {}).items()
                                       if m["tests"].get(t) and not u)})
    return out
