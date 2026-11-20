"""`you decide` to a conflict the start tests raised.

a product change that turns red a test the run started with green stops the
run as a conflict whose question names each such test. handed back, the
lead picks `the request holds` or `the spec holds`. `the request holds` is
put on record as an `override:` that names each red start test of the
question the runner wrote, so the replay lets exactly those change: a start
test the question did not name still stops the run.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops

from test_red_order import a_flow
from test_test_edits import (COUNT, ID, PLANNER, RIGHT, TESTER, TESTER_SAID,
                             WORKER, WORKER_SAID, folders, module, read,
                             running)
from test_you_decide_picks import FILE, LEAD, OTHER, OTHER_ID, planned, \
    spec_place

NL = chr(10)
UNSORTED = ("def report(names):" + NL + "    return list(names)" + NL + NL
            + NL + "def count(names):" + NL + "    return len(names)" + NL)
EMPTIED = ("def report(names):" + NL + "    return []" + NL + NL + NL
           + "def count(names):" + NL + "    return len(names)" + NL)


def start_tests_stopped(tmp_path, monkeypatch):
    place = spec_place(tmp_path / "repo")
    a_flow(tmp_path, "build", PLANNER + TESTER + WORKER + LEAD)
    planned(tmp_path)
    does = {"planner.md": ({}, WORKER_SAID),
            "tester.md": ({FILE: module(RIGHT, OTHER, COUNT)}, TESTER_SAID),
            "worker.md": ({"report.py": UNSORTED}, WORKER_SAID)}
    code, called = running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.CONFLICT)
    assert called == ["planner.md", "tester.md", "worker.md"]
    first = folders()[-1]
    assert ID in read(first / "question.md")
    assert OTHER_ID not in read(first / "question.md")
    return place, first, does


REQUEST_HOLDS = ("DECIDED: the request holds" + NL + "why: the request says"
                 " the order may change" + NL)


def test_the_request_holds_names_the_red_start_tests_and_lets_them_change(
        tmp_path, monkeypatch):
    place, first, does = start_tests_stopped(tmp_path, monkeypatch)
    does["planner.md"] = ({}, REQUEST_HOLDS)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert code == 0, read(folders()[-1] / "why.md")
    assert called == ["planner.md", "worker.md"]
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for worker.md: ")]
    assert given.decided.startswith("ruling for worker.md: override: the"
                                    " request says the order may change")
    assert ruling.names_test(ruling.own_words(given), ID)
    assert "each covered by a ruling: " + ID in read(
        folders()[-1] / "gates.md")


def test_a_start_test_the_question_did_not_name_still_stops_the_run(
        tmp_path, monkeypatch):
    place, first, does = start_tests_stopped(tmp_path, monkeypatch)
    does["planner.md"] = ({}, REQUEST_HOLDS)
    does["worker.md"] = ({"report.py": EMPTIED}, WORKER_SAID)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert code == stops.exit_code(stops.CONFLICT)
    again = read(folders()[-1] / "question.md")
    assert OTHER_ID in again


def test_the_start_tests_a_question_names_are_read_from_the_runner_s_form():
    q = ruling.question_of_start_tests("worker.md", [
        (ID, "assert ['b', 'a'] == ['a', 'b']"),
        ("tests\\test_x.py::test_" + chr(0xE9), "boom")])
    assert ruling.start_tests_asked(q) == [
        ID, "tests\\test_x.py::test_" + chr(0xE9)]
    assert ruling.start_tests_asked("NEEDS: is the order wrong?" + NL
                                    + "CITES:" + NL + "- " + ID + " - x") == []
    assert ruling.start_tests_asked("") == []
    assert ruling.start_tests_asked(None) == []


def test_an_unread_pick_re_parks_with_the_start_tests_wording(tmp_path,
                                                               monkeypatch):
    place, first, does = start_tests_stopped(tmp_path, monkeypatch)
    does["planner.md"] = ({}, "DECIDED: maybe" + NL + "why: x" + NL)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "you decide")
    assert code == stops.exit_code(stops.CONFLICT)
    assert "are not all green as they were" in read(
        folders()[-1] / "handoff.md")
