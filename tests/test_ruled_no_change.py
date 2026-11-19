"""a run whose ruling turns the change down, or whose code already does the
ask, ends with no change, not a failed gate.

a step held to a red test that shows none failing, names no test, changed
nothing, and runs under a ruling this run was given with --answer that is no
`override:`, or under the lead's decision of the question it parked on, ends
the run `done: no change` with that ruling cited: the request was answered
and there is nothing to build. no send-back is spent on it. without
such a ruling, with an `override:`, with a test named or a file changed, the
red-test gate judges the answer as it always has.

the flows are the shipped ones, on fake answers and a real git place.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops
from test_spec_conflict import (CONFLICT, PLAN, REQUEST, a_place, end,
                                feature_place, folders, go, plain)

NL = chr(10)
SPEC = "# calc" + NL + NL + "add(a, b) returns the sum of a and b." + NL
WORKS = "def add(a, b):" + NL + "    return a + b" + NL
PASSES = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
          + "    assert add(1, 2) == 3" + NL)
BUG = "Bug report: add(1, 2) must give -1, as was agreed in a chat."
CLASH = ('CONFLICT: TASK.md:3 "add(a, b) returns the sum of a and b."' + NL
         + "request: add(1, 2) must give -1" + NL)
NOTHING = ("The code already does what the spec says, so no test was written."
           + NL + NL + "FAILS: none, add(1, 2) gives 3 on this code" + NL
           + "TEST: none written" + NL + NL)
DECLINE = ("request: there is no record of that chat; keep the documented"
           " rule and say so")


def handoff(top, question="QUESTION: none" + NL):
    return (top + "HANDOFF" + NL + "DID:" + NL
            + "- no test written: add(1, 2) gives 3 on the code as it is" + NL
            + question + "END HANDOFF" + NL)


ASKS = handoff(NOTHING, "QUESTION: calc.py:2 already returns a + b. was the"
               " report about another input?" + NL
               + "RECOMMEND: close the report as not seen on this code" + NL)


def bug_place(tmp_path):
    return a_place(tmp_path / "project", {
        "TASK.md": SPEC, "calc.py": WORKS, "conftest.py": "",
        "tests/test_calc.py": PASSES})


def outcome(folder):
    return json.loads((folder / "manifest.json").read_text(
        encoding="utf-8"))["outcome"]


def gates(folder):
    path = folder / "gates.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def first_leg(tmp_path, monkeypatch, said):
    go(tmp_path, monkeypatch, "fix-with-test", plain({"worker.md": [said]}),
       lambda s, n: None, "--task", BUG)
    return folders(tmp_path)[-1]


def carried(tmp_path, monkeypatch, first, answer, said, edits=None):
    asked, _, code = go(tmp_path, monkeypatch, "fix-with-test",
                        plain({"worker.md": said}),
                        edits or (lambda s, n: None),
                        "--resume", first.name, "--answer", answer)
    return asked, code, folders(tmp_path)[-1]


def test_a_request_ruling_and_no_test_ends_with_no_change(tmp_path,
                                                          monkeypatch):
    before = bug_place(tmp_path)
    place = tmp_path / "project"
    first = first_leg(tmp_path, monkeypatch, CLASH)
    assert end(tmp_path).cause == stops.CONFLICT
    asked, code, folder = carried(tmp_path, monkeypatch, first, DECLINE,
                                  [handoff(NOTHING)])
    assert asked.count("worker.md") == 1, \
        "a send-back was spent on a run the ruling had turned down"
    assert "patcher.md" not in asked
    assert outcome(folder) == stops.outcome(stops.NO_CHANGE), gates(folder)
    assert code == stops.EXIT_OK
    line = end(tmp_path)
    assert line.cause == stops.NO_CHANGE
    [ruled] = decisions.read(place)
    assert ruled.at.strftime(stops.STAMP) in line.why
    assert "changed nothing" in line.why
    told = (folder / "handoff.md").read_text(encoding="utf-8")
    assert ruled.decided in told
    assert (place / "calc.py").read_bytes() == before["calc.py"]


def test_an_answer_the_step_makes_its_call_on_ends_with_no_change(
        tmp_path, monkeypatch):
    bug_place(tmp_path)
    place = tmp_path / "project"
    first = first_leg(tmp_path, monkeypatch, ASKS)
    assert outcome(first) == "needs you: ruling"
    again = handoff(NOTHING, "QUESTION: none (already asked at decisions.md:3"
                    " and ruled on)" + NL + "RECOMMEND: none" + NL
                    + "SIZE: none" + NL)
    asked, code, folder = carried(
        tmp_path, monkeypatch, first, "No one is available to answer. Make"
        " the call yourself and say which calls you made.", [again])
    assert asked.count("worker.md") == 1
    assert outcome(folder) == stops.outcome(stops.NO_CHANGE), \
        (folder / "why.md").read_text(encoding="utf-8")
    [ruled] = decisions.read(place)
    assert ruled.at.strftime(stops.STAMP) in end(tmp_path).why


def test_an_override_never_ends_a_run_with_no_change(tmp_path, monkeypatch):
    bug_place(tmp_path)
    first = first_leg(tmp_path, monkeypatch, ASKS)
    asked, code, folder = carried(
        tmp_path, monkeypatch, first, "override: the report holds; make the"
        " test fail on it", [handoff(NOTHING)])
    assert asked.count("worker.md") == 2
    assert outcome(folder) == stops.outcome(stops.GATE)
    assert "FAIL red-test" in gates(folder)


def test_a_named_test_under_a_request_ruling_is_still_judged(tmp_path,
                                                             monkeypatch):
    bug_place(tmp_path)
    place = tmp_path / "project"
    first = first_leg(tmp_path, monkeypatch, CLASH)
    named = ("FAILS: assert 3 == 3" + NL + "TEST: tests/test_more.py" + NL
             + NL)

    def edits(step, n):
        if step == "worker.md":
            (place / "tests" / "test_more.py").write_text(
                PASSES.replace("test_add", "test_add_again"),
                encoding="utf-8")
    asked, code, folder = carried(tmp_path, monkeypatch, first, DECLINE,
                                  [handoff(named)], edits)
    assert outcome(folder) == stops.outcome(stops.GATE)
    assert "the test passed before the patch" in gates(folder)


def test_a_step_that_changed_a_file_is_still_judged(tmp_path, monkeypatch):
    bug_place(tmp_path)
    place = tmp_path / "project"
    first = first_leg(tmp_path, monkeypatch, CLASH)

    def edits(step, n):
        if step == "worker.md":
            (place / "calc.py").write_text(WORKS + NL + "# seen" + NL,
                                           encoding="utf-8")
    asked, code, folder = carried(tmp_path, monkeypatch, first, DECLINE,
                                  [handoff(NOTHING)], edits)
    assert asked.count("worker.md") == 2
    assert outcome(folder) != stops.outcome(stops.NO_CHANGE)


def test_an_answer_with_no_test_line_is_still_judged(tmp_path, monkeypatch):
    bug_place(tmp_path)
    first = first_leg(tmp_path, monkeypatch, CLASH)
    asked, code, folder = carried(
        tmp_path, monkeypatch, first, DECLINE,
        [handoff("add(1, 2) gives 3 on this code." + NL + NL)])
    assert asked.count("worker.md") == 2
    assert outcome(folder) == stops.outcome(stops.GATE)


def test_a_ruling_found_at_the_start_is_not_this_runs(tmp_path, monkeypatch):
    bug_place(tmp_path)
    place = tmp_path / "project"
    first = first_leg(tmp_path, monkeypatch, CLASH)
    carried(tmp_path, monkeypatch, first, DECLINE, [handoff(NOTHING)])
    asked, _, code = go(tmp_path, monkeypatch, "fix-with-test",
                        plain({"worker.md": [handoff(NOTHING)]}),
                        lambda s, n: None, "--task", BUG)
    assert asked.count("worker.md") == 2
    assert outcome(folders(tmp_path)[-1]) == stops.outcome(stops.GATE)
    assert len(decisions.read(place)) == 1


def test_a_build_feature_tester_with_nothing_to_build_ends_with_no_change(
        tmp_path, monkeypatch):
    feature_place(tmp_path)
    go(tmp_path, monkeypatch, "build-feature",
       plain({"planner.md": [CONFLICT]}), lambda s, n: None, "--task",
       REQUEST)
    [first] = folders(tmp_path)
    none = ("FAILS: nothing - every planned behaviour already holds" + NL
            + "TEST: none written" + NL + NL + "HANDOFF" + NL + "DID:" + NL
            + "- no test written" + NL + "QUESTION: none" + NL
            + "END HANDOFF" + NL)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN], "tester.md": [none]}),
                        lambda s, n: None, "--resume", first.name,
                        "--answer", "request: keep the alphabetical order")
    assert asked.count("tester.md") == 1
    assert "worker.md" not in asked
    assert outcome(folders(tmp_path)[-1]) == stops.outcome(stops.NO_CHANGE)
    assert code == stops.EXIT_OK


ALREADY = "the report lists students alphabetically, as it already does"
NONE_SAID = ("FAILS: none - the report already sorts" + NL
             + "TEST: none written" + NL + NL)
ASKED_LEAD = handoff(NONE_SAID, "QUESTION: report.py:2 already sorts the"
                     " names. should the run close as already done?" + NL
                     + "RECOMMEND: close the run as already done" + NL)
CLOSE = ("DECIDED: close the run as already done" + NL
         + "why: report.py:2 already sorts, so there is nothing to build" + NL)


def lead_closes(tmp_path, monkeypatch, edits=None):
    feature_place(tmp_path)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN, CLOSE],
                               "tester.md": [ASKED_LEAD, handoff(NONE_SAID)]}),
                        edits or (lambda s, n: None), "--task", ALREADY)
    return asked, code, folders(tmp_path)[-1]


def test_a_lead_decision_that_nothing_is_to_change_ends_with_no_change(
        tmp_path, monkeypatch):
    asked, code, folder = lead_closes(tmp_path, monkeypatch)
    assert asked.count("tester.md") == 2
    assert "worker.md" not in asked
    assert len(folders(tmp_path)) == 1
    assert outcome(folder) == "done: no change", gates(folder)
    assert code == stops.EXIT_OK
    line = end(tmp_path)
    assert line.cause == stops.NO_CHANGE
    [ruled] = decisions.read(tmp_path / "project")
    assert "close the run as already done" in ruled.decided
    assert ruled.at.strftime(stops.STAMP) in line.why
    told = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "done: no change" in told


def test_a_lead_decision_never_ends_a_run_that_changed_a_file(tmp_path,
                                                             monkeypatch):
    place = tmp_path / "project"

    def edits(step, n):
        if step == "tester.md" and n == 1:
            (place / "report.py").write_text(
                (place / "report.py").read_text(encoding="utf-8")
                + NL + "# seen" + NL, encoding="utf-8")
    asked, code, folder = lead_closes(tmp_path, monkeypatch, edits)
    assert outcome(folder) != "done: no change"
    assert end(tmp_path).cause != stops.NO_CHANGE


def test_a_question_that_says_none_parks_nothing(tmp_path):
    (tmp_path / "calc.py").write_text(WORKS, encoding="utf-8")
    (tmp_path / decisions.FILE).write_text("# decisions" + NL + NL + "x" + NL,
                                           encoding="utf-8")
    said = handoff(NOTHING, "QUESTION: none (already asked at decisions.md:3"
                   " and ruled on)" + NL)
    assert ruling.no_red("worker.md", said, tmp_path) is None
    only = handoff(NOTHING, "QUESTION: is the entry at decisions.md:3 still"
                   " right?" + NL)
    assert ruling.no_red("worker.md", only, tmp_path) is None
    assert ruling.no_red("worker.md", ASKS, tmp_path) is not None
