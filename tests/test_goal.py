"""a run may carry the goal it serves, beside the task.

`--goal "<text>"` (or `--goal-file <path>`) is kept apart from the task and
the spec: every step's prompt is handed it once, with the ask to name the
part of its work that drives it and the one thing it was handed it doubts
most, and the handoff carries it. with no goal nothing is added anywhere,
so the prompts of the shipped flows stay byte for byte what they were (the
prompt-hash goldens hold that too).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.providers import cli_provider
from agentweft.runner import consult, engine, goal, prompts, resume, state

from test_build_feature_flow import AFTER, ALL, BEFORE, TASK, TEST

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
GOAL = "shop staff price a basket in one go, so a till never rounds twice"
CAFE = "le caf" + chr(0xe9) + " reste au prix du jour"
HEAD = "THE GOAL. the problem this run solves"


def run_it(tmp_path, monkeypatch, extra=(), answers=ALL):
    """the shipped build-feature flow on fake answers: -> ([(step, prompt)],
    exit code)."""
    project = tmp_path / "project"
    if not project.exists():
        (project / "tests").mkdir(parents=True)
        (project / "conftest.py").write_text("", encoding="utf-8")
        (project / "calc.py").write_text(BEFORE, encoding="utf-8")
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.append((step, prompt))
        if step == "tester.md":
            (project / "tests" / "test_mul.py").write_text(TEST,
                                                           encoding="utf-8")
        if step == "worker.md":
            (project / "calc.py").write_text(AFTER, encoding="utf-8")
        return answers.get(step, [""])[0], False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build-feature", "--force",
                                      "--flows", str(FLOWS), "--workdir",
                                      "project", "--task", TASK]
                        + list(extra))
    return sent, engine.main()


def folder(tmp_path):
    return sorted((p for p in (tmp_path / "runs").iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime)[-1]


@pytest.mark.parametrize("given", [GOAL, CAFE])
def test_every_step_is_handed_the_goal_once(tmp_path, monkeypatch, given):
    sent, code = run_it(tmp_path, monkeypatch, ["--goal", given])
    assert code == 0
    steps = [s for s, _ in sent if s != "retro.md"]
    assert steps == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md"]
    for step, prompt in sent:
        if step == "retro.md":
            continue
        assert prompt.count(given) == 1, step
        assert prompt.count(HEAD) == 1, step
        assert "name the part of your work that drives it, and the one thing" \
            " you were handed that you doubt most" in " ".join(prompt.split())
    assert (folder(tmp_path) / goal.FILE).read_text(encoding="utf-8") == given
    handoff = (folder(tmp_path) / "handoff.md").read_text(encoding="utf-8")
    assert "- goal: " + given + " (all of it in runs/" in handoff


def test_with_no_goal_no_prompt_holds_any_of_it(tmp_path, monkeypatch):
    sent, code = run_it(tmp_path, monkeypatch)
    assert code == 0
    for step, prompt in sent:
        assert HEAD not in prompt, step
        assert "doubt most" not in prompt, step
    assert not (folder(tmp_path) / goal.FILE).exists()
    assert "- goal: " not in (folder(tmp_path) / "handoff.md").read_text(
        encoding="utf-8")


def test_an_empty_goal_is_no_goal(tmp_path, monkeypatch):
    sent, code = run_it(tmp_path, monkeypatch, ["--goal", "   "])
    assert code == 0
    assert all(HEAD not in prompt for _, prompt in sent)


def test_a_goal_file_is_read_and_a_missing_one_refused(tmp_path, monkeypatch,
                                                       capsys):
    path = tmp_path / "goal.txt"
    path.write_text(chr(0xfeff) + GOAL + NL, encoding="utf-8")
    sent, code = run_it(tmp_path, monkeypatch, ["--goal-file", str(path)])
    assert code == 0
    assert all(prompt.count(GOAL) == 1 for s, prompt in sent
               if s != "retro.md")
    capsys.readouterr()
    sent, code = run_it(tmp_path, monkeypatch,
                        ["--goal-file", str(tmp_path / "nope.txt")])
    assert code == 1
    assert sent == []
    assert "no such file" in capsys.readouterr().out


def test_the_flags_are_read_once_and_wrong_uses_refused():
    assert goal.given(["x"]) is None
    assert goal.given(["--goal", GOAL]) == GOAL
    assert goal.given(["--goal", ""]) is None
    for argv in (["--goal"], ["--goal", "a", "--goal-file", "b"]):
        with pytest.raises(ValueError):
            goal.given(argv)
    assert goal.fragment(None) == "" and goal.fragment("") == ""


def test_a_resume_carries_the_goal_and_refuses_another(tmp_path, monkeypatch,
                                                       capsys):
    answers = dict(ALL, **{"worker.md": ["NEEDS: which rounding?" + NL]})
    answers["planner.md"] = ["ESCALATE: the operator knows" + NL]
    sent, code = run_it(tmp_path, monkeypatch, ["--goal", GOAL], answers)
    assert code != 0
    first = folder(tmp_path)
    capsys.readouterr()
    sent, code = run_it(tmp_path, monkeypatch, ["--resume", first.name,
                                                "--goal", "another goal",
                                                "--answer", "half up"])
    assert code == 1 and sent == []
    assert "started with another goal" in capsys.readouterr().out
    sent, code = run_it(tmp_path, monkeypatch, ["--resume", first.name,
                                                "--answer", "half up"])
    assert sent and all(prompt.count(GOAL) == 1 for s, prompt in sent
                        if s != "retro.md")


class Run(object):
    workdir = "."
    start = None
    task_text = "the request"

    def rulings(self):
        return []


def test_the_business_analyst_consult_is_handed_the_goal():
    run = Run()
    run.goal = GOAL
    ba = consult.brief(run, "ba", "what does it mean", "NEEDS: x?", "", [])
    assert ba.count(GOAL) == 1
    architect = consult.brief(run, "architect", "where", "NEEDS: x?", "", [])
    assert GOAL not in architect
    run.goal = None
    assert HEAD not in consult.brief(run, "ba", "what", "NEEDS: x?", "", [])
