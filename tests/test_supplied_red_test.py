"""a bug report that ships its own failing test, through the shipped
fix-with-test flow: the worker names the supplied test and writes none, the
patcher fixes the code and may add cases of its own. every gate is the
flow's own."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.providers import cli_provider, fake_provider
from agentweft.runner import engine, prompts, resume, state, stops

NL = chr(10)
# the shipped flow looks back after every run that ends, once, last
RETRO = "retro.md"
FLOWS = Path(__file__).resolve().parents[1] / "flows"
SUPPLIED = "tests/test_report.py"
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return sum((a, b))" + NL
RED = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
       + "    assert add(1, 2) == 3" + NL)
PIN = ("from calc import add" + NL + NL + NL + "def test_zero():" + NL
       + "    assert add(0, 0) == 0" + NL)
CAUGHT = ("from calc import add" + NL + NL + NL + "def test_two():" + NL
          + "    assert add(2, 2) == 4" + NL)
WORKER = "FAILS: assert -1 == 3" + NL + "TEST: " + SUPPLIED + NL
PATCHER = "TEST: " + SUPPLIED + NL + "add sums its arguments" + NL


def git(where, *args):
    subprocess.run(["git", "-C", str(where)] + list(args), check=True,
                   capture_output=True)


def a_project(tmp_path):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(BROKEN, encoding="utf-8")
    (project / SUPPLIED).write_text(RED, encoding="utf-8")
    git(project, "init", "-q")
    git(project, "config", "user.email", "t@t")
    git(project, "config", "user.name", "t")
    git(project, "add", ".")
    git(project, "commit", "-qm", "the report and its test")
    return project


def run_it(tmp_path, monkeypatch, added=None, fixes=True, said=PATCHER,
           worker_adds=None):
    """-> (exit code, steps asked, the red-first gate line of the patcher)."""
    project = a_project(tmp_path)
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step == RETRO:
            return fake_provider.NOTHING_TO_KEEP, False
        if step == "patcher.md":
            if fixes:
                (project / "calc.py").write_text(FIXED, encoding="utf-8")
            for rel, text in (added or {}).items():
                (project / rel).write_text(text, encoding="utf-8")
            return said, False
        for rel, text in (worker_adds or {}).items():
            (project / rel).write_text(text, encoding="utf-8")
        return WORKER, False

    monkeypatch.setattr(engine, "call", fake_call)
    # the retro is granted only to read, and a step with a grant is refused
    # unless the cli's version holds it to that grant
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--flows", str(FLOWS),
                                      "--workdir", "project",
                                      "--task", "add(1, 2) returns -1"])
    code = engine.main()
    [folder] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    lines = [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    red_first = [g for line in lines if line.get("step") == "patcher.md"
                 for g in line.get("gates") or [] if g["gate"] == "red-first"]
    return code, asked, red_first


def test_a_supplied_test_and_a_patch_that_adds_no_test_finish(
        tmp_path, monkeypatch):
    code, asked, red_first = run_it(tmp_path, monkeypatch)
    assert asked == ["worker.md", "patcher.md", RETRO]
    assert code == stops.EXIT_OK
    assert red_first[-1]["ok"]


def test_a_supplied_test_carries_a_patch_whose_new_tests_all_pass_before_it(
        tmp_path, monkeypatch):
    code, asked, red_first = run_it(tmp_path, monkeypatch,
                                    {"tests/test_more.py": PIN})
    assert asked == ["worker.md", "patcher.md", RETRO], red_first
    assert code == stops.EXIT_OK
    gate = red_first[-1]
    assert gate["ok"]
    assert SUPPLIED in gate["detail"] and "green with the fix" in gate["detail"]
    [pin] = gate["tests"]
    assert pin["test"] == "tests/test_more.py::test_zero"
    assert pin["counts"] == "pin"


def test_a_new_red_case_beside_a_supplied_test_is_still_coverage(
        tmp_path, monkeypatch):
    code, _, red_first = run_it(tmp_path, monkeypatch,
                                {"tests/test_more.py": CAUGHT})
    assert code == stops.EXIT_OK
    [case] = red_first[-1]["tests"]
    assert case["counts"] == "coverage"


def test_a_pin_does_not_carry_a_supplied_test_the_patch_leaves_red(
        tmp_path, monkeypatch):
    code, _, _ = run_it(tmp_path, monkeypatch, {"tests/test_more.py": PIN},
                        fixes=False)
    assert code != stops.EXIT_OK


INVERTED = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
            + "    assert add(1, 2) == -1" + NL)
SHADOWED = RED + NL + NL + "add = lambda a, b: 3" + NL


def test_a_patch_that_inverts_the_supplied_test_and_fixes_nothing_stops(
        tmp_path, monkeypatch):
    code, _, red_first = run_it(tmp_path, monkeypatch, {SUPPLIED: INVERTED},
                                fixes=False)
    assert code != stops.EXIT_OK, red_first
    assert not red_first[-1]["ok"]


def test_a_patch_that_shadows_the_code_in_the_supplied_test_stops(
        tmp_path, monkeypatch):
    code, _, red_first = run_it(tmp_path, monkeypatch, {SUPPLIED: SHADOWED},
                                fixes=False)
    assert code != stops.EXIT_OK, red_first
    assert not red_first[-1]["ok"]


def test_a_new_test_the_patch_names_must_be_red_beside_a_supplied_test(
        tmp_path, monkeypatch):
    code, _, red_first = run_it(
        tmp_path, monkeypatch, {"tests/test_more.py": PIN},
        said="TEST: tests/test_more.py::test_zero" + NL + "fixed" + NL)
    assert code != stops.EXIT_OK, red_first
    assert "tests/test_more.py::test_zero passes without the fix" in \
        red_first[-1]["detail"]


def test_a_green_test_the_worker_wrote_beside_a_supplied_test_is_a_pin(
        tmp_path, monkeypatch):
    code, _, red_first = run_it(tmp_path, monkeypatch,
                                worker_adds={"tests/test_more.py": PIN})
    assert code == stops.EXIT_OK, red_first
    [pin] = red_first[-1]["tests"]
    assert pin["counts"] == "pin"
    assert "pins current behaviour" in red_first[-1]["detail"]
