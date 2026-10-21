"""`continue: resume`: a step carries on its own earlier session instead of
reading everything again from nothing.

the cli here is a fake that keeps sessions the way `claude` 2.1.301 was seen
to: `--session-id` names the session a call writes, `--resume <id>
--fork-session` writes a copy of the earlier session's transcript and then
the call's own rows, `usage` is the call's alone, and `modelUsage` and
`total_cost_usd` are the whole session's.
"""
import json
import sys
import types
import uuid

import httpx
import pytest
from conftest import answering

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.flow import spec
from agentweft.providers import api_provider, cli_provider
from agentweft.runner import (engine, handoff, manifest, prompts, resume,
                              state, summary)

WORKER = "write release notes under added and fixed."
REDO = "VERDICT: redo\n\nthe notes lost the fixed section\n"
NOTES = "## added\n- a switch\n\n## fixed\n- the export keeps every column\n"
FIRST = "## added\n- a switch\n"
PER_CALL = {"input_tokens": 100, "output_tokens": 20}
COST = 0.01
OUT_OF_CALLS = {"type": "result", "is_error": True,
                "result": "You've hit your usage limit",
                "api_error": "usage_limit_reached",
                "api_error_params": {"rate_limit_info": {
                    "resetsAt": 1893456000}},
                "total_cost_usd": 0,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "modelUsage": {}}


def flag(argv, name):
    return argv[argv.index(name) + 1] if name in argv else None


class Did(object):
    """an answer that also leaves rows in its session's transcript."""

    def __init__(self, say, rows=()):
        self.say = say
        self.rows = list(rows)


def ran(command, output, n):
    """-> the two transcript rows of one Bash call and what it printed."""
    return [{"type": "assistant", "message": {"id": "msg-run-" + n, "content": [
        {"type": "tool_use", "id": "toolu-" + n, "name": "Bash",
         "input": {"command": command}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu-" + n,
                 "content": output}]}}]


class Cli(object):
    """the claude process, answering each step from its list in turn and
    keeping every session it was asked to write; with `folder`, it writes
    each session's transcript there too."""

    def __init__(self, answers, folder=None):
        self.answers = answers
        self.calls = []
        self.whole = {}
        self.step = None
        self.folder = folder

    def transcript(self, session, rows):
        if self.folder is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / (session + ".jsonl")).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def rows_of(self, session):
        if self.folder is None or not session:
            return []
        path = self.folder / (session + ".jsonl")
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(
            encoding="utf-8").split("\n") if l.strip()]

    def run(self, argv, **kw):
        if argv[1:] == ["--version"]:
            return types.SimpleNamespace(returncode=0, stderr="",
                                         stdout="2.1.296 (Claude Code)\n")
        n = len([c for c in self.calls if c["step"] == self.step])
        self.calls.append({"step": self.step, "argv": list(argv),
                           "stdin": kw.get("input") or ""})
        answer = self.answers[self.step][n]
        if isinstance(answer, dict):
            return types.SimpleNamespace(returncode=1,
                                         stdout=json.dumps(answer), stderr="")
        if isinstance(answer, BaseException):
            raise answer
        did = answer if isinstance(answer, Did) else Did(answer)
        earlier = flag(argv, "--resume")
        base = self.whole.get(earlier, ({"inputTokens": 0,
                                         "outputTokens": 0}, 0))
        whole = {"inputTokens": base[0]["inputTokens"] + PER_CALL[
            "input_tokens"], "outputTokens": base[0]["outputTokens"]
            + PER_CALL["output_tokens"]}
        session = flag(argv, "--session-id") or str(uuid.uuid4())
        self.whole[session] = (whole, base[1] + COST)
        self.transcript(session, self.rows_of(earlier) + [
            {"type": "user", "message": {"content": kw.get("input") or ""}}]
            + did.rows + [{"type": "assistant", "message": {
                "id": "msg-" + session, "content": [
                    {"type": "text", "text": did.say}],
                "usage": dict(PER_CALL)}}])
        out = json.dumps({"type": "result", "is_error": False,
                          "result": did.say, "session_id": session,
                          "total_cost_usd": base[1] + COST,
                          "usage": dict(PER_CALL),
                          "modelUsage": {"model-one": whole}})
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")

    def of(self, step):
        return [c for c in self.calls if c["step"] == step]


def a_flow(root, worker_keys="    continue: resume\n    effort: low\n"):
    flow = root / "resumer"
    flow.mkdir(parents=True)
    (flow / "flow.yaml").write_text(
        "name: resumer\nsteps:\n  - role: worker\n    prompt: worker.md\n"
        + worker_keys + "  - role: reviewer\n    prompt: reviewer.md\n"
        "    on_redo: worker\ntimeout: 300\nretries: 1\n", encoding="utf-8")
    (flow / "instructions.md").write_text("write the notes, then review "
                                          "them.\n", encoding="utf-8")
    (flow / "worker.md").write_text(WORKER + "\n", encoding="utf-8")
    (flow / "reviewer.md").write_text("review the notes. first line: VERDICT:"
                                      " ok or VERDICT: redo.\n",
                                      encoding="utf-8")


@pytest.fixture
def replay(tmp_path, monkeypatch):
    """-> a function running the flow over the scripted cli, one leg per
    call, handing back the cli."""
    root = tmp_path / "flows"
    place = tmp_path / "place"
    place.mkdir()
    monkeypatch.chdir(place)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setenv("MODEL", "model-one")
    for key in prompts.ENV_KEYS:
        monkeypatch.setenv(key, "inbox")
    held = {}

    def go(answers=None, args=(), worker_keys=None, folder=None):
        if "cli" not in held:
            if worker_keys is None:
                a_flow(root)
            else:
                a_flow(root, worker_keys)
            if folder is not None:
                monkeypatch.setattr(handoff, "PROJECTS", str(folder.parent))
            held["cli"] = Cli(answers, folder)
            cli = held["cli"]
            real_step = engine.Run.step

            def step(self, name, *a, **kw):
                cli.step = name
                return real_step(self, name, *a, **kw)

            monkeypatch.setattr(engine.Run, "step", step)
            monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
                run=cli.run, TimeoutExpired=__import__("subprocess")
                .TimeoutExpired))
            monkeypatch.setattr(cli_provider, "call", answering(cli.run))
        monkeypatch.setattr(sys, "argv", ["run.py", "resumer", "--force"]
                            + list(args))
        engine.main()
        return held["cli"]
    return go


def last_manifest():
    return manifest.load(state.RUNS / resume.runs_for("resumer")[-1]).data


def lines():
    folder = state.RUNS / resume.runs_for("resumer")[-1]
    return [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").split("\n") if l.strip()]


# the flow file


def test_continue_is_fresh_or_resume():
    raw = {"name": "x", "steps": [{"role": "worker", "continue": "resume"},
                                  {"role": "reviewer", "continue": "fresh"}]}
    assert spec.check(raw) == []
    raw["steps"][0]["continue"] = "again"
    assert spec.check(raw) == ["step 0: continue should be one of fresh, "
                               "resume"]


def test_a_fanned_step_cannot_resume_one_session():
    raw = {"name": "x", "steps": [{"role": "planner"},
                                  {"role": "worker", "fanout": True,
                                   "continue": "resume"}]}
    assert spec.check(raw) == ["step 1: continue: resume on a fanned-out "
                               "step, whose tasks run side by side with no "
                               "one session to carry on"]


# the second call carries the first one's session on


def test_a_resume_step_goes_again_as_a_fork_of_its_own_session(replay):
    cli = replay({"worker.md": [FIRST, NOTES],
                  "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]})
    first, second = [c["argv"] for c in cli.of("worker.md")]
    kept = flag(first, "--session-id")
    assert uuid.UUID(kept)
    assert "--resume" not in first and "--fork-session" not in first
    assert second[second.index("--resume"):second.index("--resume") + 3] == \
        ["--resume", kept, "--fork-session"]
    assert flag(second, "--session-id") not in (None, kept)
    assert last_manifest()["sessions"]["worker.md"]["id"] == \
        flag(second, "--session-id")


def test_the_carried_on_call_is_sent_only_what_is_new(replay):
    cli = replay({"worker.md": [FIRST, NOTES],
                  "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]})
    first, second = [c["stdin"] for c in cli.of("worker.md")]
    assert WORKER in first
    assert WORKER not in second
    assert "the notes lost the fixed section" in second


def test_an_effort_raised_by_a_send_back_still_carries_on(replay):
    cli = replay({"worker.md": [FIRST, NOTES],
                  "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]})
    first, second = [c["argv"] for c in cli.of("worker.md")]
    assert flag(first, "--effort") == "low"
    assert flag(second, "--effort") == "medium"
    assert "--resume" in second


def test_only_what_the_carried_on_call_added_is_charged(replay):
    replay({"worker.md": [FIRST, NOTES],
            "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]})
    worker = [l for l in lines() if l["step"] == "worker.md"]
    assert [l["tokens"]["input"] for l in worker] == [100, 100]
    assert [l["tokens"]["output"] for l in worker] == [20, 20]
    assert worker[1]["continued"] == worker[0]["session"]
    assert "continued" not in worker[0]
    counted = last_manifest()["spend"]["counted"]
    assert counted["input"] == 400
    assert counted["output"] == 80
    assert last_manifest()["spend"]["reported"] == "0.04"


def test_a_fresh_step_names_no_session(replay):
    cli = replay({"worker.md": [FIRST, NOTES],
                  "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]},
                 worker_keys="")
    for c in cli.calls:
        assert "--session-id" not in c["argv"]
        assert "--resume" not in c["argv"]
    assert WORKER in cli.of("worker.md")[1]["stdin"]
    assert "sessions" not in last_manifest()


# a run carried on in a new process


def test_a_carried_on_run_resumes_the_session_its_manifest_kept(replay):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    cli = replay(answers)
    kept = flag(cli.of("worker.md")[0]["argv"], "--session-id")
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    last = cli.of("worker.md")[2]
    assert flag(last["argv"], "--resume") == kept
    assert WORKER not in last["stdin"]


def test_a_model_change_starts_the_step_fresh_with_the_handoff(
        replay, monkeypatch):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    cli = replay(answers)
    monkeypatch.setenv("MODEL", "model-two")
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    last = cli.of("worker.md")[2]
    assert "--resume" not in last["argv"]
    assert flag(last["argv"], "--model") == "model-two"
    assert uuid.UUID(flag(last["argv"], "--session-id"))
    assert WORKER in last["stdin"]


def aged(seconds, lifetime=None):
    """the stopped run's worker session, kept `seconds` earlier than it
    was."""
    record = manifest.load(state.RUNS / resume.runs_for("resumer")[-1])
    kept = record.data["sessions"]["worker.md"]
    kept["at"] = kept["at"] - seconds
    if lifetime is not None:
        kept["lifetime"] = lifetime
    record.save()


def test_a_session_kept_days_ago_starts_the_step_fresh_and_says_why(
        replay, capsys):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    cli = replay(answers)
    aged(3 * 24 * 3600)
    capsys.readouterr()
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    last = cli.of("worker.md")[2]
    assert "--resume" not in last["argv"]
    assert WORKER in last["stdin"]
    assert "worker.md starts fresh from the handoff: the session it would " \
        "carry on was kept 72 h ago" in capsys.readouterr().out


def test_a_session_past_its_cache_lifetime_carries_on_marked_as_lapsed(
        replay):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    cli = replay(answers)
    aged(2 * 3600, lifetime=3600)
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    assert "--resume" in cli.of("worker.md")[2]["argv"]
    worker = [l for l in lines() if l["step"] == "worker.md"]
    assert worker[-1]["lapsed"] >= 2 * 3600
    assert worker[-1]["continued"]


def test_a_session_inside_its_cache_lifetime_is_not_marked(replay):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    replay(answers)
    aged(60, lifetime=3600)
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    worker = [l for l in lines() if l["step"] == "worker.md"]
    assert worker[-1]["continued"]
    assert "lapsed" not in worker[-1]


# what the transcript of a carried-on go is held to


CLAIM = ("\nHANDOFF\nDID:\n- notes written\nVERIFIED:\n- the suite is green\n"
         "  cmd: python -m pytest -q\n  saw: 5 passed\nNOT VERIFIED:\n- none\n"
         "ASSUMED:\n- none\nDOUBTS:\n- none\nMUST NOT MISS:\n- none\n"
         "TRIED:\n- none\nREAD:\n- none\nEND HANDOFF\n")


def worker_lines():
    return [l for l in lines() if l["step"] == "worker.md"]


def test_a_carried_on_gos_claim_is_not_backed_by_the_earlier_gos_run(
        replay, tmp_path):
    replay({"worker.md": [Did(FIRST + CLAIM, ran("python -m pytest -q",
                                                 "5 passed in 0.1s", "1")),
                          NOTES + CLAIM],
            "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]},
           folder=tmp_path / "projects" / "a-place")
    first, second = worker_lines()
    assert first["handoff"]["verified"][0]["backed"] == "backed"
    assert second["continued"] == first["session"]
    assert second["handoff"]["verified"][0]["backed"] != "backed"


def test_a_carried_on_gos_reads_are_its_own(replay, tmp_path):
    read = [{"type": "assistant", "message": {"id": "msg-read", "content": [
        {"type": "tool_use", "id": "toolu-read", "name": "Read",
         "input": {"file_path": "notes.md"}}]}}]
    replay({"worker.md": [Did(FIRST, read), NOTES],
            "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]},
           folder=tmp_path / "projects" / "a-place")
    first, second = worker_lines()
    assert summary.facts_of(first)["read"] == [("notes.md", "")]
    assert summary.facts_of(second)["read"] == []


def test_a_carried_on_gos_shell_traps_are_its_own(replay, tmp_path):
    trap = [{"type": "assistant", "message": {"id": "msg-trap", "content": [
        {"type": "text", "text": "the sed substitution did not match"}]}}]
    replay({"worker.md": [Did(FIRST, trap), NOTES],
            "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]},
           folder=tmp_path / "projects" / "a-place")
    first, second = worker_lines()
    assert first["shell_trap_recoveries"] == 1
    assert second["shell_trap_recoveries"] == 0


# when the session is not carried on


def test_an_edited_role_file_starts_the_step_fresh(replay, tmp_path):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    cli = replay(answers)
    (tmp_path / "flows" / "resumer" / "worker.md").write_text(
        WORKER + " keep each line short.\n", encoding="utf-8")
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    last = cli.of("worker.md")[2]
    assert "--resume" not in last["argv"]
    assert "keep each line short" in last["stdin"]


def test_a_session_the_cli_no_longer_has_starts_the_step_fresh(
        replay, tmp_path, monkeypatch):
    answers = {"worker.md": [NOTES, OUT_OF_CALLS, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]}
    cli = replay(answers)
    (tmp_path / "projects" / "elsewhere").mkdir(parents=True)
    monkeypatch.setattr(handoff, "PROJECTS", str(tmp_path / "projects"))
    replay(args=["--resume", resume.runs_for("resumer")[-1]])
    last = cli.of("worker.md")[2]
    assert "--resume" not in last["argv"]
    assert WORKER in last["stdin"]


GONE = {"type": "result", "is_error": True, "subtype": "error",
        "result": "No conversation found with that session id",
        "usage": {"input_tokens": 0, "output_tokens": 0}}
REFUSED = {"type": "result", "is_error": True, "result": "bad request",
           "api_error_status": 400,
           "usage": {"input_tokens": 0, "output_tokens": 0}}


@pytest.mark.parametrize("failed", [GONE, REFUSED])
def test_a_session_that_would_not_carry_on_is_dropped(replay, failed):
    replay({"worker.md": [FIRST, failed, failed],
            "reviewer.md": [REDO]})
    assert "worker.md" not in last_manifest().get("sessions", {})


def test_the_same_new_words_on_a_different_session_are_asked_again(replay):
    cli = replay({"worker.md": [FIRST, "## added\n- two\n", NOTES],
                  "reviewer.md": [REDO, REDO, "VERDICT: ok\n\n" + NOTES]},
                 worker_keys="    continue: resume\n")
    assert len(cli.of("worker.md")) == 3


# the cli provider on its own


# what `claude -p --output-format json` 2.1.301 printed for a fresh call
# with `--session-id`, then for `--resume <it> --fork-session` of it: `usage`
# is the second call's own, `modelUsage` and `total_cost_usd` run on from the
# first.
FIRST_CALL = {"input_tokens": 2, "cache_creation_input_tokens": 3004,
              "cache_read_input_tokens": 649, "output_tokens": 3,
              "cache_creation": {"ephemeral_1h_input_tokens": 3004,
                                 "ephemeral_5m_input_tokens": 0}}
FIRST_MODELS = {"m-small": {"inputTokens": 1170, "outputTokens": 15,
                            "cacheReadInputTokens": 649,
                            "cacheCreationInputTokens": 3004}}
FIRST_COST = 0.0007317900000000002
USED = {"input_tokens": 2, "cache_creation_input_tokens": 1236,
        "cache_read_input_tokens": 2745, "output_tokens": 3,
        "cache_creation": {"ephemeral_1h_input_tokens": 1236,
                           "ephemeral_5m_input_tokens": 0}}
WHOLE_MODELS = {"m-small": {"inputTokens": 1172, "outputTokens": 18,
                            "cacheReadInputTokens": 3394,
                            "cacheCreationInputTokens": 4240}}
WHOLE_COST = 0.0010081400000000003
EARLIER = {"from": "s-1", "usage": FIRST_CALL, "models": FIRST_MODELS,
           "cost": FIRST_COST}


def result(usage, cost, session="s-2", models=None):
    out = {"type": "result", "is_error": False, "result": "ok",
           "session_id": session, "total_cost_usd": cost, "usage": usage}
    if models is not None:
        out["modelUsage"] = models
    return json.dumps(out).encode("utf-8")


def claude(command="claude"):
    return providers.build({"provider": "cli", "command": command})


def test_a_carried_on_answer_keeps_its_own_usage_and_is_charged_its_cost(
        fake_cli):
    fake_cli((0, result(USED, WHOLE_COST, models=WHOLE_MODELS), b""))
    p = claude()
    p.carry = dict(EARLIER)
    r = p.ask("again")
    assert r.usage.raw == USED
    assert r.cost == pytest.approx(WHOLE_COST - FIRST_COST)
    assert r.kept == {"usage": USED, "models": WHOLE_MODELS,
                      "cost": WHOLE_COST}


def test_the_models_of_a_carried_on_answer_are_what_this_call_added(
        fake_cli):
    two = {"m-small": dict(WHOLE_MODELS["m-small"]),
           "m-big": {"inputTokens": 10, "outputTokens": 5,
                     "cacheReadInputTokens": 0,
                     "cacheCreationInputTokens": 0}}
    fake_cli((0, result(USED, WHOLE_COST, models=two), b""))
    p = claude()
    p.carry = dict(EARLIER)
    r = p.ask("again")
    assert r.models["m-small"].raw["output_tokens"] == 3
    assert r.models["m-small"].raw["cache_read_input_tokens"] == 2745
    assert r.models["m-big"].raw["output_tokens"] == 5


def test_a_cost_below_the_sessions_own_was_never_the_whole_session(fake_cli):
    fake_cli((0, result(USED, 0.0001), b""))
    p = claude()
    p.carry = dict(EARLIER)
    assert p.ask("again").cost == 0.0001


def test_a_carried_on_cost_with_no_earlier_figure_is_not_known(fake_cli):
    fake_cli((0, result(USED, WHOLE_COST), b""))
    p = claude()
    p.carry = {"from": "s-1", "usage": None, "models": None, "cost": None}
    assert p.ask("again").cost is None


def test_a_command_other_than_claude_is_never_handed_a_session(fake_cli):
    cli = fake_cli((0, b"ok", b""))
    p = claude("my-model-cli")
    p.carry = dict(EARLIER)
    p.ask("again")
    argv = cli.calls[0]["argv"]
    assert "--resume" not in argv and "--session-id" not in argv


def test_a_failed_go_at_carrying_on_goes_again_from_the_same_session(
        fake_cli):
    cli = fake_cli((1, b"overloaded", b""), (0, result(USED, 0.05), b""))
    p = claude()
    p.carry = dict(EARLIER)
    assert not p.ask("again")
    assert p.ask("again")
    one, two = [c["argv"] for c in cli.calls]
    assert flag(one, "--resume") == flag(two, "--resume") == "s-1"
    assert flag(one, "--session-id") != flag(two, "--session-id")


def test_a_session_the_clis_own_folder_lacks_is_not_carried_on(
        tmp_path, monkeypatch):
    from agentweft.runner import handoff

    monkeypatch.setattr(handoff, "PROJECTS", str(tmp_path / "projects"))
    (tmp_path / "projects" / "a-place").mkdir(parents=True)
    (tmp_path / "projects" / "a-place" / "s-1.jsonl").write_text(
        "{}\n", encoding="utf-8")
    assert claude().holds("s-1")
    assert not claude().holds("s-2")


def test_a_timed_out_carried_on_go_is_read_from_its_own_transcript(
        tmp_path, monkeypatch):
    folder = tmp_path / "projects" / "a-place"
    folder.mkdir(parents=True)
    monkeypatch.setattr(handoff, "PROJECTS", str(tmp_path / "projects"))
    copied = {"type": "assistant", "message": {
        "id": "msg-earlier", "model": "m-small", "content": [],
        "usage": {"input_tokens": 9000, "output_tokens": 900}}}
    (folder / "s-1.jsonl").write_text(json.dumps(copied) + "\n",
                                      encoding="utf-8")

    def timing_out(argv, **kw):
        rows = [{"type": "user", "message": {"content": "an older prompt"}},
                copied,
                {"type": "assistant", "message": {
                    "id": "msg-new", "model": "m-small", "content": [],
                    "usage": {"input_tokens": 40, "output_tokens": 7}}}]
        (folder / (flag(argv, "--session-id") + ".jsonl")).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        raise __import__("subprocess").TimeoutExpired(argv, 1)

    monkeypatch.setattr(cli_provider, "call", answering(timing_out))
    p = claude()
    p.carry = dict(EARLIER)
    r = p.ask("again", timeout=1)
    assert r.metered == "transcript"
    assert (r.usage.raw["input_tokens"], r.usage.raw["output_tokens"]) == \
        (40, 7)


def test_the_grant_record_names_no_session(fake_cli):
    fake_cli()
    p = providers.build({"provider": "cli", "command": "claude"},
                        grant=["read"])
    p.carry = {"from": "s-1"}
    assert "--session-id" not in p.granted()["argv"]


# the api provider keeps the conversation itself


class Sent(object):
    def __init__(self):
        self.bodies = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.bodies.append(json)
        n = len(self.bodies)
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "answer " + str(n)}],
            "stop_reason": "end_turn", "model": "m",
            "usage": {"input_tokens": 1, "output_tokens": 1}})


@pytest.fixture
def api(monkeypatch):
    sent = Sent()
    monkeypatch.setattr(api_provider.httpx, "post", sent.post)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("API_URL", "https://example.invalid/v1/messages")
    return api_provider.ApiProvider(model="m"), sent


HOUR_MARK = {"type": "ephemeral", "ttl": "1h"}


def test_the_api_carries_a_steps_messages_on_with_an_hour_cache(api):
    p, sent = api
    p.carry = {"from": None}
    first = p.ask("the whole prompt")
    assert sent.bodies[0]["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "the whole prompt",
         "cache_control": HOUR_MARK}]}]
    assert p.holds(first.session)
    p.carry = {"from": first.session}
    second = p.ask("what is new")
    assert sent.bodies[1]["messages"] == [
        {"role": "user", "content": [{"type": "text",
                                      "text": "the whole prompt"}]},
        {"role": "assistant", "content": [{"type": "text",
                                           "text": "answer 1"}]},
        {"role": "user", "content": [{"type": "text", "text": "what is new",
                                      "cache_control": HOUR_MARK}]}]
    assert second.session != first.session
    assert p.holds(second.session)
    assert not p.holds(first.session)


def test_a_fresh_api_step_sends_what_it_always_sent(api):
    p, sent = api
    p.ask("x")
    assert sent.bodies[0]["messages"] == [{"role": "user", "content": "x"}]


def test_an_api_session_from_another_process_is_not_held(api):
    p, _ = api
    assert not p.holds("from-a-run-before")


# an eval measures the same flow


def test_a_recorded_step_carries_its_session_on_as_it_would_unrecorded(
        fake_cli):
    from agentweft.evals import recording

    cli = fake_cli((0, result(FIRST_CALL, FIRST_COST, session="",
                              models=FIRST_MODELS), b""),
                   (0, result(USED, WHOLE_COST, session="",
                              models=WHOLE_MODELS), b""))
    rec = recording.Recorder(claude())
    rec.at("worker.md", None)
    assert rec.continues()
    rec.carry = {"from": None}
    first = rec.ask("the whole prompt")
    assert rec.holds(first.session)
    rec.carry = providers.base.carry_of({"id": first.session,
                                         **first.kept})
    second = rec.ask("what is new")
    assert flag(cli.calls[1]["argv"], "--resume") == first.session
    assert second.cost == pytest.approx(WHOLE_COST - FIRST_COST)
    assert [c.get("kept") for c in rec.blob()["calls"]] == [
        first.kept, second.kept]


def test_a_replay_carries_the_recorded_sessions_on():
    from agentweft.evals import recording

    blob = {"asked": "m-small", "calls": [
        {"step": "worker.md", "task": None, "go": 1, "prompt": "x",
         "say": "ok", "session": "s-1", "kept": {"usage": FIRST_CALL,
                                                 "models": None,
                                                 "cost": FIRST_COST}}]}
    replay = recording.Replay(blob)
    assert replay.continues()
    assert replay.holds("s-1")
    assert not replay.holds("s-2")
    assert recording.reply_of(blob["calls"][0]).kept["cost"] == FIRST_COST


def test_a_recording_with_no_session_kept_does_not_carry_on():
    from agentweft.evals import recording

    assert not recording.Replay({"calls": [
        {"step": "w", "task": None, "go": 1, "prompt": "x", "say": "ok",
         "session": "s-1"}]}).continues()


READER = ("read it\n\nHANDOFF\nDID:\n- read the notes\n"
          "READ:\n- notes.md:1 - the first line\nEND HANDOFF\n")


def test_a_resumed_leg_is_handed_the_brief_of_the_legs_before_it(
        tmp_path, monkeypatch):
    from agentweft.runner import brief

    cli = a_briefed_run(tmp_path, monkeypatch, {
        "reader.md": [READER], "worker.md": [OUT_OF_CALLS, NOTES],
        "reviewer.md": ["VERDICT: ok\n\n" + NOTES]})
    engine.main()
    first = cli.of("worker.md")[0]["stdin"]
    assert "old notes" in first
    monkeypatch.setattr(sys, "argv", [
        "run.py", "briefed", "--force", "--resume",
        resume.runs_for("briefed")[-1]])
    engine.main()
    again = cli.of("worker.md")[-1]["stdin"]
    assert brief.NONE_YET not in again
    assert "notes.md:1 - the first line" in again
    assert "old notes" in again


def test_a_resume_of_a_resume_keeps_the_cap_the_first_leg_was_given(
        tmp_path, monkeypatch):
    a_briefed_run(tmp_path, monkeypatch, {
        "reader.md": [READER], "worker.md": [OUT_OF_CALLS, NOTES],
        "reviewer.md": [OUT_OF_CALLS, "VERDICT: ok\n\n" + NOTES]})
    monkeypatch.setattr(sys, "argv", ["run.py", "briefed", "--force",
                                      "--max-calls", "9"])
    engine.main()
    for leg in (2, 3):
        monkeypatch.setattr(sys, "argv", [
            "run.py", "briefed", "--force", "--resume",
            resume.runs_for("briefed")[-1]])
        engine.main()
        assert len(resume.runs_for("briefed")) == leg
        assert manifest.load(state.RUNS / resume.runs_for("briefed")[-1]) \
            .data["caps"] == {"max_calls": 9}, "leg " + str(leg)


def a_briefed_run(tmp_path, monkeypatch, answers):
    """the reader -> worker -> reviewer flow `briefed` over the scripted
    cli, in a place holding notes.md. -> the cli."""
    root = tmp_path / "flows" / "briefed"
    root.mkdir(parents=True)
    (root / "flow.yaml").write_text(
        "name: briefed\nsteps:\n  - role: reader\n    prompt: reader.md\n"
        "  - role: worker\n    prompt: worker.md\n    continue: resume\n"
        "  - role: reviewer\n    prompt: reviewer.md\n    on_redo: worker\n"
        "timeout: 300\nretries: 1\n", encoding="utf-8")
    (root / "reader.md").write_text("read the notes.\n", encoding="utf-8")
    (root / "worker.md").write_text(WORKER + "\n", encoding="utf-8")
    (root / "reviewer.md").write_text("review the notes. first line: VERDICT:"
                                      " ok or VERDICT: redo.\n",
                                      encoding="utf-8")
    place = tmp_path / "place"
    place.mkdir()
    (place / "notes.md").write_text("old notes\n", encoding="utf-8")
    monkeypatch.chdir(place)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setenv("MODEL", "model-one")
    cli = Cli(answers)
    real_step = engine.Run.step

    def step(self, name, *a, **kw):
        cli.step = name
        return real_step(self, name, *a, **kw)

    monkeypatch.setattr(engine.Run, "step", step)
    monkeypatch.setattr(cli_provider, "call", answering(cli.run))
    monkeypatch.setattr(sys, "argv", ["run.py", "briefed", "--force"])
    return cli


def test_a_brief_quoting_a_file_the_step_edited_still_carries_on(
        tmp_path, monkeypatch):
    root = tmp_path / "flows" / "briefed"
    root.mkdir(parents=True)
    (root / "flow.yaml").write_text(
        "name: briefed\nsteps:\n  - role: reader\n    prompt: reader.md\n"
        "  - role: worker\n    prompt: worker.md\n    continue: resume\n"
        "  - role: reviewer\n    prompt: reviewer.md\n    on_redo: worker\n"
        "timeout: 300\nretries: 1\n", encoding="utf-8")
    (root / "reader.md").write_text("read the notes.\n", encoding="utf-8")
    (root / "worker.md").write_text(WORKER + "\n", encoding="utf-8")
    (root / "reviewer.md").write_text("review the notes. first line: VERDICT:"
                                      " ok or VERDICT: redo.\n",
                                      encoding="utf-8")
    place = tmp_path / "place"
    place.mkdir()
    (place / "notes.md").write_text("old notes\n", encoding="utf-8")
    monkeypatch.chdir(place)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setenv("MODEL", "model-one")
    cli = Cli({"reader.md": [READER], "worker.md": [FIRST, NOTES],
               "reviewer.md": [REDO, "VERDICT: ok\n\n" + NOTES]})
    real_run, real_step = cli.run, engine.Run.step

    def run(argv, **kw):
        out = real_run(argv, **kw)
        if cli.step == "worker.md":
            (place / "notes.md").write_text("new notes\n", encoding="utf-8")
        return out

    def step(self, name, *a, **kw):
        cli.step = name
        return real_step(self, name, *a, **kw)

    monkeypatch.setattr(engine.Run, "step", step)
    monkeypatch.setattr(cli_provider, "call", answering(run))
    monkeypatch.setattr(sys, "argv", ["run.py", "briefed", "--force"])
    engine.main()
    first, second = cli.of("worker.md")
    assert "old notes" in first["stdin"]
    assert "--resume" in second["argv"], "the brief's quote moved the head"
