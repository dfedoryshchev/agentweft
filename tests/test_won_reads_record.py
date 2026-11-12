"""a pass's `won` reads what its record shows, never a bare none.

a lead that put its own question's decision on record decided; a reviewer
whose routed case went red on the start commit, by the next test writer's
red-test gate, caught a test gap; a review whose handoff names an adjacent
defect or a question nothing settles found something; a retro that wrote or
refused facts or tickets maintained the trail; a pass a start-tests, command
or project gate ran green on held; a pass that ran checks and found nothing
checked. `none` is left for a pass the record shows no effect of.
"""
import json
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.runner import stops, summary, trace

import test_lead_own_question as own
from test_won import Said, a_line, a_pass_of, lines_of, verified

NL = chr(10)


def test_a_lead_that_decided_its_own_question_won_decided(tmp_path,
                                                          monkeypatch):
    own.a_flow(tmp_path, monkeypatch)
    own.answering(monkeypatch, own.block(own.ASK, own.REC, own.SETTLES))
    assert own.run(monkeypatch) == stops.EXIT_OK
    [planner] = [l for l in lines_of(own.folder(tmp_path))
                 if l["step"] == "planner.md"]
    assert planner["won"] == "decided"


def block_with(adjacent=(), questions=()):
    return {"state": "present", "verified": [], "adjacent": list(adjacent),
            "questions": list(questions)}


def test_a_review_that_names_an_adjacent_defect_found_it():
    said = a_line(block=block_with(adjacent=[
        "an option error that repeats a value holding LF prints two lines,"
        " already true for `--scale` at calc/cli.py:77\nfixed: no\ntest:"
        " none"]), step="reviewer-runs.md")
    assert said["won"] == "found"


def test_a_review_that_asks_what_nothing_settles_found_it():
    said = a_line(block=block_with(questions=[
        {"question": "should the error print a CR as given, which breaks the"
                     " one-line rule at TASK.md:11?",
         "recommend": "leave it", "size": "none", "settled": "none"}]),
        step="reviewer-runs.md")
    assert said["won"] == "found"


def test_an_adjacent_line_that_says_none_and_a_settled_question_find_nothing():
    said = a_line(block=block_with(
        adjacent=["none found in the diff read\nfixed: no\ntest: none"],
        questions=[{"question": "which order?", "recommend": "keep it",
                    "settled": 'TASK.md:3 "the order given"'}]),
        step="reviewer-runs.md")
    assert said["won"] == "none"


def test_a_review_that_ran_checks_and_found_nothing_checked():
    said = a_line(block=verified("backed", "backed", "backed"),
                  step="reviewer-runs.md")
    assert (said["won"], said["checked"]) == ("checked", 3)


def test_a_pass_a_suite_gate_ran_green_on_held():
    command = types.SimpleNamespace(gate="command", ok=True, detail="exit 0",
                                    unproven=None)
    said = a_line(gates=[command], step="reviewer.md")
    assert said["won"] == "held"


def test_a_retro_that_wrote_facts_maintained_the_trail():
    entry = trace.Entry(1, "retro.md", [], Said(), None, None, False)
    entry.facts = {"written": ["F-0001"], "tickets": [], "refused": []}
    assert trace.line(entry, "ok")["won"] == "maintained"
    entry.facts = {"written": [], "tickets": [], "refused": []}
    assert trace.line(entry, "ok")["won"] == "none"


def a_run(tmp_path, red_test_ok=True, red=False):
    folder = tmp_path / "run"
    folder.mkdir()
    lines = [
        {"seq": 1, "step": "worker.md", "outcome": "ok", "won": "delivered"},
        {"seq": 2, "step": "reviewer.md", "outcome": "routed",
         "to": "tester.md", "won": "checked", "checked": 5},
        {"seq": 3, "step": "tester.md", "outcome": "ok", "won": "delivered",
         "case": {"seq": 2, "step": "reviewer.md", "red": red},
         "gates": [{"gate": "red-test", "ok": red_test_ok,
                    "detail": "red, exit 1 (on the start commit, without the"
                              " product changes)"}]}]
    (folder / "steps.jsonl").write_text(
        NL.join(json.dumps(l) for l in lines) + NL, encoding="utf-8")
    return [(p["step"], p["facts"]["won"]) for p in summary.passes_of(
        folder, {}, types.SimpleNamespace(steps=[]))]


def test_a_routed_case_red_on_the_start_commit_is_a_caught_test_gap(
        tmp_path):
    assert a_run(tmp_path)[1] == ("reviewer.md", "caught-test-gap")


def test_a_routed_case_the_red_test_gate_did_not_pass_caught_no_gap(
        tmp_path):
    assert a_run(tmp_path, red_test_ok=False)[1] == ("reviewer.md",
                                                      "checked")


def test_a_routed_case_red_on_the_code_still_caught(tmp_path):
    assert a_run(tmp_path, red=True)[1] == ("reviewer.md", "caught")


def test_the_spend_that_bought_clarity_is_never_on_the_waste_line():
    passes = [a_pass_of("worker.md", 0.1, "delivered", 2),
              a_pass_of("reviewer.md", 0.2, "checked", 5),
              a_pass_of("reviewer-runs.md", 0.3, "none", 0),
              a_pass_of("reviewer.md", 0.25, "held", 1),
              a_pass_of("retro.md", 0.05, "maintained", 0)]
    said = summary.bought(passes)
    assert ("- USD on steps that won nothing and checked nothing: $0.3000 of"
            " $0.9000") in said
    assert ("- USD on steps that bought clarity, checked 6 and held 1:"
            " $0.4500") in said
    assert "- won checked: 1 pass, 1.0s, $0.2000" in said
    assert "- upkeep, not waste: the retro $0.0500" in said
