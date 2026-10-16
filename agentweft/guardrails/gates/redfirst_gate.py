import ast
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
MISSES = ("ImportError", "ModuleNotFoundError", "NameError")
COULD_NOT_RUN = MISSES + ("SyntaxError",)
IMPORT_NAME = re.compile(r"cannot import name '([\w.]+)'(?: from '([\w.]+)')?")
NO_MODULE = re.compile(r"No module named '([\w.]+)'")
NOT_DEFINED = re.compile(r"name '(\w+)' is not defined")
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


def missing_of(output):
    """-> (module, name) the first import or name error in `output` says is
    missing: name "" for a missing module, module "" when the error names
    none. None when no error names what it misses."""
    found = [(m.start(), rx, m) for rx in (IMPORT_NAME, NO_MODULE, NOT_DEFINED)
             for m in [rx.search(output or "")] if m]
    if not found:
        return None
    _, rx, m = min(found, key=lambda f: f[0])
    if rx is IMPORT_NAME:
        return m.group(2) or "", m.group(1)
    if rx is NO_MODULE:
        return m.group(1), ""
    return "", m.group(1)


def module_file(root, module):
    """-> the file (or namespace folder) `module` imports from under `root`
    or its src/, the way the replay's PYTHONPATH finds it; None when absent."""
    for base in (Path(root), Path(root) / "src"):
        p = base.joinpath(*module.split("."))
        for f in (p.parent / (p.name + ".py"), p / "__init__.py"):
            if f.is_file():
                return f
        if p.is_dir():
            return p
    return None


def bound(body):
    """-> the names a module's top-level statements bind, into its if and
    try blocks."""
    for st in body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef)):
            yield st.name
        elif isinstance(st, (ast.Assign, ast.AnnAssign)):
            for t in getattr(st, "targets", [getattr(st, "target", None)]):
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        yield n.id
        elif isinstance(st, (ast.Import, ast.ImportFrom)):
            for a in st.names:
                yield a.asname or a.name.split(".")[0]
        elif isinstance(st, (ast.If, ast.Try)):
            yield from bound(st.body + st.orelse + getattr(st, "finalbody", [])
                             + [x for h in getattr(st, "handlers", [])
                                for x in h.body])


def defines(path, name):
    """-> whether the python file at `path` binds `name` at module level,
    None when it does not parse."""
    if path is None or not Path(path).is_file():
        return False
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8",
                                              errors="replace"))
    except (SyntaxError, ValueError):
        return None
    return name in bound(tree.body)


def py_files(root):
    """-> the .py files git sees under `root`, tracked or not ignored: what
    the replay's checkout lays out."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co",
                              "--exclude-standard", "-z", "--", "*.py"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(root) / f for f in out.split("\0") if f]


def exists(root, module, name):
    """-> whether `module`, or `name` in it (anywhere when module is ""), is
    under `root`. None when a file that could say does not parse."""
    if not name:
        return module_file(root, module) is not None
    if module:
        if module_file(root, module + "." + name) is not None:
            return True
        return defines(module_file(root, module), name)
    said = [defines(f, name) for f in py_files(root)]
    return True if True in said else (None if None in said else False)


def fix_adds(output, start, now):
    """-> whether the import or name error in `output` misses a name that
    is not in the start tree `start` and is in the place `now`: a test of
    what the fix adds, red without it. False when the name cannot be read,
    and a file that does not parse at the start counts as having it."""
    missing = missing_of(output)
    if missing is None:
        return False
    return exists(start, *missing) is False and exists(now, *missing) is True


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
    removes). an ImportError, ModuleNotFoundError or NameError is red when
    the module or name it misses is not in the start tree and is in the
    place now (a feature's test fails on the name the feature adds). any
    other of those, a SyntaxError, or a collection error (exit 2) is a test
    that could not run, not one that caught the bug, whatever a step says.
    then each runs in the place, with the fix, and has to pass. at least one
    has to be red without the fix, and a test a step named on a TEST: line as
    `file::name` has to be one of the red ones; a new test green both ways
    is recorded as passing without the fix, and the record says so test by
    test.

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
    no test but carried its red in (`--continue`), or whose red is a test
    supplied at the start, runs each of those tests with the fix, and each
    has to pass. the same holds when every test it did add passes without
    the fix: those are pins beside the given red, labelled as pins.
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
        carried, came = self.order.given() if self.order is not None \
            else ({}, "")
        if not ids and carried:
            return self.carried_green(cmd, carried, came, start)
        if not ids:
            return self.fail("no test was added or changed since the run"
                             " started, so nothing shows the fix is needed")
        try:
            with worktree.temporary(start.root, start.start) as tree:
                start.lay_out(tree, changes)
                there = start.place_in(tree)
                before = dict((i, self.one(cmd, i, there, lambda out: fix_adds(
                    out, there, start.place))) for i in ids)
        except ValueError as e:
            return self.fail("could not replay without the fix: " + str(e))
        after = dict((i, self.one(cmd, i, start.place)) for i in ids)
        record = [{"test": i, "before": before[i][0], "kind": before[i][1],
                   "after": after[i][0]} for i in ids]
        self.label(record)
        return self.judge(record, text, (cmd, carried, came, start))

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

    def carried_green(self, cmd, carried, came, start):
        """a run that wrote no test: its red was shown on tests carried in
        or supplied at the start, so what is left to show is each of them
        green with the fix."""
        for f in sorted(carried):
            after = self.one(cmd, f, start.place)[0]
            if after != "green":
                return self.fail(f + ", " + came + ", does not pass with the"
                                 " fix: " + after)
        return self.ok(came + ", green with the fix: "
                       + ", ".join(sorted(carried)))

    def one(self, cmd, test, where, adds=None):
        """-> (red | green | error | exit N | timed out | not on PATH |
        could not start: why, kind). `adds(output)` says whether an import
        or name error misses what the fix adds, which makes it red."""
        r, why = self.ran(cmd, test, where)
        if r is None:
            return why, ""
        if r.returncode == 0:
            return "green", ""
        kind = kind_of(r.stdout + "\n" + r.stderr)
        broken = kind in COULD_NOT_RUN or r.returncode == 2
        if broken and kind in MISSES and adds \
                and adds(r.stdout + "\n" + r.stderr):
            return "red", kind
        if broken:
            return "error", kind or "a collection error"
        if r.returncode == int(self.opts.get("expect", 1)):
            return "red", kind
        return "exit " + str(r.returncode), kind

    def ran(self, cmd, test, where):
        """-> (the finished process, "") for `cmd` run on one test in
        `where`, or (None, timed out | not on PATH | could not start: why)."""
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
            return None, "timed out"
        except OSError as e:
            if isinstance(e, FileNotFoundError) and Path(where).is_dir():
                return None, "not on PATH"
            return None, "could not start: " + str(e)
        return r, ""

    def judge(self, record, text, given=None):
        """`given` is (cmd, carried, came, start) when the red proof is
        on tests the run did not write: then new tests that all pass without
        the fix are pins beside it, and what has to hold is the given tests
        green with the fix."""
        named = [n for n in (named_test(t) for t in [text]
                             + list(reversed(self.earlier)) if TEST in t)
                 if n]
        for t in record:
            if t["before"] == "error":
                return self.done(False, t["test"] + " errors without the fix ("
                                 + t["kind"] + "): it could not run, so it"
                                 " failed on neither an assertion nor the"
                                 " code. an import or name error is red only"
                                 " when what it misses is not in the start"
                                 " tree and is in the place now", record)
            if t["before"] not in ("red", "green"):
                return self.done(False, t["test"] + " did not run without the"
                                 " fix: " + t["before"], record)
            if t["after"] != "green":
                return self.done(False, t["test"] + " does not pass with the"
                                 " fix: " + t["after"], record)
        red = [t["test"] for t in record if t["before"] == "red"]
        green = [t["test"] for t in record if t["before"] == "green"]
        if not red and given and given[1]:
            r = self.carried_green(*given)
            if not r.ok:
                return self.done(False, r.detail, record)
            return self.done(True, r.detail + "; every new test passes"
                             " without the fix too: " + ", ".join(green)
                             + added_after(record), record)
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
