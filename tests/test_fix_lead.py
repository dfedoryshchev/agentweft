"""fix-with-test names a lead that is no step of its route: the architect
role, called only when a step asks.

a question a step cannot go on without goes to it before the operator, the
way build-feature's planner takes one. it raises no question of its own, it
changes no file, and what only the operator can settle still goes up without
a call: a CONFLICT line, a question that names a test the run started with,
a typed SPLIT beside it.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import stops
from agentweft.runner.config import config

from test_lead import FLOWS, NL, run_it

LEAD = "architect.md"
BUG = "add(1, 2) returns -1"
NO_RED_ASKS = ("add(1, 2) is 3 on this code, so no test was written." + NL
               + NL + "HANDOFF" + NL + "DID:" + NL
               + "- wrote no test: add(1, 2) gives 3" + NL
               + "QUESTION: calc.py:2 already adds, so add(1, 2) is 3. was"
               " the report about another input?" + NL
               + "RECOMMEND: close the report as not seen on this code" + NL
               + "END HANDOFF" + NL)
NOTHING_TO_TEST = ("the code already does it, so no test was written." + NL
                   + NL + "FAILS: none" + NL + "TEST: none written" + NL + NL
                   + "HANDOFF" + NL + "DID:" + NL
                   + "- wrote no test: the code already does the ask" + NL
                   + "QUESTION: none" + NL + "END HANDOFF" + NL)
CLOSE = ("DECIDED: close the report as not seen on this code" + NL
         + "why: calc.py:2 returns a + b, so add(1, 2) is 3 as the report"
         " wants" + NL)
ESCALATE = "ESCALATE: the report may name another input only its writer knows" + NL
OLD_TEST = ("from calc import add" + NL + NL + NL + "def test_add_zero():" + NL
            + "    assert add(0, 0) == 0" + NL)
ON_A_START_TEST = ("no test was written." + NL + NL + "HANDOFF" + NL + "DID:"
                   + NL + "- wrote no test" + NL
                   + "QUESTION: calc.py:2 already adds, and"
                   " tests/test_old.py::test_add_zero covers add; should it"
                   " change to take the report?" + NL
                   + "RECOMMEND: change tests/test_old.py::test_add_zero" + NL
                   + "END HANDOFF" + NL)
CONFLICT = ('CONFLICT: TASK.md:3 "mul(a, b) returns a times b"' + NL
            + "request: mul should add" + NL)


def fix(tmp_path, monkeypatch, answers, writes=None, task=BUG, start=()):
    return run_it(tmp_path, monkeypatch, "fix-with-test", answers,
                  writes or {}, task=task, start=start)


def steps_of(folder):
    return [(json.loads(x)["step"], json.loads(x)["outcome"]) for x in (
        folder / "steps.jsonl").read_text(encoding="utf-8").splitlines()]


def test_the_shipped_fix_flow_names_the_architect_as_its_lead():
    assert config("fix-with-test").get("lead") == "architect"
    assert spec.lead_of(config("fix-with-test").raw) is None
    assert spec.off_lead(config("fix-with-test").raw) == LEAD


def test_the_lead_decides_a_no_red_question_and_the_run_ends_in_one_leg(
        tmp_path, monkeypatch):
    asked, sent, code, folder, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [NO_RED_ASKS, NOTHING_TO_TEST], LEAD: [CLOSE]})
    assert asked[:3] == ["worker.md", LEAD, "worker.md"]
    assert code == 0
    head = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "done: no change at worker.md" in head.split(NL)[0]
    assert not (folder / "question.md").exists()
    assert (LEAD, "decided") in steps_of(folder)
    told = sent[2]
    assert "close the report as not seen on this code" in told


def test_the_lead_is_handed_the_request_and_where_the_spec_is(tmp_path,
                                                             monkeypatch):
    asked, sent, _, _, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [NO_RED_ASKS, NOTHING_TO_TEST], LEAD: [CLOSE]})
    prompt = sent[asked.index(LEAD)]
    assert BUG in prompt
    assert "TASK.md" in prompt
    assert "QUESTION FOR THE LEAD. worker.md" in prompt
    assert prompt.rstrip().endswith("not seen on this code")
    assert "you decide nothing" not in prompt


def test_a_question_the_lead_escalates_waits_for_the_operator(tmp_path,
                                                              monkeypatch):
    asked, _, code, folder, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [NO_RED_ASKS], LEAD: [ESCALATE]})
    assert asked[:2] == ["worker.md", LEAD]
    assert "worker.md" not in asked[2:]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert question.startswith("NEEDS: worker.md could not make a test fail")
    assert "escalated it: the report may name another input" in question
    assert (LEAD, "escalated") in steps_of(folder)


def test_a_lead_answer_in_no_taught_form_waits_for_the_operator(tmp_path,
                                                                monkeypatch):
    asked, _, code, folder, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [NO_RED_ASKS], LEAD: ["close it, i think" + NL]})
    assert code == stops.EXIT_STOP
    assert "worker.md" not in asked[2:]
    assert "answered with neither DECIDED: nor ESCALATE:" in (
        folder / "question.md").read_text(encoding="utf-8")


def test_an_empty_lead_answer_waits_for_the_operator(tmp_path, monkeypatch):
    asked, _, code, folder, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [NO_RED_ASKS], LEAD: [""]})
    assert code == stops.EXIT_STOP
    assert "worker.md" not in asked[2:]
    assert (folder / "question.md").exists()


def test_a_lead_that_changes_a_file_is_not_held(tmp_path, monkeypatch):
    asked, _, code, folder, project = fix(
        tmp_path, monkeypatch, {"worker.md": [NO_RED_ASKS], LEAD: [CLOSE]},
        writes={LEAD: [("calc.py", "def add(a, b):" + NL + "    return 3" + NL)]})
    assert code == stops.EXIT_STOP
    assert "worker.md" not in asked[2:]
    assert "changed a file" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_a_question_naming_a_start_test_never_costs_a_lead_call(tmp_path,
                                                                monkeypatch):
    asked, _, code, folder, _ = fix(
        tmp_path, monkeypatch, {"worker.md": [ON_A_START_TEST]},
        start=[("tests/test_old.py", OLD_TEST)])
    assert LEAD not in asked
    assert code == stops.EXIT_STOP
    assert "tests/test_old.py::test_add_zero" in (
        folder / "question.md").read_text(encoding="utf-8")


def test_a_conflict_never_reaches_the_lead(tmp_path, monkeypatch):
    asked, _, code, folder, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [CONFLICT]}, task="mul should add")
    assert LEAD not in asked
    assert asked[0] == "worker.md"
    assert "spec conflict at worker.md" in (folder / "handoff.md").read_text(
        encoding="utf-8").split(NL)[0]


def test_a_copy_of_the_flow_with_no_lead_parks_at_once(tmp_path,
                                                       monkeypatch):
    import shutil

    from agentweft.runner import prompts

    flows = tmp_path / "flows-none"
    shutil.copytree(FLOWS / "fix-with-test", flows / "fix-with-test")
    yml = flows / "fix-with-test" / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8").replace(
        "lead: architect", "lead: none"), encoding="utf-8")
    monkeypatch.setitem(run_it.__globals__, "FLOWS", flows)
    asked, _, code, _, _ = fix(tmp_path, monkeypatch, {
        "worker.md": [NO_RED_ASKS], LEAD: [CLOSE]})
    assert prompts.FLOW_ROOT == [str(flows)]
    assert asked == ["worker.md"]
    assert code == stops.EXIT_STOP


def flow(**more):
    raw = {"name": "x", "steps": [{"role": "worker", "prompt": "worker.md"},
                                  {"role": "patcher", "prompt": "patcher.md"}]}
    raw.update(more)
    return raw


def test_a_lead_may_be_a_library_role_that_is_no_step():
    assert spec.check(flow(lead="architect")) == []
    assert spec.check(flow(lead="ba")) == []
    assert spec.off_lead(flow(lead="architect")) == "architect.md"
    assert spec.off_lead(flow(lead="worker")) is None
    assert spec.off_lead(flow(lead="none")) is None
    assert spec.off_lead(flow()) is None
    assert spec.lead_of(flow(lead="architect")) is None


def test_a_lead_that_is_neither_a_step_nor_a_library_role_is_refused():
    [said] = spec.check(flow(lead="judge"))
    assert said.startswith("lead names no step of the flow: judge")
    assert "architect" in said
    assert spec.off_lead(flow(lead="judge")) is None
    [said] = spec.check(flow(lead="architect.md"))
    assert said.startswith("lead names no step of the flow: architect.md")


def test_a_step_named_like_the_role_is_the_lead_as_a_step():
    raw = {"name": "x", "lead": "architect",
           "steps": [{"role": "architect", "prompt": "architect.md"},
                     {"role": "worker", "prompt": "worker.md"}]}
    assert spec.check(raw) == []
    assert spec.lead_of(raw) == "architect.md"
    assert spec.off_lead(raw) is None
