"""how hard the model thinks: a level per tier, per role or per step, and one
level higher each time a step is sent back."""
import json
import sys

import httpx
import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.providers import api_provider, base, cli_provider
from agentweft.runner import engine

from test_trace import a_flow, answer, every_line, folders, no_waiting


def argv_efforts(calls):
    """-> the --effort each call was started with, None for none."""
    out = []
    for c in calls:
        argv = c["argv"]
        out.append(argv[argv.index("--effort") + 1] if "--effort" in argv
                   else None)
    return out


@pytest.fixture
def no_levels(monkeypatch):
    for key in ("EFFORT", "EFFORT_HIGH", "EFFORT_MID", "EFFORT_LOW",
                "CLAUDE_CODE_EFFORT_LEVEL"):
        monkeypatch.delenv(key, raising=False)


# where a level comes from


def test_nothing_set_sends_no_effort_and_the_line_says_the_default(
        tmp_path, monkeypatch, fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "plain", ["worker"])
    cli = fake_cli(answer("did it\n"))
    assert engine.main() == 0
    assert argv_efforts(cli.calls) == [None]
    [line] = every_line(tmp_path)
    assert line["effort"] == {"asked": "provider default", "base": None,
                              "raised": 0, "applies": True}


def test_a_tier_sets_the_effort_beside_the_model(tmp_path, monkeypatch,
                                                 fake_cli, no_levels):
    monkeypatch.setenv("EFFORT_LOW", "low")
    monkeypatch.setenv("EFFORT", "medium")
    a_flow(tmp_path, monkeypatch, "tiered", ["worker\nmodel: low", "reviewer"],
           tail="provider:\n  provider: cli\n")
    cli = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"))
    assert engine.main() == 0
    assert argv_efforts(cli.calls) == ["low", "medium"]


def test_the_provider_block_names_a_level_over_the_environment(
        monkeypatch, no_levels):
    monkeypatch.setenv("EFFORT_HIGH", "high")
    assert base.effort_for({"effort": "low", "tier": "high"}) == "low"
    assert base.effort_for({"tier": "high"}) == "high"
    assert base.effort_for({"tier": "mid"}) == ""


def test_the_run_gives_one_role_its_level_and_leaves_the_rest(
        tmp_path, monkeypatch, fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "two", ["worker", "reviewer"],
           args=["--effort-for", "reviewer=high"])
    cli = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"))
    assert engine.main() == 0
    assert argv_efforts(cli.calls) == [None, "high"]
    worker, reviewer = every_line(tmp_path)
    assert worker["effort"]["asked"] == "provider default"
    assert reviewer["effort"] == {"asked": "high", "base": "high",
                                  "raised": 0, "applies": True}


def test_a_level_the_run_does_not_know_is_refused_before_anything_is_asked(
        tmp_path, monkeypatch, fake_cli, no_levels, capsys):
    a_flow(tmp_path, monkeypatch, "typo", ["worker"],
           args=["--effort-for", "worker=hard"])
    cli = fake_cli(answer("should not be asked\n"))
    assert engine.main() == 1
    assert cli.calls == []
    assert "worker should be one of low, medium, high, xhigh, max" in \
        capsys.readouterr().out


def test_a_level_in_a_resumed_runs_file_is_refused_before_the_cli_is_asked(
        tmp_path, monkeypatch, fake_cli, no_levels, capsys):
    a_flow(tmp_path, monkeypatch, "edited", ["worker", "reviewer"],
           args=["--effort-for", "reviewer=high"])
    no_waiting(monkeypatch)
    fake_cli(answer("worked\n"), answer(""), answer(""), answer(""))
    engine.main()
    [first] = folders(tmp_path)
    (first / "efforts").write_text("reviewer=ultra", encoding="utf-8")
    cli = fake_cli(answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "edited", "--force",
                                      "--resume", first.name])
    assert engine.main() == 1
    assert cli.calls == []
    assert "reviewer should be one of low, medium, high, xhigh, max" in \
        capsys.readouterr().out


def test_a_step_and_the_flow_may_name_a_level():
    ok = {"name": "x", "steps": [{"role": "worker", "effort": "low"},
                                 {"role": "reviewer"}],
          "efforts": {"reviewer": "high"}}
    assert spec.check(ok) == []
    bad = {"name": "x", "steps": [{"role": "worker", "effort": "hard"}],
           "efforts": {"reviwer": "high"}}
    assert spec.check(bad) == [
        "step 0: effort should be one of low, medium, high, xhigh, max",
        "efforts: no role called reviwer. there is: worker"]


# a sent-back step thinks harder


def test_a_redo_runs_the_work_one_level_higher_and_the_judge_at_its_own(
        tmp_path, monkeypatch, fake_cli, no_levels):
    monkeypatch.setenv("EFFORT", "low")
    a_flow(tmp_path, monkeypatch, "again", ["worker", "reviewer"])
    cli = fake_cli(answer("first go\n"),
                   answer("VERDICT: redo\n\nthe total is off by one\n"),
                   answer("second go\n"),
                   answer("VERDICT: ok\n\nfine now\n"))
    assert engine.main() == 0
    assert argv_efforts(cli.calls) == ["low", "low", "medium", "low"]
    got = [(l["step"], l["effort"]["asked"], l["effort"]["raised"])
           for l in every_line(tmp_path)]
    assert got == [("worker.md", "low", 0), ("reviewer.md", "low", 0),
                   ("worker.md", "medium", 1), ("reviewer.md", "low", 0)]


def test_a_failed_gate_sends_the_step_back_one_level_higher(
        tmp_path, monkeypatch, fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "gated",
           ["worker\neffort: medium\ngates:\n  - gate: length\n"
            "    max_lines: 1", "reviewer"])
    cli = fake_cli(answer("one\ntwo\n"), answer("one\n"),
                   answer("VERDICT: ok\n"))
    assert engine.main() == 0
    assert argv_efforts(cli.calls) == ["medium", "high", None]
    lines = every_line(tmp_path)
    assert lines[1]["effort"] == {"asked": "high", "base": "medium",
                                  "raised": 1, "applies": True}


def test_a_scored_run_raises_a_sent_back_step_too(tmp_path, monkeypatch,
                                                 fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "gated",
           ["worker\neffort: low\ngates:\n  - gate: length\n    max_lines: 1",
            "reviewer"])
    cli = fake_cli(answer("one\ntwo\n"), answer("one\n"),
                   answer("VERDICT: ok\n"))
    out, _, stopped = engine.run_once("gated", trail=tmp_path / "trail")
    assert stopped == ""
    assert argv_efforts(cli.calls) == ["low", "medium", None]


def test_raising_stops_at_xhigh_and_max_is_only_asked_for_by_name():
    assert base.raised("low", 1) == "medium"
    assert base.raised("high", 2) == "xhigh"
    assert base.raised("xhigh", 1) == "xhigh"
    assert base.raised("max", 1) == "max"
    assert base.raised("low", 0) == "low"


def test_a_wrong_test_goes_back_to_its_writer_one_level_higher(
        tmp_path, monkeypatch, no_levels):
    import test_wrong_test as wt

    monkeypatch.setenv("EFFORT", "low")
    answers = {"planner.md": [wt.PLAN], "tester.md": [wt.TESTER],
               "worker.md": [wt.claim("tests/test_mul.py::test_mul"),
                             wt.WORKER],
               "reviewer.md": [wt.OK]}
    writes = {"tester.md": [("tests/test_mul.py", wt.WRONG),
                            ("tests/test_mul.py", wt.RIGHT)],
              "worker.md": [("", ""), ("calc.py", wt.AFTER)]}
    asked, _, _, folder, _ = wt.run_it(tmp_path, monkeypatch, answers, writes)
    assert asked[:4] == ["planner.md", "tester.md", "worker.md", "tester.md"]
    lines = [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").split("\n") if l.strip()]
    got = [(l["step"], l["effort"]["asked"]) for l in lines]
    assert got[:5] == [("planner.md", "low"), ("tester.md", "low"),
                       ("worker.md", "low"), ("tester.md", "medium"),
                       ("worker.md", "low")]


# what reaches the cli


def test_a_parent_effort_variable_does_not_reach_a_call_that_names_one(
        monkeypatch, no_levels):
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "max")
    p = cli_provider.CliProvider(effort="low")
    assert "CLAUDE_CODE_EFFORT_LEVEL" not in p.child_env()
    assert p.argv("x")[0][-2:] == ["--effort", "low"]


def test_a_recorded_live_run_hands_the_level_to_the_provider_it_wraps(
        no_levels):
    from agentweft.evals.recording import Recorder

    inner = cli_provider.CliProvider(effort="low")
    wrapped = Recorder(inner)
    assert wrapped.own_effort() == "low" and wrapped.chooses_effort()
    wrapped.going = "medium"
    assert inner.argv("x")[0][-2:] == ["--effort", "medium"]


def test_a_cli_answer_cut_off_at_its_cap_fails(monkeypatch, fake_cli,
                                               no_levels):
    cut = json.dumps({"type": "result", "is_error": False, "result": "half",
                      "stop_reason": "max_tokens", "session_id": "s",
                      "usage": {"input_tokens": 1, "output_tokens": 2}})
    fake_cli((0, cut.encode("utf-8"), b""))
    r = cli_provider.CliProvider().ask("x")
    assert not r and r.retryable is False
    assert "max_tokens" in r.detail
    assert r.usage is not None


def test_a_command_that_is_not_claude_records_effort_as_not_applied(
        tmp_path, monkeypatch, fake_cli, no_levels):
    monkeypatch.setenv("EFFORT", "low")
    a_flow(tmp_path, monkeypatch, "other", ["worker"],
           tail="provider:\n  provider: cli\n  command: mycli\n")
    cli = fake_cli((0, b"did it\n", b""))
    engine.main()
    assert "--effort" not in cli.calls[0]["argv"]
    assert every_line(tmp_path)[0]["effort"]["applies"] is False


# what reaches the api


class Sent(object):
    def __init__(self, reply):
        self.reply = reply
        self.body = None
        self.headers = None

    def post(self, url, json=None, timeout=None, headers=None):
        self.body, self.headers = json, headers
        return httpx.Response(200, json=self.reply)


def an_api(monkeypatch, reply, **opts):
    sent = Sent(reply)
    monkeypatch.setattr(api_provider.httpx, "post", sent.post)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("API_URL", "https://example.invalid/v1/messages")
    return api_provider.ApiProvider(model="m", **opts), sent


WHOLE = {"content": [{"type": "text", "text": "done"}],
         "stop_reason": "end_turn", "model": "m",
         "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_the_api_sends_the_effort_and_a_cap_to_think_in(monkeypatch,
                                                        no_levels):
    p, sent = an_api(monkeypatch, WHOLE, effort="high")
    assert p.ask("x").text == "done"
    assert sent.body["output_config"] == {"effort": "high"}
    assert sent.body["max_tokens"] == 64000
    assert sent.headers["anthropic-version"] == "2023-06-01"


def test_the_api_sends_no_effort_when_none_is_set(monkeypatch, no_levels):
    p, sent = an_api(monkeypatch, WHOLE)
    p.ask("x")
    assert "output_config" not in sent.body
    assert sent.body["max_tokens"] == 32000


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_an_api_answer_cut_off_or_declined_fails(monkeypatch, no_levels, stop):
    p, _ = an_api(monkeypatch, dict(WHOLE, stop_reason=stop))
    r = p.ask("x")
    assert not r and r.retryable is False
    assert stop in r.detail
    assert r.usage is not None


def test_a_step_sent_back_before_a_budget_stop_resumes_one_level_higher(
        tmp_path, monkeypatch, fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "paused",
           ["worker\neffort: medium\ngates:\n  - gate: length\n"
            "    max_lines: 1", "reviewer"],
           tail="provider:\n  provider: cli\n  command: claude\n"
                "max_calls: 1\n")
    cli = fake_cli(answer("one\ntwo\n"), answer("one\n"),
                   answer("VERDICT: ok\n"))
    engine.main()
    assert argv_efforts(cli.calls) == ["medium"]
    [first] = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())
    monkeypatch.setattr(sys, "argv", ["run.py", "paused", "--resume",
                                      first.name, "--max-calls", "3"])
    assert engine.main() == 0
    assert argv_efforts(cli.calls) == ["medium", "high", None]
    resumed = [l for l in every_line(tmp_path) if l["step"] == "worker.md"]
    assert resumed[-1]["effort"]["raised"] == 1
