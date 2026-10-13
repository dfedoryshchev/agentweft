"""a step that writes tests is told what to test, and at which levels.

the coding steps of the shipped flows wrote the one test that went red and
stopped there. the brief asks for the cases the change reaches, and the
levels go in as values read from the settings, not as prose to infer.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import engine, prompts, resume, settings, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return sum((a, b))" + NL
THREE = NL.join([
    "from calc import add", "", "",
    "def test_add_two_positives():", "    assert add(1, 2) == 3", "", "",
    "def test_add_zero_is_the_other_number():", "    assert add(0, 5) == 5",
    "", "",
    "def test_add_negatives():", "    assert add(-1, -2) == -3", ""])
WORKER = ("FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
          + NL + THREE)
PATCHER = "TEST: tests/test_calc.py" + NL + "return a + b"
VERIFIED = NL.join(["PASS the test is written before the patch",
                    "PASS the test fails on the unpatched code",
                    "PASS the patch is the smallest thing that turns it green"])
ANSWERS = {"worker.md": WORKER, "patcher.md": PATCHER, "verify.md": VERIFIED}


def fix_run(tmp_path, monkeypatch, flows=FLOWS, project_files=None):
    """-> (the prompt each step was sent, the run's folder)."""
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(BROKEN, encoding="utf-8")
    for name, text in (project_files or {}).items():
        (project / name).write_text(text, encoding="utf-8")
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent[step] = prompt
        if step == "worker.md":
            (project / "tests" / "test_calc.py").write_text(THREE,
                                                            encoding="utf-8")
        if step == "patcher.md":
            (project / "calc.py").write_text(FIXED, encoding="utf-8")
        return ANSWERS.get(step, ""), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--flows", str(flows),
                                      "--workdir", "project",
                                      "--task", "add(1, 2) returns -1"])
    engine.main()
    run_dir = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    return sent, run_dir


def test_the_fix_with_test_worker_is_asked_for_more_than_the_red_test(
        tmp_path, monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch)
    prompt = sent["worker.md"]
    flat = " ".join(prompt.split())
    for ask in ("every behaviour the change can reach, asserted",
                "each branch it can take and each result it can return",
                "both sides of every boundary",
                "empty, zero, very large, very long, non-ASCII, malformed and"
                " missing",
                "every type and format the interface accepts",
                "the error messages and exit codes",
                "what goes to stdout and what goes to stderr",
                "every error path a user can reach",
                "each caller or command",
                "each pair where one option changes what another does",
                "a case a test already covers is not added",
                "stop when every behaviour the code permits is asserted",
                "never from running the code"):
        assert ask in flat, ask
    assert NL + "    NEEDS: " in prompt
    for level in ("    unit: on", "    integration: ", "    e2e: "):
        assert level in prompt


def test_with_e2e_off_the_prompt_says_not_to_write_them(tmp_path,
                                                        monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch)
    assert "    e2e: off - do not write e2e tests" in sent["worker.md"]
    assert settings.get("tests_e2e") is False


def test_the_patcher_gets_the_same_brief(tmp_path, monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch)
    assert "both sides of every boundary" in sent["patcher.md"]
    assert "    e2e: off" in sent["patcher.md"]
    assert "both sides of every boundary" not in sent["verify.md"]


def test_a_worker_that_adds_three_tests_keeps_all_three_in_its_record(
        tmp_path, monkeypatch):
    _, run_dir = fix_run(tmp_path, monkeypatch)
    record = (run_dir / "worker.md").read_text(encoding="utf-8")
    for name in ("test_add_two_positives", "test_add_zero_is_the_other_number",
                 "test_add_negatives"):
        assert "def " + name + "():" in record
    gates = (run_dir / "gates.md").read_text(encoding="utf-8")
    assert "PASS red-test - red, exit 1" in gates.split("## patcher.md")[0]
    assert "PASS red-test - green, exit 0" in gates.split("## patcher.md")[1]


def test_the_brief_names_no_count_of_cases(tmp_path, monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch)
    prompt = sent["worker.md"]
    brief = prompt[prompt.find("## the tests around the change"):]
    brief = brief[:brief.find("the levels for this run")]
    assert "no number of cases to reach" in brief
    for count in ("two tests", "three", "five", "at least", "at most"):
        assert count not in brief


def copied_flow(tmp_path, extra):
    """-> a flows folder holding fix-with-test with `extra` added to its file."""
    root = tmp_path / "flows"
    (root / "fix-with-test").mkdir(parents=True)
    for p in (FLOWS / "fix-with-test").iterdir():
        (root / "fix-with-test" / p.name).write_text(
            p.read_text(encoding="utf-8"), encoding="utf-8")
    flow = root / "fix-with-test" / "flow.yaml"
    flow.write_text(flow.read_text(encoding="utf-8") + extra, encoding="utf-8")
    return root


def test_a_flow_that_turns_e2e_on_says_so(tmp_path, monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch,
                      flows=copied_flow(tmp_path, "tests_e2e: true" + NL))
    assert "    e2e: on" in sent["worker.md"]
    assert "do not write e2e tests" not in sent["worker.md"]


def test_integration_is_on_where_the_project_has_an_entry_point(tmp_path,
                                                                monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch, project_files={
        "pyproject.toml": "[project]" + NL + "name = 'calc'" + NL + NL
        + "[project.scripts]" + NL + "calc = 'calc:main'" + NL})
    assert ("    integration: on - the project has an entry point"
            " (pyproject.toml [project.scripts])") in sent["worker.md"]


def test_integration_is_off_where_there_is_no_entry_point(tmp_path,
                                                          monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch)
    assert ("    integration: off - no entry point found, do not write"
            " integration tests") in sent["worker.md"]


def test_a_flow_can_turn_integration_off_over_an_entry_point(tmp_path,
                                                             monkeypatch):
    sent, _ = fix_run(tmp_path, monkeypatch,
                      flows=copied_flow(tmp_path,
                                        "tests_integration: false" + NL),
                      project_files={"__main__.py": "print(1)" + NL})
    assert ("    integration: off - tests_integration is false, do not write"
            " integration tests") in sent["worker.md"]


@pytest.mark.parametrize("files, why", [
    ({"pyproject.toml": "[project.scripts]" + NL + "x = 'x:main'" + NL},
     "pyproject.toml [project.scripts]"),
    ({"__main__.py": ""}, "__main__.py"),
    ({"pkg/__main__.py": ""}, "pkg/__main__.py"),
    ({"main.py": ""}, "main.py"),
    ({"pyproject.toml": "[project]" + NL + "name = 'x'" + NL}, ""),
    ({}, ""),
])
def test_what_counts_as_an_entry_point(tmp_path, files, why):
    from agentweft.runner import levels
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert levels.entry_point(tmp_path) == why


def test_the_build_feature_tester_and_worker_get_the_brief_and_the_rest_not(
        monkeypatch):
    from agentweft import runner
    from agentweft.roles import resolver
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    fm = runner.config("build-feature")
    by_role = resolver.resolve(fm.raw, runner.flow_path("build-feature"))
    run = runner.Run("build-feature", fm, by_role, workdir=str(FLOWS))
    assert run.writes_tests("tester.md")
    assert run.writes_tests("worker.md")
    assert not run.writes_tests("reviewer.md")
    assert not run.writes_tests("planner.md")
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent[step] = " ".join(prompt.split())
        return "ok", False

    monkeypatch.setattr(engine, "call", fake_call)
    for step in ("planner.md", "tester.md", "worker.md", "reviewer.md"):
        run.step(step)
    rule = "stop when every behaviour the code permits is asserted"
    assert rule in sent["tester.md"]
    assert rule in sent["worker.md"]
    assert rule not in sent["planner.md"]
    assert rule not in sent["reviewer.md"]


@pytest.mark.parametrize("flow", ["code-review", "weekly-digest",
                                  "release-notes", "repo-audit", "ops-check",
                                  "summarise-and-check"])
def test_a_worker_that_writes_no_code_gets_no_test_brief(flow, monkeypatch):
    from agentweft import runner
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    fm = runner.config(flow)
    assert not any(s.get("writes_tests") for s in fm.steps)


def test_the_loader_takes_the_test_settings_and_refuses_wrong_values():
    good = {"name": "x", "tests_e2e": True, "tests_integration": "auto",
            "steps": [{"role": "worker", "writes_tests": True}]}
    assert spec.check(good) == []
    bad = spec.check({"name": "x", "tests_e2e": "yes",
                      "tests_integration": "sometimes",
                      "steps": [{"role": "worker", "writes_tests": 1}]})
    assert "tests_e2e should be bool" in bad
    assert "tests_integration should be true, false or auto" in bad
    assert "step 0: writes_tests should be true or false" in bad
