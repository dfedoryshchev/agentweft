"""a go that ran out of time, or was ended, still cost something.

the cli prints its usage only when it answers. a go it never answered for is
read back from the session transcript the cli wrote, and when there is none it
is estimated from the prompt and says so. either way it is in the step's total
and the run's, never a null that the sum quietly drops.
"""
import json
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.guardrails import prices
from agentweft.guardrails.budget import Budget
from agentweft.providers import cli_provider
from agentweft.runner import engine, handoff, state, trace

from test_prices import TABLE, a_flow, answer
from test_trace import no_waiting

PROMPT = "# worker\n\ndo it.\n"


@pytest.fixture
def table(tmp_path, monkeypatch):
    path = tmp_path / "prices.yaml"
    path.write_text(TABLE, encoding="utf-8")
    monkeypatch.setenv("PRICES", str(path))
    return prices.load(path)


def claude():
    return providers.build({"provider": "cli", "command": "claude",
                            "model": "m-small"})


def said(kind, session, **over):
    out = {"type": kind, "sessionId": session}
    out.update(over)
    return json.dumps(out)


def assistant(session, msg, usage, model="m-small", piece="text"):
    return said("assistant", session, requestId="req-" + msg,
                message={"id": msg, "model": model, "role": "assistant",
                         "content": [{"type": piece, "text": "..."}],
                         "usage": usage})


FIRST = {"input_tokens": 3, "cache_creation_input_tokens": 1000,
         "cache_read_input_tokens": 20000, "output_tokens": 50,
         "cache_creation": {"ephemeral_5m_input_tokens": 1000,
                            "ephemeral_1h_input_tokens": 0}}
SECOND = {"input_tokens": 2, "cache_creation_input_tokens": 0,
          "cache_read_input_tokens": 21000, "output_tokens": 30,
          "cache_creation": {"ephemeral_5m_input_tokens": 0,
                             "ephemeral_1h_input_tokens": 0}}


def a_session(folder, session, prompt, *more):
    """the file the cli keeps for one session, one json object a line."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = [said("user", session,
                 message={"role": "user", "content": prompt})] + list(more)
    (folder / (session + ".jsonl")).write_text("\n".join(rows) + "\n",
                                               encoding="utf-8")


def timing_out(monkeypatch, write=None):
    """a cli call that runs out of time, having written `write` first."""
    def call(argv, stdin=None, cwd=None, timeout=None, done=None, env=None):
        if write:
            write()
        return cli_provider.Ran(None, "", "", 0, timed_out=True)
    monkeypatch.setattr(cli_provider, "call", call)


def test_a_timed_out_go_with_a_transcript_is_priced_from_it(
        tmp_path, monkeypatch, table):
    home = tmp_path / "projects"
    monkeypatch.setattr(handoff, "PROJECTS", home)

    def write():
        # another session in the same minute, on another prompt, is not it
        a_session(home / "elsewhere", "s-other", "something else",
                  assistant("s-other", "m-9", FIRST))
        # the cli writes a line per content block, each with the same usage
        a_session(home / "here", "s-7", PROMPT,
                  assistant("s-7", "m-1", FIRST),
                  assistant("s-7", "m-1", FIRST, piece="tool_use"),
                  assistant("s-7", "m-2", SECOND))

    timing_out(monkeypatch, write)
    r = claude().ask(PROMPT, timeout=600)
    assert not r and "timed out" in r.detail
    assert getattr(r, "metered", None) == "transcript"
    assert r.usage is not None
    assert (r.usage.input_tokens, r.usage.output_tokens) == (42005, 80)
    assert r.usage.cache_read_input_tokens == 41000
    assert r.usage.cache_creation_input_tokens == 1000
    assert r.session == "s-7" and r.model == "m-small"
    tried = trace.Attempt()
    tried.replies = [r]
    tried.retries = {"transient": 1}
    got = trace.facts([tried], "m-small")
    # 5 input + 1000 5m writes + 41000 reads + 80 output on m-small
    assert got["cost"] == 0.005755
    assert got.get("cost_from") == {"transcript": 1}
    assert got["tokens"]["counted"] is True


def test_a_timed_out_go_with_no_transcript_is_estimated_and_says_so(
        tmp_path, monkeypatch, table):
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "nothing")
    timing_out(monkeypatch)
    prompt = "x" * 4000000
    r = claude().ask(prompt, timeout=600)
    assert getattr(r, "metered", None) == "estimate"
    assert r.usage is None
    tried = trace.Attempt()
    tried.replies = [r]
    tried.retries = {"transient": 1}
    got = trace.facts([tried], "m-small")
    # a million input tokens at 1 per million, nothing out
    assert got["cost"] == 1.0
    assert got.get("cost_from") == {"estimate": 1}
    assert got["tokens"] == {"counted": False}
    b = Budget(prices=table)
    b.charge(prompt, r, error="transient", model="m-small")
    assert b.unreported == {}
    assert (b.estimated_calls, b.calls) == (1, 1)
    assert b.money()["estimated"] is True
    assert b.money()["usd"] == 1.0


def test_a_retried_step_counts_its_first_go_and_totals_every_go(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "slow", ["worker"], "m-small")
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "nothing")
    no_waiting(monkeypatch)
    cli_ = fake_cli((subprocess.TimeoutExpired("claude", 600), b"", b""),
                    answer("did it\n", "m-small", 0.005, input_tokens=1000,
                           output_tokens=800))
    assert engine.main() == 0
    [folder] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    [step] = [json.loads(l) for l in (folder / trace.FILE)
              .read_text(encoding="utf-8").split("\n") if l]
    assert step["retries"] == {"transient": 1}
    sent = cli_.calls[0]["stdin"].decode("utf-8")
    first = round((len(sent) // 4) / 1000000.0, 6)
    assert step["cost"] == round(0.005 + first, 6)
    assert step.get("cost_from") == {"provider": 1, "estimate": 1}
    journal = (state.RUNS / "journal.md").read_text(encoding="utf-8")
    assert "2 calls" in journal and "failed call" not in journal
