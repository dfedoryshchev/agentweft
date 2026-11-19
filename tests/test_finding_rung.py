"""a step's finding on a spec line the code breaks reaches the flow's lead,
and what the run holds of such marks survives a resume.

a mark the run holds as a spec line the code already breaks for a sibling
path is fixed test-first: a test of the run shows it red on the start commit
and the change shows it fixed. a mark no test showed broken by the end of
the run parks as a plain `breaks`, never passes in silence. the marks held,
the marks not shown broken, the ASSUMED items that answered a step and the
findings put to the lead go into the runner's own record of the run, so a
resumed leg carries them on.
"""
import json
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.guardrails import rulings
from agentweft.runner import asking, engine, stops

import test_already_broken as ab
import test_lead as tl

NL = chr(10)


def held_run(tmp_path, adjacent):
    return types.SimpleNamespace(adjacent=adjacent, workdir=str(tmp_path),
                                 start=None, kept=None)


def test_a_mark_no_test_showed_broken_parks_at_the_end(tmp_path):
    run = held_run(tmp_path, {ab.MARK: {"spec": "TASK.md:3",
                                        "at": "calc.py:2", "test": None}})
    broken, unfixed = asking.sibling_unfixed(run)
    assert broken is None
    assert unfixed.startswith("NEEDS: ")
    assert "no test of the run showed it broken there" in unfixed
    assert "- " + ab.MARK in unfixed.split(NL)
    assert ab.MARK in run.not_broken and not run.adjacent


def test_with_no_mark_held_the_end_passes_quietly(tmp_path):
    assert asking.sibling_unfixed(held_run(tmp_path, {})) == (None, "")


def test_the_marks_a_run_holds_are_on_its_record_and_carried(tmp_path):
    first = rulings.Kept(tmp_path)
    first.keep_in(tmp_path / "leg1")
    run = types.SimpleNamespace(
        kept=first, adjacent={ab.MARK: {"spec": "TASK.md:3",
                                        "at": "calc.py:2", "test": "t::x",
                                        "how": "assertion"}},
        not_broken={"spec: breaks TASK.md:9"},
        assumed_led={("worker.md", "planner.md", 2)},
        found={("TASK.md:3", "calc.py:2")})
    asking.keep_state(run)
    saved = json.loads((tmp_path / "leg1" / rulings.FILE).read_text(
        encoding="utf-8"))
    assert saved["state"]["adjacent"][ab.MARK]["test"] == "t::x"
    second = rulings.Kept(tmp_path)
    second.carry(tmp_path / "leg1")
    again = types.SimpleNamespace(kept=second)
    asking.carry_state(again)
    assert again.adjacent == run.adjacent
    assert again.not_broken == run.not_broken
    assert again.assumed_led == run.assumed_led
    assert again.found == run.found
    assert getattr(again, "state_unread", "") == ""


def test_a_record_with_no_marks_writes_no_state(tmp_path):
    kept = rulings.Kept(tmp_path)
    kept.keep_in(tmp_path / "leg1")
    asking.keep_state(types.SimpleNamespace(kept=kept))
    saved = json.loads((tmp_path / "leg1" / rulings.FILE).read_text(
        encoding="utf-8"))
    assert "state" not in saved


def test_a_carried_state_that_cannot_be_read_parks_at_the_end(tmp_path):
    (tmp_path / "leg1").mkdir()
    (tmp_path / "leg1" / rulings.FILE).write_text(json.dumps(
        {"found": [], "written": [], "state": {"adjacent": ["not", "a",
                                                            "dict"]}}),
        encoding="utf-8")
    kept = rulings.Kept(tmp_path)
    kept.carry(tmp_path / "leg1")
    run = types.SimpleNamespace(kept=kept, workdir=str(tmp_path), start=None)
    asking.carry_state(run)
    assert run.state_unread
    broken, unfixed = asking.sibling_unfixed(run)
    assert broken is None
    assert "could not be read" in unfixed


START_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
              + "    assert add(2, 1) == 3" + NL)
ASKS_ON_START_TEST = (
    "NEEDS: may tests/test_add.py:5 change, now that add is fixed?" + NL
    + "CITES:" + NL + "- tests/test_add.py:5 - assert add(2, 1) == 3" + NL
    + "OPTIONS:" + NL + "- yes: change it" + NL + "- no: leave it" + NL)
DECIDES_ON_START_TEST = (
    "DECIDED: keep: return the product as it is, and loosen"
    " tests/test_add.py::test_add" + NL + "why: TASK.md:3 says a times b" + NL)


def worker_asks(tmp_path, monkeypatch, worker, lead_says=(tl.DECIDED,),
                reviewer=tl.OK):
    answers = {"planner.md": [tl.PLAN] + list(lead_says),
               "tester.md": [tl.TESTER], "worker.md": [worker, tl.WORKER],
               "reviewer.md": [reviewer], "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", tl.TEST)],
              "worker.md": [("", ""), ("calc.py", tl.AFTER)]}
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, writes,
                     start=[("tests/test_add.py", START_TEST)])


def test_a_needs_naming_a_start_test_never_costs_a_lead_call(tmp_path,
                                                             monkeypatch):
    asked, _, code, folder, _ = worker_asks(tmp_path, monkeypatch,
                                            ASKS_ON_START_TEST)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_STOP
    said = ab.question(folder)
    assert "tests/test_add.py::test_add - a test the run started with" in said
    assert "override:" in said


def test_a_lead_decision_naming_a_start_test_parks_as_the_test_question(
        tmp_path, monkeypatch):
    asked, _, code, folder, _ = worker_asks(
        tmp_path, monkeypatch, tl.NEEDS, lead_says=(DECIDES_ON_START_TEST,))
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    said = ab.question(folder)
    assert "- tests/test_add.py - a test the run started with" in said
    assert "RECOMMEND: keep: return the product as it is" in said
    assert "planner.md decided for worker.md" not in (
        tmp_path / "project" / "decisions.md").read_text(encoding="utf-8") \
        if (tmp_path / "project" / "decisions.md").exists() else True


SPLITS = (tl.NEEDS + 'SPLIT: the request "calc gets mul(a, b)" reads as a'
          " new function, or as a new operator" + NL)


def test_a_typed_split_beside_a_needs_goes_up_with_no_lead_call(tmp_path,
                                                                monkeypatch):
    asked, _, code, folder, _ = worker_asks(tmp_path, monkeypatch, SPLITS)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_STOP
    assert "SPLIT: the request" in ab.question(folder)
    assert "(the quote is in the request)" in ab.question(folder)


def test_a_needs_with_no_typed_risk_still_goes_to_the_lead(tmp_path,
                                                           monkeypatch):
    asked, _, code, _, _ = worker_asks(tmp_path, monkeypatch, tl.NEEDS)
    assert asked[:5] == ["planner.md", "tester.md", "worker.md",
                         "planner.md", "worker.md"]
    assert code == stops.EXIT_OK


DISPUTES = (tl.OK + NL + "HANDOFF" + NL + "DID:" + NL + "- reviewed" + NL
            + "DOUBTS:" + NL + "- should mul round a float product: I would"
            " answer round, TASK.md:3 asks for whole numbers" + NL
            + "END HANDOFF" + NL)


def test_a_doubt_that_disputes_a_lead_decision_goes_back_to_the_lead(
        tmp_path, monkeypatch):
    stands = "DECIDED 1: keep stands" + NL + "why: TASK.md:3 says a times b" + NL
    asked, _, code, _, project = worker_asks(
        tmp_path, monkeypatch, tl.NEEDS, lead_says=(tl.DECIDED, stands),
        reviewer=DISPUTES)
    assert asked.count("planner.md") == 3
    assert code == stops.EXIT_OK
    assert "planner.md decided for reviewer.md: keep stands" in (
        project / "decisions.md").read_text(encoding="utf-8")


LEFT = ab.BROKEN + ab.MUL


def handoff_with(item):
    return (NL + "HANDOFF" + NL + "DID:" + NL + "- mul added" + NL
            + "ADJACENT:" + NL + item + "END HANDOFF" + NL)


FOUND_ITEM = ("- add returns a minus b, against TASK.md:3, at calc.py:2" + NL
              + "  fixed: no" + NL + "  test: none" + NL)
LEAD_MARKS = ("FIX 1: TASK.md:3 for add, which returns a minus b" + NL
              + 'spec: breaks TASK.md:3, already at calc.py:2 "return a - b"'
              + NL)
SIBLING_TESTER = tl.TESTER + "SIBLING TEST: " + ab.SIBLING_ID + NL


def found_by_the_worker(tmp_path, monkeypatch, lead_says, item=FOUND_ITEM,
                        reviewer=tl.OK, left=LEFT):
    monkeypatch.setattr(tl, "BEFORE", ab.BROKEN)
    answers = {"planner.md": [tl.PLAN] + list(lead_says),
               "tester.md": [tl.TESTER, SIBLING_TESTER],
               "worker.md": [tl.WORKER + handoff_with(item), tl.WORKER],
               "reviewer.md": [reviewer], "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", tl.TEST),
                            ("tests/test_mul.py",
                             ab.with_sibling("add(2, 1) == 3"))],
              "worker.md": [("calc.py", left), ("calc.py", ab.FIXED)]}
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, writes)


def test_a_workers_finding_on_a_spec_line_is_marked_by_the_lead_and_fixed(
        tmp_path, monkeypatch):
    asked, sent, code, folder, _ = found_by_the_worker(tmp_path, monkeypatch,
                                                       [LEAD_MARKS])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    brief = sent[3]
    assert "TASK.md:3" in brief and "mul(a, b) returns a times b" in brief
    assert "calc.py:2" in brief and "return a - b" in brief
    assert "SIBLING TEST" in sent[4]
    names = ab.gate_names(folder)
    assert ("tester.md", "sibling-red") in names
    assert ("runner", "already-broken") in names
    assert ab.beside_first(folder).startswith(
        "- runner: TASK.md:3 already broken at calc.py:2")


ACCENTED = "    return a - b  # " + chr(0xE9) + "cart"


def test_a_finding_by_a_windows_path_on_a_non_ascii_line_is_marked_too(
        tmp_path, monkeypatch):
    broken = ab.BROKEN.replace("    return a - b", ACCENTED)
    monkeypatch.setattr(ab, "BROKEN", broken)
    item = FOUND_ITEM.replace("at calc.py:2", "at .\\calc.py:2")
    marks = LEAD_MARKS.replace('"return a - b"', '"' + ACCENTED.strip() + '"')
    asked, sent, code, folder, _ = found_by_the_worker(
        tmp_path, monkeypatch, [marks], item=item, left=broken + ab.MUL)
    assert asked.count("planner.md") == 2 and asked.count("tester.md") == 2
    assert chr(0xE9) + "cart" in sent[3]
    assert code == stops.EXIT_OK
    assert ("runner", "already-broken") in ab.gate_names(folder)


def test_a_lead_the_run_cannot_pay_for_leaves_the_finding_and_goes_on(
        tmp_path):
    (tmp_path / "TASK.md").write_text(tl.SPEC, encoding="utf-8")
    (tmp_path / "calc.py").write_text(ab.BROKEN, encoding="utf-8")
    run = types.SimpleNamespace(
        lead="planner.md", workdir=str(tmp_path), start=None, kept=None,
        budget=types.SimpleNamespace(ahead=lambda n: ("cap", "over the cap")))
    found = [("add returns a minus b, TASK.md:3, calc.py:2",
              [("TASK.md:3", "calc.py:2")])]
    assert asking.finding_pass(run, "worker.md", found, {}, "r", None) == (
        None, "", "")
    assert ("TASK.md:3", "calc.py:2") in run.found


def test_a_finding_citing_no_spec_line_costs_no_lead_call(tmp_path,
                                                          monkeypatch):
    item = ("- add returns a minus b, at calc.py:2" + NL + "  fixed: no" + NL
            + "  test: none" + NL)
    asked, _, code, _, _ = found_by_the_worker(tmp_path, monkeypatch, [],
                                               item=item)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK


def test_a_finding_the_lead_decides_is_recorded_and_the_run_goes_on(
        tmp_path, monkeypatch):
    decided = "DECIDED 1: leave add as it is" + NL + "why: not this task" + NL
    asked, _, code, folder, project = found_by_the_worker(
        tmp_path, monkeypatch, [decided])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "reviewer.md", "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    assert "planner.md decided for worker.md: leave add as it is" in (
        project / "decisions.md").read_text(encoding="utf-8")


def test_a_finding_the_lead_escalates_parks(tmp_path, monkeypatch):
    asked, _, code, folder, _ = found_by_the_worker(
        tmp_path, monkeypatch, ["ESCALATE 1: the operator's call" + NL])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    assert "TASK.md:3" in ab.question(folder)


def test_a_lead_mark_whose_quote_is_not_on_the_code_line_parks(tmp_path,
                                                               monkeypatch):
    asked, _, code, folder, _ = found_by_the_worker(
        tmp_path, monkeypatch, [LEAD_MARKS.replace("a - b", "a * b")])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    assert "spec: breaks TASK.md:3" in ab.question(folder)


def test_a_lead_answer_in_no_taught_form_parks(tmp_path, monkeypatch):
    asked, _, code, _, _ = found_by_the_worker(
        tmp_path, monkeypatch, ["it is fine, I think" + NL])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP


def test_the_same_finding_from_a_later_step_costs_no_second_call(
        tmp_path, monkeypatch):
    asked, _, code, _, _ = found_by_the_worker(
        tmp_path, monkeypatch, [LEAD_MARKS],
        reviewer=tl.OK + handoff_with(FOUND_ITEM))
    assert asked.count("planner.md") == 2
    assert code == stops.EXIT_OK


REVIEW_ASKS = ("NEEDS: should add name its operands in the error?" + NL
               + "CITES:" + NL + "- TASK.md:3 - mul(a, b) returns a times b"
               + NL + "OPTIONS:" + NL + "- yes: name them" + NL
               + "- no: leave it" + NL)


def test_a_mark_proved_before_a_park_is_shown_fixed_on_the_resumed_leg(
        tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "BEFORE", ab.BROKEN)
    answers = {"planner.md": [ab.PLAN, "ESCALATE: the operator's call" + NL],
               "tester.md": [tl.TESTER + "SIBLING TEST: " + ab.SIBLING_ID
                             + NL],
               "worker.md": [tl.WORKER], "reviewer.md": [tl.OK],
               "reviewer-runs.md": [REVIEW_ASKS, tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py",
                             ab.with_sibling("add(2, 1) == 3"))],
              "worker.md": [("calc.py", ab.FIXED)]}
    asked, _, code, folder, _ = tl.run_it(tmp_path, monkeypatch,
                                          "build-feature", answers, writes)
    assert code == stops.EXIT_STOP
    assert ("tester.md", "sibling-red") in ab.gate_names(folder)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "build-feature", "--force", "--flows", str(tl.FLOWS),
        "--resume", folder.name, "--answer", "no: leave it"])
    assert engine.main() == stops.EXIT_OK
    [again] = [p for p in (tmp_path / "runs").iterdir()
               if p.is_dir() and p != folder]
    assert ("runner", "already-broken") in ab.gate_names(again)
