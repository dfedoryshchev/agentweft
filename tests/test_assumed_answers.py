"""a step's NEEDS that an ASSUMED item of this run already answers on the same
cited line is told that item as its answer, by the runner, with no call to
the lead.

the match is typed: a cite the question carries is the very cite an
ASSUMED item of an earlier step of the run carries in its choice or its
`why:`, the same line or the same range, a line the file had when the run
started. a question on a cite no ASSUMED item carries goes to the lead as
before, and so does a question the item already answered for this step once,
whatever its words, and one that carries the item's `if wrong:` words.
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


REWORDED = ("NEEDS: must mul round a float product, since the test wants an"
            " int?" + NL + "CITES:" + NL
            + "- TASK.md:3 - mul(a, b) returns a times b" + NL)


def plan_citing(why, wrong="a float test would expect an int"):
    return tl.PLAN + NL.join([
        "", "HANDOFF", "DID:", "- planned mul", "ASSUMED:", "- " + CHOICE,
        "  why: " + why, "  if wrong: " + wrong, "END HANDOFF", ""])


def build_with(tmp_path, monkeypatch, plan, lead_says, worker_says):
    answers = {"planner.md": [plan] + list(lead_says),
               "tester.md": [tl.TESTER], "worker.md": list(worker_says),
               "reviewer.md": [tl.OK], "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", tl.TEST)],
              "worker.md": [("", ""), ("", ""), ("calc.py", tl.AFTER)]}
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, writes)


def test_a_reworded_needs_on_a_line_the_item_already_answered_goes_to_the_lead(
        tmp_path, monkeypatch):
    asked, _, _, _, project = build_with(
        tmp_path, monkeypatch, PLAN, [tl.DECIDED],
        (tl.NEEDS, REWORDED, tl.WORKER))
    assert asked[:5] == ["planner.md", "tester.md", "worker.md", "worker.md",
                         "planner.md"]
    assert len(decisions.read(project)) == 2


def test_an_item_on_a_range_does_not_answer_one_line_inside_it(
        tmp_path, monkeypatch):
    asked, _, _, _, project = build_with(
        tmp_path, monkeypatch, plan_citing("TASK.md:1-3 say a times b"),
        [tl.DECIDED], (ELSEWHERE, tl.WORKER))
    assert asked[3] == "planner.md"
    [said] = decisions.read(project)
    assert said.decided.startswith("planner.md decided for worker.md")


def test_the_same_range_written_the_same_way_is_answered(tmp_path,
                                                          monkeypatch):
    ranged = ("NEEDS: should mul round a float product to an int?" + NL
              + "CITES:" + NL + "- TASK.md:1-3 - the spec" + NL)
    asked, _, code, _, _ = build_with(
        tmp_path, monkeypatch, plan_citing("TASK.md:1-3 say a times b"), [],
        (ranged, tl.WORKER))
    assert asked[:4] == ["planner.md", "tester.md", "worker.md", "worker.md"]
    assert "planner.md" not in asked[1:]


def test_a_line_the_file_does_not_have_answers_nothing(tmp_path,
                                                       monkeypatch):
    ghost = ("NEEDS: should mul log its inputs?" + NL + "CITES:" + NL
             + "- TASK.md:99 - mul logs" + NL)
    asked, _, _, _, _ = build_with(
        tmp_path, monkeypatch, plan_citing("TASK.md:99 says it"),
        [tl.DECIDED], (ghost, tl.WORKER))
    assert asked[3] == "planner.md"


def test_a_needs_that_carries_the_items_if_wrong_goes_to_the_lead(
        tmp_path, monkeypatch):
    wrong = ("NEEDS: a float test would expect an int here, so should mul"
             " round?" + NL + "CITES:" + NL
             + "- TASK.md:3 - mul(a, b) returns a times b" + NL)
    asked, _, _, _, _ = build_with(tmp_path, monkeypatch, PLAN, [tl.DECIDED],
                                   (wrong, tl.WORKER))
    assert asked[3] == "planner.md"
