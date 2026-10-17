"""a run that stops says why, from a fixed list, and exits non-zero."""
import datetime
import json
import runpy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import signoff
from agentweft.guardrails.gates import redtest_gate
from agentweft.mcp import server
from agentweft.providers import cli_provider
from agentweft.runner import cli, engine, errors, prompts, resume, state, stops

REPO = Path(__file__).resolve().parent.parent
CLAUDE = "provider:\n  provider: cli\n  command: claude\n  model: m-small\n"
FAKE = "provider:\n  provider: fake\n"
DOT = chr(0xB7)
LIMIT = "You've hit your session limit " + DOT + " resets 7:20pm (Europe/London)"


def answer(text, session="s-1", cost=0.25):
    return (0, json.dumps({"type": "result", "is_error": False, "result": text,
                           "session_id": session, "total_cost_usd": cost,
                           "usage": {"input_tokens": 10, "output_tokens": 4},
                           "modelUsage": {"m-small-1": {}}}).encode("utf-8"),
            b"")


def refused_by_the_limit(text=LIMIT, **more):
    """what `claude -p --output-format json` printed when the session limit
    refused the call: an error result, status 429, the limit in the text."""
    body = {"type": "result", "subtype": "success", "is_error": True,
            "api_error_status": 429, "result": text, "session_id": "s-x",
            "total_cost_usd": 0, "usage": {"input_tokens": 0,
                                           "output_tokens": 0}}
    body.update(more)
    return (1, json.dumps(body).encode("utf-8"), b"")


def a_flow(tmp_path, monkeypatch, name, steps, tail=CLAUDE, args=()):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + "\nsteps:\n"
    for s in steps:
        role = s.split("\n")[0]
        body = body + "  - role: " + role + "\n    prompt: " + role + ".md\n"
        for more in s.split("\n")[1:]:
            body = body + "    " + more + "\n"
        (d / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    (d / "instructions.md").write_text("the " + name + " flow.\n",
                                       encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force"] + list(args))
    monkeypatch.setattr(resume, "JOURNAL", None)


def no_waiting(monkeypatch):
    real = engine.retry
    monkeypatch.setattr(engine, "retry",
                        lambda fn, cap=3: real(fn, cap, sleep=lambda s: None))


def journal():
    p = state.RUNS / "journal.md"
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def ends():
    return [stops.read(l) for l in journal() if stops.read(l).kind != "running"]


def the_folder():
    [folder] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    return folder


def steps_of(folder):
    text = (folder / "steps.jsonl").read_text(encoding="utf-8")
    return [json.loads(l) for l in text.split("\n") if l.strip()]


# the stop the row was written for


def test_an_interrupt_in_a_fanout_is_written_down_with_spend_and_a_why(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "wide",
           ["planner", "worker\nfanout: true\nworkers: 2", "merge"])
    fake_cli(answer("TASK: look at a\nFILES:\n- a.py\n\n"
                    "TASK: look at b\nFILES:\n- b.py\n"),
             (KeyboardInterrupt(), b"", b""))
    assert engine.main() == 130
    [end] = ends()
    assert end.status == "failed at worker.md"
    assert end.cause == "interrupt"
    assert end.spend.startswith("1 call, ")
    assert "worker.md" in end.why
    folder = the_folder()
    last = steps_of(folder)[-1]
    assert (last["step"], last["outcome"], last["cause"]) == \
        ("worker.md", "crashed", "interrupt")
    assert last["why"] == end.why
    assert end.why in (folder / "why.md").read_text(encoding="utf-8")


def test_a_gate_stop_exits_2(tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated",
           ["worker\ngates:\n  - gate: length\n    max_lines: 1", "reviewer"])
    fake_cli(answer("one\ntwo\n"))
    assert engine.main() == 2
    [end] = ends()
    assert (end.status, end.cause) == ("failed at worker.md", "gate failed")
    assert end.why == ("length: 2 lines, cap is 1; worker.md was sent back 1"
                       " time already (send_backs: 1)")


def test_the_first_saved_run_of_a_day_is_1(tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "once", ["worker"], tail=FAKE)
    assert engine.main() == 0
    day = datetime.date.today().isoformat()
    assert (state.RUNS / ("once-" + day + "-1.md")).exists()
    assert not (state.RUNS / ("once-" + day + "-2.md")).exists()
    assert engine.main() == 0
    assert (state.RUNS / ("once-" + day + "-2.md")).exists()


def test_a_usage_limit_parks_after_one_call_with_the_reset_time(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fix",
           ["worker\ngates:\n  - gate: red-test", "reviewer"])
    asked = []
    monkeypatch.setattr(redtest_gate.RedTestGate, "run",
                        lambda self, text: asked.append(text))
    slept = []
    real = engine.retry
    monkeypatch.setattr(engine, "retry",
                        lambda fn, cap=3: real(fn, cap, sleep=slept.append))
    cli = fake_cli(refused_by_the_limit())
    code = engine.main()
    assert code != 0 and code == 2
    assert len(cli.calls) == 1 and slept == [] and asked == []
    [end] = ends()
    assert (end.status, end.cause) == ("parked at worker.md", "provider outage")
    assert end.why.startswith("limit reached, resets 7:20pm (Europe/London)")
    handoff = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    assert "limit reached, resets 7:20pm (Europe/London)" in handoff
    assert "stopped at     worker.md" in handoff
    [line] = steps_of(the_folder())
    assert (line["outcome"], line["cause"]) == ("parked", "provider outage")
    assert line["retries"] == {"outage": 1}


def test_the_structured_limit_is_read_before_the_text(tmp_path, monkeypatch,
                                                      fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"])
    at = datetime.datetime(2031, 5, 6, 19, 20)
    fake_cli(refused_by_the_limit(
        "nothing in these words names it", api_error="usage_limit_reached",
        api_error_params={"rate_limit_info": {
            "status": "rejected", "resetsAt": int(at.timestamp())}}))
    assert engine.main() == 2
    [end] = ends()
    assert end.cause == "provider outage"
    assert end.why.startswith("limit reached, resets 2031-05-06 19:20")


def test_a_limit_that_names_no_reset_says_unknown(tmp_path, monkeypatch,
                                                  fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"])
    fake_cli(refused_by_the_limit("Usage limit reached",
                                  api_error="usage_limit_reached"))
    assert engine.main() == 2
    [end] = ends()
    assert end.why.startswith("limit reached, resets unknown")


def test_a_plain_429_is_still_a_retry_not_an_outage(tmp_path, monkeypatch,
                                                   fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"])
    no_waiting(monkeypatch)
    cli = fake_cli(refused_by_the_limit("Rate limited, try again"),
                   answer("done\n"), answer("VERDICT: ok\n\nfine\n"))
    assert engine.main() == 0
    assert len(cli.calls) == 3


def test_a_plain_command_falls_back_to_the_words(tmp_path, monkeypatch,
                                                 fake_cli):
    tail = "provider:\n  provider: cli\n  command: other-model-cli\n"
    a_flow(tmp_path, monkeypatch, "plain", ["worker", "reviewer"], tail=tail)
    cli = fake_cli((1, b"", ("Claude AI usage limit reached|"
                             + str(int(datetime.datetime(2031, 5, 6, 19, 20)
                                       .timestamp()))).encode("utf-8")))
    assert engine.main() == 2
    assert len(cli.calls) == 1
    [end] = ends()
    assert end.cause == "provider outage"
    assert end.why.startswith("limit reached, resets 2031-05-06 19:20")


def test_a_resumed_outage_runs_the_step_it_parked_on_again(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"])
    fake_cli(refused_by_the_limit())
    engine.main()
    first = the_folder().name
    cli = fake_cli(answer("done\n"), answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "fix", "--force", "--resume",
                                      first])
    assert engine.main() == 0
    assert len(cli.calls) == 2


def test_a_limit_in_a_fanout_parks_the_fanned_step(tmp_path, monkeypatch,
                                                   fake_cli):
    a_flow(tmp_path, monkeypatch, "wide",
           ["planner", "worker\nfanout: true\nworkers: 2", "merge"])
    fake_cli(answer("TASK: look at a\nFILES:\n- a.py\n\n"
                    "TASK: look at b\nFILES:\n- b.py\n"),
             refused_by_the_limit())
    assert engine.main() == 2
    [end] = ends()
    assert (end.status, end.cause) == ("parked at worker.md", "provider outage")
    handoff = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    assert "  worker.md\n  merge.md" in handoff


def test_a_scored_run_names_the_outage(tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"])
    cli = fake_cli(refused_by_the_limit())
    _, budget, why = engine.run_once("fix")
    assert why.startswith("provider outage at worker.md: limit reached, "
                          "resets 7:20pm (Europe/London)")
    assert len(cli.calls) == 1
    assert budget.summary() == "0 calls, 1 refused, 0 tokens"


def test_limit_refusals_across_a_chain_of_resumes_do_not_reach_the_call_cap(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"],
           tail=CLAUDE + "max_calls: 2\n")
    fake_cli(answer("done\n"), refused_by_the_limit())
    assert engine.main() == 2
    seen = {the_folder().name}
    last = the_folder().name
    for _ in range(8):
        fake_cli(refused_by_the_limit())
        monkeypatch.setattr(sys, "argv", ["run.py", "fix", "--force",
                                          "--resume", last])
        assert engine.main() == 2
        [last] = {p.name for p in state.RUNS.iterdir() if p.is_dir()} - seen
        seen.add(last)
    fake_cli(answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "fix", "--force", "--resume",
                                      last])
    assert engine.main() == 0
    end = ends()[-1]
    assert end.spend.startswith("2 calls, 9 refused, ")


def test_one_step_on_its_own_says_the_limit_and_exits_2(tmp_path, monkeypatch,
                                                         fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", "reviewer"])
    fake_cli(refused_by_the_limit())
    monkeypatch.setattr(sys, "argv", ["run.py", "step", "fix", "worker"])
    monkeypatch.setattr(sys, "stdin", type("tty", (), {"read": lambda s: ""})())
    monkeypatch.setattr("os.isatty", lambda fd: True)
    assert cli.cmd_step() == 2
    assert "limit reached, resets 7:20pm" in capsys.readouterr().out


def test_a_crash_after_the_last_step_is_still_a_stop(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "f", ["worker"], tail=FAKE)

    def broken(flow):
        raise OSError("disk full")

    monkeypatch.setattr(engine, "next_run_path", broken)
    assert engine.main() == 2
    [end] = ends()
    assert (end.status, end.cause, end.why) == \
        ("failed at worker.md", "exception", "OSError: disk full")
    assert [l["outcome"] for l in steps_of(the_folder())] == ["ok"]


# every cause on the list, reached by the run itself


def test_every_stop_names_a_cause_from_the_list(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        engine.journal("flow", stops.status("tired", "worker.md"),
                       datetime.datetime.now(), cause="tired")
    with pytest.raises(ValueError):
        stops.checked("tired")


def test_the_list_is_the_one_the_rollup_counts():
    assert stops.CAUSES == ("gate failed", "refused", "parked",
                            "provider outage", "budget", "exception",
                            "interrupt", "no answer", "declined", "conflict",
                            "overlap", "target moved", "merge unchecked",
                            "off task")


def run_to_a_stop(tmp_path, monkeypatch, fake_cli, cause):
    if cause == "gate failed":
        a_flow(tmp_path, monkeypatch, "f",
               ["worker\ngates:\n  - gate: length\n    max_lines: 1",
                "reviewer"])
        fake_cli(answer("one\ntwo\n"))
    elif cause == "refused":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"], tail=FAKE)
        monkeypatch.setattr(engine.Run, "refused", lambda self, step:
                            "AGENTS.md changed" if step == "reviewer.md"
                            else "")
    elif cause == "parked":
        a_flow(tmp_path, monkeypatch, "f", ["worker\npause: user",
                                            "reviewer"], tail=FAKE)
    elif cause == "provider outage":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
        fake_cli(refused_by_the_limit())
    elif cause == "budget":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"],
               tail=FAKE + "max_calls: 1\n")
    elif cause == "exception":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
        fake_cli(answer("worked\n"), (1, b"", b"unauthorized"))
    elif cause == "interrupt":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
        fake_cli(answer("worked\n"), (KeyboardInterrupt(), b"", b""))
    elif cause == "no answer":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
        no_waiting(monkeypatch)
        fake_cli(answer(""))
    elif cause == "declined":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
        (tmp_path / "TASK.md").write_text("amounts are strings\n",
                                          encoding="utf-8")
        fake_cli(answer('REFUSED: TASK.md:1 "amounts are strings"\n'))
    elif cause == "conflict":
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
        (tmp_path / "TASK.md").write_text("amounts are strings\n",
                                          encoding="utf-8")
        fake_cli(answer('CONFLICT: TASK.md:1 "amounts are strings" | make'
                        ' them numbers\n'))
    elif cause == "overlap":
        a_flow(tmp_path, monkeypatch, "f",
               ["planner", "worker\nfanout: true", "reviewer"],
               tail=FAKE + "  replies:\n"
               "    planner.md: \"TASK: tidy a\\nFILES:\\n- a.py\\n\"\n"
               "    worker.md:\n"
               "      - say: \"tidied\"\n"
               "        writes:\n"
               "          c.py: \"c = 1\\n\"\n")
    elif cause in ("target moved", "merge unchecked"):
        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"], tail=FAKE)
        ends_as = signoff.CONFLICT if cause == "target moved" \
            else signoff.UNCHECKED
        monkeypatch.setattr(engine.signoff, "check", lambda place, start:
                            signoff.Signed(ends_as, "main", "abc123",
                                           ["a.py"], why="main moved"))
    elif cause == "off task":
        from agentweft.guardrails import police

        a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"],
               tail=CLAUDE + "police: on\n")
        monkeypatch.setattr(police, "check", lambda *a, **kw: [police.Hit(
            police.NET, 'Bash "pip install leftpad" installs a package')])
        fake_cli(answer("worked\n"))
    return engine.main()


@pytest.mark.parametrize("cause", stops.CAUSES)
def test_each_cause_is_a_stop_the_runner_makes(cause, tmp_path, monkeypatch,
                                               fake_cli, capsys):
    code = run_to_a_stop(tmp_path, monkeypatch, fake_cli, cause)
    assert code == {"interrupt": 130, "declined": 0}.get(cause, 2)
    [end] = ends()
    assert end.cause == cause
    assert end.why and end.spend and end.run == the_folder().name
    folder = the_folder()
    last = steps_of(folder)[-1]
    assert last["cause"] == cause and last["why"] == end.why
    said = (folder / "why.md").read_text(encoding="utf-8")
    assert cause in said and end.why in said
    printed = capsys.readouterr().out
    assert "started worker.md" in printed


# the one outcome a run ends with, read off its cause

OUTCOME = {"gate failed": "stopped: gate failed",
           "refused": "stopped: guard refused",
           "parked": "needs you: ruling",
           "provider outage": "waiting: provider limit",
           "budget": "needs you: budget",
           "exception": "stopped: tool fault",
           "interrupt": "stopped: interrupted",
           "no answer": "stopped: tool fault",
           "declined": "refused (spec cited)",
           "conflict": "stopped: spec conflict",
           "overlap": "stopped: tasks overlap",
           "target moved": "stopped: target moved",
           "merge unchecked": "stopped: merge unchecked",
           "off task": "stopped: off task"}


def test_every_cause_has_exactly_one_outcome():
    assert {c: stops.outcome(c) for c in stops.CAUSES} == OUTCOME
    assert all(stops.outcome(c) in stops.OUTCOMES for c in stops.CAUSES)


def test_a_cause_off_the_list_has_no_outcome():
    with pytest.raises(ValueError):
        stops.outcome("tired")


def test_a_clean_run_is_done_and_unproven_checks_are_counted():
    assert stops.done() == "done"
    assert stops.done(1) == "done, 1 check unproven"
    assert stops.done(3) == "done, 3 checks unproven"


@pytest.mark.parametrize("cause", stops.CAUSES)
def test_each_stop_ends_with_its_outcome_on_record(cause, tmp_path,
                                                   monkeypatch, fake_cli,
                                                   capsys):
    run_to_a_stop(tmp_path, monkeypatch, fake_cli, cause)
    folder = the_folder()
    first = (folder / "handoff.md").read_text(encoding="utf-8").split("\n")[0]
    assert first.startswith("# f " + folder.name + ": " + OUTCOME[cause]
                            + " at "), first
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["outcome"] == OUTCOME[cause]
    assert first in capsys.readouterr().out


def test_a_finished_run_is_done_on_record(tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "f", ["worker"], tail=FAKE)
    assert engine.main() == 0
    folder = the_folder()
    first = (folder / "handoff.md").read_text(encoding="utf-8").split("\n")[0]
    assert first == "# f " + folder.name + ": done"
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["outcome"] == "done"
    assert first in capsys.readouterr().out


def test_the_no_answer_why_carries_what_the_provider_said(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
    no_waiting(monkeypatch)
    fake_cli((1, b"", b"connection reset by peer"))
    assert engine.main() == 2
    [end] = ends()
    assert end.cause == "no answer"
    assert "connection reset by peer" in end.why and "3 goes" in end.why


def test_an_empty_answer_never_reaches_a_gate(tmp_path, monkeypatch,
                                              fake_cli):
    a_flow(tmp_path, monkeypatch, "fix",
           ["worker\ngates:\n  - gate: red-test", "reviewer"])
    asked = []
    monkeypatch.setattr(redtest_gate.RedTestGate, "run",
                        lambda self, text: asked.append(text))
    no_waiting(monkeypatch)
    fake_cli(answer(""))
    assert engine.main() == 2
    assert asked == []
    assert ends()[0].cause == "no answer"


def test_an_exception_after_the_step_answered_is_still_written_down(
        tmp_path, monkeypatch, fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"], tail=FAKE)

    def broken(*a, **k):
        raise RuntimeError("the gate list is broken")

    monkeypatch.setattr(engine.Run, "gates_for", broken)
    assert engine.main() == 2
    [end] = ends()
    assert (end.status, end.cause) == ("failed at worker.md", "exception")
    assert end.why == "RuntimeError: the gate list is broken"
    assert "Traceback" in capsys.readouterr().err
    [line] = steps_of(the_folder())
    assert (line["outcome"], line["cause"]) == ("crashed", "exception")
    assert line["file"] == "steps/001-worker.md"


# the journal around a stop


def test_a_run_says_it_is_running_before_its_first_step(tmp_path,
                                                        monkeypatch):
    a_flow(tmp_path, monkeypatch, "f", ["worker"], tail=FAKE)
    seen = []
    real = engine.Run.step

    def step(self, *a, **k):
        seen.append(journal())
        return real(self, *a, **k)

    monkeypatch.setattr(engine.Run, "step", step)
    assert engine.main() == 0
    [before] = seen
    [line] = before
    got = stops.read(line)
    assert (got.flow, got.kind, got.status) == ("f", "running", "running")
    assert got.run == the_folder().name
    last = stops.read(journal()[-1])
    assert (last.kind, last.run) == ("ok", got.run)


def test_the_finished_line_goes_through_the_one_writer(tmp_path,
                                                       monkeypatch):
    a_flow(tmp_path, monkeypatch, "f", ["worker"], tail=FAKE)
    written = []
    real = engine.journal

    def journal_(*a, **k):
        written.append(a[1])
        return real(*a, **k)

    monkeypatch.setattr(engine, "journal", journal_)
    assert engine.main() == 0
    assert written == ["running", "ok"]
    assert len(journal()) == 2


def test_a_flow_kept_out_of_the_journal_writes_no_running_line(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "f", ["worker"],
           tail=FAKE + "journal: false\n")
    assert engine.main() == 0
    assert journal() == []


def test_run_py_hands_the_code_to_the_shell(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(engine, "main", lambda: 2)
    import agentweft.runner as runner

    monkeypatch.setattr(runner, "main", lambda: 2)
    monkeypatch.setattr(sys, "argv", ["run.py", "f"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(REPO / "run.py"), run_name="__main__")
    got.append(e.value.code)
    assert got == [2]


# what reads the journal


def test_resume_reads_every_stop_cause(tmp_path, monkeypatch):
    j = tmp_path / "journal.md"
    monkeypatch.setattr(resume, "JOURNAL", j)
    now = datetime.datetime(2026, 1, 2, 3, 4)
    lines = []
    for cause in stops.CAUSES:
        lines.append(stops.line(now, "demo", stops.status(cause, "w.md"), 3,
                                "demo-2026-01-02-030400", cause, "1 call",
                                "why"))
    for cause, text in zip(stops.CAUSES, lines):
        j.write_text(text + "\n", encoding="utf-8")
        stop = resume.last_stop("demo")
        assert (stop.step, stop.cause) == ("w.md", cause)
        assert stop.parked == (cause in ("parked", "off task"))


def test_resume_skips_a_running_line(tmp_path, monkeypatch):
    j = tmp_path / "journal.md"
    monkeypatch.setattr(resume, "JOURNAL", j)
    j.write_text("2026-01-02 03:04  demo  failed at w.md  3s  demo-1  "
                 "no answer  1 call  nothing came out\n"
                 "2026-01-02 04:00  demo  running  0s  demo-2\n",
                 encoding="utf-8")
    assert resume.last_stop("demo").step == "w.md"


def test_resume_still_reads_the_old_lines(tmp_path, monkeypatch):
    j = tmp_path / "journal.md"
    monkeypatch.setattr(resume, "JOURNAL", j)
    j.write_text("2025-11-20 09:00  weekly digest  failed at merge.md  12s\n",
                 encoding="utf-8")
    assert resume.last_stop("weekly digest").step == "merge.md"
    j.write_text("2025-11-20 09:00  weekly digest  ok  12s  wd-1.md  2 calls\n",
                 encoding="utf-8")
    assert resume.last_stop("weekly digest") is None


def a_week(tmp_path):
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    rows = [stops.line(now, "digest", "running", 0, "digest-1"),
            stops.line(now, "digest", "ok", 40, "digest-1", saved="d-1.md",
                       spend="3 calls"),
            stops.line(now, "digest", "running", 0, "digest-2"),
            stops.line(now, "digest", stops.status("provider outage", "w.md"),
                       2, "digest-2", "provider outage", "1 call",
                       "limit reached, resets unknown"),
            stops.line(now, "digest", "running", 0, "digest-3"),
            stops.line(now, "digest", stops.status("gate failed", "r.md"), 9,
                       "digest-3", "gate failed", "2 calls", "regex: no"),
            stops.line(now, "digest", "running", 0, "digest-4"),
            stops.line(now, "digest", stops.status("gate failed", "r.md"), 9,
                       "digest-4", "gate failed", "2 calls", "regex: no"),
            stops.line(now, "digest", "running", 0, "digest-5"),
            # the old shape, from before the cause had a column
            now.strftime("%Y-%m-%d %H:%M") + "  digest  over budget at r.md"
            "  5s"]
    j = tmp_path / "runs" / "journal.md"
    j.parent.mkdir(parents=True, exist_ok=True)
    j.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return j


def load_rollup():
    return runpy.run_path(str(REPO / "rollup.py"), run_name="rollup")


def test_the_rollup_counts_stops_per_cause(tmp_path, monkeypatch, capsys):
    a_week(tmp_path)
    rollup = load_rollup()
    monkeypatch.setattr(sys, "argv", ["rollup.py"])
    assert rollup["main"]() == 0
    out = capsys.readouterr().out
    assert "digest  5 runs, 4 stopped" in out
    assert "  gate failed  2" in out
    assert "  provider outage  1" in out
    assert "  budget  1" in out
    assert "1 started and never wrote how it ended" in out


def test_the_rollup_has_a_count_for_every_cause_and_no_other(tmp_path):
    j = a_week(tmp_path)
    rollup = load_rollup()
    week = rollup["week"](j.read_text(encoding="utf-8").split("\n"),
                          datetime.datetime.now() - datetime.timedelta(days=7))
    assert set(week["causes"]) == set(stops.CAUSES)
    assert sum(week["causes"].values()) == 4


def test_the_rollup_refuses_a_cause_it_has_no_count_for(tmp_path):
    rollup = load_rollup()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with pytest.raises(ValueError):
        rollup["week"]([now + "  f  failed at w.md  1s  f-1  tired  1 call  x"],
                       datetime.datetime.now() - datetime.timedelta(days=7))


def test_spend_prints_every_line_that_spent(tmp_path, monkeypatch, capsys):
    a_week(tmp_path)
    assert cli.cmd_spend() == 0
    out = capsys.readouterr().out.strip().split("\n")
    assert len(out) == 4
    assert all("running" not in l for l in out)
    assert any("provider outage" in l for l in out)


def test_the_server_says_a_stopped_run_stopped(monkeypatch):
    import types

    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k:
                        types.SimpleNamespace(returncode=2, stdout="parked",
                                              stderr=""))
    said = server.run_flow("weekly-digest")
    assert said.startswith("the run stopped before the end (exit 2)")
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k:
                        types.SimpleNamespace(returncode=130, stdout="",
                                              stderr=""))
    assert server.run_flow("weekly-digest").startswith(
        "the run was interrupted (exit 130)")


# the limit, read by the provider


def test_the_provider_reads_a_limit_off_the_structured_reply():
    p = cli_provider.CliProvider()
    import types

    data = json.loads(refused_by_the_limit()[1])
    reply = p.read(data, types.SimpleNamespace(returncode=1, killed=0))
    assert reply.outage == "7:20pm (Europe/London)"
    assert reply.retryable is False
    data = json.loads(refused_by_the_limit("Rate limited")[1])
    reply = p.read(data, types.SimpleNamespace(returncode=1, killed=0))
    assert reply.outage is None and reply.retryable is True


@pytest.mark.parametrize("said,resets", [
    (LIMIT, "7:20pm (Europe/London)"),
    ("You've hit your weekly limit " + DOT + " resets Oct 14, 9am",
     "Oct 14, 9am"),
    ("Usage limit reached " + DOT + " limit resets 3pm", "3pm"),
    ("Usage limit reached", "unknown"),
])
def test_the_words_of_a_limit_are_an_outage(said, resets):
    assert errors.classify(said) is errors.Outage
    assert errors.resets(said) == resets


@pytest.mark.parametrize("said", ["rate limit", "429 Too Many Requests",
                                  "timed out after 30s", "the context limit"])
def test_a_throttle_is_not_an_outage(said):
    assert errors.classify(said) is not errors.Outage
