"""every NEEDS of one answer reaches the lead, numbered, and each gets its
ruling.

a step may ask more than one question in one answer, each on its own `NEEDS:`
line with its RECOMMEND and SIZE under it. each is read on its own, the lead
is handed them numbered and answers `DECIDED <n>:` with a `why:` under each;
every decision is its own entry in decisions.md and the runner's record, and
the step runs again with all of them. a lead that leaves one undecided is
asked once more for the ones it left; still short, the run parks with them
named and nothing recorded. one NEEDS goes as it always did.
"""
import json
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.orchestrate import decisions
from agentweft.runner import lead, ruling, stops, verbs

import test_lead as tl

NL = chr(10)
FIRST = ("the order when `--sep ;;` is given with another bad option value,"
         " such as `--scale abc`. TASK.md:3 puts option values first as a group but does not"
         " say which one is reported first.")
SECOND = ("a separator that is one visible character but more than one code"
          " point. the spec says exactly one character and not which kind.")
TWO = NL.join(["NEEDS: " + FIRST,
               "RECOMMEND: leave it unspecified",
               "SIZE: one TASK.md line and one test",
               "",
               "NEEDS: " + SECOND,
               "RECOMMEND: count code points",
               "SIZE: none, or one TASK.md line to say it",
               "",
               "- calc.py: mul added", ""])
BOTH = NL.join(["DECIDED 1: keep the order the code has now",
                "why: TASK.md:3 does not rank one option value over another",
                "DECIDED 2: count code points",
                "why: the csv reader takes a separator of one code point", ""])
ONLY_ONE = NL.join(["DECIDED 1: keep the order the code has now",
                    "why: TASK.md:3 does not rank one option value over"
                    " another", ""])
THE_OTHER = NL.join(["DECIDED 2: count code points",
                     "why: the csv reader takes a separator of one code point",
                     ""])


def test_every_needs_of_an_answer_is_read_on_its_own():
    found = verbs.every_needs(TWO)
    assert [v.needs for v in found] == [FIRST, SECOND]
    assert [v.recommend for v in found] == ["leave it unspecified",
                                            "count code points"]
    assert verbs.parse(TWO).needs == FIRST


def test_two_needs_ask_one_question_with_each_numbered():
    kind, question = ruling.asked_of(TWO, ".")
    assert kind == ruling.ASKED
    assert question.startswith("NEEDS: 1. " + FIRST)
    assert "NEEDS: 2. " + SECOND in question
    assert lead.numbers(question) == [1, 2]


def test_one_needs_is_asked_as_it_always_was():
    kind, question = ruling.asked_of(tl.NEEDS, ".")
    assert kind == ruling.ASKED
    assert question.startswith("NEEDS: should mul round")
    assert lead.numbers(question) == []


def test_a_needs_beside_a_cited_refusal_asks_as_before(tmp_path):
    (tmp_path / "TASK.md").write_text("a" + NL + "b" + NL, encoding="utf-8")
    both = TWO + 'REFUSED: TASK.md:2 "b"' + NL
    kind, question = ruling.asked_of(both, str(tmp_path))
    assert kind == ruling.ASKED
    assert lead.numbers(question) == [1, 2]
    refused = 'REFUSED: TASK.md:2 "b"' + NL
    assert ruling.asked_of(refused, str(tmp_path))[0] == ruling.DECLINED


def test_the_lead_decides_each_by_its_number():
    question = ruling.asked_of(TWO, ".")[1]
    got = lead.each(BOTH, [1, 2])
    assert got[0] == {1: ("keep the order the code has now",
                          "TASK.md:3 does not rank one option value over"
                          " another"),
                      2: ("count code points",
                          "the csv reader takes a separator of one code"
                          " point")}
    assert lead.numbers(question) == [1, 2]
    assert "DECIDED <n>:" in lead.brief("worker.md", question)


def test_a_two_question_answer_gets_two_rulings_and_the_step_both(
        tmp_path, monkeypatch):
    asked, sent, code, folder, project = tl.build(
        tmp_path, monkeypatch, [BOTH], worker_says=(TWO, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "worker.md", "reviewer.md", "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    to_lead = sent[3]
    assert "NEEDS: 1. " + FIRST in to_lead
    assert "NEEDS: 2. " + SECOND in to_lead
    again = sent[4]
    assert "DECIDED 1: keep the order the code has now" in again
    assert "DECIDED 2: count code points" in again
    said = decisions.read(project)
    assert [d.decided for d in said] == [
        "planner.md decided for worker.md: keep the order the code has now",
        "planner.md decided for worker.md: count code points"]
    assert "NEEDS: 2. " + SECOND in said[1].why
    written = json.loads((folder / "rulings.json").read_text(
        encoding="utf-8"))["written"]
    assert [(w["by"], w.get("question")) for w in written] == [
        ("lead", 1), ("lead", 2)]
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "planner.md decided for worker.md: keep the order" in handoff
    assert "planner.md decided for worker.md: count code points" in handoff


def test_a_lead_that_leaves_one_undecided_is_asked_once_more(tmp_path,
                                                             monkeypatch):
    asked, sent, code, _, project = tl.build(
        tmp_path, monkeypatch, [ONLY_ONE, THE_OTHER],
        worker_says=(TWO, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "planner.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    assert "not decided: 2" in sent[4]
    assert len(decisions.read(project)) == 2


def test_a_lead_still_short_parks_with_the_undecided_named(tmp_path,
                                                           monkeypatch):
    asked, _, code, folder, project = tl.build(
        tmp_path, monkeypatch, [ONLY_ONE, ONLY_ONE],
        worker_says=(TWO, tl.WORKER))
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "planner.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert "NEEDS: 2. " + SECOND in question
    assert "not decided: 2" in question
    assert decisions.read(project) == []
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "- worker asks 2: " + SECOND in handoff
    head = handoff.split("## the one decision")[1].split("\n## ")[0]
    assert "2. " + SECOND + " (worker; recommendation: count code points" \
        in head
