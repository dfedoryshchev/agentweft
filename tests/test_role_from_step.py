"""a step declares a role and points at a prompt file, and they are two things.

every flow in here names the file after the role, so the runner had been
reading one off the other: `role = step[:-3]`, a fanout matched as
`role + ".md"`, an `on_redo` target turned into a file name the same way. the
day a flow points two steps at two files for one role, all of that is wrong,
and a run dies with a KeyError on a name nobody wrote down.
"""
import io
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.roles import resolver
from agentweft.runner import cli, engine, prompts
from agentweft.runner.handoff import Handoff
from agentweft.runner.router import Router

NL = chr(10)
REDO = Handoff("reviewer", "VERDICT: redo", "redo")
PLAN = "a.py | look at a" + NL + "b.py | look at b" + NL

MINIMAL = "cut it down. say less." + NL
MAXIMAL = "say what else it could have been." + NL

PERSONA = ("name: personas" + NL
           + "steps:" + NL
           + "  - role: worker" + NL
           + "    prompt: worker.md" + NL
           + "  - role: reviewer" + NL
           + "    prompt: reviewer-minimalist.md" + NL
           + "journal: false" + NL
           + "provider:" + NL
           + "  provider: fake" + NL)

BOTH = ("name: both" + NL
        + "steps:" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "  - role: reviewer" + NL
        + "    prompt: reviewer-minimalist.md" + NL
        + "  - role: reviewer" + NL
        + "    prompt: reviewer-maximalist.md" + NL
        + "journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL)

FANNED = ("name: fan-named" + NL
          + "steps:" + NL
          + "  - role: planner" + NL
          + "    prompt: planner.md" + NL
          + "  - role: worker" + NL
          + "    prompt: worker-scan.md" + NL
          + "    fanout: true" + NL
          + "    workers: 2" + NL
          + "  - role: merge" + NL
          + "    prompt: merge.md" + NL
          + "journal: false" + NL
          + "provider:" + NL
          + "  provider: fake" + NL)

FILES = {"worker.md": "do the work." + NL,
         "planner.md": "split it up." + NL,
         "merge.md": "put it back together." + NL,
         "worker-scan.md": "scan the one file you were given." + NL,
         "reviewer-minimalist.md": MINIMAL,
         "reviewer-maximalist.md": MAXIMAL}


def a_flow(tmp_path, body, name):
    root = tmp_path / "flows"
    d = root / name
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (d / "instructions.md").write_text("review what you are given." + NL,
                                       encoding="utf-8")
    for filename, text in FILES.items():
        (d / filename).write_text(text, encoding="utf-8")
    return root


def go(tmp_path, monkeypatch, body, name, answers=None):
    """run main() over a throwaway flow; hand back what was asked of whom."""
    root = a_flow(tmp_path, body, name)
    answers = answers or {}
    asked = []
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        sent.setdefault(step, []).append(prompt)
        return answers.get(step, "nothing to report"), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", name, "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    return asked, sent


def run_dir(tmp_path):
    return [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]


def test_a_step_whose_file_is_not_named_after_its_role_still_runs(tmp_path,
                                                                  monkeypatch):
    asked, sent = go(tmp_path, monkeypatch, PERSONA, "personas")
    assert asked == ["worker.md", "reviewer-minimalist.md"]
    assert (run_dir(tmp_path) / "reviewer-minimalist.md").exists()


def test_the_role_library_answers_to_the_role_not_to_the_file_name(tmp_path,
                                                                   monkeypatch):
    """the reviewer contract lives in the library under the role's name.

    a step that points somewhere else is still a reviewer, so it still has to
    be told how to answer, and the flow's own words still have to reach it.
    """
    _, sent = go(tmp_path, monkeypatch, PERSONA, "personas")
    prompt = sent["reviewer-minimalist.md"][0]
    assert MINIMAL.strip() in prompt
    assert "VERDICT: redo" in prompt
    assert resolver.role_prompt("reviewer.md").strip() in prompt


def test_one_role_can_be_two_steps_with_a_prompt_file_each(tmp_path,
                                                           monkeypatch):
    asked, sent = go(tmp_path, monkeypatch, BOTH, "both")
    assert asked == ["worker.md", "reviewer-minimalist.md",
                     "reviewer-maximalist.md"]
    assert MINIMAL.strip() in sent["reviewer-minimalist.md"][0]
    assert MAXIMAL.strip() not in sent["reviewer-minimalist.md"][0]
    assert MAXIMAL.strip() in sent["reviewer-maximalist.md"][0]
    assert MINIMAL.strip() not in sent["reviewer-maximalist.md"][0]


def test_the_fanned_out_step_is_recognised_by_its_own_file(tmp_path,
                                                           monkeypatch):
    """the fanout is found by the step, so a renamed prompt still fans out."""
    asked, _ = go(tmp_path, monkeypatch, FANNED, "fan-named",
                  {"planner.md": PLAN})
    assert asked.count("worker-scan.md") == 2
    assert asked[-1] == "merge.md"
    written = run_dir(tmp_path) / "worker-scan.md"
    assert written.read_text(encoding="utf-8").count("nothing to report") == 2


def test_on_redo_names_a_role_and_gets_the_file_that_role_runs():
    fm = spec.load({"name": "x", "steps": [
        {"role": "worker", "prompt": "worker.md"},
        {"role": "patcher", "prompt": "patcher-second-go.md"},
        {"role": "verify", "prompt": "verify.md", "on_redo": "patcher"},
    ]})
    assert Router(fm, cap=2).next("verify.md", REDO) == "patcher-second-go.md"


def test_a_redo_with_nothing_declared_looks_for_the_worker_role():
    fm = spec.load({"name": "x", "steps": [
        {"role": "planner", "prompt": "planner.md"},
        {"role": "worker", "prompt": "first-pass.md"},
        {"role": "reviewer", "prompt": "reviewer.md"},
    ]})
    assert Router(fm, cap=2).next("reviewer.md", REDO) == "first-pass.md"


def test_one_step_asked_for_by_role_opens_the_file_that_role_runs(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    """`run.py step <flow> <role>` takes a role, and it says so in the usage."""
    root = a_flow(tmp_path, PERSONA, "personas")
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.append(prompt)
        return "nothing to report", False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "argv", ["run.py", "step", "personas", "reviewer"])
    monkeypatch.chdir(tmp_path)
    assert cli.cmd_step() == 0
    capsys.readouterr()
    assert MINIMAL.strip() in sent[0]


def test_a_step_nothing_in_the_flow_answers_to_is_named_in_the_error():
    fm = spec.load({"name": "x", "steps": [{"role": "worker"}]})
    run = engine.Run.__new__(engine.Run)
    run.fm = fm
    with pytest.raises(KeyError) as e:
        run.role_for("ghost.md")
    assert "ghost.md" in str(e.value)
