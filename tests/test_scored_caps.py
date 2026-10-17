"""a scored run is held to the flow's caps, the same as a run of main."""
import sys

sys.path.insert(0, ".")
from agentweft.evals import steps as took
from agentweft.runner import engine
from test_run_cache import FAKE, a_flow


def test_a_scored_run_stops_at_the_flows_call_cap(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "capped", ["worker", "reviewer"],
           tail=FAKE + "max_calls: 1\n")
    trail = tmp_path / "trail"
    trail.mkdir()
    out, budget, stopped = engine.run_once(
        "capped", provider={"provider": "fake", "reply": "VERDICT: ok\n"},
        trail=trail)
    assert budget.calls == 1
    assert stopped.startswith("over budget at reviewer.md: call cap: 1 of 1")
    assert took.ended(took.read(trail), stopped) == "needs you: budget"


def test_a_scored_run_under_its_cap_goes_to_the_end(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "roomy", ["worker", "reviewer"],
           tail=FAKE + "max_calls: 2\n")
    out, budget, stopped = engine.run_once(
        "roomy", provider={"provider": "fake", "reply": "VERDICT: ok\n"})
    assert (budget.calls, stopped) == (2, "")
