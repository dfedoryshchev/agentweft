"""an item a later step answered leaves what is open, and says what answered it.

the handoff gathers each step's questions and not verified lines. one a later
step answered is not open: the one decision is picked from what is still
open, and the answered item is kept in the full record with what answered
it. what answers is a typed link only: a later step's `led to:` the record
holds, or a later step's VERIFIED claim its transcript backs, naming a test
the item names by its exact id. an item that names no test, and every word
of a test name read as words, answers nothing: such an item stays open.
"""
import datetime
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import handoff, lead, stops, summary

NO_GIT = {"git": False}
NL = chr(10)
WRONG = ("should test_other_char_accepted use a letter that is not in the"
         " fixture data (for example `q`)? As written, TASK.md:9 requires the"
         " error it does not expect.")
LIVE = ("Should the error print C as given when C is CR or LF, which breaks"
        " the one-line stderr rule at TASK.md:3?")
TEST = "tests/test_sep.py::test_other_char_accepted"


def a_pass(step, said, outcome="ok", gates=(), backed=False, case=None):
    block = handoff.parse(said)
    if backed:
        for item in block["verified"]:
            item["backed"], item["why"] = "backed", ""
    return summary.a_pass(step, step[:-3], 1.0, block, list(gates), False,
                          outcome, said, case=case)


def asking(question, recommend, size):
    return ("HANDOFF" + NL + "DID:" + NL + "- read the tests" + NL
            + "QUESTION: " + question + NL + "RECOMMEND: " + recommend + NL
            + "SIZE: " + size + NL + "END HANDOFF" + NL)


def because(reason, cited, led_to, did="- swapped the letter"):
    return ("HANDOFF" + NL + "DID:" + NL + did + NL + "BECAUSE:" + NL + "- "
            + reason + NL + "  from: " + cited + NL + "  led to: " + led_to
            + NL + "END HANDOFF" + NL)


def red_first(*ids):
    return {"gate": "red-first", "ok": True, "command": "python -m pytest"
            " -q {test}", "detail": str(len(ids)) + " of " + str(len(ids))
            + " new tests red without the fix and green with it: "
            + ", ".join(ids),
            "tests": [{"test": i, "before": "red", "kind": "assertion",
                       "after": "green", "red_on": "assertion"} for i in ids]}


PROOF = {"how": "gate", "gate": "red-test", "step": "tester.md",
         "source": "written", "ids": [TEST], "tests": {"tests/test_sep.py": "0"}}


def build(passes, decided=(), proof=PROOF):
    return summary.build("f-1", "f", "add the separator option", passes,
                         NO_GIT, list(decided), "1 call", proof=proof)


def section(lines, name):
    text = NL.join(lines)
    if NL + "## " + name + NL not in NL + text:
        return ""
    return (NL + text).split(NL + "## " + name + NL, 1)[1].split(
        NL + "## ")[0]


def default_view(lines):
    return lines[:lines.index("## full record")]


def the_decision(lines):
    return section(default_view(lines), "the one decision")


def a_question_answered_in_the_run(later):
    return [a_pass("planner.md", "HANDOFF" + NL + "DID:" + NL + "- planned"
                   + NL + "END HANDOFF" + NL),
            a_pass("tester.md", "HANDOFF" + NL + "DID:" + NL + "- wrote 3"
                   " failing tests" + NL + "END HANDOFF" + NL),
            a_pass("worker.md", asking(WRONG, "the tester swaps `x` for a"
                                       " letter that is not in the data",
                                       "one line, one test file"), "redo"),
            later,
            a_pass("worker.md", "HANDOFF" + NL + "DID:" + NL + "- built it"
                   + NL + "END HANDOFF" + NL, gates=[red_first(TEST)]),
            a_pass("reviewer-runs.md", asking(LIVE, "leave it as is: the"
                                              " request asks for the value"
                                              " as given", "none if left"))]


def test_a_question_a_later_step_led_to_its_test_for_is_answered_not_open():
    lines = build(a_question_answered_in_the_run(a_pass("tester.md", because(
        "the worker showed `x` collides with the data", "TASK.md:9", TEST))))
    decision = the_decision(lines)
    assert decision.startswith("- " + LIVE), decision
    assert "test_other_char_accepted" not in decision
    gaps = section(default_view(lines), "product gaps")
    assert "TASK.md:3 - the one decision turns on it" in gaps
    assert "TASK.md:9" not in gaps
    answered = section(lines, "answered in the run")
    assert ("- worker: " + WRONG + " - answered by tester.md, pass 4 of the"
            " run: led to " + TEST) in answered, answered
    assert "test_other_char_accepted" not in section(lines, "open questions")


def test_a_later_step_on_the_same_line_but_another_test_answers_nothing():
    lines = build(a_question_answered_in_the_run(a_pass("tester.md", because(
        "the field count rule", "TASK.md:9",
        "tests/test_sep.py::test_field_count"))),
        proof=dict(PROOF, ids=[TEST, "tests/test_sep.py::test_field_count"]))
    assert the_decision(lines).startswith("- " + WRONG)
    assert section(lines, "answered in the run") == ""


def test_a_led_to_the_record_does_not_hold_answers_nothing():
    lines = build(a_question_answered_in_the_run(a_pass("tester.md", because(
        "the worker showed `x` collides", "TASK.md:9",
        "tests/test_sep.py::test_other_char_accepted_again"))))
    assert the_decision(lines).startswith("- " + WRONG)


def test_a_test_name_that_shares_words_with_a_question_answers_nothing():
    asked = "Should an offset at year 0001 that overflows be an error?"
    passes = [a_pass("planner.md", asking(asked, "reject it", "one line")),
              a_pass("tester.md", because(
                  "the ruling rejects such times", "decisions.md",
                  "tests/test_t.py::test_offset_at_year_0001_overflows_error"),
                  gates=[red_first(
                      "tests/test_t.py::test_offset_at_year_0001_overflows"
                      "_error")])]
    lines = build(passes, proof=dict(PROOF, ids=[
        "tests/test_t.py::test_offset_at_year_0001_overflows_error"]))
    assert the_decision(lines).startswith("- " + asked)


def test_a_question_with_nothing_after_it_stays_the_one_decision():
    lines = build([a_pass("worker.md", asking(WRONG, "swap it", "one line"))])
    assert the_decision(lines).startswith("- " + WRONG)
    assert section(lines, "answered in the run") == ""


def test_the_lead_decisions_stay_first_and_the_open_question_follows():
    own = "Is an impossible date an invalid time (TASK.md:5)?"
    planner = a_pass("planner.md", asking(own, "reject it", "one line"))
    ruled = decisions.Decision(*lead.recorded(
        "planner.md", "planner.md", "f-1", "NEEDS: " + own, "reject it",
        "TASK.md:5 says so"), at=datetime.datetime(2026, 1, 1))
    passes = a_question_answered_in_the_run(a_pass("tester.md", because(
        "the worker showed `x` collides", "TASK.md:9", TEST)))
    lines = build([planner] + passes, [ruled])
    decision = the_decision(lines).split(NL)
    assert decision[0] == "- decided by the lead: " + own, decision
    rest = NL.join(decision[1:])
    assert "- " + LIVE in rest
    assert "test_other_char_accepted" not in rest


NOT_VERIFIED = ("Whether tests/test_b.py::test_report_lines sets its budgets in"
                " sorted order - I did not read its body")


def checked(claim):
    return ("HANDOFF" + NL + "DID:" + NL + "- sorted the report" + NL
            + "VERIFIED:" + NL + "- " + claim + NL + "  cmd: cat -n"
            " tests/test_b.py" + NL + "  saw: store[\"budgets\"] = {}" + NL
            + "END HANDOFF" + NL)


def worker_left(*items):
    return ("HANDOFF" + NL + "DID:" + NL + "- wrote the test" + NL
            + "NOT VERIFIED:" + NL + NL.join("- " + i for i in items) + NL
            + "END HANDOFF" + NL)


def test_a_not_verified_line_a_later_backed_check_names_leaves_the_head():
    lines = build([a_pass("worker.md", worker_left(NOT_VERIFIED)),
                   a_pass("patcher.md", checked(
                       "The existing test_report_lines sets its budgets in"
                       " sorted order already"), backed=True)], proof=None)
    head = section(default_view(lines), "not done")
    assert "test_report_lines" not in head, head
    full = section(lines, "not verified")
    assert ("- worker: " + NOT_VERIFIED + " - answered by patcher.md, pass 2"
            " of the run: verified: The existing test_report_lines sets its"
            " budgets in sorted order already") in full, full


def test_a_check_the_transcript_does_not_back_answers_nothing():
    lines = build([a_pass("worker.md", worker_left(NOT_VERIFIED)),
                   a_pass("patcher.md", checked(
                       "The existing test_report_lines sets its budgets in"
                       " sorted order already"))], proof=None)
    assert "test_report_lines" in section(default_view(lines), "not done")
    assert "answered by" not in section(lines, "not verified")


def test_a_not_verified_line_that_names_no_test_stays_open():
    left = ["That the existing suite passes at baseline - no tests were run",
            "Whether a year 0001 time with an offset overflows - not run"]
    lines = build([
        a_pass("planner.md", worker_left(*left)),
        a_pass("worker.md", because(
            "the ruling rejects times outside the years", "decisions.md",
            "tests/test_t.py::test_time_outside_years_is_an_error"),
            gates=[red_first("tests/test_t.py::test_time_outside_years_is_an"
                             "_error"),
                   {"gate": "start-tests", "ok": True, "command": "",
                    "detail": "32 tests the run started with pass against"
                    " the product as it is now"}])],
        proof=dict(PROOF, ids=["tests/test_t.py::test_time_outside_years_is"
                               "_an_error"]))
    full = section(lines, "not verified")
    for item in left:
        assert "- planner: " + item + NL in full + NL, full
    assert "answered by" not in full
    assert "existing suite" in section(default_view(lines), "not done")


def test_a_stopped_runs_question_is_never_answered_by_what_came_before():
    said = ("NEEDS: should test_other_char_accepted use `q` (TASK.md:9)?" + NL
            + "RECOMMEND: swap it" + NL + "SIZE: one line" + NL)
    lines = summary.build(
        "f-1", "f", "add it", [a_pass("tester.md", because(
            "x collides", "TASK.md:9", TEST)),
            a_pass("worker.md", said, "asked")], NO_GIT, [], "1 call",
        stopped={"cause": stops.REFUSED, "at": "worker.md",
                 "why": "worker.md asks", "question": said}, proof=PROOF)
    assert "test_other_char_accepted use" in the_decision(lines).split(NL)[0]
