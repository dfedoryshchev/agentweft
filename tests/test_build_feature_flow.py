"""the shipped build-feature flow end to end, on fake answers and a real pytest.

each step's answer is canned, and the tester and the worker write into the
project the way a model with a shell would. the gates are the flow's own.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
TASK = "calc gets mul(a, b), which multiplies"
BEFORE = "def add(a, b):" + NL + "    return a + b" + NL
AFTER = BEFORE + NL + NL + "def mul(a, b):" + NL + "    return a * b" + NL
TEST = ("def test_mul():" + NL + "    from calc import mul" + NL + NL
        + "    assert mul(2, 3) == 6" + NL)
PLAN = "- mul(2, 3) is 6 | calc.py" + NL
TESTER = ("FAILS: ImportError: cannot import name 'mul' from 'calc'" + NL
          + "TEST: tests/test_mul.py" + NL)
WORKER = "- calc.py: mul(a, b) added" + NL
OK = "VERDICT: ok" + NL + NL + WORKER
REDO = "VERDICT: redo" + NL + NL + "mul is not tried on a negative number" + NL


def run_it(tmp_path, monkeypatch, answers, builds=True, before=BEFORE,
           task=TASK):
    """-> (steps asked, in order, gates.md, every prompt sent, exit code)."""
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(before, encoding="utf-8")
    asked = []
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        n = asked.count(step)
        asked.append(step)
        sent.append(prompt)
        if step == "tester.md":
            (project / "tests" / "test_mul.py").write_text(TEST,
                                                           encoding="utf-8")
        if step == "worker.md" and builds:
            (project / "calc.py").write_text(AFTER, encoding="utf-8")
        said = answers.get(step, [""])
        return said[min(n, len(said) - 1)], False

    monkeypatch.setattr(engine, "call", fake_call)
    # the reviewer's grant asks the cli its version before the step starts
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    argv = ["run.py", "build-feature", "--force", "--flows", str(FLOWS),
            "--workdir", "project"]
    if task is not None:
        argv = argv + ["--task", task]
    monkeypatch.setattr(sys, "argv", argv)
    code = engine.main()
    runs = tmp_path / "runs"
    written = "".join((p / "gates.md").read_text(encoding="utf-8")
                      for p in (runs.iterdir() if runs.exists() else [])
                      if (p / "gates.md").exists())
    return asked, written, sent, code


ALL = {"planner.md": [PLAN], "tester.md": [TESTER], "worker.md": [WORKER],
       "reviewer.md": [OK]}


def test_a_task_walks_planner_tester_worker_suite_reviewer(tmp_path,
                                                          monkeypatch):
    asked, written, sent, code = run_it(tmp_path, monkeypatch, ALL)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md"]
    assert "PASS red-test - red, exit 1" in written.split("## tester.md")[1]
    assert "PASS command - exit 0" in written.split("## worker.md")[1]
    assert "FAIL " not in written
    assert all(TASK in prompt for prompt in sent)


def test_a_reviewer_redo_sends_the_worker_back(tmp_path, monkeypatch):
    again = WORKER + "- tests/test_mul.py: mul(-2, 3) is -6" + NL
    answers = dict(ALL, **{"worker.md": [WORKER, again],
                           "reviewer.md": [REDO, OK]})
    asked, written, _, _ = run_it(tmp_path, monkeypatch, answers)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "worker.md", "reviewer.md"]
    assert "FAIL " not in written


def test_a_failing_suite_stops_the_run_at_the_worker(tmp_path, monkeypatch):
    asked, written, _, _ = run_it(tmp_path, monkeypatch, ALL, builds=False)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    at_worker = written.split("## worker.md")[1]
    assert "FAIL command - exit 1" in at_worker
    journal = (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")
    assert "  failed at worker.md  " in journal
    assert "command: exit 1" in journal


def test_a_test_that_already_passes_stops_the_run_before_any_code(
        tmp_path, monkeypatch):
    asked, written, _, _ = run_it(tmp_path, monkeypatch, ALL, before=AFTER)
    assert asked == ["planner.md", "tester.md"]
    assert "the test passed before the patch" in written


def test_it_will_not_start_without_a_task(tmp_path, monkeypatch, capsys):
    asked, _, _, code = run_it(tmp_path, monkeypatch, ALL, task=None)
    assert code == 1
    assert "build-feature takes a task" in capsys.readouterr().out
    assert asked == []
