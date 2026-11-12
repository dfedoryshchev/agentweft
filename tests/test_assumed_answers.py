"""a step's NEEDS that an ASSUMED item of this run already answers on the same
cited line is told that item as its answer, by the runner, with no call to
the lead.

the match is typed: a `<file>:<line>` the question cites is a line an
ASSUMED item of an earlier step of the run cites in its choice or its
`why:`. the item's `if wrong:` words never decide it. a question on a line
no ASSUMED item cites goes to the lead as before, and so does a question
already answered once this way and asked again.
"""
import json
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.orchestrate import decisions
from agentweft.runner import stops

import test_lead as tl

NL = chr(10)
CHOICE = "mul keeps a float product as it is"
PLAN = tl.PLAN + NL.join([
    "", "HANDOFF", "DID:", "- planned mul", "ASSUMED:", "- " + CHOICE,
    "  why: TASK.md:3 says a times b and nothing about rounding",
    "  if wrong: a float test would expect an int", "END HANDOFF", ""])
ELSEWHERE = ("NEEDS: should the module keep its title line?" + NL
             + "CITES:" + NL + "- TASK.md:1 - # calc" + NL)
UNCITED = "NEEDS: should mul accept strings?" + NL
TWO = tl.NEEDS + NL + UNCITED


def build(tmp_path, monkeypatch, lead_says, worker_says):
    answers = {"planner.md": [PLAN] + list(lead_says),
               "tester.md": [tl.TESTER], "worker.md": list(worker_says),
               "reviewer.md": [tl.OK], "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", tl.TEST)],
              "worker.md": [("", ""), ("calc.py", tl.AFTER)]}
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, writes)


def written(folder):
    return json.loads((folder / "rulings.json").read_text(
        encoding="utf-8"))["written"]


def test_a_needs_on_a_line_an_assumed_item_cites_is_told_the_item(
        tmp_path, monkeypatch):
    asked, sent, code, folder, project = build(
        tmp_path, monkeypatch, [], (tl.NEEDS, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "worker.md",
                     "reviewer.md", "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    again = sent[3]
    assert CHOICE in again
    assert "should mul round a float product" in again
    [said] = decisions.read(project)
    assert "planner.md's ASSUMED 1" in said.decided
    assert CHOICE in said.decided
    assert [(w["by"], w.get("step"), w.get("item")) for w in written(folder)] \
        == [("assumed", "planner.md", 1)]
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "answered by planner.md's ASSUMED 1" in handoff


def test_a_needs_on_a_line_no_assumed_item_cites_still_asks_the_lead(
        tmp_path, monkeypatch):
    asked, _, code, _, project = build(
        tmp_path, monkeypatch, [tl.DECIDED], (ELSEWHERE, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "worker.md", "reviewer.md", "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    [said] = decisions.read(project)
    assert said.decided.startswith("planner.md decided for worker.md")


def test_of_two_needs_the_one_an_item_answers_is_told_and_the_other_asked(
        tmp_path, monkeypatch):
    asked, sent, code, _, project = build(
        tmp_path, monkeypatch, ["DECIDED: no, numbers only" + NL
                                + "why: TASK.md:3 names a and b" + NL],
        (TWO, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "worker.md", "reviewer.md", "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    to_lead = sent[3]
    assert "NEEDS: should mul accept strings?" in to_lead
    assert "should mul round" not in to_lead.split("what worker.md asked")[1]
    again = sent[4]
    assert CHOICE in again and "numbers only" in again
    assert len(decisions.read(project)) == 2


def test_the_same_needs_asked_again_after_the_item_goes_to_the_lead(
        tmp_path, monkeypatch):
    asked, _, code, _, _ = build(
        tmp_path, monkeypatch, [tl.DECIDED], (tl.NEEDS, tl.NEEDS, tl.WORKER))
    assert asked[:5] == ["planner.md", "tester.md", "worker.md", "worker.md",
                         "planner.md"]
