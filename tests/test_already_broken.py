"""a spec line the code already breaks for a sibling path is fixed test-first,
never stopped on and never extended.

a plan may mark a behaviour `spec: breaks <spec line>, already at <file>:<line>
"<quote>"`. the runner checks the quote is on that line of the code as the
run found it, and the plan carries a behaviour `fix: <spec line> for <the
sibling path>`; then the mark does not stop the run. the test writer names
the sibling's test on a `SIBLING TEST:` line, and the runner runs it alone
on the code as the run found it: red is the proof the line is already
broken there, and the handoff lists it first among the defects fixed beside
the change. green, or no such line, and the mark is a plain `breaks` that
parks as it always did.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.runner import ruling, stops

import test_lead as tl

NL = chr(10)
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = ("def add(a, b):" + NL + "    return a + b" + NL + NL + NL
         + "def mul(a, b):" + NL + "    return a * b" + NL)
MARK = 'spec: breaks TASK.md:3, already at calc.py:2 "return a - b"'
PLAN = NL.join(["- behaviour: mul(2, 3) is 6", "  file: calc.py",
                "  " + MARK,
                "- behaviour: fix: TASK.md:3 for add, which returns a minus b",
                "  file: calc.py", "  spec: allows TASK.md:3", ""])
SIBLING_ID = "tests/test_mul.py::test_add_sibling"


def with_sibling(sibling):
    return (tl.TEST + NL + NL + "def test_add_sibling():" + NL
            + "    from calc import add" + NL + NL + "    assert " + sibling
            + NL)


def run(tmp_path, monkeypatch, plan=PLAN, sibling="add(2, 1) == 3",
        tester=tl.TESTER + "SIBLING TEST: " + SIBLING_ID + NL):
    monkeypatch.setattr(tl, "BEFORE", BROKEN)
    answers = {"planner.md": [plan], "tester.md": [tester],
               "worker.md": [tl.WORKER], "reviewer.md": [tl.OK],
               "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py", with_sibling(sibling))],
              "worker.md": [("calc.py", FIXED)]}
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, writes)


def test_the_second_form_holds_only_with_its_quote_on_the_code_line(
        tmp_path):
    (tmp_path / "calc.py").write_text(BROKEN, encoding="utf-8")
    (tmp_path / "TASK.md").write_text(tl.SPEC, encoding="utf-8")
    assert ruling.already_at(MARK, str(tmp_path)) == ("TASK.md:3", "calc.py:2")
    assert ruling.already_at(MARK.replace("a - b", "a * b"),
                             str(tmp_path)) is None
    assert ruling.already_at("spec: breaks TASK.md:3", str(tmp_path)) is None


def test_a_line_already_broken_for_a_sibling_is_fixed_test_first(
        tmp_path, monkeypatch):
    asked, _, code, folder, _ = run(tmp_path, monkeypatch)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", tl.RETRO]
    assert code == stops.EXIT_OK
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    beside = handoff.split("## found beside the change")[1].split(NL + "## ")[0]
    first = beside.strip().split(NL)[0]
    assert first.startswith("- runner: TASK.md:3 already broken at calc.py:2")
    assert "fixed, shown by " + SIBLING_ID in first
    assert "red on the start commit" in (folder / "gates.md").read_text(
        encoding="utf-8")


def test_a_sibling_test_green_on_the_start_tree_parks_as_a_break(
        tmp_path, monkeypatch):
    asked, _, code, folder, _ = run(tmp_path, monkeypatch,
                                    sibling="add(2, 1) == 1")
    assert asked == ["planner.md", "tester.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert "passes on the code as the run found it" in question
    assert MARK in question


def test_no_sibling_test_named_parks_as_a_break(tmp_path, monkeypatch):
    asked, _, code, folder, _ = run(tmp_path, monkeypatch, tester=tl.TESTER)
    assert asked == ["planner.md", "tester.md"]
    assert code == stops.EXIT_STOP
    assert "names no SIBLING TEST" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_the_second_form_with_no_fix_planned_parks_as_today(tmp_path,
                                                            monkeypatch):
    plan = NL.join(PLAN.split(NL)[:3]) + NL
    asked, _, code, _, _ = run(tmp_path, monkeypatch, plan=plan)
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP


def test_a_quote_not_on_the_cited_code_line_parks_as_today(tmp_path,
                                                           monkeypatch):
    asked, _, code, _, _ = run(tmp_path, monkeypatch,
                               plan=PLAN.replace("a - b\"", "a / b\""))
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP
