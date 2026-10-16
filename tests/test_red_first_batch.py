"""the red-first replay takes every new test in one process per side when
the flow's command can, and reads each test's outcome from the results file
the flow names. the labels must be the ones the one-process-per-test path
gives, and a results file that is missing, empty or not xml must never turn
into a green."""
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.guardrails import gates
from agentweft.guardrails.gates import redfirst_gate
from agentweft.roles import resolver

NL = chr(10)
BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
WITH_ADD_ALL = FIXED + NL + NL + "def add_all(xs):" + NL + "    return sum(xs)" + NL
LOOKUP = ("def get(d, k):" + NL + "    return d[k]" + NL)
LOOKUP_FIXED = ("def get(d, k):" + NL + "    return d.get(k)" + NL)
BASE = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
JUNIT = BASE + ["--junitxml={results}", "{test}"]
ONE_BY_ONE = BASE + ["{test}"]

MANY = ("import pytest" + NL + NL + "from calc import add, get" + NL + NL + NL
        + "def test_add():" + NL + "    assert add(1, 2) == 3" + NL + NL + NL
        + "def test_zero():" + NL + "    assert add(0, 0) == 0" + NL + NL + NL
        + "def test_get_missing():" + NL + "    assert get({}, 'x') is None"
        + NL + NL + NL
        + "@pytest.mark.parametrize('a', [0, 1])" + NL
        + "def test_twice(a):" + NL + "    assert add(a, a) == 2 * a" + NL
        + NL + NL
        + "def test_add_all_inside():" + NL
        + "    from calc import add_all" + NL
        + "    assert add_all([1, 2]) == 3" + NL + NL + NL
        + "class TestOuter:" + NL + "    class TestInner:" + NL
        + "        def test_two(self):" + NL
        + "            assert add(2, 2) == 4" + NL)
TOP_IMPORT = ("from calc import add_all" + NL + NL + NL
              + "def test_sum():" + NL + "    assert add_all([1, 2]) == 3"
              + NL + NL + NL
              + "def test_empty():" + NL + "    assert add_all([]) == 0" + NL)
MISSPELT_TOP = ("from calc import ad" + NL + NL + NL
                + "def test_ad():" + NL + "    assert ad(1, 2) == 3" + NL)
WORKER_SAID = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text(BUGGY + NL + NL + LOOKUP, encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_old.py").write_text(
        "def test_old():" + NL + "    assert True" + NL, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def changed(place, files, product):
    for rel, text in files.items():
        (place / rel).write_text(text, encoding="utf-8")
    (place / "calc.py").write_text(product, encoding="utf-8")


def started(place):
    fm = runner.config("fix-with-test")
    by_role = resolver.resolve(fm.raw, runner.flow_path("fix-with-test"))
    run = runner.Run("fix-with-test", fm, by_role, workdir=str(place))
    run.produced["worker.md"] = WORKER_SAID
    return run


def a_gate(run, **opts):
    """the shipped patcher's red-first gate, its options swapped for `opts`."""
    [shipped] = [g for g in run.gates_for("patcher.md") if g.name == "red-first"]
    return gates.build(dict(opts, gate="red-first"), where=shipped.where,
                       earlier=shipped.earlier, said_by=shipped.said_by,
                       start=shipped.start, order=shipped.order)


class Launches(object):
    """counts the test processes the gate starts, and lets a test do
    something to the results file after the runner wrote it."""

    def __init__(self, monkeypatch, after=None):
        self.argvs = []
        self.after = after
        real = subprocess.run

        def run(argv, *a, **kw):
            r = real(argv, *a, **kw)
            if "pytest" in argv:
                self.argvs.append(list(argv))
                if self.after:
                    for arg in argv:
                        if arg.startswith("--junitxml="):
                            self.after(Path(arg.split("=", 1)[1]))
            return r

        monkeypatch.setattr(redfirst_gate, "subprocess", types.SimpleNamespace(
            run=run, TimeoutExpired=subprocess.TimeoutExpired,
            CalledProcessError=subprocess.CalledProcessError))

    def count(self):
        return len(self.argvs)


def two_ways(tmp_path, monkeypatch, files, product, after=None):
    """-> (the one-by-one result, its launches, the batched result, its
    launches), each on a fresh repo with the same change."""
    out = []
    for name, cmd, extra in (("one", ONE_BY_ONE, {}),
                             ("batch", JUNIT, {"results": "junit"})):
        place = a_repo(tmp_path / name)
        run = started(place)
        changed(place, files, product)
        launches = Launches(monkeypatch, after if name == "batch" else None)
        r = a_gate(run, command=cmd, **extra).run("patched it")
        monkeypatch.undo()
        out.extend([r, launches.count()])
    return out


def test_a_command_that_takes_every_id_runs_one_process_a_side(tmp_path,
                                                               monkeypatch):
    one, one_n, batch, batch_n = two_ways(
        tmp_path, monkeypatch, {"tests/test_calc.py": MANY},
        WITH_ADD_ALL + NL + NL + LOOKUP_FIXED)
    ids = [t["test"] for t in one.tests]
    assert len(ids) == 6
    assert one_n == 2 * len(ids)
    assert batch_n == 2
    assert batch.tests == one.tests
    assert batch.ok == one.ok and batch.detail == one.detail
    by_id = dict((t["test"], (t["before"], t["kind"])) for t in batch.tests)
    assert by_id["tests/test_calc.py::test_add"] == ("red", "assertion")
    assert by_id["tests/test_calc.py::test_zero"] == ("green", "")
    assert by_id["tests/test_calc.py::test_get_missing"] == ("red", "KeyError")
    assert by_id["tests/test_calc.py::test_add_all_inside"] == (
        "red", "ImportError")


def test_a_module_that_cannot_import_what_the_fix_adds_reads_as_before(
        tmp_path, monkeypatch):
    """pytest stops the whole batch on a collection error, so the tests of
    the other files run in a second batch, not one by one."""
    one, one_n, batch, batch_n = two_ways(
        tmp_path, monkeypatch, {"tests/test_sum.py": TOP_IMPORT,
                                "tests/test_calc.py": MANY},
        WITH_ADD_ALL + NL + NL + LOOKUP_FIXED)
    assert one_n == 2 * len(one.tests) == 16
    assert batch.tests == one.tests
    assert batch.ok == one.ok
    assert batch_n == 3
    sums = [t for t in batch.tests if t["test"].startswith("tests/test_sum")]
    assert [(t["before"], t["kind"]) for t in sums] == [
        ("red", "ImportError"), ("red", "ImportError")]


def test_a_misspelt_import_at_the_top_is_an_error_both_ways(tmp_path,
                                                            monkeypatch):
    one, _, batch, batch_n = two_ways(
        tmp_path, monkeypatch, {"tests/test_ad.py": MISSPELT_TOP}, FIXED)
    assert not one
    assert batch.tests == one.tests
    assert batch.detail == one.detail
    assert batch_n <= 2


def test_a_flow_without_results_keeps_one_process_per_test(tmp_path,
                                                           monkeypatch):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    changed(place, {"tests/test_calc.py": MANY},
            WITH_ADD_ALL + NL + NL + LOOKUP_FIXED)
    launches = Launches(monkeypatch)
    r = a_gate(run, command=JUNIT).run("patched it")
    assert launches.count() == 2 * len(r.tests)
    assert all(len([a for a in argv if "test_calc.py" in a]) == 1
               for argv in launches.argvs)


@pytest.mark.parametrize("spoil", ["missing", "not xml", "no cases",
                                   "a folder"])
def test_a_results_file_that_cannot_be_read_never_reads_as_green(
        tmp_path, monkeypatch, spoil):
    def after(path):
        if spoil == "missing":
            path.unlink()
        elif spoil == "not xml":
            path.write_text("<testsuites><testcase", encoding="utf-8")
        elif spoil == "no cases":
            path.write_text("<testsuites><testsuite tests='0'/></testsuites>",
                            encoding="utf-8")
        else:
            path.unlink()
            path.mkdir()

    one, one_n, batch, batch_n = two_ways(
        tmp_path, monkeypatch, {"tests/test_calc.py": MANY},
        WITH_ADD_ALL + NL + NL + LOOKUP_FIXED, after=after)
    assert batch.tests == one.tests
    assert batch_n > 2, "nothing was read, so every test runs on its own"


def test_a_results_file_left_by_an_earlier_run_is_never_read(tmp_path,
                                                             monkeypatch):
    """the path is new for every batch; a stale file there would be a green
    nobody ran."""
    seen = []

    def after(path):
        seen.append(path)

    two_ways(tmp_path, monkeypatch, {"tests/test_calc.py": MANY},
             WITH_ADD_ALL + NL + NL + LOOKUP_FIXED, after=after)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert not any(p.exists() for p in seen)


@pytest.mark.parametrize("opts,said", [
    ({"command": JUNIT, "results": "tap"}, "results"),
    ({"command": ONE_BY_ONE, "results": "junit"}, "{results}")])
def test_a_results_key_the_gate_cannot_use_fails(tmp_path, opts, said):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    changed(place, {"tests/test_calc.py": MANY}, FIXED)
    r = a_gate(run, **opts).run("patched it")
    assert not r
    assert said in r.detail


def test_one_test_run_with_a_results_command_leaves_no_file_in_the_place(
        tmp_path):
    place = a_repo(tmp_path / "repo")
    status = git(place, "status", "--porcelain")
    g = redfirst_gate.RedFirstGate(command=JUNIT, results="junit")
    said = g.one(JUNIT, "tests/test_old.py::test_old", place)
    assert said == ("green", "")
    assert git(place, "status", "--porcelain") == status


@pytest.mark.parametrize("flow", ["fix-with-test", "build-feature"])
def test_the_shipped_flows_name_a_junit_results_file(flow):
    fm = runner.config(flow)
    [g] = [g for s in fm.steps for g in (s.get("gates") or [])
           if g.get("gate") == "red-first"]
    assert g.get("results") == "junit"
    assert "--junitxml={results}" in g["command"]
    assert g["command"][-1] == "{test}"
