"""the tests the run started with, run again after a step writes product code.

a step told it may write product code can still make a test it was given
fail, and a test step before it can rewrite that test's assertion so the
suite in the place stays green. neither shows in the place's own test run.
so after a `writes: product` step the start commit's python test modules,
and the ones already loose when the run started, run against the product
files as they are now: a temporary checkout of the start commit
(`worktree.py`) gets the place's start state, then every product file as it
is now (the start snapshot says which files are product), and the tests
there are the ones the run found, whatever the place holds now. one pytest
run, no model.

a test green when the run started and red now is the run's doing. a test that
was red when the run started is not counted, so an inherited red is never
blamed on the run; which ones were green is read from the run's suite
baseline (`baseline.py`, cached by start commit), and only when something
came back red, unless the flow asked for it as the run starts. with
`baseline: off` the same tests run here on the start state, once per run.

the commits a step makes change nothing here: the start commit is the one
the snapshot kept, and the product is read from the files. product files
whose hashes are what they were at the start mean there is nothing to run.
"""
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from agentweft.guardrails import worktree
from agentweft.guardrails.gates.base import Result, fresh_python
from agentweft.guardrails.snapshot import TEST_MODULE, _read, changed

NAME = "start-tests"
SUMMARY = re.compile(r"^=+ short test summary info =+$")
LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS) (\S+)(?: - (.*))?$")
RED = ("FAILED", "ERROR")
PYTEST = ["python", "-m", "pytest"]
TIMEOUT = 300


class Replay(object):
    """what the replay found. `result` is the line for the record, None when
    there was nothing to run. `red` is [(test id, what it said)] for each
    test green at the start and red now."""

    __slots__ = ("result", "red")

    def __init__(self, result=None, red=()):
        self.result = result
        self.red = list(red)


def modules(start):
    """-> the python test modules the run started with, as paths from the
    place."""
    return sorted(start.from_place(rel) for rel in start.tests
                  if TEST_MODULE.search(PurePosixPath(rel).name))


def base_of(cmd):
    """-> the flow's own way of starting pytest, up to `pytest`, from a test
    command, or `python -m pytest`."""
    cmd = list(cmd or [])
    for i, arg in enumerate(cmd):
        if arg == "pytest" or arg.endswith("pytest") or \
                arg.endswith("pytest.exe"):
            return cmd[:i + 1]
    return list(PYTEST)


def outcomes(text):
    """-> {test id or file: (PASSED | FAILED | ERROR | XFAIL | XPASS, what it
    said)} read from pytest's `-rA` short summary."""
    out = {}
    seen = False
    for line in (text or "").splitlines():
        if SUMMARY.match(line.strip()):
            seen = True
            continue
        if not seen:
            continue
        m = LINE.match(line.strip())
        if m:
            out[m.group(2)] = (m.group(1), (m.group(3) or "").strip())
    return out


def run_tests(base, files, there, timeout):
    """-> ({id: (state, said)}, "") for one pytest run of `files` in
    `there`, or (None, why it could not run)."""
    argv = list(base) + ["-q", "-rA", "--tb=short", "-p", "no:cacheprovider",
                         "--continue-on-collection-errors", "--rootdir",
                         str(there)] + list(files)
    path = [str(there), str(Path(there) / "src")]
    if os.environ.get("PYTHONPATH"):
        path.append(os.environ["PYTHONPATH"])
    try:
        # pytest cuts a summary line to the terminal's width, and the
        # assertion at its end is what the stop has to show
        with fresh_python(dict(os.environ, PYTHONPATH=os.pathsep.join(path),
                               COLUMNS="1000")) as env:
            r = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               cwd=str(there), env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "the tests timed out after " + str(timeout) + "s"
    except OSError as e:
        return None, "could not start " + " ".join(base) + ": " + str(e)
    found = outcomes(r.stdout)
    if r.returncode not in (0, 1) and not found:
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        return None, ("pytest exited " + str(r.returncode) + ": "
                      + tail[0][:200])
    return found, ""


def lay_out_now(start, tree):
    """the place's start state in a checkout of the start commit, then every
    product file as it is now, and none of the product files gone since."""
    start.lay_out(tree, [])
    now = start.product_now()
    for rel in now:
        data = _read(start.root / rel)
        if data is None:
            continue
        target = Path(tree) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for rel in start.product:
        if rel not in now and (Path(tree) / rel).is_file():
            (Path(tree) / rel).unlink()


def tests_in(start, files, base, timeout, now):
    """-> (outcomes, "") of `files` on the start state, with the product as
    it is now when `now`, or (None, why)."""
    try:
        with worktree.temporary(start.root, start.start) as tree:
            if now:
                lay_out_now(start, tree)
            else:
                start.lay_out(tree, [])
            return run_tests(base, files, start.place_in(tree), timeout)
    except ValueError as e:
        return None, "could not check out the start commit: " + str(e)


def gone_red(after, before):
    """-> [(id, what it said now)] for each test that passed in `before` and
    did not in `after`."""
    out = []
    for test in sorted(t for t, (s, _) in before.items()
                       if s == "PASSED" and "::" in t):
        state, said = after.get(test, (None, ""))
        if state in RED:
            out.append((test, said or state.lower()))
        elif state is None:
            whole = after.get(test.split("::")[0], (None, ""))
            if whole[0] == "ERROR":
                out.append((test, "its file no longer collects: "
                            + (whole[1] or "an error")))
            else:
                out.append((test, "it did not run against the product as it"
                            " is now"))
    return out


def replay(start, cmd=None, timeout=TIMEOUT, green=None, known=None):
    """-> a Replay of the run's start tests against the product as it is now.
    `green` is a dict the run keeps the start state's outcomes in, so they
    are run once. `known` gives them instead of a run here: a function that
    returns (outcomes, "") or (None, why), the run's suite baseline."""
    if start is None or not start.hashed:
        return Replay()
    files = modules(start)
    if not files or not changed(start.product, start.product_now()):
        return Replay()
    if not start.start:
        return Replay(Result(NAME, True, "not replayed - " + (
            start.why or "the run has no start commit")))
    base = base_of(cmd)
    after, why = tests_in(start, files, base, timeout, now=True)
    if after is None:
        return Replay(Result(NAME, False, why))
    if not any(s in RED for s, _ in after.values()) and \
            all(t in after for t in (green or {}).get("passed", [])):
        return Replay(Result(NAME, True, ok_line(after)))
    if green is None:
        green = {}
    if "found" not in green:
        before, why = known() if known else \
            tests_in(start, files, base, timeout, now=False)
        if before is None:
            return Replay(Result(NAME, False, "could not run the start tests"
                                 " on the start state: " + why))
        green["found"] = before
        green["passed"] = [t for t, (s, _) in before.items()
                           if s == "PASSED"]
    red = gone_red(after, green["found"])
    if not red:
        return Replay(Result(NAME, True, ok_line(after)))
    return Replay(Result(NAME, False, said_of(red)), red)


def ok_line(after):
    passed = sum(1 for s, _ in after.values() if s == "PASSED")
    red = sum(1 for s, _ in after.values() if s in RED)
    line = (str(passed) + " test" + ("" if passed == 1 else "s")
            + " the run started with pass against the product as it is now")
    if red:
        line = line + "; " + str(red) + " red, as they were at the start"
    return line


def said_of(red):
    return "; ".join(t + " was green when the run started and is red now: "
                     + said for t, said in red)
