"""a reviewer names one wrong implementation the tests as they are would let
pass, and the step that wrote the tests adds the case that fails it.

the shipped build-feature flow's first reviewer has `on_missed: tester`: a
`WOULD PASS:` line under its verdict goes to the tester, at the end of its
prompt, once a run; `none` goes nowhere. canned answers, a real pytest in a
git repo, as `test_wrong_test.py` runs them.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.flow import reader
from agentweft.flow import spec as flowspec
from agentweft.runner import stops

from test_wrong_test import (AFTER, OK, PLAN, RIGHT, TESTER, WORKER, NL,
                             run_it)

try:
    from agentweft.runner import wouldpass
except ImportError:
    wouldpass = None

FLOWS = Path(__file__).resolve().parents[1] / "flows"
RETRO = "retro.md"
WRONG_WAY = "mul returns a + b, which the one test passes since 2 + 2 is 2 * 2"
CASE = "mul(2, 5) is 10"
NAMED = ("VERDICT: ok" + NL + "WOULD PASS: " + WRONG_WAY + NL + "CATCH: "
         + CASE + NL + NL + WORKER)
NAMED_NONE = "VERDICT: ok" + NL + "WOULD PASS: none" + NL + NL + WORKER
MORE = RIGHT + NL + NL + ("def test_mul_two_five():" + NL
                          + "    from calc import mul" + NL + NL
                          + "    assert mul(2, 5) == 10" + NL)


def test_the_line_and_its_case_are_read_off_their_own_lines():
    assert wouldpass is not None, "no agentweft.runner.wouldpass"
    assert wouldpass.read(NAMED) == (WRONG_WAY, CASE)
    assert wouldpass.read(NAMED_NONE) is None
    assert wouldpass.read(OK) is None
    assert wouldpass.read("VERDICT: ok" + NL + "WOULD PASS: x | y" + NL) \
        == ("x | y", "")


def test_the_shipped_reviewer_asks_for_one_and_sends_it_to_the_tester():
    flow = flowspec.load(reader.read((FLOWS / "build-feature" / "flow.yaml")
                                     .read_text(encoding="utf-8")))
    first = [s for s in flow.steps if s["role"] == "reviewer"][0]
    assert first.get("on_missed") == "tester"
    words = (FLOWS / "build-feature" / "reviewer.md").read_text(
        encoding="utf-8")
    assert "WOULD PASS:" in words and "CATCH:" in words


def test_a_named_wrong_implementation_goes_to_the_tester_with_its_case(
        tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER, TESTER],
               "worker.md": [WORKER], "reviewer.md": [NAMED, NAMED],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT),
                            ("tests/test_mul.py", MORE)],
              "worker.md": [("calc.py", AFTER), ("", "")]}
    asked, sent, code, folder, project = run_it(tmp_path, monkeypatch,
                                                answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    reviewer = sent[3]
    assert "WOULD PASS:" in reviewer
    again = sent[4]
    assert "# tester" in again
    assert again.rstrip().endswith("CATCH: " + CASE)
    assert WRONG_WAY in again
    assert WRONG_WAY in sent[5]
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    second = gates.split("## tester.md")[2].split("##")[0]
    assert "PASS red-test - red" in second
    steps = (folder / "steps.jsonl").read_text(encoding="utf-8")
    assert '"to": "tester.md"' in steps


def test_none_goes_nowhere(tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER], "reviewer.md": [NAMED_NONE],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER)]}
    asked, _, code, _, _ = run_it(tmp_path, monkeypatch, answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK


def test_a_redo_is_a_redo_and_the_line_waits(tmp_path, monkeypatch):
    redo = "VERDICT: redo" + NL + "WOULD PASS: " + WRONG_WAY + NL \
        + "CATCH: " + CASE + NL + NL + WORKER
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER], "reviewer.md": [redo, NAMED_NONE],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER), ("", "")]}
    asked = run_it(tmp_path, monkeypatch, answers, writes)[0]
    assert asked[:5] == ["planner.md", "tester.md", "worker.md",
                         "reviewer.md", "worker.md"]
    assert asked.count("tester.md") == 1
