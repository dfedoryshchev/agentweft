import os
import re
import subprocess
from pathlib import Path

from agentweft.guardrails import worktree

from .base import Gate, fresh_python, register
from .redtest_gate import TEST, named_test

SUMMARY = re.compile(r"^(?:FAILED|ERROR) \S+ - (.+)$", re.M)
E_LINE = re.compile(r"^E\s+(.+)$", re.M)
ERROR_NAME = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception))\b")
# the errors of a test that never got as far as the code it tests. any other
# exception is the unfixed code failing, which is the bug a crash fix removes
COULD_NOT_RUN = ("ImportError", "ModuleNotFoundError", "NameError",
                 "SyntaxError")
PIN_OK = re.compile(r"^PIN OK:(.*)$")
# the steps that decide what is built, not the ones that write it: a step
# cannot excuse the pins it wrote itself
PIN_ROLES = ("planner", "architect", "ba")


def kind_of(output):
    """-> "assertion", an exception's name, or "" when the output names
    neither. read from pytest's short summary, else its first `E` line."""
    for said in (SUMMARY.findall(output or "")[:1]
                 or E_LINE.findall(output or "")[:1]):
        m = ERROR_NAME.match(said.strip())
        if not m:
            return "assertion"
        name = m.group(1).rsplit(".", 1)[-1]
        return "assertion" if name == "AssertionError" else name
    return ""


def said_of(test):
    """one test's record as a line: what it did without the fix and with it."""
    before = test["before"]
    if before == "red":
        before = "red without the fix (" + (test.get("kind") or "kind not"
                                           " read") + ")"
    elif before == "green":
        before = "green without the fix"
    elif before == "error":
        before = "errors without the fix (" + (test.get("kind") or "") + ")"
    else:
        before = before + " without the fix"
    line = test["test"] + ": " + before + ", " + test["after"] + " with it"
    if test.get("counts") == "coverage":
        line = line + "; added after green, coverage"
    elif test.get("counts") == "pin":
        line = line + ("; added after green, pins current behaviour, not"
                       " counted as coverage")
        if test.get("pin_ok"):
            line = line + " (allowed by " + test["pin_ok"] + ")"
    return line


def pin_ok(said_by):
    """-> "<role>: <reason>" from the last PIN OK: line a step of a
    PIN_ROLES role wrote, "" when none did."""
    found = ""
    for role, text in said_by:
        if role not in PIN_ROLES:
            continue
        for line in (text or "").splitlines():
            m = PIN_OK.match(line.strip())
            if m and m.group(1).strip():
                found = role + ": " + m.group(1).strip()
    return found


def added_after(record):
    """-> the gate's words on the tests added after green, "" for none."""
    late = [t for t in record if t.get("added")]
    if not late:
        return ""
    pins = [t for t in late if t.get("counts") == "pin"]
    out = ("; added after green: " + str(len(late) - len(pins))
           + " coverage, " + str(len(pins)) + " pin" + ("" if len(pins) == 1
                                                        else "s"))
    for t in pins:
        out = out + "; " + t["test"] + " pins current behaviour, not counted" \
            " as coverage"
        if t.get("pin_ok"):
            out = out + " (allowed by " + t["pin_ok"] + ")"
    return out


def declared(texts):
    """-> the FAILS: lines in `texts`, joined: a red step that says its test
    fails with an error has said that error is the bug."""
    return "\n".join(line for t in texts for line in (t or "").splitlines()
                     if line.strip().startswith("FAILS:"))


@register
class RedFirstGate(Gate):
    """each new test fails without the fix and passes with it, shown by
    running it rather than by a step saying so.

    the run took a snapshot of the place as it started. after the step that
    made the fix, the tests that are new or changed since then are found by
    content (no commit is needed, and commits made by the steps change
    nothing). a temporary checkout of the start commit gets the place's start
    state and only the test files' changes, and each new test runs there
    alone: without the fix it has to fail. an assertion is red, and so is
    any exception the unfixed code raises (a KeyError is the bug a crash fix
    removes). an ImportError, ModuleNotFoundError, NameError or SyntaxError,
    or a collection error (exit 2), is a test that could not run, not one
    that caught the bug, unless the red step's FAILS: line said that error is
    the bug (a feature's test fails on the name the feature adds); the fix
    step cannot declare it for itself. then each runs in the
    place, with the fix, and has to pass. at least one has to be red without
    the fix, and a test a step named on a TEST: line as `file::name` has to be
    one of the red ones; a new test green both ways is recorded as passing
    without the fix, and the record says so test by test.

    a test added after the red was first shown (the run's red proof keeps
    the ids there were then) is new test work too. red without the fix, it
    is coverage; green there, it pins current behaviour, which the record
    and the handoff list and never count as coverage. a PIN OK: <reason>
    line from a planner, architect or ba step allows the pins, and the reason
    goes in the record; the step that wrote the case cannot give one.

    it shows the tests tell the fixed code from the unfixed. it does not
    show they are good tests, and one run each way says nothing about a
    flaky one. a place outside git, or a repo with no commit, has no start to
    replay from: the gate passes saying it was not replayed. a run that wrote
    no test but carried its red in (`--continue`) runs each carried test
    with the fix, and each has to pass.
    """

    name = "red-first"
    options = ("command", "timeout", "expect")

    def run(self, text):
        if not (text or "").strip():
            return self.fail("the step answered nothing")
        cmd = self.opts.get("command")
        if not isinstance(cmd, (list, tuple)) or "{test}" not in cmd:
            return self.fail("command has to be a list with {test} in it")
        start = self.start
        if start is None:
            return self.ok("not replayed - the run took no start snapshot")
        if start.why:
            return self.ok("not replayed - " + start.why)
        changes = start.test_changes()
        ids = start.new_test_ids(changes)
        said = declared(self.earlier)
        carried = self.order.carried() if self.order is not None else {}
        if not ids and carried:
            return self.carried_green(cmd, carried, start, said)
        if not ids:
            return self.fail("no test was added or changed since the run"
                             " started, so nothing shows the fix is needed")
        try:
            with worktree.temporary(start.root, start.start) as tree:
                start.lay_out(tree, changes)
                there = start.place_in(tree)
                before = dict((i, self.one(cmd, i, there, said)) for i in ids)
        except ValueError as e:
            return self.fail("could not replay without the fix: " + str(e))
        after = dict((i, self.one(cmd, i, start.place, said)) for i in ids)
        record = [{"test": i, "before": before[i][0], "kind": before[i][1],
                   "after": after[i][0]} for i in ids]
        self.label(record)
        return self.judge(record, text)

    def label(self, record):
        """mark each test added after the red was first shown: red without
        the fix is coverage, green there pins current behaviour. a PIN OK:
        line from a step of a PIN_ROLES role allows the pins, and says why."""
        first = self.order.first_ids() if self.order is not None else None
        if first is None:
            return
        allowed = pin_ok(self.said_by)
        for t in record:
            if t["test"] in first:
                continue
            t["added"] = "after green"
            t["counts"] = "coverage" if t["before"] == "red" else "pin"
            if t["before"] == "green" and allowed:
                t["pin_ok"] = allowed

    def carried_green(self, cmd, carried, start, said):
        """a continued run wrote no test: its red was shown when the tests
        were carried in, so what is left to show is each of them green with
        the fix."""
        for f in sorted(carried):
            after = self.one(cmd, f, start.place, said)[0]
            if after != "green":
                return self.fail(f + ", carried from "
                                 + self.order.proof["from"] + ", does not"
                                 " pass with the fix: " + after)
        return self.ok("carried from " + self.order.proof["from"]
                       + ", green with the fix: " + ", ".join(sorted(carried)))

    def one(self, cmd, test, where, said):
        """-> (red | green | error | exit N | timed out | not on PATH |
        could not start: why, kind)."""
        argv = [test if a == "{test}" else a for a in cmd]
        # an editable install puts the person's own tree on sys.path, and the
        # checkout without the fix would import the fixed code from there
        path = [str(where), str(Path(where) / "src")]
        if os.environ.get("PYTHONPATH"):
            path.append(os.environ["PYTHONPATH"])
        try:
            with fresh_python(dict(os.environ, PYTHONPATH=os.pathsep.join(
                    path))) as env:
                r = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   cwd=str(where), env=env,
                                   timeout=int(self.opts.get("timeout", 120)))
        except subprocess.TimeoutExpired:
            return "timed out", ""
        except OSError as e:
            if isinstance(e, FileNotFoundError) and Path(where).is_dir():
                return "not on PATH", ""
            return "could not start: " + str(e), ""
        if r.returncode == 0:
            return "green", ""
        kind = kind_of(r.stdout + "\n" + r.stderr)
        broken = kind in COULD_NOT_RUN or r.returncode == 2
        if broken and kind and kind in said:
            return "red", kind
        if broken:
            return "error", kind or "a collection error"
        if r.returncode == int(self.opts.get("expect", 1)):
            return "red", kind
        return "exit " + str(r.returncode), kind

    def judge(self, record, text):
        named = [n for n in (named_test(t) for t in [text]
                             + list(reversed(self.earlier)) if TEST in t)
                 if n]
        for t in record:
            if t["before"] == "error":
                return self.done(False, t["test"] + " errors without the fix ("
                                 + t["kind"] + "): it could not run, so it"
                                 " failed on neither an assertion nor the"
                                 " code. a FAILS: line from the red step"
                                 " naming " + t["kind"] + " says that is the"
                                 " bug", record)
            if t["before"] not in ("red", "green"):
                return self.done(False, t["test"] + " did not run without the"
                                 " fix: " + t["before"], record)
            if t["after"] != "green":
                return self.done(False, t["test"] + " does not pass with the"
                                 " fix: " + t["after"], record)
        red = [t["test"] for t in record if t["before"] == "red"]
        green = [t["test"] for t in record if t["before"] == "green"]
        if not red:
            return self.done(False, "every new test passes without the fix: "
                             + ", ".join(green), record)
        for n in named:
            if n in green:
                return self.done(False, n + " passes without the fix", record)
        detail = (str(len(red)) + " of " + str(len(record)) + " new test"
                  + ("" if len(record) == 1 else "s") + " red without the fix"
                  " and green with it: " + ", ".join(red))
        if green:
            detail = detail + "; green without it too: " + ", ".join(green)
        return self.done(True, detail + added_after(record), record)

    def done(self, ok, detail, record):
        r = self.ok(detail) if ok else self.fail(detail)
        r.tests = record
        return r
