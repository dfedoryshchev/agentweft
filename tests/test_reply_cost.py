import json
import subprocess
import sys
import types

import httpx
import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.providers import cli_provider

USAGE = {"input_tokens": 2, "cache_creation_input_tokens": 8124,
         "cache_read_input_tokens": 12097, "output_tokens": 4,
         "output_tokens_details": {"thinking_tokens": 0},
         "service_tier": "standard"}


def result(**over):
    """a `claude -p --output-format json` answer, trimmed to what is read."""
    out = {"type": "result", "subtype": "success", "is_error": False,
           "result": "ok", "session_id": "305e1f31-0000-4000-8000-000000000000",
           "total_cost_usd": 0.0337497, "usage": dict(USAGE),
           "modelUsage": {"claude-sonnet-x": {"inputTokens": 2,
                                              "outputTokens": 4,
                                              "costUSD": 0.0337497}},
           "api_error_status": None, "stop_reason": "end_turn"}
    out.update(over)
    return json.dumps(out).encode("utf-8")


def claude(tier="", **opts):
    return providers.build(dict({"provider": "cli", "command": "claude"}, **opts),
                           tier=tier)


# what the answer carries


def test_a_json_answer_carries_its_text_usage_cost_session_and_model(fake_cli):
    fake_cli((0, result(), b""))
    r = claude().ask("say ok")
    assert r.text == "ok"
    assert r.usage.raw == USAGE
    assert r.cost == 0.0337497
    assert r.session == "305e1f31-0000-4000-8000-000000000000"
    assert r.model == "claude-sonnet-x"
    assert r.counted


def test_the_input_total_counts_the_cache_and_the_raw_split_is_kept(fake_cli):
    """anthropic's `input_tokens` leaves the cache out; the otel total puts it
    back in, so the two numbers differ by exactly the cache."""
    fake_cli((0, result(), b""))
    u = claude().ask("say ok").usage
    assert u.input_tokens == 2 + 8124 + 12097
    assert u.output_tokens == 4
    assert u.cache_read_input_tokens == 12097
    assert u.cache_creation_input_tokens == 8124
    assert u.reasoning_output_tokens == 0
    assert u.as_otel() == {"gen_ai.usage.input_tokens": 20223,
                           "gen_ai.usage.output_tokens": 4,
                           "gen_ai.usage.cache_read.input_tokens": 12097,
                           "gen_ai.usage.cache_creation.input_tokens": 8124,
                           "gen_ai.usage.reasoning.output_tokens": 0}


def test_cache_fields_left_out_count_as_none_used(fake_cli):
    fake_cli((0, result(usage={"input_tokens": 7, "output_tokens": 3}), b""))
    u = claude().ask("x").usage
    assert (u.input_tokens, u.output_tokens) == (7, 3)
    assert u.cache_read_input_tokens == 0
    assert u.reasoning_output_tokens is None
    assert "gen_ai.usage.reasoning.output_tokens" not in u.as_otel()


def test_an_answer_from_two_models_names_both(fake_cli):
    fake_cli((0, result(modelUsage={"b-model": {}, "a-model": {}}), b""))
    assert claude().ask("x").model == "a-model, b-model"


def test_an_answer_with_no_usage_block_says_it_was_not_counted(fake_cli):
    fake_cli((0, result(usage=None, total_cost_usd=None, modelUsage={}), b""))
    r = claude().ask("x")
    assert r.text == "ok"
    assert r.usage is None and r.cost is None and r.model is None
    assert not r.counted


# how it is asked


def test_the_prompt_goes_on_stdin_and_the_answer_is_asked_for_as_json(fake_cli):
    cli = fake_cli((0, result(), b""))
    claude().ask("say ok")
    call = cli.calls[0]
    assert call["argv"] == ["claude", "-p", "--output-format", "json"]
    assert call["stdin"] == b"say ok"


def test_a_session_is_never_carried_on(fake_cli):
    """a resumed session's total already includes the earlier calls, so one
    answer would be charged for work another answer was charged for."""
    cli = fake_cli((0, result(), b""))
    claude(tier="high").ask("x")
    argv = cli.calls[0]["argv"]
    for flag in ("--resume", "-r", "--continue", "-c", "--session-id"):
        assert flag not in argv


def test_a_tier_reaches_the_cli_as_a_model(fake_cli, monkeypatch):
    monkeypatch.setenv("MODEL_HIGH", "x")
    cli = fake_cli((0, result(), b""))
    claude(tier="high").ask("hi")
    assert cli.calls[0]["argv"][-2:] == ["--model", "x"]


def test_a_tier_with_nothing_behind_it_reads_the_one_model(fake_cli, monkeypatch):
    monkeypatch.delenv("MODEL_LOW", raising=False)
    monkeypatch.setenv("MODEL", "the-only-one")
    cli = fake_cli((0, result(), b""))
    claude(tier="low").ask("hi")
    assert cli.calls[0]["argv"][-2:] == ["--model", "the-only-one"]


def test_a_model_named_in_the_block_wins_over_the_tier(fake_cli, monkeypatch):
    monkeypatch.setenv("MODEL_HIGH", "x")
    cli = fake_cli((0, result(), b""))
    claude(tier="high", model="named").ask("hi")
    assert cli.calls[0]["argv"][-2:] == ["--model", "named"]


def test_no_model_anywhere_leaves_the_choice_to_the_cli(fake_cli, monkeypatch):
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("MODEL_MID", raising=False)
    cli = fake_cli((0, result(), b""))
    claude(tier="mid").ask("hi")
    assert "--model" not in cli.calls[0]["argv"]


@pytest.mark.parametrize("command", ["tools\\claude.cmd", "/usr/bin/claude",
                                     "CLAUDE.EXE"])
def test_claude_by_a_path_or_an_extension_is_still_claude(fake_cli, command):
    cli = fake_cli((0, result(), b""))
    providers.build({"provider": "cli", "command": command}).ask("x")
    assert cli.calls[0]["argv"][1:] == ["-p", "--output-format", "json"]


def test_another_command_keeps_plain_text_and_says_nothing_was_counted(fake_cli):
    """echo is handed `-p` and the prompt as it always was: what another
    command reads from stdin, or which flags it takes, is not ours to guess."""
    cli = fake_cli((0, b"-p hi\n", b""))
    r = providers.build({"provider": "cli", "command": "echo"}).ask("hi")
    assert cli.calls[0]["argv"] == ["echo", "-p", "hi"]
    assert cli.calls[0]["stdin"] is None
    assert r.text == "-p hi\n"
    assert r.usage is None and r.cost is None and r.session is None
    assert not r.counted


@pytest.mark.parametrize("stdout", [b"plain words, no json\n", b'"ok"', b"[1, 2]",
                                    b"{not json"])
def test_claude_answering_with_something_other_than_a_result_is_plain_text(
        fake_cli, stdout):
    fake_cli((0, stdout, b""))
    r = claude().ask("x")
    assert r.text == stdout.decode("utf-8")
    assert r.usage is None


def test_an_empty_result_is_no_answer_but_still_counted(fake_cli):
    fake_cli((0, result(result=""), b""))
    r = claude().ask("x")
    assert not r
    assert "empty" in r.detail
    assert r.usage.output_tokens == 4


# when it goes wrong


def test_an_error_result_keeps_what_it_cost(fake_cli):
    """the attempt that failed was still paid for."""
    fake_cli((1, result(is_error=True, subtype="success",
                        result="API Error: 529 overloaded", api_error_status=529),
              b""))
    r = claude().ask("x")
    assert not r
    assert "529 overloaded" in r.detail
    assert r.usage.raw == USAGE
    assert r.cost == 0.0337497
    assert r.session == "305e1f31-0000-4000-8000-000000000000"
    assert r.retryable is True


def test_an_error_result_with_no_usage_says_so_rather_than_zero(fake_cli):
    fake_cli((1, result(is_error=True, subtype="error_during_execution",
                        result=None, usage=None, total_cost_usd=None), b""))
    r = claude().ask("x")
    assert not r
    assert "error_during_execution" in r.detail
    assert r.usage is None and r.cost is None
    assert r.retryable is None


@pytest.mark.parametrize("status,again", [(429, True), (500, True), (401, False),
                                          (400, False)])
def test_the_status_behind_an_error_says_whether_to_go_again(fake_cli, status,
                                                             again):
    fake_cli((1, result(is_error=True, result="API Error", api_error_status=status),
              b""))
    assert claude().ask("x").retryable is again


def test_an_error_flagged_in_a_zero_exit_is_still_an_error(fake_cli):
    fake_cli((0, result(is_error=True, subtype="error_max_turns", result=None), b""))
    r = claude().ask("x")
    assert not r
    assert "error_max_turns" in r.detail


def test_a_failure_with_no_json_keeps_the_old_detail(fake_cli):
    fake_cli((1, b"", b"Invalid API key\n"))
    r = claude().ask("x")
    assert r.detail == "Invalid API key"
    assert r.usage is None


def test_a_timeout_is_worth_going_again(fake_cli):
    fake_cli((subprocess.TimeoutExpired("claude", 5), b"", b""))
    r = claude().ask("x", timeout=5)
    assert r.detail == "timed out after 5s"
    assert r.retryable is True and r.usage is None


def test_a_missing_binary_is_not(fake_cli):
    fake_cli((FileNotFoundError(), b"", b""))
    r = claude().ask("x")
    assert "not on PATH" in r.detail
    assert r.retryable is False


def test_a_command_the_system_will_not_start_is_an_answer_not_a_crash(fake_cli):
    """Windows refuses a command line over ~32k characters with an OSError,
    and a command that is not claude still gets the prompt in argv."""
    fake_cli((OSError(206, "The filename or extension is too long"), b"", b""))
    r = providers.build({"provider": "cli", "command": "echo"}).ask("x" * 40000)
    assert "too long" in r.detail
    assert r.retryable is False


# text that is not ascii


def test_non_ascii_both_ways_survives_a_cp1252_machine(fake_cli):
    said = "\u2013 \u6f22\u5b57 caf\u00e9"
    cli = fake_cli((0, result(result="back: " + said), b""))
    r = claude().ask("ask: " + said)
    assert r.text == "back: " + said
    assert cli.calls[0]["stdin"] == ("ask: " + said).encode("utf-8")


def test_bytes_that_are_not_utf8_do_not_lose_the_answer(fake_cli):
    fake_cli((0, b"half \xff then the rest", b""))
    r = providers.build({"provider": "cli", "command": "echo"}).ask("x")
    assert r.text.startswith("half ") and r.text.endswith(" then the rest")


FAKE_CLAUDE = r"""
import json, sys
prompt = sys.stdin.buffer.read().decode("utf-8")
sys.stdout.buffer.write(json.dumps({
    "type": "result", "is_error": False, "result": prompt[-11:] + " \u2013 ok",
    "session_id": "s-%d" % len(prompt), "total_cost_usd": 0.5,
    "usage": {"input_tokens": len(prompt), "output_tokens": 1},
    "argv": sys.argv[1:]}, ensure_ascii=False).encode("utf-8"))
"""


def test_a_prompt_past_the_windows_command_line_limit_reaches_a_real_process(
        tmp_path, monkeypatch):
    """a real child process, not the fake: the encoding and the stdin handoff
    are only proven where an operating system sits in between."""
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")

    def run(argv, **kw):
        return subprocess.run([sys.executable, str(script)] + argv[1:], **kw)

    monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
        run=run, TimeoutExpired=subprocess.TimeoutExpired))
    prompt = "x" * 100000 + "tail \u6f22\u5b57 end"
    r = claude().ask(prompt, timeout=60)
    assert r.text == "tail \u6f22\u5b57 end \u2013 ok"
    assert r.session == "s-" + str(len(prompt))
    assert r.usage.input_tokens == len(prompt)


# the api provider


class Answered(object):
    def __init__(self, status, body):
        self.status_code = status
        self.body = body
        self.text = json.dumps(body)

    def json(self):
        return self.body


def api(monkeypatch, status, body):
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("MODEL", "m")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: Answered(status, body))
    return providers.build({"provider": "api", "url": "https://example.invalid"})


def test_the_api_answer_keeps_the_usage_it_was_sent(monkeypatch):
    usage = {"input_tokens": 10, "output_tokens": 5,
             "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0}
    r = api(monkeypatch, 200, {"model": "m-2", "content": [{"text": "hi"}],
                               "usage": usage}).ask("x")
    assert r.text == "hi"
    assert r.usage.raw == usage
    assert r.usage.input_tokens == 110
    assert r.model == "m-2"
    assert r.cost is None


def test_an_api_answer_with_no_usage_says_it_was_not_counted(monkeypatch):
    r = api(monkeypatch, 200, {"content": [{"text": "hi"}]}).ask("x")
    assert r.text == "hi"
    assert r.usage is None and not r.counted


@pytest.mark.parametrize("status,again", [(429, True), (529, True), (400, False),
                                          (401, False)])
def test_an_api_refusal_says_whether_to_go_again(monkeypatch, status, again):
    r = api(monkeypatch, status, {"error": "no"}).ask("x")
    assert not r
    assert r.retryable is again


def test_an_api_call_that_timed_out_is_worth_going_again(monkeypatch):
    p = api(monkeypatch, 200, {})

    def late(*a, **kw):
        raise httpx.ReadTimeout("read timed out")

    monkeypatch.setattr(httpx, "post", late)
    r = p.ask("x")
    assert "timed out" in r.detail
    assert r.retryable is True and r.usage is None


def test_the_fake_reports_nothing_and_says_so():
    r = providers.build({"provider": "fake", "reply": "VERDICT: ok"}).ask("x")
    assert r.text == "VERDICT: ok"
    assert r.usage is None and not r.counted
