"""`--keep-warm`: a `continue: resume` step's session that has waited close
to the end of its cache's lifetime gets one cheap call that keeps the cache
and nothing else. off unless the run asks for it."""
import json
import subprocess
import sys
import threading
import time

import pytest
from test_continue import (EARLIER, FIRST, NOTES, REDO, USED, WHOLE_COST,
                           claude, flag, replay, result)

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.guardrails.budget import Budget
from agentweft.providers import cli_provider
from agentweft.runner import engine, state, warm

__all__ = ["replay"]


# the warm call itself


def test_a_warm_call_is_a_low_effort_fork_that_is_not_kept(fake_cli):
    cli = fake_cli((0, result(USED, WHOLE_COST), b""))
    r = claude().warm(dict(EARLIER))
    argv = cli.calls[0]["argv"]
    assert argv[argv.index("--resume"):argv.index("--resume") + 3] == \
        ["--resume", "s-1", "--fork-session"]
    assert "--no-session-persistence" in argv
    assert "--session-id" not in argv
    assert flag(argv, "--effort") == "low"
    assert r.cost == pytest.approx(WHOLE_COST - EARLIER["cost"])


def test_a_warm_call_keeps_the_steps_tools_and_may_use_none_of_them(
        fake_cli):
    cli = fake_cli((0, result(USED, WHOLE_COST), b""), (0, b"{}", b""))
    p = providers.build({"provider": "cli", "command": "claude"},
                        grant=["read", "shell"])
    p.warm(dict(EARLIER))
    argv = cli.calls[0]["argv"]
    step, _ = p.argv("x")
    assert flag(argv, "--tools") == flag(step, "--tools")
    hooks = json.loads(flag(argv, "--settings"))["hooks"]["PreToolUse"]
    assert [h["matcher"] for h in hooks] == ["*"]
    assert hooks[0]["hooks"][0]["args"][-1] == cli_provider.NO_TOOLS


def test_the_no_tools_hook_refuses_every_tool():
    done = subprocess.run([sys.executable, "-I", "-c", cli_provider.NO_TOOLS],
                          input="{}", capture_output=True, text=True)
    assert done.returncode == 2
    assert done.stderr


def test_a_warm_call_in_flight_ends_when_the_run_stops_warming(monkeypatch):
    monkeypatch.setattr(cli_provider, "subprocess", subprocess)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    began = time.monotonic()
    ran = cli_provider.call([sys.executable, "-c",
                             "import time; time.sleep(30)"], stop=stop)
    assert ran.timed_out
    assert time.monotonic() - began < 10


def test_the_warmer_hands_its_stop_to_the_call(fake_cli, monkeypatch):
    seen = {}

    def call(argv, stdin=None, cwd=None, timeout=None, done=None, env=None,
             stop=None):
        seen["stop"] = stop
        return cli_provider.Ran(0, result(USED, WHOLE_COST).decode(), "", 0)

    monkeypatch.setattr(cli_provider, "call", call)
    stop = threading.Event()
    claude().warm(dict(EARLIER), stop=stop)
    assert seen["stop"] is stop


# when a session is warmed


class Waiting(object):
    """what the warmer reads off a run."""

    def __init__(self, sessions, warmed):
        self.sessions = sessions
        self.busy = set()
        self.budget = Budget()
        self.lock = threading.Lock()
        self.warmed = warmed

    def provider_for(self, step):
        return self.warmed


class Warmed(object):
    name = "cli"

    def __init__(self, hold=False):
        self.asked = []
        self.hold = hold

    def warm(self, carry, timeout=None, stop=None):
        self.asked.append(carry["from"])
        if self.hold:
            stop.wait(30)
        return providers.base.Reply("ok", usage=providers.base.Usage(
            {"input_tokens": 1, "output_tokens": 1}))

    def asks_for(self):
        return None


def waiting(lifetime=warm.LIFETIME, hold=False):
    p = Warmed(hold)
    run = Waiting({"worker.md": {"id": "s-1", "usage": None, "cost": 0,
                                 "at": 0, "lifetime": lifetime}}, p)
    return run, p, warm.Warmer(run)


DUE = warm.LIFETIME - warm.MARGIN


def test_a_session_is_not_warmed_before_its_cache_would_lapse():
    run, p, w = waiting()
    w.tick(now=DUE - 1)
    assert p.asked == []


def test_a_session_waiting_past_its_cache_lifetime_less_the_margin_is_warmed():
    run, p, w = waiting()
    w.tick(now=DUE)
    assert p.asked == ["s-1"]
    assert run.budget.calls == 1
    assert run.sessions["worker.md"]["warmed"] == 1
    assert run.sessions["worker.md"]["at"] == DUE


def test_a_cache_already_lapsed_is_left_to_the_steps_own_next_call():
    run, p, w = waiting()
    w.tick(now=warm.LIFETIME)
    assert p.asked == []


def test_warming_stops_at_its_cap():
    run, p, w = waiting()
    for n in range(1, warm.MOST + 3):
        w.tick(now=n * DUE)
    assert len(p.asked) == warm.MOST


def test_a_run_at_its_cap_warms_nothing():
    run, p, w = waiting()
    run.budget.max_calls = 1
    run.budget.calls = 1
    w.tick(now=DUE)
    assert p.asked == []


def test_a_step_in_a_call_is_not_warmed():
    run, p, w = waiting()
    run.busy.add("worker.md")
    w.tick(now=DUE)
    assert p.asked == []


@pytest.mark.parametrize("lifetime", [warm.SHORT, None])
def test_a_short_or_unknown_cache_lifetime_is_never_warmed(lifetime):
    run, p, w = waiting(lifetime)
    for now in range(0, warm.LIFETIME * 2, 30):
        w.tick(now=now)
    assert p.asked == []


@pytest.mark.parametrize("usage, before, lifetime", [
    ({"cache_creation": {"ephemeral_1h_input_tokens": 9,
                         "ephemeral_5m_input_tokens": 0}}, None,
     warm.LIFETIME),
    ({"cache_creation": {"ephemeral_1h_input_tokens": 0,
                         "ephemeral_5m_input_tokens": 9}}, None, warm.SHORT),
    ({"input_tokens": 3}, None, None),
    ({"cache_creation": {"ephemeral_1h_input_tokens": 0,
                         "ephemeral_5m_input_tokens": 0}}, warm.LIFETIME,
     warm.LIFETIME)])
def test_a_sessions_cache_lifetime_is_read_from_where_it_wrote(
        usage, before, lifetime):
    assert warm.lifetime(usage, before) == lifetime


def test_stopping_waits_for_the_warm_call_in_flight_and_its_charge(
        monkeypatch):
    monkeypatch.setattr(warm, "EVERY", 0.01)
    run, p, w = waiting(hold=True)
    monkeypatch.setattr(warm.time, "time", lambda: DUE)
    w.start()
    deadline = time.monotonic() + 10
    while not p.asked and time.monotonic() < deadline:
        time.sleep(0.01)
    w.stop()
    assert p.asked == ["s-1"]
    assert run.budget.calls == 1
    assert not w.thread.is_alive()


def test_warming_is_off_unless_the_run_asks_for_it():
    assert not warm.wanted(["run.py", "resumer"])
    assert warm.wanted(["run.py", "resumer", warm.FLAG])


# in a run


ANSWERS = {"worker.md": [FIRST, NOTES],
           "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}


@pytest.mark.parametrize("args, started", [([], 0), ([warm.FLAG], 1)])
def test_a_run_warms_only_with_the_flag_and_stops_before_it_writes_down(
        replay, monkeypatch, args, started):
    seen = []

    def start(self):
        seen.append(self)
        warm.STARTED.append(self)
        return self

    def stop(self):
        runs = [p for p in state.RUNS.iterdir() if p.is_dir()]
        seen.append(any((p / "handoff.md").exists() for p in runs))
        self.stopped.set()

    monkeypatch.setattr(warm.Warmer, "start", start)
    monkeypatch.setattr(warm.Warmer, "stop", stop)
    replay(ANSWERS, args=args)
    assert seen == ([] if not started else [seen[0], False])
    assert warm.STARTED == []


def test_a_step_is_busy_while_its_call_runs_and_its_session_is_timed(
        replay, monkeypatch):
    busy = []
    real = engine.Run.ask

    def ask(self, prompt, step, used):
        busy.append(sorted(self.busy))
        return real(self, prompt, step, used)

    monkeypatch.setattr(engine.Run, "ask", ask)
    replay(ANSWERS)
    assert busy[0] == ["worker.md"]
    assert busy[1] == []
    from test_continue import last_manifest
    kept = last_manifest()["sessions"]["worker.md"]
    assert kept["warmed"] == 0 and kept["at"] > 0
    assert "lifetime" in kept


def test_a_kept_session_knows_its_cache_lifetime_from_its_usage(
        replay, monkeypatch):
    import test_continue

    monkeypatch.setattr(test_continue, "PER_CALL", dict(
        test_continue.PER_CALL, cache_creation={
            "ephemeral_1h_input_tokens": 50,
            "ephemeral_5m_input_tokens": 0}))
    replay(ANSWERS)
    kept = test_continue.last_manifest()["sessions"]["worker.md"]
    assert kept["lifetime"] == warm.LIFETIME
