"""a case can say which steps the run took, not only what it handed back.

what a step says is the model's; which steps ran, where each one sent the work
and what every gate said is the runner's, and that is what is held here. it is
read off the run's steps.jsonl, the record the golden runs are compared on.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.evals import __main__ as evals_main
from agentweft.evals import harness, recording, steps
from agentweft.providers import fake_provider
from agentweft.runner import engine, prompts

REPO = Path(__file__).resolve().parent.parent
FLOW = "weekly-digest"
DIGEST = ("VERDICT: ok\n\n## what changed\n- a.md | changed | x\n\n"
          "## needs me\n- b.md | needs-me | y\n")
CHATTY = DIGEST + "\nhere is the digest\n"
PLAN = ("TASK: a.md\nLIST: changed\nWHY: x\nFILES:\n- a.md\n\n"
        "TASK: b.md\nLIST: needs-me\nWHY: y\nFILES:\n- b.md\n")
WHOLE = ["planner.md", "worker.md", "merge.md", "reviewer.md"]


def nothing_is_called(monkeypatch):
    def ask(self, prompt, timeout=None):
        raise AssertionError("a replayed case called its provider")
    monkeypatch.setattr(fake_provider.FakeProvider, "ask", ask)


@pytest.fixture
def root(tmp_path, monkeypatch):
    flows = tmp_path / "flows"
    shutil.copytree(REPO / "flows" / FLOW, flows / FLOW)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    evals = tmp_path / "evals"
    monkeypatch.setattr(harness, "ROOT", evals)
    monkeypatch.setattr(harness, "LAST", evals / ".last.json")
    return tmp_path


def a_case(root, expect, reply=DIGEST, name="case"):
    case = root / "evals" / FLOW / "cases" / name
    shutil.copytree(REPO / "evals" / FLOW / "cases" / "busy-week" / "inbox",
                    case / "inbox")
    provider = {"provider": "fake"}
    if reply is not None:
        provider["reply"] = reply
        provider["replies"] = {"planner.md": PLAN}
    (case / "case.yaml").write_text(yaml.safe_dump(
        {"inbox": "inbox", "provider": provider,
         "expect": dict({"invariants": "all"}, **expect)}), encoding="utf-8")
    return case


def without_merge(root):
    """the flow as it would read with its merge step deleted."""
    path = root / "flows" / FLOW / "flow.yaml"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec["steps"] = [s for s in spec["steps"] if s["role"] != "merge"]
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")


def replayed(case, monkeypatch):
    """record the case, then score it from the recording alone."""
    out = harness.run_flow_for(FLOW, harness.load_case(case), record=True)
    assert out[2].startswith(recording.PREFIX) is False
    nothing_is_called(monkeypatch)
    loaded = harness.load_case(case)
    assert loaded["recording"] is not None
    ran = harness.run_flow_for(FLOW, loaded)
    return harness.score(engine.config(FLOW), *ran, steps=ran.steps,
                         expect=loaded["expect"])


def failed(scored):
    return [(r["invariant"], r["detail"]) for r in scored["rows"]
            if r["ok"] is False]


def test_a_case_whose_flow_skipped_a_step_it_asserts_fails_naming_it(
        root, monkeypatch):
    case = a_case(root, {"steps": {"match": "superset", "path": WHOLE}})
    without_merge(root)
    assert failed(replayed(case, monkeypatch)) == [
        ("the steps it took (superset)", "missing merge.md")]


def test_the_same_case_on_the_whole_flow_passes(root, monkeypatch):
    case = a_case(root, {"steps": {"match": "superset", "path": WHOLE}})
    scored = replayed(case, monkeypatch)
    assert failed(scored) == []
    assert ("the steps it took (superset)", True) in [
        (r["invariant"], r["ok"]) for r in scored["rows"]]


def test_the_command_prints_the_step_and_the_mode(root, monkeypatch, capsys):
    a_case(root, {"steps": {"match": "superset", "path": WHOLE}})
    without_merge(root)
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, "--record", "--no-save"])
    assert evals_main.main() == 0
    nothing_is_called(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, "--no-save"])
    capsys.readouterr()
    assert evals_main.main() == 0
    printed = capsys.readouterr().out
    assert "FAIL the steps it took (superset) - missing merge.md" in printed


def test_subset_holds_a_run_that_stopped_to_what_it_may_have_run(
        root, monkeypatch):
    """the fake's own answer plans nothing, so the run stops at the fanned
    step: nothing ran past it but the retro, which is what subset asks."""
    case = a_case(root, {"steps": {"match": "subset",
                                   "path": ["planner.md", "worker.md",
                                            "retro.md"]}},
                  reply=None)
    rows = failed(replayed(case, monkeypatch))
    assert [r for r in rows if r[0].startswith("the steps")] == []


def test_subset_fails_a_run_that_went_on_past_the_reference(root,
                                                            monkeypatch):
    case = a_case(root, {"steps": {"match": "subset",
                                   "path": ["planner.md", "worker.md",
                                            "retro.md"]}})
    assert failed(replayed(case, monkeypatch)) == [
        ("the steps it took (subset)",
         "ran outside the reference: merge.md ok -> reviewer.md, "
         "reviewer.md ok  PASS length  PASS regex  PASS quote")]


def test_a_case_can_assert_the_gate_that_failed(root, monkeypatch):
    want = {"steps": {"match": "superset", "path": [
        "reviewer.md gate failed  PASS length  FAIL regex"]}}
    rows = failed(replayed(a_case(root, want, reply=CHATTY), monkeypatch))
    assert [r for r in rows if r[0].startswith("the steps")] == []


def test_a_gate_asserted_to_fail_that_passed_fails_the_case(root,
                                                           monkeypatch):
    want = {"steps": {"match": "superset", "path": [
        "reviewer.md gate failed  PASS length  FAIL regex"]}}
    assert failed(replayed(a_case(root, want), monkeypatch)) == [
        ("the steps it took (superset)",
         "missing reviewer.md gate failed  PASS length  FAIL regex")]


def test_strict_holds_the_order_and_the_outcomes(root, monkeypatch):
    want = {"steps": {"match": "strict", "path": [
        "planner.md ok -> worker.md", "worker.md ok", "merge.md",
        "reviewer.md ok  PASS length  PASS regex", "retro.md ok"]}}
    assert failed(replayed(a_case(root, want), monkeypatch)) == []


def test_the_number_of_calls_is_asserted(root, monkeypatch):
    assert failed(replayed(a_case(root, {"calls": 6}), monkeypatch)) == []


def test_a_wrong_number_of_calls_fails_the_case(root, monkeypatch):
    assert failed(replayed(a_case(root, {"calls": 4}), monkeypatch)) == [
        ("it made 4 calls", "it made 6")]


def test_a_mode_that_does_not_exist_fails_the_case_and_says_the_four(
        root, monkeypatch):
    want = {"steps": {"match": "mostly", "path": WHOLE}}
    assert failed(replayed(a_case(root, want), monkeypatch)) == [
        ("the steps it took (mostly)",
         "no match mode mostly. there is strict, unordered, subset, superset")]


def test_a_case_that_asserts_no_steps_scores_as_it_did(root, monkeypatch):
    rows = replayed(a_case(root, {}), monkeypatch)["rows"]
    assert [r["invariant"] for r in rows] == [
        "the run got to the end", "no file appears in two lists",
        "needs me is at most 5 lines", "every line names a file"]


@pytest.mark.parametrize("golden,reply", [("pass", DIGEST),
                                          ("gate-fail", CHATTY)])
def test_a_scored_run_records_the_path_its_golden_run_does(root, golden,
                                                           reply):
    case = harness.load_case(a_case(root, {}, reply=reply))
    ran = harness.run_flow_for(FLOW, case)
    want = json.loads((REPO / "tests" / "golden" / FLOW / (golden + ".json"))
                      .read_bytes().decode("utf-8"))["path"]
    assert [l["seq"] for l in ran.steps] == list(range(1, len(want) + 1))
    assert [steps.said(l) for l in ran.steps] == [
        p.split(" ", 1)[1] for p in want]


PATH = ["planner.md ok -> worker.md", "worker.md ok -> merge.md",
        "merge.md ok -> reviewer.md",
        "reviewer.md ok  PASS length  PASS regex"]


@pytest.mark.parametrize("mode,want,why", [
    ("strict", WHOLE, ""),
    ("strict", ["worker.md", "planner.md", "merge.md", "reviewer.md"],
     "step 1 is planner.md ok -> worker.md, want worker.md"),
    ("strict", WHOLE[:3],
     "took 4 steps, want 3: ran outside the reference: "
     "reviewer.md ok  PASS length  PASS regex"),
    ("unordered", list(reversed(WHOLE)), ""),
    ("unordered", WHOLE + ["verify.md"], "missing verify.md"),
    ("unordered", WHOLE[:2],
     "ran outside the reference: merge.md ok -> reviewer.md, "
     "reviewer.md ok  PASS length  PASS regex"),
    ("superset", ["reviewer.md", "planner.md"], ""),
    ("superset", ["verify.md"], "missing verify.md"),
    ("subset", WHOLE + ["verify.md"], ""),
    ("subset", WHOLE[1:], "ran outside the reference: "
     "planner.md ok -> worker.md"),
])
def test_the_four_modes(mode, want, why):
    assert steps.match(mode, want, PATH) == why


def test_an_item_stops_only_at_a_whole_word():
    assert steps.match("superset", ["reviewer"], PATH) == "missing reviewer"
    assert steps.match("superset", ["reviewer.md ok  PASS"], PATH) == ""


def test_the_narrower_item_is_matched_first():
    """an item that says more is matched before one that says less, so the
    broad one does not take the only pass the narrow one could have."""
    path = ["reviewer.md redo -> worker.md", "reviewer.md ok"]
    assert steps.match("unordered", ["reviewer.md", "reviewer.md ok"],
                       list(reversed(path))) == ""
    assert steps.match("unordered", ["reviewer.md", "reviewer.md ok"],
                       path) == ""


def test_a_pass_counts_once():
    assert steps.match("superset", ["worker.md", "worker.md"], PATH) == (
        "missing worker.md")


def test_the_shipped_quiet_week_case_replays_to_full_marks(monkeypatch):
    path = [p for p in harness.cases_for(FLOW) if p.name == "quiet-week"][0]
    case = harness.load_case(path)
    nothing_is_called(monkeypatch)
    ran = harness.run_flow_for(FLOW, case)
    scored = harness.score(engine.config(FLOW), *ran, steps=ran.steps,
                           expect=case["expect"])
    assert failed(scored) == []
    assert scored["passed"] == scored["checked"] == 6
