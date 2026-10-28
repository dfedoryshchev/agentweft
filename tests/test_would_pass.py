"""a reviewer names one wrong implementation the tests as they are would let
pass, and the step that wrote the tests adds the case that fails it.

the shipped build-feature flow's first reviewer has `on_missed: tester`: a
`WOULD PASS:` line under its verdict goes to the tester, at the end of its
prompt, once a run; `none` goes nowhere. canned answers, a real pytest in a
git repo, as `test_wrong_test.py` runs them.
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.flow import reader
from agentweft.flow import spec as flowspec
from agentweft.runner import stops, summary

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
# passes the one test there is and fails the case the reviewer names
SIX = AFTER.replace("return a * b", "return 6")


def lines(folder):
    return [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]


def won_of(folder):
    """-> (step, won) of each pass, as the handoff and the retro read them."""
    return [(p["step"], p["facts"]["won"]) for p in summary.passes_of(
        folder, {}, types.SimpleNamespace(steps=[]))]


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
              "worker.md": [("calc.py", SIX), ("calc.py", AFTER)]}
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


def test_a_reviewer_whose_case_fails_on_the_code_caught_it(tmp_path,
                                                          monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER, TESTER],
               "worker.md": [WORKER], "reviewer.md": [NAMED, NAMED],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT),
                            ("tests/test_mul.py", MORE)],
              "worker.md": [("calc.py", SIX), ("calc.py", AFTER)]}
    folder = run_it(tmp_path, monkeypatch, answers, writes)[3]
    said = lines(folder)
    reviewer = said[3]
    assert (reviewer["step"], reviewer["outcome"], reviewer["won"]) == (
        "reviewer.md", "routed", "none")
    assert said[4]["step"] == "tester.md"
    assert said[4]["case"] == {"seq": reviewer["seq"], "step": "reviewer.md",
                               "red": True}
    assert won_of(folder)[3] == ("reviewer.md", "caught")


def test_a_reviewer_whose_case_passes_on_the_code_caught_nothing(
        tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER, TESTER],
               "worker.md": [WORKER], "reviewer.md": [NAMED],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT),
                            ("tests/test_mul.py", MORE)],
              "worker.md": [("calc.py", AFTER)]}
    folder = run_it(tmp_path, monkeypatch, answers, writes)[3]
    said = lines(folder)
    reviewer = said[3]
    assert (reviewer["step"], reviewer["outcome"], reviewer["won"]) == (
        "reviewer.md", "routed", "none")
    assert said[4]["case"] == {"seq": reviewer["seq"], "step": "reviewer.md",
                               "red": False}
    assert won_of(folder)[3] == ("reviewer.md", "none")


def test_a_red_suite_alone_is_not_a_catch_the_case_has_to_fail_itself():
    from agentweft.guardrails.gates.base import Result

    broken = Result("command", False,
                    "ERROR tests/test_mul.py - SyntaxError: invalid syntax")
    case = {"seq": 3, "named": "reviewer.md"}
    assert wouldpass.held(case, [broken])["red"] is None
    assert wouldpass.held(case, [broken], alone=False)["red"] is False
    assert wouldpass.held(case, [broken], alone=True)["red"] is True
    assert wouldpass.held(case, [Result("command", True)], alone=True)[
        "red"] is False


def test_the_case_is_run_alone_and_only_a_failure_of_its_own_is_red(
        tmp_path):
    run = types.SimpleNamespace(fm=types.SimpleNamespace(steps=[]),
                                workdir=tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_red():" + NL + "    assert 1 == 2" + NL + NL
        + "def test_green():" + NL + "    assert 1 == 1" + NL,
        encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(
        "def test_x(:" + NL, encoding="utf-8")
    assert wouldpass.alone(run, ["tests/test_a.py::test_red"]) is True
    assert wouldpass.alone(run, ["tests/test_a.py::test_green"]) is False
    assert wouldpass.alone(run, ["tests/test_b.py::test_x"]) is False
    assert wouldpass.alone(run, ["tests/calc.test.ts"]) is None
    assert wouldpass.alone(run, []) is None


def test_a_case_added_inside_a_test_the_writer_wrote_first_is_a_case(
        tmp_path):
    import subprocess

    from agentweft.guardrails import snapshot

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c",
                        "user.email=t@t"] + list(args), check=True,
                       capture_output=True)

    (tmp_path / "calc.py").write_text(AFTER, encoding="utf-8")
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "start")
    start = snapshot.Snapshot(tmp_path)
    (tmp_path / "tests").mkdir()
    test = tmp_path / "tests" / "test_mul.py"
    test.write_text("def test_mul():" + NL + "    assert 2 * 2 == 4" + NL,
                    encoding="utf-8")
    (tmp_path / "tests" / "calc.test.js").write_text("one" + NL,
                                                     encoding="utf-8")
    before = wouldpass.ids(start)
    assert wouldpass.added(before, start) == []
    test.write_text("def test_mul():" + NL + "    assert 2 * 2 == 4" + NL
                    + "    assert 2 * 5 == 10" + NL, encoding="utf-8")
    (tmp_path / "tests" / "calc.test.js").write_text("one" + NL + "two" + NL,
                                                     encoding="utf-8")
    assert wouldpass.added(before, start) == ["tests/calc.test.js",
                                              "tests/test_mul.py::test_mul"]


def test_a_case_that_already_passes_does_not_send_the_worker_round_again(
        tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER, TESTER],
               "worker.md": [WORKER], "reviewer.md": [NAMED],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT),
                            ("tests/test_mul.py", MORE)],
              "worker.md": [("calc.py", AFTER)]}
    asked, sent, code, folder, _ = run_it(tmp_path, monkeypatch, answers,
                                          writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "tester.md", "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    assert WRONG_WAY not in sent[5]
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    second = gates.split("## tester.md")[2]
    assert "PASS red-test - red" in second
    assert "the case passes on the code as it is" in second
    steps = (folder / "steps.jsonl").read_text(encoding="utf-8")
    assert '"to": "reviewer-runs.md"' in steps


def no_case_added(tmp_path, monkeypatch, scored=False, then=RIGHT):
    """the tester's next go writes the tests it had, and adds no case; the
    go after it writes `then`."""
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER], "reviewer.md": [NAMED, OK],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT),
                            ("tests/test_mul.py", RIGHT),
                            ("tests/test_mul.py", then)],
              "worker.md": [("calc.py", AFTER)]}
    return run_it(tmp_path, monkeypatch, answers, writes, scored=scored)


def test_a_tester_that_adds_no_case_goes_back_once_and_never_skips_the_worker(
        tmp_path, monkeypatch):
    asked, sent, code, folder, _ = no_case_added(tmp_path, monkeypatch)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "tester.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    assert "added no case" in sent[5]
    assert WRONG_WAY in sent[5]
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    assert "the case passes on the code as it is" not in gates
    assert "no case added" in gates.split("## tester.md")[3]
    assert WRONG_WAY in sent[6]
    assert "added a case" not in sent[6]
    steps = (folder / "steps.jsonl").read_text(encoding="utf-8")
    assert "no case added" in steps


def test_a_tester_that_adds_the_case_when_sent_back_for_it_counts(
        tmp_path, monkeypatch):
    asked = no_case_added(tmp_path, monkeypatch, then=MORE)[0]
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "tester.md", "tester.md", "reviewer-runs.md", RETRO]


def test_a_scored_run_whose_tester_adds_no_case_never_skips_the_worker(
        tmp_path, monkeypatch):
    asked, sent, _, trail, _ = no_case_added(tmp_path, monkeypatch,
                                             scored=True)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "tester.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert "added no case" in sent[5]
    assert "added a case" not in sent[6]
    steps = (trail / "steps.jsonl").read_text(encoding="utf-8")
    assert "no case added" in steps


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
