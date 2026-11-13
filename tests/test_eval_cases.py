"""every shipped recorded case, replayed, and what each one is there to catch:
take the behaviour away and its case scores worse. each case's ending is
written here as well as in its own gold, so a case re-recorded with its gold
rewritten to match fails until the word here is changed too, and a new
recorded case fails until its ending is written here (None: the case names
no outcome, and is held to getting to the end)."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.evals import harness, recording
from agentweft.guardrails import testedits
from agentweft.guardrails.gates import base as gates_base
from agentweft.guardrails.gates import command_gate, redfirst_gate
from agentweft.guardrails.gates import redtest_gate
from agentweft.providers import fake_provider
from agentweft.runner import ruling, wrongtest


def shipped():
    """-> (flow, case) for every case under the evals tree with a recording,
    read from the tree so a case added there is replayed without being
    listed here."""
    found = [(flow.name, path.name)
             for flow in sorted(harness.ROOT.iterdir())
             if (flow / "cases").is_dir()
             for path in harness.cases_for(flow.name)
             if (path / recording.FILE).is_file()]
    if not found:
        raise RuntimeError("no recorded case under " + str(harness.ROOT))
    return found


OUTCOMES = {
    ("build-feature", "added-option"): "done",
    ("build-feature", "never-cached"): "stopped: spec conflict",
    ("build-feature", "wrong-test"): "done",
    ("build-feature", "wrong-test-after-code"): "done",
    ("fix-with-test", "breaks-a-start-test"): "stopped: gate failed",
    ("fix-with-test", "clean-fix"): "done",
    ("fix-with-test", "green-without-fix"): "stopped: gate failed",
    ("fix-with-test", "question-priced-on-the-other"): "done",
    ("fix-with-test", "rewrites-a-start-test"): "needs you: ruling",
    ("fix-with-test", "spec-conflict"): "stopped: spec conflict",
    ("fix-with-test", "spec-declined"): "refused (spec cited)",
    ("fix-with-test", "supplied-test"): "done",
    ("repo-audit", "two-files"): "done",
    ("weekly-digest", "busy-week"): None,
    ("weekly-digest", "quiet-week"): None,
}
SHIPPED = shipped()


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


@pytest.mark.parametrize("flow,name", sorted(set(SHIPPED) | set(OUTCOMES)))
def test_a_shipped_case_replays_offline_and_keeps_every_promise(
        flow, name, monkeypatch):
    assert (flow, name) in OUTCOMES, "no ending written here for this case"
    assert (flow, name) in SHIPPED, "no recorded case by this name"
    word = OUTCOMES[(flow, name)]
    case = case_of(flow, name)
    assert case["recording"] is not None
    assert case["expect"]["steps"]["match"] == "strict"
    assert case["expect"].get("outcome") == word
    ending = ("it ended " + word if word is not None
              else "the run got to the end")
    nothing_is_called(monkeypatch)
    r = scored(flow, case)
    assert failed(r) == []
    assert r["passed"] == r["checked"]
    assert ending in [row["invariant"] for row in r["rows"]]


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
    for flow, name in (("fix-with-test", "spec-conflict"),
                       ("build-feature", "never-cached")):
        r = scored(flow, live(flow, name))
        assert r["passed"] < r["checked"], name
        assert any(f.startswith("it ended stopped: spec conflict")
                   for f in failed(r)), name


def test_without_reading_a_cited_refusal_the_declined_case_drops(monkeypatch):
    real = ruling.asked_of

    def unread(*a, **k):
        said = real(*a, **k)
        return None if said and said[0] == ruling.DECLINED else said
    monkeypatch.setattr(ruling, "asked_of", unread)
    r = scored("fix-with-test", live("fix-with-test", "spec-declined"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("it ended refused (spec cited)")
               for f in failed(r))


def test_without_the_suite_gate_the_broken_start_test_case_drops(
        monkeypatch):
    def passes(self, text):
        return gates_base.Result("command", True, "exit 0")
    monkeypatch.setattr(command_gate.CommandGate, "run", passes)
    r = scored("fix-with-test", live("fix-with-test", "breaks-a-start-test"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("the steps it took") for f in failed(r))


def test_without_the_test_edit_check_the_rewritten_start_test_case_drops(
        monkeypatch):
    monkeypatch.setattr(testedits, "changes", lambda start: [])
    r = scored("fix-with-test", live("fix-with-test", "rewrites-a-start-test"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("it ended needs you: ruling") for f in failed(r))


def test_priced_on_the_whole_size_the_recommended_no_code_case_drops(
        monkeypatch):
    monkeypatch.setattr(ruling, "costs_nothing",
                        lambda size, recommend: ruling.no_code(size))
    r = scored("fix-with-test", live("fix-with-test",
                                     "question-priced-on-the-other"))
    assert r["passed"] < r["checked"]
    assert any(f.startswith("it ended done") for f in failed(r))


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
