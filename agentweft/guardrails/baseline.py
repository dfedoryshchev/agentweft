"""the state of the suite the run started from, kept by commit.

a test that was red before the run touched anything is not the run's doing,
and a gate, a stop or a handoff that reads it as one blames the run for what
it found. so the run's start tests (`starttests.modules`) run once on the
start state, in a temporary checkout of the start commit given the files that
were already loose (`worktree.py`), and what each one did is kept as
runs/<id>/baseline.json.

`baseline:` in flow.yaml says when: `on` as the run starts, `auto` (the
default) only once a test comes back red after a step, `off` never. with
`off` the start-tests replay still runs the start state for itself when it
has to, and nothing is kept.

the outcome is cached under the runs root by what decides it: the start
commit, a hash of the files that were loose at the start (the dirty-tree id,
"" for a clean tree), the command that starts pytest, the python version and
the lock files at the start. a second run on the same commit reads the cache
and runs nothing.

a test red at the start is run again, alone, up to RETRIES times in the same
checkout. one that passes on a retry is flaky, not red: it is neither blamed
on the run nor counted as green at the start.
"""
import json
import sys
from pathlib import Path, PurePosixPath

from agentweft.guardrails import starttests, worktree
from agentweft.guardrails.snapshot import _sha

FILE = "baseline.json"
AUTO, ON, OFF = "auto", "on", "off"
KEY = "baseline"
CACHE = "baseline-"
RETRIES = 3
LOCKS = ("poetry.lock", "uv.lock", "pdm.lock", "Pipfile.lock",
         "requirements.txt", "requirements-dev.txt", "package-lock.json",
         "pnpm-lock.yaml", "yarn.lock")


def mode(fm):
    """-> AUTO, ON or OFF for the flow. a bare `on` or `off` in yaml is read
    as true or false."""
    said = fm.get(KEY)
    if said is None:
        return AUTO
    if said is True:
        return ON
    if said is False:
        return OFF
    return said


def dirty_id(start):
    """-> a hash of the files that were loose when the run started, "" when
    none were."""
    if not start.loose:
        return ""
    parts = [rel + "\0" + ("gone" if data is None else _sha(data))
             for rel, data in sorted(start.loose.items())]
    return _sha("\n".join(parts).encode("utf-8"))


def locks(start):
    """-> {lock file: sha256} from the start state's product files."""
    return dict((rel, sha) for rel, sha in sorted(start.product.items())
                if PurePosixPath(rel).name in LOCKS)


def key_of(start, base):
    python = "%d.%d" % sys.version_info[:2]
    found = [start.start, dirty_id(start), list(base), python, locks(start)]
    return _sha(json.dumps(found, sort_keys=True).encode("utf-8"))[:24]


def cached(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "tests" in data else None


def run(start, files, base, timeout):
    """-> ({id: state}, {id: what it said}, [flaky ids], "") of the start
    tests on the start state, or (None, None, None, why)."""
    try:
        with worktree.temporary(start.root, start.start) as tree:
            start.lay_out(tree, [])
            there = start.place_in(tree)
            found, why = starttests.run_tests(base, files, there, timeout)
            if found is None:
                return None, None, None, why
            flaky = []
            for test in sorted(t for t, (s, _) in found.items()
                               if s in starttests.RED and "::" in t):
                for _ in range(RETRIES):
                    again, _why = starttests.run_tests(base, [test], there,
                                                       timeout)
                    if (again or {}).get(test, (None,))[0] == "PASSED":
                        flaky.append(test)
                        break
    except ValueError as e:
        return None, None, None, "could not check out the start commit: " \
            + str(e)
    states = dict((t, s) for t, (s, _) in found.items())
    said = dict((t, w or s.lower()) for t, (s, w) in found.items()
                if s in starttests.RED)
    return states, said, flaky, ""


def ensure(start, cmd, root, timeout=starttests.TIMEOUT):
    """-> (the baseline record, "") for the run's start, read from the cache
    under `root` or run and cached there, or (None, why there is none)."""
    if start is None or not start.hashed:
        return None, "the run took no start snapshot"
    if not start.start:
        return None, start.why or "the run has no start commit"
    files = starttests.modules(start)
    if not files:
        return None, "no python test module when the run started"
    base = starttests.base_of(cmd)
    key = key_of(start, base)
    path = Path(root) / (CACHE + key + ".json")
    found = cached(path)
    if found is not None:
        found["from"] = "cache"
        return found, ""
    states, said, flaky, why = run(start, files, base, timeout)
    if states is None:
        return None, why
    record = {"key": key, "commit": start.start, "dirty": dirty_id(start),
              "command": list(base), "python": "%d.%d" % sys.version_info[:2],
              "tests": states, "flaky": flaky,
              "passed": sorted(t for t, s in states.items() if s == "PASSED"),
              "red": dict((t, w) for t, w in sorted(said.items())
                          if t not in flaky)}
    Path(root).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True),
                    encoding="utf-8")
    record["from"] = "run"
    return record, ""


def save(record, folder):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / FILE).write_text(json.dumps(record, indent=1,
                                                sort_keys=True),
                                     encoding="utf-8")


def outcomes(record):
    """-> {id: (state, what it said)} as `starttests.outcomes` gives them,
    a flaky test as FLAKY so it is never read as green at the start."""
    out = {}
    for test, state in (record.get("tests") or {}).items():
        if test in (record.get("flaky") or []):
            out[test] = ("FLAKY", "")
        else:
            out[test] = (state, (record.get("red") or {}).get(test, ""))
    return out


def red_at_start(record):
    """-> the ids red or flaky when the run started."""
    if not record:
        return set()
    return set(record.get("red") or {}) | set(record.get("flaky") or [])


def label(left, record):
    """-> `left` (`leftred.check`) with each test red when the run started
    said to be so."""
    if not left or not left.get("red") or not record:
        return left
    was = red_at_start(record)
    out = dict(left)
    out["red"] = [(i, did + " - red when the run started" if i in was
                   else did) for i, did in left["red"]]
    return out


def lines(record):
    """-> the handoff's lines for the suite as the run found it, [] with no
    record."""
    if not record:
        return []
    out = ["- red when the run started, not the run's doing: " + test + ": "
           + said for test, said in sorted((record.get("red") or {}).items())]
    out.extend("- flaky when the run started (red, then green on a retry): "
               + test for test in record.get("flaky") or [])
    if not out:
        out.append("- the suite was green when the run started ("
                   + str(len(record.get("passed") or [])) + " passed)")
    return out
