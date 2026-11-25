"""a reply the cli printed without the model having run is not an answer.

a prompt hook in the person's own cli settings that refuses the prompt makes
`claude -p` exit 0 with `is_error: false`, `num_turns: 0`, no output token,
and the hook's notice, the prompt echoed under it, as `result`. taken as the
step's answer, the prompt's own answer template reads as claims, and a
send-back only gets the same text again."""
import json
import sys
import types

sys.path.insert(0, ".")
from agentweft.runner import engine

from test_grant import claude
from test_trace import CLAUDE, a_flow, answer, folders

FIRST = "UserPromptSubmit operation blocked by hook: caf" + chr(0xE9) + " check"
NOTICE = (FIRST + "\n[a prompt check]: this prompt is not allowed here.\n\n"
          "Original prompt: # worker\n\ndo it.\n\n"
          "CONFLICT: <file>:<line> \"<the line>\"\n")


def blocked(turns=0, output=0, **more):
    """what the cli prints when a prompt hook refused the prompt."""
    data = {"type": "result", "subtype": "success", "is_error": False,
            "result": NOTICE, "num_turns": turns, "total_cost_usd": 0,
            "duration_ms": 62, "session_id": "s-blocked",
            "usage": {"input_tokens": 0, "output_tokens": output,
                      "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0},
            "modelUsage": {}}
    data.update(more)
    return 0, json.dumps(data).encode("utf-8"), b""


def test_a_reply_no_model_made_is_not_an_answer(fake_cli):
    fake_cli(blocked())
    r = claude().ask("go")
    assert r.text == ""
    assert r.retryable is False
    assert r.detail == ("the cli answered without the model (0 turns, 0"
                        " output tokens): " + FIRST)


def test_a_real_answer_stays_an_answer(fake_cli):
    fake_cli(answer("did it\n"))
    assert claude().ask("go").text == "did it\n"


def test_a_turn_count_the_cli_did_not_print_as_a_number_is_no_zero(fake_cli):
    code, out, err = answer("did it\n")
    for turns in (None, "0", False):
        data = json.loads(out)
        if turns is not None:
            data["num_turns"] = turns
        fake_cli((code, json.dumps(data).encode("utf-8"), err))
        assert claude().ask("go").text == "did it\n", turns


def test_zero_turns_with_output_counted_is_still_the_model_s(fake_cli):
    fake_cli(blocked(turns=0, output=12))
    assert claude().ask("go").text == NOTICE


def test_an_error_with_zero_turns_stays_the_error_it_was(fake_cli):
    fake_cli(blocked(is_error=True, result="API Error: 500"))
    r = claude().ask("go")
    assert r.text == "" and "without the model" not in r.detail
    assert "API Error: 500" in r.detail


def test_a_resumed_call_no_model_answered_is_not_an_answer():
    code, out, _ = blocked()
    ran = types.SimpleNamespace(returncode=code, killed=False)
    r = claude().read(json.loads(out), ran,
                      carry={"from": "s-0", "cost": 0.3, "models": None})
    assert r.text == "" and r.retryable is False
    assert "without the model" in r.detail


def test_a_run_whose_step_the_cli_answered_alone_stops_without_a_send_back(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "blocked", [
        "worker\nmust_produce: \"FAILS:\""], tail=CLAUDE)
    cli = fake_cli(blocked(), blocked(), blocked(), blocked())
    assert engine.main() != 0
    workers = [c for c in cli.calls if b"# worker" in (c["stdin"] or b"")]
    assert len(workers) == 1, [c["stdin"][:40] for c in cli.calls]
    [run] = folders(tmp_path)
    handoff = (run / "handoff.md").read_text(encoding="utf-8")
    assert "without the model" in handoff
    assert "<file>:<line>" not in handoff
