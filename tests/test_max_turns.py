"""every `claude` call is started with `--max-turns`, a runaway guard and not
a budget: a step still calling tools at the limit is stopped, once, and the
run says which guard stopped it."""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.providers import cli_provider
from agentweft.runner import engine, stops

from test_trace import a_flow, answer, every_line, no_waiting


def turns_in(argv):
    return argv[argv.index("--max-turns") + 1] if "--max-turns" in argv \
        else None


RUNAWAY = (1, json.dumps({"type": "result", "subtype": "error_max_turns",
                          "is_error": True, "session_id": "s-1",
                          "num_turns": 51, "total_cost_usd": 0.4,
                          "usage": {"input_tokens": 9, "output_tokens": 3}})
           .encode("utf-8"), b"")


def test_a_claude_call_is_held_to_fifty_turns_unless_told_otherwise(
        monkeypatch):
    monkeypatch.delenv("AGENTWEFT_MAX_TURNS", raising=False)
    assert turns_in(cli_provider.CliProvider().argv("x")[0]) == "50"
    monkeypatch.setenv("AGENTWEFT_MAX_TURNS", "12")
    assert turns_in(cli_provider.CliProvider().argv("x")[0]) == "12"
    assert turns_in(cli_provider.CliProvider(max_turns=30).argv("x")[0]) \
        == "30"
    assert turns_in(cli_provider.CliProvider(max_turns=0).argv("x")[0]) \
        is None


def test_a_warm_call_and_a_command_that_is_not_claude_get_no_limit(
        monkeypatch):
    monkeypatch.delenv("AGENTWEFT_MAX_TURNS", raising=False)
    p = cli_provider.CliProvider()
    assert turns_in(p.argv("x", tools_used=False)[0]) is None
    assert turns_in(cli_provider.CliProvider(command="mycli")
                    .argv("x")[0]) is None


@pytest.mark.parametrize("said", [-1, "many", True, 2.5])
def test_a_limit_that_is_not_a_whole_number_is_refused(said):
    with pytest.raises(ValueError, match="max_turns"):
        cli_provider.CliProvider(max_turns=said)


def test_a_flow_with_a_bad_limit_stops_before_anything_is_asked(
        tmp_path, monkeypatch, fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "bad", ["worker"],
           tail="provider:\n  provider: cli\n  max_turns: many\n")
    cli = fake_cli(answer("should not be asked\n"))
    assert engine.main() == 1
    assert cli.calls == []
    assert "max_turns should be a whole number" in capsys.readouterr().out


def test_a_call_stopped_at_the_limit_is_not_gone_again_and_says_why(
        monkeypatch, fake_cli):
    monkeypatch.delenv("AGENTWEFT_MAX_TURNS", raising=False)
    fake_cli(RUNAWAY)
    r = cli_provider.CliProvider().ask("x")
    assert not r and r.retryable is False
    assert "--max-turns 50" in r.detail and "runaway" in r.detail
    assert r.usage is not None and r.cost == 0.4


def turned(text, turns):
    code, out, err = answer(text)
    said = json.loads(out.decode("utf-8"))
    said["num_turns"] = turns
    return code, json.dumps(said).encode("utf-8"), err


def test_a_step_line_says_how_many_turns_its_calls_took(
        tmp_path, monkeypatch, fake_cli):
    no_waiting(monkeypatch)
    a_flow(tmp_path, monkeypatch, "counted", ["worker", "reviewer"])
    fake_cli(turned("done\n", 7), answer("VERDICT: ok\n"))
    assert engine.main() == 0
    worker, reviewer = every_line(tmp_path)
    assert worker["turns"] == 7
    assert "turns" not in reviewer


def test_a_carried_on_call_s_turns_are_not_taken_for_its_own():
    said = cli_provider.carried_on({"num_turns": 9, "total_cost_usd": 0.5},
                                   {"from": "s-0", "cost": 0.2})
    assert "num_turns" not in said


def test_a_step_that_runs_away_stops_the_run_after_one_go(
        tmp_path, monkeypatch, fake_cli):
    monkeypatch.delenv("AGENTWEFT_MAX_TURNS", raising=False)
    no_waiting(monkeypatch)
    a_flow(tmp_path, monkeypatch, "runaway", ["worker", "reviewer"])
    cli = fake_cli(RUNAWAY, answer("VERDICT: ok\n"))
    code = engine.main()
    assert len(cli.calls) == 1
    assert turns_in(cli.calls[0]["argv"]) == "50"
    assert code == stops.exit_code(stops.EXCEPTION)
    [line] = every_line(tmp_path)
    assert "--max-turns 50" in (line.get("why") or "")
    assert line["cost"] == 0.4 and line["tokens"]["output"] == 3
    assert line["turns"] == 51
