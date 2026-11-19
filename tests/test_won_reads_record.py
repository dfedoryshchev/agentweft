"""a pass's `won` reads what its record shows, never a bare none.

a lead that put its own question's decision on record decided; a reviewer
whose routed case went red on the start commit, by the next test writer's
red-test gate, caught a test gap; a review whose handoff names an adjacent
defect with a typed `fixed:` line, or a question its SETTLED BY line says
nothing settles, found something; a retro that wrote or refused facts or
tickets maintained the trail; a pass a start-tests, command or project gate
ran green on held. `none` is left for a pass the record shows no effect of.
"""
import json
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.runner import stops, summary, trace

import test_lead_own_question as own
from test_won import Said, a_gate, a_line, lines_of, verified

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
    said = a_line(block=block_with(adjacent=[
        "looked at the callers, all fine\nfixed: no"]),
        step="reviewer-runs.md")
    assert said["won"] == "found", "the typed line is read, never the defect"


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
    said = a_line(block=block_with(
        adjacent=["looked at the callers, all fine"],
        questions=[{"question": "which order?", "recommend": "keep it"}]),
        step="reviewer-runs.md")
    assert said["won"] == "none"
    said = a_line(block=block_with(
        adjacent=["the callers pass None\nfixed: maybe"]),
        step="reviewer-runs.md")
    assert said["won"] == "none"


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


def test_a_plan_backed_only_by_its_own_verified_lines_is_said_checked():
    said = a_line(block=verified(*["backed"] * 6), step="planner.md")
    assert (said["won"], said["checked"], said["checked_said"]) == (
        "said-checked", 6, 6)


def test_a_pass_an_executing_gate_ran_green_on_is_gate_checked():
    said = a_line(block=verified("backed"), gates=[
        a_gate("quote", True, "1 quoted")], step="reviewer-runs.md")
    assert (said["won"], said["checked"], said["checked_said"]) == (
        "gate-checked", 2, 1)


def asked_line(changed):
    entry = trace.Entry(3, "worker.md", [], Said(), None, None, False)
    entry.handoff = verified("backed", "backed", "backed")
    entry.changed = changed
    return trace.line(entry, "asked", why="NEEDS: 1. the order", to="worker.md")


def test_a_step_that_built_then_asked_is_not_a_check():
    assert asked_line(True)["won"] == "built-then-asked"
    assert asked_line(False)["won"] == "said-checked"


def asking_worker(tmp_path, monkeypatch, first_write):
    """-> the first worker line of a shipped build-feature run whose worker
    writes `first_write` and asks a NEEDS the lead's ASSUMED item answers.
    the place has no .gitignore, so pytest's caches already read as a
    change: only a run that wrote code is a fair case here."""
    import test_assumed_answers as aa
    import test_lead as tl

    answers = {"planner.md": [aa.PLAN], "tester.md": [tl.TESTER],
               "worker.md": [tl.NEEDS, tl.WORKER], "reviewer.md": [tl.OK],
               "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", tl.TEST)],
              "worker.md": [first_write, ("calc.py", tl.AFTER)]}
    folder = tl.run_it(tmp_path, monkeypatch, "build-feature", answers,
                       writes)[3]
    return [l for l in lines_of(folder) if l["step"] == "worker.md"][0]


def test_a_worker_that_wrote_code_then_asked_built_then_asked(
        tmp_path, monkeypatch):
    import test_lead as tl

    first = asking_worker(tmp_path, monkeypatch, ("calc.py", tl.AFTER))
    assert (first["outcome"], first["won"]) == ("asked", "built-then-asked")


def a_spend(won, cost, step="reviewer-runs.md", lead=False, checked=3):
    return {"step": step, "role": step, "seconds": 1.0, "lead": lead,
            "facts": {"won": won, "cost": cost, "checked": checked}}


def test_the_waste_line_prints_none_said_checked_and_plan_only_apart():
    said = summary.bought([
        a_spend("said-checked", 0.3417, step="planner.md", lead=True),
        a_spend("said-checked", 0.5600),
        a_spend("said-checked", 0.4757),
        a_spend("none", 0.1000, checked=0),
        a_spend("held", 0.2529),
        a_spend("caught-test-gap", 0.3444)])
    assert "- USD on steps that won nothing and checked nothing: $0.1000 of" \
        " $2.0747" in said
    assert "- USD on steps checked only by their own word that found" \
        " nothing: $1.0357" in said
    assert "- USD on the lead's plan, checked only by its own word: $0.3417" \
        in said
    assert any(l.startswith("- USD on steps that bought clarity, checked 3"
                            " and held 1: $0.2529") for l in said), said


def test_bought_clarity_counts_the_gates_never_the_pass_s_own_word():
    gated = a_spend("gate-checked", 0.2000, checked=5)
    gated["facts"]["checked_said"] = 4
    said = summary.bought([gated])
    assert any(l.startswith("- USD on steps that bought clarity, checked 1"
                            " and held 0: $0.2000") for l in said), said
