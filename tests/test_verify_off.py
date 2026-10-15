"""fix-with-test's promises are shown by programs, so its judge is off.

every check the verify step used to answer is a gate now: the red-test gate
shows the new test fails before the patch and passes after it, the red-first
gate shows each new test fails on the unpatched code, and the command gate
runs the suite. `verify: judge` puts the judge back for the one thing no
program shows, whether the patch is the smallest one.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.guardrails import promises
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parent.parent / "flows"

BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return sum((a, b))" + NL
RED_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
            + "    assert add(1, 2) == 3" + NL)
MORE_CASES = RED_TEST + (NL + NL + "def test_add_negative():" + NL
                         + "    assert add(-1, -2) == -3" + NL)
GUARD = ("from calc import add" + NL + NL + NL + "def test_zero():" + NL
         + "    assert add(0, 0) == 0" + NL)
WORKER = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py::test_add" + NL
ORDER_FAIL = NL.join([
    "FAIL the test is written before the patch - test_add_negative came after",
    "PASS the test fails on the unpatched code",
    "PASS the patch is the smallest thing that turns it green"])


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text(BUGGY, encoding="utf-8")
    (where / "conftest.py").write_text("", encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_old.py").write_text(
        "def test_old():" + NL + "    assert True" + NL, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def go(tmp_path, monkeypatch, patcher_writes, patcher_says, verify=None,
       verify_says=ORDER_FAIL):
    """the shipped flow on fake answers in a real repo, with `verify:` set to
    `verify` when given. -> (steps asked, gates.md, prompts seen)."""
    place = a_repo(tmp_path / "repo")
    flows = tmp_path / "flows"
    shutil.copytree(FLOWS / "fix-with-test", flows / "fix-with-test")
    yml = flows / "fix-with-test" / "flow.yaml"
    text = yml.read_text(encoding="utf-8")
    if verify is not None:
        text = NL.join(l for l in text.split(NL)
                       if not l.startswith("verify:")) + NL
        text = text + "verify: " + verify + NL
    yml.write_text(text + "provider:" + NL + "  provider: fake" + NL,
                   encoding="utf-8")
    asked, seen = [], {}
    answers = {"worker.md": WORKER, "patcher.md": patcher_says,
               "verify.md": verify_says}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        seen[step] = prompt
        if step == "worker.md":
            (place / "tests" / "test_calc.py").write_text(RED_TEST,
                                                          encoding="utf-8")
        if step == "patcher.md":
            for rel, body in patcher_writes.items():
                (place / rel).write_text(body, encoding="utf-8")
        return answers[step], False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--workdir", str(place),
                                      "--task", "add(1, 2) returns -1"])
    engine.main()
    written = "".join((p / "gates.md").read_text(encoding="utf-8")
                      for p in state.RUNS.iterdir()
                      if (p / "gates.md").exists())
    return asked, written, seen


def test_the_default_flow_makes_no_verify_call_and_runs_the_suite(
        tmp_path, monkeypatch):
    asked, written, _ = go(tmp_path, monkeypatch, {"calc.py": FIXED},
                           "TEST: tests/test_calc.py::test_add" + NL + "fixed")
    assert asked == ["worker.md", "patcher.md"], written
    patcher = written.split("## patcher.md")[1]
    assert "PASS red-first" in patcher
    assert "PASS command" in patcher
    journal = (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")
    assert "not checked" not in journal


def test_the_default_flow_still_stops_a_new_test_that_passes_without_the_fix(
        tmp_path, monkeypatch):
    asked, written, _ = go(
        tmp_path, monkeypatch,
        {"calc.py": FIXED, "tests/test_calc.py": RED_TEST + NL + NL + GUARD
         .replace("from calc import add" + NL + NL + NL, "")},
        "TEST: tests/test_calc.py::test_zero" + NL + "fixed")
    assert "verify.md" not in asked
    assert "FAIL red-first" in written.split("## patcher.md")[1]
    assert "test_zero passes without the fix" in written


def test_cases_the_patcher_adds_after_the_fix_are_proven_by_the_gate(
        tmp_path, monkeypatch):
    """a judge asked about the order fails a test written after the patch;
    the red-first gate shows the late case red on the unpatched code."""
    asked, written, _ = go(tmp_path, monkeypatch,
                           {"calc.py": FIXED, "tests/test_calc.py": MORE_CASES},
                           "TEST: tests/test_calc.py::test_add" + NL + "fixed")
    assert asked == ["worker.md", "patcher.md"], written
    assert "FAIL " not in written
    assert "2 of 2 new tests red without the fix" in written


def test_with_the_judge_on_it_asks_only_for_the_smallest_patch(tmp_path,
                                                              monkeypatch):
    asked, written, seen = go(
        tmp_path, monkeypatch, {"calc.py": FIXED},
        "TEST: tests/test_calc.py::test_add" + NL + "fixed", verify="judge",
        verify_says="PASS the patch is the smallest thing that turns it green")
    assert asked == ["worker.md", "patcher.md", "verify.md"], written
    assert "FAIL " not in written
    words = (FLOWS / "fix-with-test" / "verify.md").read_text(encoding="utf-8")
    assert "smallest" in words
    assert "before the patch" not in words.lower()
    assert "order" not in words.lower()
    assert "before the patch" not in seen["verify.md"].lower()


def test_the_shipped_flow_says_verify_off():
    fm = runner.config("fix-with-test")
    assert fm.raw["verify"] == "off"
    assert [s["role"] for s in fm.steps] == ["worker", "patcher"]


def test_no_promise_of_the_flow_is_left_to_a_model():
    fm = runner.config("fix-with-test")
    shown = promises.shown_by(fm.steps, fm.promises.invariants)
    assert shown and all(by for _inv, by in shown), shown
    assert not [i for i in fm.promises.invariants if "before the patch" in i]


def test_show_names_the_gate_behind_each_promise(monkeypatch, capsys):
    from agentweft.runner import cli
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(sys, "argv", ["run.py", "show", "fix-with-test"])
    cli.cmd_show()
    said = capsys.readouterr().out
    assert ("always: the whole suite passes with the patch  (shown by command"
            " on patcher.md)") in said
    assert "  verify: off" in said


def test_shown_by_names_the_gate_and_the_step():
    steps = [{"role": "worker", "prompt": "worker.md",
              "gates": [{"gate": "red-test", "red": True, "command": ["x"]}]},
             {"role": "patcher", "prompt": "patcher.md",
              "gates": [{"gate": "red-test", "red": False, "command": ["x"]},
                        {"gate": "command", "command": ["pytest"]}]}]
    got = dict(promises.shown_by(steps, [
        "the new test fails on the unpatched code",
        "the new test passes with the patch",
        "the whole suite passes with the patch",
        "the patch is the smallest thing that turns it green"]))
    assert got["the new test fails on the unpatched code"] == [
        "red-test on worker.md"]
    assert got["the new test passes with the patch"] == [
        "red-test on patcher.md"]
    assert got["the whole suite passes with the patch"] == [
        "command on patcher.md"]
    assert got["the patch is the smallest thing that turns it green"] == []


def flow(**more):
    raw = {"name": "x", "steps": [{"role": "worker"}, {"role": "verify"}]}
    raw.update(more)
    return raw


def test_verify_off_drops_the_verify_steps_and_judge_keeps_them():
    assert [s["role"] for s in spec.load(flow(verify="off")).steps] == [
        "worker"]
    # a bare `off` in yaml is read as false
    assert [s["role"] for s in spec.load(flow(verify=False)).steps] == [
        "worker"]
    assert spec.load(flow(verify=False)).raw["verify"] == "off"
    assert [s["role"] for s in spec.load(flow(verify="judge")).steps] == [
        "worker", "verify"]
    assert [s["role"] for s in spec.load(flow()).steps] == ["worker", "verify"]


@pytest.mark.parametrize("raw, said", [
    (flow(verify="maybe"), "verify should be one of judge, off"),
    ({"name": "x", "steps": [{"role": "worker"}], "verify": "judge"},
     "verify: judge, but no step has the role verify"),
])
def test_a_wrong_verify_key_is_refused(raw, said):
    assert said in spec.check(raw)
