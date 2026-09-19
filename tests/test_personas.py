"""one role, two stances, and a judge that has to resolve them.

a reviewer told to cut and a reviewer told to say what else it could have been
are the same role, and they will not agree. that disagreement is the whole
value of running the role twice, and the judge is the step that ends it.

the flow file had the words for all of it and they did not meet. a role has
been able to be two steps since the prompt file stopped naming it, and a step
has been able to name the `reports` it judges - but what a step produced was
filed under its ROLE, so the second reviewer landed on top of the first and
`reports: [reviewer]` handed the judge one report out of two. a pair whose
judge silently reads one of them is a pair that is not worth running.
"""
import io
import pathlib
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import cli, engine, prompts
from agentweft.runner.handoff import Handoff
from agentweft.runner.router import Router

NL = chr(10)
REDO = Handoff("judge", "VERDICT: redo", "redo")

MINIMAL = "cut it down. say less." + NL
MAXIMAL = "say what else it could have been." + NL

TAIL = ("journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL)

PAIR = ("name: personas" + NL
        + "steps:" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "  - role: reviewer" + NL
        + "    prompt: reviewer-minimalist.md" + NL
        + "  - role: reviewer" + NL
        + "    prompt: reviewer-maximalist.md" + NL
        + "  - role: judge" + NL
        + "    prompt: judge.md" + NL
        + "    reports: [worker, reviewer]" + NL
        + TAIL)

ONE = ("name: personas" + NL
       + "steps:" + NL
       + "  - role: worker" + NL
       + "    prompt: worker.md" + NL
       + "  - role: reviewer" + NL
       + "    prompt: reviewer-minimalist.md" + NL
       + "  - role: judge" + NL
       + "    prompt: judge.md" + NL
       + "    reports: [worker, reviewer]" + NL
       + TAIL)

NAMED = ("name: personas" + NL
         + "steps:" + NL
         + "  - role: worker" + NL
         + "    prompt: worker.md" + NL
         + "  - role: reviewer" + NL
         + "    prompt: reviewer-minimalist.md" + NL
         + "  - role: reviewer" + NL
         + "    prompt: reviewer-maximalist.md" + NL
         + "  - role: judge" + NL
         + "    prompt: judge.md" + NL
         + "    reports: [reviewer-maximalist]" + NL
         + TAIL)

TWICE = ("name: personas" + NL
         + "steps:" + NL
         + "  - role: worker" + NL
         + "    prompt: worker.md" + NL
         + "  - role: reviewer" + NL
         + "    prompt: reviewer-minimalist.md" + NL
         + "  - role: judge" + NL
         + "    prompt: judge.md" + NL
         + "    reports: [reviewer, reviewer-minimalist]" + NL
         + TAIL)

FILES = {"worker.md": "do the work." + NL,
         "reviewer-minimalist.md": MINIMAL,
         "reviewer-maximalist.md": MAXIMAL}

RULED = NL.join(["VERDICT: ok", "", "## Rulings",
                 "- one cuts and one keeps -> cut it -> "
                 "the same logic in 3+ places", "",
                 "## Deliberately not fixing", "- nothing else was raised", ""])

ANSWERS = {"worker.md": "a.py has six functions",
           "reviewer-minimalist.md": "four of them can go",
           "reviewer-maximalist.md": "keep all six and name them better",
           "judge.md": RULED}


def a_flow(tmp_path, body):
    root = tmp_path / "flows"
    d = root / "personas"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (d / "instructions.md").write_text("review what you are given." + NL,
                                       encoding="utf-8")
    for filename, text in FILES.items():
        (d / filename).write_text(text, encoding="utf-8")
    return root


def go(tmp_path, monkeypatch, body, answers=None):
    """run main() over a throwaway flow; hand back what was sent to whom."""
    root = a_flow(tmp_path, body)
    answers = ANSWERS if answers is None else answers
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.setdefault(step, []).append(prompt)
        return answers.get(step, "nothing to report"), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "personas", "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    return sent


def test_both_stances_of_one_role_reach_the_judge(tmp_path, monkeypatch):
    """the pair is the feature. one report out of two is the old behaviour
    wearing the new flow file."""
    sent = go(tmp_path, monkeypatch, PAIR)
    judge = sent["judge.md"][0]
    assert "--- reviewer-minimalist ---" in judge
    assert "--- reviewer-maximalist ---" in judge
    assert "four of them can go" in judge
    assert "keep all six and name them better" in judge


def test_a_role_that_is_one_step_is_still_named_by_the_role(tmp_path,
                                                            monkeypatch):
    """`reports: [worker]` has always arrived as `--- worker ---`, and a step
    whose file is named after its role is the same name either way."""
    sent = go(tmp_path, monkeypatch, ONE)
    judge = sent["judge.md"][0]
    assert "--- worker ---" in judge
    assert "a.py has six functions" in judge
    assert "--- reviewer-minimalist ---" in judge


def test_a_judge_can_name_one_stance_instead_of_the_role(tmp_path, monkeypatch):
    """the role is the pair and the step is one of them, so a flow that wants
    a single stance judged says which one rather than losing the other."""
    sent = go(tmp_path, monkeypatch, NAMED)
    judge = sent["judge.md"][0]
    assert "--- reviewer-maximalist ---" in judge
    assert "--- reviewer-minimalist ---" not in judge
    assert "four of them can go" not in judge


def test_a_report_named_twice_arrives_once(tmp_path, monkeypatch):
    """a role and one of its steps are two names for the same report. the same
    text twice is the judge being told to weigh one of them heavier."""
    sent = go(tmp_path, monkeypatch, TWICE)
    judge = sent["judge.md"][0]
    assert judge.count("--- reviewer-minimalist ---") == 1
    assert judge.count("four of them can go") == 1


def test_the_checker_takes_a_step_name_as_well_as_a_role():
    s = spec.load({"name": "x", "steps": [
        {"role": "reviewer", "prompt": "reviewer-minimalist.md"},
        {"role": "reviewer", "prompt": "reviewer-maximalist.md"},
        {"role": "judge", "reports": ["reviewer-minimalist"]}]})
    assert s.steps[-1]["reports"] == ["reviewer-minimalist"]


def test_a_name_that_is_neither_a_role_nor_a_step_is_refused():
    """the complaint lists both, because both are now answers to it."""
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x", "steps": [
            {"role": "reviewer", "prompt": "reviewer-minimalist.md"},
            {"role": "judge", "reports": ["minimalist"]}]})
    assert "reports minimalist" in str(e.value)
    assert "there is: reviewer, reviewer-minimalist" in str(e.value)


def test_a_redo_goes_back_to_the_nearest_earlier_step_of_that_role():
    """`on_redo` names a role and two steps answer to it. the router already
    decides this once, in the fallback: it walks BACK from the step sending the
    work away. the declared target gets the same walk."""
    fm = spec.load({"name": "x", "steps": [
        {"role": "worker", "prompt": "worker.md"},
        {"role": "reviewer", "prompt": "reviewer-minimalist.md"},
        {"role": "reviewer", "prompt": "reviewer-maximalist.md"},
        {"role": "judge", "prompt": "judge.md", "on_redo": "reviewer"}]})
    assert Router(fm, cap=2).next("judge.md", REDO) == "reviewer-maximalist.md"


def test_on_redo_still_answers_for_a_role_that_has_not_run_yet():
    """nothing behind it to walk back to, so it is the flow's first step of
    that role, which is what it has always been."""
    fm = spec.load({"name": "x", "steps": [
        {"role": "verify", "prompt": "verify.md", "on_redo": "patcher"},
        {"role": "patcher", "prompt": "patcher-second-go.md"}]})
    assert Router(fm, cap=2).next("verify.md", REDO) == "patcher-second-go.md"


def test_one_stance_can_be_run_on_its_own_by_name(tmp_path, monkeypatch,
                                                  capsys):
    """`run.py step` takes a role, and a role that is a pair is ambiguous.
    the second of them is reachable by the name that tells them apart."""
    root = a_flow(tmp_path, PAIR)
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.append(prompt)
        return "nothing to report", False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "step", "personas", "reviewer-maximalist"])
    monkeypatch.chdir(tmp_path)
    assert cli.cmd_step() == 0
    capsys.readouterr()
    assert MAXIMAL.strip() in sent[0]
    assert MINIMAL.strip() not in sent[0]


def test_the_shipped_example_hands_its_judge_both_stances(tmp_path,
                                                          monkeypatch):
    """the example is the flow file a reader copies, so it is run here too."""
    root = str(pathlib.Path("examples").resolve())
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.setdefault(step, []).append(prompt)
        return ANSWERS.get(step, "nothing to report"), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [root])
    monkeypatch.setattr(sys, "argv", ["run.py", "personas", "--force",
                                      "--flows", root])
    monkeypatch.chdir(tmp_path)
    engine.main()
    judge = sent["judge.md"][0]
    assert "--- reviewer-minimalist ---" in judge
    assert "--- reviewer-maximalist ---" in judge
