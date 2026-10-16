import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.guardrails.gates.base import Result
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parent.parent / "flows"

BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
RED_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
            + "    assert add(1, 2) == 3" + NL)
CASES = ("from calc import add" + NL + NL + NL
         + "def test_add_two():" + NL + "    assert add(2, 2) == 4" + NL + NL + NL
         + "def test_add_negative():" + NL + "    assert add(1, -1) == 0" + NL
         + NL + NL
         + "def test_zero():" + NL + "    assert add(0, 0) == 0" + NL)
WORKER_SAID = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
PIN = "tests/test_cases.py::test_zero"


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text(BUGGY, encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_old.py").write_text(
        "def test_old():" + NL + "    assert True" + NL, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def write(place, rel, text):
    (place / rel).write_text(text, encoding="utf-8")


def replays_left(place):
    return [l for l in git(place, "worktree", "list", "--porcelain").split(NL)
            if l.startswith("worktree ") and "agentweft-replay-" in l]


def started(place, flow):
    fm = runner.config(flow)
    by_role = resolver.resolve(fm.raw, runner.flow_path(flow))
    return runner.Run(flow, fm, by_role, workdir=str(place))


def red_shown(run, step):
    """the red step's red-test gate saw the first test fail."""
    assert run.order.proven(step, [Result("red-test", True, "red, exit 1")],
                            WORKER_SAID)


def replayed(run, step, answer="patched it"):
    [gate] = [g for g in run.gates_for(step) if g.name == "red-first"]
    return gate.run(answer)


def by_id(record):
    return dict((t["test"], t) for t in record)


def test_two_red_and_one_green_added_after_green_are_2_coverage_and_1_pin(
        tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place, "fix-with-test")
    write(place, "tests/test_calc.py", RED_TEST)
    run.produced["worker.md"] = WORKER_SAID
    red_shown(run, "worker.md")
    write(place, "calc.py", FIXED)
    write(place, "tests/test_cases.py", CASES)
    r = replayed(run, "patcher.md")
    assert r, r.detail
    tests = by_id(r.tests)
    assert "added" not in tests["tests/test_calc.py::test_add"]
    assert tests["tests/test_cases.py::test_add_two"].get("counts") == \
        "coverage"
    assert tests["tests/test_cases.py::test_add_negative"].get("counts") == \
        "coverage"
    assert tests[PIN].get("counts") == "pin"
    assert all(tests[i].get("added") == "after green" for i in tests
               if i.startswith("tests/test_cases.py"))
    assert "added after green: 2 coverage, 1 pin" in r.detail
    assert PIN + " pins current behaviour" in r.detail
    assert replays_left(place) == []


def test_a_late_unit_test_importing_what_the_fix_adds_is_coverage(tmp_path):
    """the tester's FAILS: line names the CLI's error, not the ImportError a
    unit test of the new helper gives without the fix."""
    place = a_repo(tmp_path / "repo")
    run = started(place, "build-feature")
    write(place, "tests/test_calc.py", RED_TEST)
    run.produced["tester.md"] = ("FAILS: error: unrecognized arguments: --all"
                                 + NL + "TEST: tests/test_calc.py" + NL)
    red_shown(run, "tester.md")
    write(place, "calc.py", FIXED + NL + NL + "def add_all(xs):" + NL
          + "    return sum(xs)" + NL)
    write(place, "tests/test_units.py", "def test_add_all():" + NL
          + "    from calc import add_all" + NL + NL
          + "    assert add_all([1, 2]) == 3" + NL)
    r = replayed(run, "worker.md")
    assert r, r.detail
    late = by_id(r.tests)["tests/test_units.py::test_add_all"]
    assert late["before"] == "red"
    assert late["kind"] == "ImportError"
    assert late.get("counts") == "coverage"
    assert "added after green: 1 coverage, 0 pins" in r.detail
    assert replays_left(place) == []


def test_a_pin_ok_from_the_planner_exempts_the_pin_and_is_recorded(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place, "build-feature")
    run.produced["planner.md"] = ("- add two numbers | calc.py" + NL
                                  + "PIN OK: zero is a guard the change must"
                                  " keep" + NL)
    write(place, "tests/test_calc.py", RED_TEST)
    run.produced["tester.md"] = WORKER_SAID
    red_shown(run, "tester.md")
    write(place, "calc.py", FIXED)
    write(place, "tests/test_cases.py", CASES)
    r = replayed(run, "worker.md")
    assert r, r.detail
    pin = by_id(r.tests)[PIN]
    assert pin.get("counts") == "pin"
    assert pin.get("pin_ok") == \
        "planner: zero is a guard the change must keep"
    assert "allowed by planner: zero is a guard the change must keep" \
        in r.detail
    assert replays_left(place) == []


def test_a_pin_ok_from_the_step_that_wrote_the_case_exempts_nothing(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place, "fix-with-test")
    write(place, "tests/test_calc.py", RED_TEST)
    run.produced["worker.md"] = WORKER_SAID + "PIN OK: the worker says so" + NL
    red_shown(run, "worker.md")
    write(place, "calc.py", FIXED)
    write(place, "tests/test_cases.py", CASES)
    r = replayed(run, "patcher.md", answer="patched it" + NL
                 + "PIN OK: it is only a guard")
    assert r, r.detail
    assert "pin_ok" not in by_id(r.tests)[PIN]
    assert "allowed by" not in r.detail


def test_the_handoff_and_steps_record_list_the_pin(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    flows = tmp_path / "flows"
    shutil.copytree(FLOWS / "fix-with-test", flows / "fix-with-test")
    yml = flows / "fix-with-test" / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8") + "provider:" + NL
                   + "  provider: fake" + NL, encoding="utf-8")

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if step == "worker.md":
            write(place, "tests/test_calc.py", RED_TEST)
            return WORKER_SAID, False
        if step == "patcher.md":
            write(place, "calc.py", FIXED)
            write(place, "tests/test_cases.py", CASES)
            return "TEST: tests/test_calc.py" + NL + "patched it" + NL, False
        return "PASS fine" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--workdir", str(place),
                                      "--task", "add(1, 2) returns -1"])
    engine.main()
    [folder] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    lines = [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]
    patcher = [l for l in lines if l["step"] == "patcher.md"][0]
    record = [g for g in patcher["gates"] if g["gate"] == "red-first"][0]
    assert record["ok"]
    assert by_id(record["tests"])[PIN].get("counts") == "pin"
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    tests = handoff.split("## tests and checks")[1].split("## ")[0]
    assert ("- " + PIN + ": green without the fix, green with it; added after"
            " green, pins current behaviour, not counted as coverage") in tests
    assert ("- tests/test_cases.py::test_add_two: red without the fix"
            " (assertion), green with it; added after green, coverage") in tests
    assert replays_left(place) == []
