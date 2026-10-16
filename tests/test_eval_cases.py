"""the shipped cases of the flows that write code, replayed, and what each one
is there to catch: take the behaviour away and its case scores worse."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.evals import harness
from agentweft.guardrails.gates import base as gates_base
from agentweft.guardrails.gates import redfirst_gate
from agentweft.guardrails.gates import redtest_gate
from agentweft.providers import fake_provider
from agentweft.runner import ruling, wrongtest

CASES = [("fix-with-test", "clean-fix", "done"),
         ("fix-with-test", "green-without-fix", "stopped: gate failed"),
         ("fix-with-test", "spec-conflict", "stopped: spec conflict"),
         ("build-feature", "wrong-test", "done"),
         ("build-feature", "wrong-test-after-code", "done"),
         ("repo-audit", "two-files", "done")]


def case_of(flow, name):
    path = [p for p in harness.cases_for(flow) if p.name == name][0]
    return harness.load_case(path)


def scored(flow, case):
    ran = harness.run_flow_for(flow, case)
    return harness.score(runner.config(flow), *ran, steps=ran.steps,
                         expect=case["expect"])


def failed(r):
    return [row["invariant"] + " - " + row["detail"] for row in r["rows"]
            if row["ok"] is False]


def nothing_is_called(monkeypatch):
    def ask(self, prompt, timeout=None):
        raise AssertionError("a replayed case called its provider")
    monkeypatch.setattr(fake_provider.FakeProvider, "ask", ask)


@pytest.mark.parametrize("flow,name,word", CASES)
def test_a_shipped_case_replays_offline_and_keeps_every_promise(
        flow, name, word, monkeypatch):
    case = case_of(flow, name)
    assert case["recording"] is not None
    assert case["expect"]["outcome"] == word
    assert case["expect"]["steps"]["match"] == "strict"
    nothing_is_called(monkeypatch)
    r = scored(flow, case)
    assert failed(r) == []
    assert r["passed"] == r["checked"]
    assert "it ended " + word in [row["invariant"] for row in r["rows"]]


def live(flow, name):
    return dict(case_of(flow, name), recording=None)


def test_without_the_red_first_gate_the_green_test_case_drops(monkeypatch):
    def passes(self, text):
        return gates_base.Result("red-first", True, "not run")
    monkeypatch.setattr(redfirst_gate.RedFirstGate, "run", passes)
    r = scored("fix-with-test", live("fix-with-test", "green-without-fix"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("it ended stopped: gate failed") for f in failed(r))


def test_without_the_conflict_check_the_conflict_case_drops(monkeypatch):
    monkeypatch.setattr(ruling, "conflict_of", lambda *a, **k: None)
    r = scored("fix-with-test", live("fix-with-test", "spec-conflict"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("it ended stopped: spec conflict")
               for f in failed(r))


def test_without_the_wrong_test_send_back_the_wrong_test_case_drops(
        monkeypatch):
    monkeypatch.setattr(wrongtest, "judge", lambda *a, **k: None)
    r = scored("build-feature", live("build-feature", "wrong-test"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("the steps it took") for f in failed(r))


def test_a_red_proof_run_beside_the_code_drops_the_after_code_case(
        monkeypatch):
    monkeypatch.setattr(redtest_gate.RedTestGate, "product_moved",
                        lambda self: False)
    r = scored("build-feature", live("build-feature", "wrong-test-after-code"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("it ended done - it ended stopped: gate failed")
               for f in failed(r))


def row(expect, stopped="", record=()):
    rows = harness.score(runner.config("fix-with-test"), "", None, stopped,
                         steps=record, expect=expect)["rows"]
    return rows[0]


def test_a_case_that_names_its_outcome_is_held_to_it():
    stop = [{"step": "patcher.md", "outcome": "conflict", "to": None,
             "gates": [], "cause": "conflict"}]
    got = row({"outcome": "stopped: spec conflict"},
              "spec conflict at patcher.md: which one holds?", stop)
    assert got["invariant"] == "it ended stopped: spec conflict"
    assert got["ok"] is True
    got = row({"outcome": "done"},
              "spec conflict at patcher.md: which one holds?", stop)
    assert got["ok"] is False
    assert got["detail"] == ("it ended stopped: spec conflict - spec "
                             "conflict at patcher.md: which one holds?")
    assert row({"outcome": "done"})["ok"] is True
    # a run that stopped with no step to blame still did not end done
    got = row({"outcome": "done"}, "recording is stale: x.md prompt changed")
    assert got["ok"] is False


def test_a_case_that_names_no_outcome_still_has_to_get_to_the_end():
    got = row({}, "gate red-test failed at worker.md")
    assert got["invariant"] == "the run got to the end"
    assert got["ok"] is False
