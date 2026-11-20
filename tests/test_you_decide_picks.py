"""the operator's `you decide` to a park that guards a spec line or a test.

under the hand-back the lead decides in the question's own context, and
what it may change ends where the question the run stopped on ends:

- the lead's own question stopped on a start test it names, or on spec
  lines it marks broken: the answer lets exactly those tests and lines
  change, read from what the runner kept of the question, and nothing else;
- the test-edits check's park, which holds no recommendation: one go of the
  lead picks `override` or `put them back`, word for word, with a why;
- a conflict stop: one go of the lead picks `the request holds` or `the
  spec holds`, word for word, with a why, put on record as an `override:`
  or a `request:` on the lines the stop cites;
- a flow with no lead: the park stands, and says so.

a pick the program cannot read leaves the park standing.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops

from test_red_order import a_flow
from test_test_edits import (COUNT, COUNTED, ID, LINE, LOOSER, PATCHER,
                             PLANNER, RIGHT, TESTER, TESTER_SAID, WORKER,
                             WORKER_SAID, a_place, folders, module, read,
                             running)

NL = chr(10)
FILE = "tests/test_report.py"
LEAD = "lead: planner" + NL
OTHER = ("def test_other():" + NL
         + "    assert listed(['c']) == ['c']" + NL)
OTHER_LOOSE = ("def test_other():" + NL
               + "    assert len(listed(['c'])) == 1" + NL)
OTHER_ID = "tests/test_report.py::test_other"
SECOND = "the report prints one student per line."
SPEC = "# report" + NL + NL + LINE + NL + SECOND + NL
RULED = "the report lists students by entry."
SECOND_NOW = "the report prints every student on one line."


def page(question, recommend, mark=None):
    lines = ["- behaviour: the report counts students", "  file: report.py",
             "  spec: " + (mark or "allows TASK.md:3"), "", "HANDOFF", "DID:",
             "- set out the count", "QUESTION: " + question,
             "RECOMMEND: " + recommend, "SIZE: 2 lines in report.py",
             "END HANDOFF", ""]
    return NL.join(lines)


def planned(place):
    (place / "flows" / "build" / "planner.md").write_text(
        "# planner" + NL + NL + "plan it." + NL, encoding="utf-8")


def spec_place(where):
    place = a_place(where, baseline=module(RIGHT, OTHER))
    (place / "TASK.md").write_text(SPEC, encoding="utf-8")
    from test_test_edits import git
    git(place, "commit", "-qam", "spec")
    return place


TEST_Q = "may " + ID + " give way to the count, as the order no longer holds?"
TEST_REC = "loosen " + ID + " to the length only"


def start_test_parked(tmp_path, monkeypatch, flow_more=""):
    place = spec_place(tmp_path / "repo")
    a_flow(tmp_path, "build", PLANNER + TESTER + PATCHER + LEAD + flow_more)
    planned(tmp_path)
    does = {"planner.md": ({}, page(TEST_Q, TEST_REC)),
            "tester.md": ({FILE: module(RIGHT, OTHER, COUNT)}, TESTER_SAID),
            "worker.md": ({"report.py": COUNTED}, WORKER_SAID)}
    code, called = running(tmp_path, monkeypatch, place, does, False)
    assert called == ["planner.md"]
    assert code == stops.exit_code(stops.PARKED)
    first = folders()[-1]
    assert "- " + FILE + " - a test the run started with" in read(
        first / "question.md")
    return place, first, does


@pytest.mark.parametrize("answer", ["you decide", "You decide."])
def test_a_hand_back_to_the_lead_s_test_question_lets_that_test_change(
        tmp_path, monkeypatch, answer):
    place, first, does = start_test_parked(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED,
                          FILE: module(LOOSER, OTHER, COUNT)}, WORKER_SAID)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", answer)
    assert code == 0, read(folders()[-1] / "why.md")
    assert called == ["planner.md", "tester.md", "worker.md"]
    assert "each covered by a ruling" in read(folders()[-1] / "gates.md") \
        or ID + " (changed" in read(folders()[-1] / "gates.md")
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for planner.md: ")]
    assert "this authorises changing " + ID + ", and nothing else." \
        in given.why


def test_a_hand_back_to_the_test_question_lets_no_other_start_test_change(
        tmp_path, monkeypatch):
    place, first, does = start_test_parked(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED,
                          FILE: module(LOOSER, OTHER_LOOSE, COUNT)},
                         WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "you decide")
    assert code == stops.exit_code(stops.PARKED)
    question = read(folders()[-1] / "question.md")
    assert "- " + OTHER_ID + " - changed" in question
    assert "- " + ID + " - changed" not in question


def test_a_free_answer_to_the_test_question_still_lets_nothing_change(
        tmp_path, monkeypatch):
    place, first, does = start_test_parked(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED,
                          FILE: module(LOOSER, OTHER, COUNT)}, WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer",
                      "loosen it to the length")
    assert code == stops.exit_code(stops.PARKED)
    assert "- " + ID + " - changed" in read(folders()[-1] / "question.md")


MARK = 'breaks TASK.md:3 "' + LINE + '"'
MARK_Q = "the count lists students by entry: may the order line give way?"


def marks_parked(tmp_path, monkeypatch):
    place = spec_place(tmp_path / "repo")
    a_flow(tmp_path, "build", PLANNER + TESTER + PATCHER + LEAD
           + "spec_files: additions" + NL)
    planned(tmp_path)
    does = {"planner.md": ({}, page(MARK_Q, "let the order line say by"
                                     " entry", MARK)),
            "tester.md": ({FILE: module(RIGHT, OTHER, COUNT)}, TESTER_SAID),
            "worker.md": ({"report.py": COUNTED}, WORKER_SAID)}
    code, called = running(tmp_path, monkeypatch, place, does, False)
    assert called == ["planner.md"]
    assert code == stops.exit_code(stops.PARKED)
    first = folders()[-1]
    assert MARK in read(first / "question.md")
    return place, first, does


def test_a_hand_back_to_the_lead_s_marked_line_lets_that_spec_line_change(
        tmp_path, monkeypatch):
    place, first, does = marks_parked(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED,
                          "TASK.md": SPEC.replace(LINE, RULED)}, WORKER_SAID)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert code == 0, read(folders()[-1] / "why.md")
    assert called == ["planner.md", "tester.md", "worker.md"]
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for planner.md: ")]
    assert "this authorises changing TASK.md:3, and nothing else." \
        in given.why


def test_a_hand_back_to_a_marked_line_lets_no_other_spec_line_change(
        tmp_path, monkeypatch):
    place, first, does = marks_parked(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED, "TASK.md": SPEC.replace(
        LINE, RULED).replace(SECOND, SECOND_NOW)}, WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "you decide")
    assert code == stops.exit_code(stops.PARKED)
    question = read(folders()[-1] / "question.md")
    assert SECOND in question
    assert 'was "' + LINE + '"' not in question


def test_a_hand_back_to_a_marked_line_lets_no_same_words_elsewhere_change(
        tmp_path, monkeypatch):
    from test_test_edits import git
    place = spec_place(tmp_path / "repo")
    (place / "docs").mkdir()
    (place / "docs" / "spec.md").write_text("# also" + NL + NL + LINE + NL,
                                            encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "second spec")
    a_flow(tmp_path, "build", PLANNER + TESTER + PATCHER + LEAD
           + "spec_files: additions" + NL)
    planned(tmp_path)
    does = {"planner.md": ({}, page(MARK_Q, "let the order line say by"
                                     " entry", MARK)),
            "tester.md": ({FILE: module(RIGHT, OTHER, COUNT)}, TESTER_SAID),
            "worker.md": ({"report.py": COUNTED}, WORKER_SAID)}
    code, _ = running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.PARKED)
    first = folders()[-1]
    does["worker.md"] = ({"report.py": COUNTED,
                          "TASK.md": SPEC.replace(LINE, RULED),
                          "docs/spec.md": "# also" + NL + NL + RULED + NL},
                         WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "you decide")
    assert code == stops.exit_code(stops.PARKED), read(
        folders()[-1] / "gates.md")
    question = read(folders()[-1] / "question.md")
    assert "- docs/spec.md:3 - was" in question
    assert "- TASK.md:3 - was" not in question


def test_a_hand_back_matches_a_marked_line_by_its_file_and_words():
    cafe = "le caf" + chr(0xe9) + " est servi chaud"
    entry = decisions.Decision(
        "ruling for planner.md: you decide",
        "asked by planner.md in r1:" + NL + NL + "NEEDS: x" + ruling.ANSWERED
        + "you decide" + ruling.ANSWERED_BY + "op" + ruling.ANSWERED_END,
        None)
    handed = {"r1": ((), (cafe,), ("docs/api.md:1",))}
    assert ruling.handed_line(entry, "docs/api.md", cafe, handed)
    assert ruling.handed_line(entry, "docs\\api.md", cafe, handed)
    assert not ruling.handed_line(entry, "TASK.md", cafe, handed)
    assert not ruling.handed_line(entry, None, cafe, handed)
    assert not ruling.handed_line(entry, "docs/api.md", "other", handed)
    assert not ruling.handed_line(entry, "docs/api.md", cafe,
                                  {"r1": ((), (cafe,), ())})
    assert not ruling.handed_line(entry, "docs/api.md", cafe, {"r2": handed[
        "r1"]})


def test_an_override_to_a_marked_line_is_read_as_before(tmp_path, monkeypatch):
    place, first, does = marks_parked(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED,
                          "TASK.md": SPEC.replace(LINE, RULED)}, WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer",
                      "override: the count lists by entry")
    assert code == stops.exit_code(stops.PARKED)
    assert 'was "' + LINE + '"' in read(folders()[-1] / "question.md")


def test_what_a_hand_back_lets_change_is_read_from_the_record_only():
    tests = ruling.edits_asked([ID])
    marks = {"id": ruling.SPEC_MARKS, "lines": [LINE], "cites": ["TASK.md:3"]}
    lead = "planner.md"
    waits = {"step": lead, "cause": stops.PARKED}
    assert ruling.handed_asked(dict(waits, runner=tests), lead) == \
        ((ID,), (), (ID,))
    assert ruling.handed_asked(dict(waits, runner=marks), lead) == \
        ((), (LINE,), ("TASK.md:3",))
    nothing = ((), (), ())
    # a park of another step, a stop that is no park, a held test-edits
    # park and a record in no form the runner writes let nothing change
    assert ruling.handed_asked(dict(waits, step="worker.md", runner=tests),
                               lead) == nothing
    assert ruling.handed_asked(dict(waits, cause=stops.CONFLICT,
                                    runner=tests), lead) == nothing
    assert ruling.handed_asked(dict(waits, runner=ruling.edits_asked(
        [ID], held=True)), lead) == nothing
    assert ruling.handed_asked(dict(waits, runner={"id": ruling.SPEC_MARKS,
                                                    "lines": "x"}),
                               lead) == nothing
    assert ruling.handed_asked(dict(waits, runner=tests), None) == nothing
    assert ruling.handed_asked(None, lead) == nothing


def test_a_test_question_lets_the_tests_it_names_change_and_no_more():
    lead = "planner.md"
    asked = ruling.edits_asked([FILE, "tests/test_db.py"])
    question = NL.join([
        "NEEDS: may tests\\test_report.py::test_alphabetical give way?",
        "CITES:", "- tests/test_report.py - a test the run started with",
        "- tests/test_db.py - a test the run started with",
        "RECOMMEND: loosen tests/test_report.py::test_other too",
        "OPTIONS:", "- override: tests/test_db.py::test_rows"])
    tests, lines, _ = ruling.handed_asked(
        {"step": lead, "cause": stops.PARKED, "runner": asked,
         "question": question}, lead)
    # the named test, and the file it names no test of, which only a whole
    # file change matches; never a test the RECOMMEND or the OPTIONS name
    assert tests == (ID, "tests/test_db.py")
    assert lines == ()


def test_marks_whose_lines_cannot_be_read_keep_nothing(tmp_path):
    (tmp_path / "TASK.md").write_text(SPEC, encoding="utf-8")
    kept = ruling.marks_asked(["spec: " + MARK], tmp_path)
    assert kept == {"id": ruling.SPEC_MARKS, "lines": [ruling.flat(LINE)],
                    "cites": ["TASK.md:3"]}
    assert ruling.marks_asked(["spec: breaks TASK.md:40"], tmp_path) is None
    assert ruling.marks_asked(["spec: breaks"], tmp_path) is None
    assert ruling.marks_asked([], tmp_path) is None
    win = ruling.marks_asked(["spec: breaks docs\\api.md:1"], tmp_path)
    assert win is None
    (tmp_path / "docs").mkdir()
    cafe = "le caf" + chr(0xe9) + " est servi chaud"
    (tmp_path / "docs" / "api.md").write_text(cafe + NL, encoding="utf-8")
    assert ruling.marks_asked(["spec: breaks docs\\api.md:1"], tmp_path) == {
        "id": ruling.SPEC_MARKS, "lines": [cafe], "cites": ["docs/api.md:1"]}


# the test-edits check's park, picked by the lead

def edits_parked(tmp_path, monkeypatch, lead=LEAD):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", PLANNER + TESTER + PATCHER + lead)
    planned(tmp_path)
    does = {"planner.md": ({}, WORKER_SAID),
            "tester.md": ({FILE: module(RIGHT, COUNT)},
                          "FAILS: assert False" + NL + "TEST: " + FILE + NL),
            "worker.md": ({"report.py": COUNTED, FILE: module(COUNT)},
                          WORKER_SAID)}
    code, called = running(tmp_path, monkeypatch, place, does, False)
    assert called == ["planner.md", "tester.md", "worker.md", "worker.md"]
    assert code == stops.exit_code(stops.PARKED)
    first = folders()[-1]
    assert ID + " - removed" in read(first / "question.md")
    return place, first, does


def test_a_hand_back_to_a_test_edits_park_is_the_lead_s_override(
        tmp_path, monkeypatch):
    place, first, does = edits_parked(tmp_path, monkeypatch)
    does["planner.md"] = ({}, "DECIDED: override" + NL + "why: the"
                          " alphabetical case goes with the count" + NL)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert called == ["planner.md", "worker.md"]
    assert code == 0, read(folders()[-1] / "why.md")
    assert "each covered by a ruling: " + ID in read(
        folders()[-1] / "gates.md")
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for worker.md: ")]
    assert given.decided == ("ruling for worker.md: override: the alphabetical"
                             " case goes with the count")
    assert "planner.md, the flow's lead, picking under the operator's you" \
        " decide" in given.why
    steps = read(folders()[-1] / "steps.jsonl")
    assert '"step": "planner.md"' in steps


def test_a_hand_back_to_a_test_edits_park_the_lead_puts_back(
        tmp_path, monkeypatch):
    place, first, does = edits_parked(tmp_path, monkeypatch)
    does["planner.md"] = ({}, "DECIDED: put them back" + NL + "why: the order"
                          " line still holds" + NL)
    does["worker.md"] = ({"report.py": COUNTED, FILE: module(RIGHT, COUNT)},
                         WORKER_SAID)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert called == ["planner.md", "worker.md"]
    assert code == 0, read(folders()[-1] / "why.md")
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for worker.md: ")]
    assert given.decided == ("ruling for worker.md: put them back: the order"
                             " line still holds")


@pytest.mark.parametrize("said", [
    "DECIDED: maybe" + NL + "why: either works" + NL,
    "DECIDED: override, or put them back" + NL + "why: either" + NL,
    "DECIDED: override: no" + NL + "why: it does not hold" + NL,
    "DECIDED: override" + NL,
    "ESCALATE: the operator knows the order" + NL,
    "",
])
def test_a_pick_that_cannot_be_read_leaves_the_test_park_standing(
        tmp_path, monkeypatch, capsys, said):
    place, first, does = edits_parked(tmp_path, monkeypatch)
    does["planner.md"] = ({}, said)
    legs = len(folders())
    capsys.readouterr()
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    out = capsys.readouterr().out
    assert called == ["planner.md"]
    assert code == stops.exit_code(stops.PARKED)
    assert "the run stays parked" in out
    assert not [d for d in decisions.read(place)
                if d.decided.startswith("ruling for worker.md: ")]
    # the lead's go is on the leg that parks again, on the same question
    assert len(folders()) == legs + 1
    again = folders()[-1]
    assert read(again / "question.md") == read(first / "question.md")
    assert '"step": "planner.md"' in read(again / "steps.jsonl")
    does["planner.md"] = ({}, "DECIDED: override" + NL + "why: it goes" + NL)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", again.name, "--answer", "you decide")
    assert called == ["planner.md", "worker.md"]
    assert code == 0


def test_a_test_edits_park_offers_the_hand_back_when_the_flow_has_a_lead(
        tmp_path, monkeypatch):
    _, first, _ = edits_parked(tmp_path, monkeypatch)
    assert '--answer "you decide"' in read(first / "handoff.md")


# a conflict stop, picked by the lead

CONFLICT = 'CONFLICT: TASK.md:3 "' + LINE + '"' + NL \
    + "request: list the students by entry" + NL


def conflict_stopped(tmp_path, monkeypatch, lead=LEAD):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", PLANNER + TESTER + WORKER + lead)
    planned(tmp_path)
    does = {"planner.md": ({}, WORKER_SAID),
            "tester.md": ({FILE: module(RIGHT, COUNT)}, TESTER_SAID),
            "worker.md": [({}, CONFLICT), ({"report.py": COUNTED},
                                           WORKER_SAID)]}
    code, called = running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.CONFLICT)
    assert called == ["planner.md", "tester.md", "worker.md"]
    return place, folders()[-1], does


def test_a_hand_back_to_a_conflict_the_lead_lets_the_request_win(
        tmp_path, monkeypatch):
    place, first, does = conflict_stopped(tmp_path, monkeypatch)
    does["planner.md"] = ({}, "DECIDED: the request holds" + NL + "why: the"
                          " request says the order changes" + NL)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert code == 0, read(folders()[-1] / "why.md")
    assert called == ["planner.md", "worker.md"]
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for worker.md: ")]
    assert given.decided == ("ruling for worker.md: override: the request says"
                             " the order changes")
    assert "this authorises changing TASK.md:3, and nothing else." \
        in given.why


def test_a_hand_back_to_a_conflict_the_lead_keeps_the_spec(tmp_path,
                                                          monkeypatch):
    place, first, does = conflict_stopped(tmp_path, monkeypatch)
    does["planner.md"] = [({}, "DECIDED: the spec holds" + NL + "why: the"
                           " request only wants a count" + NL),
                          ({}, WORKER_SAID)]
    does["worker.md"] = ({"report.py": COUNTED}, WORKER_SAID)
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert code == 0, read(folders()[-1] / "why.md")
    assert called[0] == "planner.md"
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for worker.md: ")]
    assert given.decided == ("ruling for worker.md: request: the request only"
                             " wants a count")


@pytest.mark.parametrize("said", [
    "DECIDED: the request" + NL + "why: it says so" + NL,
    "DECIDED: the spec holds, or the request holds" + NL + "why: x" + NL,
    "DECIDED: the spec holds - not really" + NL + "why: x" + NL,
    "ESCALATE: only the operator knows" + NL,
])
def test_a_conflict_pick_that_cannot_be_read_leaves_the_stop_standing(
        tmp_path, monkeypatch, capsys, said):
    place, first, does = conflict_stopped(tmp_path, monkeypatch)
    does["planner.md"] = ({}, said)
    legs = len(folders())
    capsys.readouterr()
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    assert called == ["planner.md"]
    assert code == stops.exit_code(stops.CONFLICT)
    assert len(folders()) == legs + 1
    assert "the run stays parked" in capsys.readouterr().out
    assert decisions.read(place) == []
    assert "cause          conflict" in read(folders()[-1] / "handoff.md")


def test_a_conflict_offers_the_hand_back_when_the_flow_has_a_lead(
        tmp_path, monkeypatch):
    _, first, _ = conflict_stopped(tmp_path, monkeypatch)
    assert '--answer "you decide"' in read(first / "handoff.md")


# what a pick lets change: the cited set, never what its why names

def conflict_on_two_lines(tmp_path, monkeypatch):
    place = spec_place(tmp_path / "repo")
    a_flow(tmp_path, "build", PLANNER + TESTER + WORKER + LEAD
           + "spec_files: additions" + NL)
    planned(tmp_path)
    does = {"planner.md": ({}, WORKER_SAID),
            "tester.md": ({FILE: module(RIGHT, OTHER, COUNT)}, TESTER_SAID),
            "worker.md": [({}, CONFLICT), ({"report.py": COUNTED},
                                           WORKER_SAID)]}
    code, _ = running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.CONFLICT)
    return place, folders()[-1], does


def picked_with_both_lines_changed(tmp_path, monkeypatch, why):
    place, first, does = conflict_on_two_lines(tmp_path, monkeypatch)
    does["planner.md"] = ({}, "DECIDED: the request holds" + NL + "why: "
                          + why + NL)
    does["worker.md"] = ({"report.py": COUNTED, "TASK.md": SPEC.replace(
        LINE, RULED).replace(SECOND, SECOND_NOW)}, WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "you decide")
    return place, code


@pytest.mark.parametrize("why", [
    'the request says the order changes, and "' + SECOND + '" goes with it',
    "the request says the order changes, so update TASK.md",
    "the request says the order changes",
])
def test_a_conflict_pick_lets_only_the_cited_line_change_whatever_its_why(
        tmp_path, monkeypatch, why):
    place, code = picked_with_both_lines_changed(tmp_path, monkeypatch, why)
    assert code == stops.exit_code(stops.PARKED), read(
        folders()[-1] / "gates.md")
    question = read(folders()[-1] / "question.md")
    assert 'was "' + SECOND + '"' in question
    assert 'was "' + LINE + '"' not in question
    [given] = [d for d in decisions.read(place)
               if d.decided.startswith("ruling for worker.md: ")]
    assert "this authorises changing TASK.md:3, and nothing else." \
        in given.why


def test_the_operator_s_own_override_naming_the_spec_file_still_widens(
        tmp_path, monkeypatch):
    place, first, does = conflict_on_two_lines(tmp_path, monkeypatch)
    does["worker.md"] = ({"report.py": COUNTED, "TASK.md": SPEC.replace(
        LINE, RULED).replace(SECOND, SECOND_NOW)}, WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer",
                      "override: the order changes, so update TASK.md")
    assert code == 0, read(folders()[-1] / "gates.md")


def edits_held_on_one_of_two(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo", baseline=module(RIGHT, OTHER))
    a_flow(tmp_path, "build", PLANNER + TESTER + PATCHER + LEAD)
    planned(tmp_path)
    does = {"planner.md": ({}, WORKER_SAID),
            "tester.md": ({FILE: module(RIGHT, OTHER, COUNT)},
                          "FAILS: assert False" + NL + "TEST: " + FILE + NL),
            "worker.md": ({"report.py": COUNTED, FILE: module(OTHER, COUNT)},
                          WORKER_SAID)}
    code, _ = running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.PARKED)
    first = folders()[-1]
    question = read(first / "question.md")
    assert ID + " - removed" in question and "test_other" not in question
    return place, first, does


@pytest.mark.parametrize("why", [
    "the alphabetical case goes with the count, and so does test_other",
    "the alphabetical case goes with the count, and so does " + OTHER_ID,
    "the alphabetical case goes with the count",
])
def test_an_edits_pick_lets_only_the_named_tests_change_whatever_its_why(
        tmp_path, monkeypatch, why):
    place, first, does = edits_held_on_one_of_two(tmp_path, monkeypatch)
    does["planner.md"] = ({}, "DECIDED: override" + NL + "why: " + why + NL)
    does["worker.md"] = ({"report.py": COUNTED, FILE: module(COUNT)},
                         WORKER_SAID)
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "you decide")
    assert code == stops.exit_code(stops.PARKED), read(
        folders()[-1] / "gates.md")
    question = read(folders()[-1] / "question.md")
    assert OTHER_ID + " - removed" in question
    assert ID + " - removed" not in question


def test_a_pick_is_told_apart_by_the_runner_s_line_never_by_its_words():
    def entry(by, answer="override: as TASK.md:4 says"):
        return decisions.Decision(
            "ruling for worker.md: " + answer,
            "asked by worker.md in r1:" + NL + NL + "NEEDS: x" + ruling.ANSWERED
            + answer + ruling.ANSWERED_BY + by + ruling.ANSWERED_END, None)
    assert ruling.picked(entry(ruling.picked_by("planner.md", "op")))
    assert ruling.picked(entry(ruling.picked_by("architect.md", "o p")))
    # the operator's own answer, even one quoting the pick's words
    assert not ruling.picked(entry("op"))
    assert not ruling.picked(entry(
        "op", "override: " + ruling.picked_by("planner.md", "op")))
    assert not ruling.picked(decisions.Decision("by hand", "a note", None))


# a flow with no lead

@pytest.mark.parametrize("parks", ["edits", "conflict"])
def test_a_hand_back_in_a_flow_with_no_lead_leaves_the_park_standing(
        tmp_path, monkeypatch, capsys, parks):
    place, first, does = (edits_parked if parks == "edits"
                          else conflict_stopped)(tmp_path, monkeypatch,
                                                 lead="")
    capsys.readouterr()
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer", "you decide")
    out = capsys.readouterr().out
    assert called == []
    assert code == stops.exit_code(stops.PARKED if parks == "edits"
                                   else stops.CONFLICT)
    assert "this flow names no lead to decide it" in out
    assert '--answer "you decide"' not in out
    assert decisions.read(place) == []
