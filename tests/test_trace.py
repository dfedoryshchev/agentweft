import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner.handoff import Handoff


def test_a_handoff_carries_its_own_timing():
    h = Handoff("worker", "text", meta={"seconds": 1.2, "cached": False})
    assert h.meta["seconds"] == 1.2


def test_meta_defaults_to_empty_rather_than_none():
    h = Handoff("worker", "text")
    assert h.meta == {}


def test_a_step_records_seconds_and_provider(monkeypatch):
    spec = runner.config("summarise-and-check")
    from agentweft.roles import resolver
    by_role = resolver.resolve(spec.raw, runner.flow_path("summarise-and-check"))
    run = runner.Run("summarise-and-check", spec, by_role)
    monkeypatch.setattr(runner, "call", lambda *a, **k: ("VERDICT: ok", False))
    from agentweft.runner import engine
    monkeypatch.setattr(engine, "call", lambda *a, **k: ("VERDICT: ok", False))
    out = run.step("worker.md")
    assert "seconds" in out.meta
    assert out.meta["provider"]
