"""a step's NEEDS resting on the very spec line an ASSUMED item of the lead's
own rests on is told that item as its answer, by the runner, with no call to
the lead.

the match is typed: every spec-file cite the question carries is a single
line the lead's item carries in its choice or its `why:`, a line the file
had when the run started. a range, a code-file line alone, another step's
item and a flow with no lead answer nothing. a question on a spec line the
item does not carry goes to the lead as before, and so does a question the
item already answered for this step once, whatever its words, and one that
carries the item's `if wrong:` words.
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


def test_the_same_range_written_the_same_way_goes_to_the_lead(tmp_path,
                                                               monkeypatch):
    """a cite is one line: an item resting on a whole section would answer
    any question on that section, whatever it asks."""
    logging = ("NEEDS: should mul log its inputs to stderr?" + NL + "CITES:"
               + NL + "- TASK.md:1-3 - the spec" + NL)
    asked, _, _, folder, _ = build_with(
        tmp_path, monkeypatch, plan_citing("TASK.md:1-3 say a times b"),
        [tl.DECIDED], (logging, tl.WORKER))
    assert asked[3] == "planner.md", asked
    assert "assumed" not in [w["by"] for w in written_or_none(folder)]


def written_or_none(folder):
    if not (folder / "rulings.json").exists():
        return []
    return written(folder)


def test_a_question_resting_on_a_second_spec_line_goes_to_the_lead(
        tmp_path, monkeypatch):
    two = ("NEEDS: should mul round, and should the title line stay?" + NL
           + "CITES:" + NL + "- TASK.md:3 - mul(a, b) returns a times b" + NL
           + "- TASK.md:1 - # calc" + NL)
    asked, _, _, _, _ = build_with(
        tmp_path, monkeypatch, PLAN, [tl.DECIDED], (two, tl.WORKER))
    assert asked[3] == "planner.md", asked


def test_a_needs_citing_the_spec_line_and_a_code_line_is_answered(
        tmp_path, monkeypatch):
    """a code line in a question is where the step would change, not a line
    that decides: only its spec lines have to be the item's."""
    beside = (tl.NEEDS.split("OPTIONS:")[0]
              + "- calc.py:1 - def add(a, b):" + NL)
    asked, _, code, folder, _ = build(
        tmp_path, monkeypatch, [], (beside, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "worker.md",
                     "reviewer.md", "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    assert [w["by"] for w in written(folder)] == ["assumed"]


def test_an_item_and_a_needs_on_a_code_line_answer_nothing(tmp_path,
                                                           monkeypatch):
    on_code = ("NEEDS: should mul round a float product to an int?" + NL
               + "CITES:" + NL + "- calc.py:1 - def add(a, b):" + NL)
    asked, _, _, folder, _ = build_with(
        tmp_path, monkeypatch,
        plan_citing("calc.py:1 holds add, which rounds nothing"),
        [tl.DECIDED], (on_code, tl.WORKER))
    assert asked[3] == "planner.md", asked
    assert "assumed" not in [w["by"] for w in written_or_none(folder)]


HANDED = NL.join(["", "HANDOFF", "DID:", "- wrote the mul test", "ASSUMED:",
                  "- " + CHOICE,
                  "  why: TASK.md:3 says a times b and nothing about rounding",
                  "  if wrong: a float test would expect an int",
                  "END HANDOFF", ""])


def test_a_non_lead_steps_assumed_item_never_answers(tmp_path, monkeypatch):
    """the tester's choice is a choice nobody with the lead's role took: the
    question reaches the lead, who may adopt it."""
    answers = {"planner.md": [tl.PLAN, tl.DECIDED],
               "tester.md": [tl.TESTER + HANDED],
               "worker.md": [tl.NEEDS, tl.WORKER],
               "reviewer.md": [tl.OK], "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", tl.TEST)],
              "worker.md": [("", ""), ("calc.py", tl.AFTER)]}
    asked, _, _, folder, _ = tl.run_it(tmp_path, monkeypatch,
                                       "build-feature", answers, writes)
    assert asked[3] == "planner.md", asked
    assert "assumed" not in [w["by"] for w in written_or_none(folder)]


def test_a_flow_with_no_lead_sends_the_question_to_the_person(tmp_path,
                                                              monkeypatch):
    answers = {"worker.md": [tl.TESTER + HANDED],
               "patcher.md": [tl.NEEDS, tl.WORKER],
               "verify.md": [tl.OK]}
    writes = {"worker.md": [("tests/test_mul.py", tl.TEST)],
              "patcher.md": [("", ""), ("calc.py", tl.AFTER)]}
    asked, _, code, folder, _ = tl.run_it(tmp_path, monkeypatch,
                                          "fix-with-test", answers, writes,
                                          task="mul is missing from calc")
    assert asked == ["worker.md", "patcher.md"]
    assert code == stops.EXIT_STOP
    assert "assumed" not in [w["by"] for w in written_or_none(folder)]
    assert (folder / "question.md").read_text(
        encoding="utf-8").startswith("NEEDS: should mul round")


def test_a_line_past_the_last_newline_is_not_a_line(tmp_path):
    from agentweft.runner import ruling

    (tmp_path / "ends.md").write_text("a" + NL + "b" + NL, encoding="utf-8")
    (tmp_path / "open.md").write_text("a" + NL + "b", encoding="utf-8")
    assert ruling.lines_of(str(tmp_path), "ends.md", 3, 3)[0] is None
    assert ruling.lines_of(str(tmp_path), "ends.md", 2, 2)[0] == ["a", "b"]
    assert ruling.lines_of(str(tmp_path), "open.md", 2, 2)[0] == ["a", "b"]


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
