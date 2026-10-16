import json
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.mcp import server
from agentweft.runner import engine, prompts, trace
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


KEYS = ["seq", "time", "step", "from", "to", "provider", "command", "model",
        "model_reported", "model_choice", "effort", "verbosity", "grant", "tokens", "cost", "priced", "cost_from",
        "cost_parts", "budget", "session", "seconds", "cached",
        "retries", "background_killed", "shell_writes_denied",
        "shell_trap_recoveries", "gates", "ungated", "outcome", "won", "cause", "why", "file",
        "task_file", "tasks", "handoff", "chain"]

# an en dash, a CJK word and a Cyrillic letter: cp1252 has the first under
# another byte and no byte at all for the rest
SAID = chr(0x2013) + " " + chr(0x6f22) + chr(0x5b57) + " " + chr(0x41d)

CLAUDE = "provider:\n  provider: cli\n  command: claude\n  model: m-small\n"
FAKE = "provider:\n  provider: fake\n"


def answer(text, session="s-1", cost=0.25, model="m-small-1"):
    """what `claude -p --output-format json` prints for one call."""
    return (0, json.dumps({"type": "result", "is_error": False, "result": text,
                           "session_id": session, "total_cost_usd": cost,
                           "usage": {"input_tokens": 10, "output_tokens": 4,
                                     "cache_read_input_tokens": 2},
                           "modelUsage": {model: {}}},
                          ensure_ascii=False).encode("utf-8"), b"")


def a_flow(tmp_path, monkeypatch, name, steps, tail=CLAUDE, args=()):
    """a throwaway flow under tmp_path, ready for main() to run.

    `steps` is the yaml under `steps:`, one string per step, role first."""
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


def no_waiting(monkeypatch):
    real = engine.retry
    monkeypatch.setattr(engine, "retry",
                        lambda fn, cap=3: real(fn, cap, sleep=lambda s: None))


def folders(tmp_path):
    return sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())


def lines(folder):
    text = (folder / "steps.jsonl").read_bytes().decode("utf-8")
    return [json.loads(l) for l in text.split("\n") if l.strip()]


def every_line(tmp_path):
    out = []
    for f in folders(tmp_path):
        if (f / "steps.jsonl").exists():
            out = out + lines(f)
    return out


def test_a_two_step_run_writes_one_line_per_step(tmp_path, monkeypatch,
                                                 fake_cli):
    a_flow(tmp_path, monkeypatch, "two",
           ["worker\ngates:\n  - gate: length\n    max_lines: 5", "reviewer"])
    fake_cli(answer("did the thing\n", session="s-1"),
             answer("VERDICT: ok\n\nfine\n", session="s-2", cost=0.5))
    engine.main()
    [folder] = folders(tmp_path)
    first, second = lines(folder)
    assert list(first) == KEYS and list(second) == KEYS
    assert first["seq"] == 1 and second["seq"] == 2
    assert first["step"] == "worker.md" and first["from"] is None
    assert first["to"] == "reviewer.md"
    assert (first["provider"], first["command"], first["model"]) == \
        ("cli", "claude", "m-small")
    assert first["model_reported"] == "m-small-1"
    assert first["tokens"] == {"counted": True, "input": 12, "output": 4,
                               "cache_read": 2, "cache_creation": 0}
    assert (first["cost"], first["session"]) == (0.25, "s-1")
    assert isinstance(first["seconds"], (int, float))
    assert first["cached"] is False and first["retries"] == {}
    assert first["gates"] == [{"gate": "length", "ok": True,
                               "detail": "1 lines"}]
    assert (first["outcome"], first["why"]) == ("ok", None)
    assert first["file"] == "steps/001-worker.md"
    assert first["tasks"] is None and first["handoff"]["state"] == "missing"
    assert len(first["time"]) == len("2026-01-01T00:00:00")
    # the reviewer declares no gates and still has its line, saying so
    assert second["gates"] == []
    assert (second["from"], second["to"]) == ("worker.md", None)
    assert (second["cost"], second["session"]) == (0.5, "s-2")
    assert (folder / first["file"]).read_text(encoding="utf-8") == \
        "did the thing\n"


def test_a_redo_leaves_both_reviewer_files_readable(tmp_path, monkeypatch,
                                                    fake_cli):
    a_flow(tmp_path, monkeypatch, "again", ["worker", "reviewer"])
    fake_cli(answer("first go\n"),
             answer("VERDICT: redo\n\nthe total is off by one\n"),
             answer("second go\n"),
             answer("VERDICT: ok\n\nfine now\n"))
    engine.main()
    [folder] = folders(tmp_path)
    got = lines(folder)
    assert [(l["seq"], l["step"], l["outcome"]) for l in got] == [
        (1, "worker.md", "ok"), (2, "reviewer.md", "redo"),
        (3, "worker.md", "ok"), (4, "reviewer.md", "ok")]
    assert got[1]["to"] == "worker.md" and got[2]["from"] == "reviewer.md"
    assert "off by one" in (folder / "steps" / "002-reviewer.md").read_text(
        encoding="utf-8")
    assert "fine now" in (folder / "steps" / "004-reviewer.md").read_text(
        encoding="utf-8")
    # the file resume reads is still the last pass
    assert "fine now" in (folder / "reviewer.md").read_text(encoding="utf-8")


def test_a_failed_gate_writes_the_line_of_the_step_it_stopped(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated",
           ["worker\ngates:\n  - gate: length\n    max_lines: 1", "reviewer"])
    fake_cli(answer("one\ntwo\n"))
    engine.main()
    back, line = lines(folders(tmp_path)[0])
    assert (back["outcome"], back["to"], back["cause"]) == \
        ("gate failed", "worker.md", None)
    assert back["why"] == "length: 2 lines, cap is 1"
    assert line["outcome"] == "gate failed" and line["to"] is None
    assert line["cause"] == "gate failed"
    assert line["why"] == ("length: 2 lines, cap is 1; worker.md was sent"
                           " back 1 time already (send_backs: 1)")
    assert line["gates"] == [{"gate": "length", "ok": False,
                              "detail": "2 lines, cap is 1"}]
    assert line["file"] == "steps/002-worker.md"


def test_a_step_the_flow_parks_on_gets_its_line(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "pause",
           ["worker\npause: user", "reviewer"], tail=FAKE)
    engine.main()
    [line] = lines(folders(tmp_path)[0])
    assert (line["outcome"], line["why"], line["to"]) == \
        ("parked", "waiting for user", None)


def test_a_step_paused_at_the_cap_gets_its_line(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "spent", ["worker", "reviewer"],
           tail=FAKE + "max_calls: 1\n")
    engine.main()
    got = lines(folders(tmp_path)[0])
    assert [l["outcome"] for l in got] == ["ok", "parked"]
    assert got[1]["cause"] == "budget"
    assert got[1]["why"] == ("reached, completion 1/2 steps, call cap: 1 of 1"
                             " calls spent, and the next step takes 1")


def test_a_step_refused_before_it_starts_gets_a_line_with_nothing_spent(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "moved", ["worker", "reviewer"], tail=FAKE)
    monkeypatch.setattr(engine.Run, "refused", lambda self, step:
                        "AGENTS.md changed" if step == "reviewer.md" else "")
    engine.main()
    got = lines(folders(tmp_path)[0])
    assert [l["outcome"] for l in got] == ["ok", "refused"]
    assert got[1]["why"] == "AGENTS.md changed"
    assert (got[1]["file"], got[1]["cost"], got[1]["tokens"]) == \
        (None, None, {"counted": False})


def test_a_step_that_produced_nothing_says_how_often_it_went_again(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "empty", ["worker"])
    no_waiting(monkeypatch)
    fake_cli(answer(""))
    engine.main()
    [line] = lines(folders(tmp_path)[0])
    assert line["outcome"] == "failed"
    assert line["retries"] == {"transient": 3}
    # every go was counted by the provider, so every go is in the total
    assert line["tokens"]["input"] == 36 and line["cost"] == 0.75


def test_a_resumed_run_carries_on_numbering_where_the_first_stopped(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "picked", ["worker", "reviewer"])
    no_waiting(monkeypatch)
    fake_cli(answer("worked\n"), answer(""), answer(""), answer(""))
    engine.main()
    [first] = folders(tmp_path)
    assert [l["seq"] for l in lines(first)] == [1, 2]
    fake_cli(answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "picked", "--force",
                                      "--resume", first.name])
    engine.main()
    last = every_line(tmp_path)[-1]
    assert (last["seq"], last["step"], last["outcome"]) == \
        (3, "reviewer.md", "ok")
    assert last["from"] == "worker.md"
    assert last["file"] == "steps/003-reviewer.md"


def test_a_cached_answer_is_marked_and_costs_nothing(tmp_path, monkeypatch):
    """the redo sends the reviewer the same work, so its second answer is the
    cache's, and so is the worker's third."""
    a_flow(tmp_path, monkeypatch, "stuck",
           ["worker\nprovider:\n  provider: fake\n  reply: \"done\"",
            "reviewer\nprovider:\n  provider: fake\n"
            "  reply: \"VERDICT: redo\\n\\nstill wrong\\n\""], tail=FAKE)
    engine.main()
    got = lines(folders(tmp_path)[0])
    assert [(l["step"], l["cached"]) for l in got] == [
        ("worker.md", False), ("reviewer.md", False), ("worker.md", False),
        ("reviewer.md", True), ("worker.md", True), ("reviewer.md", True)]
    assert all(l["cost"] == 0 for l in got if l["cached"])
    assert got[-1]["outcome"] == "parked"
    assert "redo" in got[-1]["why"]


def test_a_provider_that_reports_nothing_is_not_counted(tmp_path,
                                                        monkeypatch):
    a_flow(tmp_path, monkeypatch, "quiet", ["worker"], tail=FAKE)
    engine.main()
    [line] = lines(folders(tmp_path)[0])
    assert line["provider"] == "fake" and line["command"] is None
    assert line["tokens"] == {"counted": False}
    assert (line["cost"], line["session"], line["model_reported"]) == \
        (None, None, None)


def test_a_fanned_out_step_is_one_line_with_a_task_each(tmp_path,
                                                         monkeypatch,
                                                         fake_cli):
    a_flow(tmp_path, monkeypatch, "wide",
           ["planner", "worker\nfanout: true\nworkers: 2", "merge"])
    fake_cli(answer("a.py | look at a\nb.py | look at b\n"))
    engine.main()
    got = lines(folders(tmp_path)[0])
    assert [l["step"] for l in got] == ["planner.md", "worker.md", "merge.md"]
    fan = got[1]
    assert [t["task"] for t in fan["tasks"]] == [1, 2]
    assert all(t["session"] == "s-1" and t["cost"] == 0.25
               for t in fan["tasks"])
    assert fan["cost"] == 0.5 and fan["tokens"]["input"] == 24
    assert fan["session"] is None
    assert got[0]["tasks"] is None


def test_a_crash_mid_step_is_written_down_and_the_run_exits_2(tmp_path,
                                                              monkeypatch,
                                                              fake_cli, cp1252):
    a_flow(tmp_path, monkeypatch, "broke", ["worker", "reviewer"])
    fake_cli(answer("worked\n"), (1, b"", ("unauthorized " + SAID)
                                  .encode("utf-8")))
    assert engine.main() == 2
    got = lines(folders(tmp_path)[0])
    assert [l["outcome"] for l in got] == ["ok", "crashed"]
    assert got[1]["cause"] == "exception"
    assert got[1]["why"] == "Fatal: unauthorized " + SAID
    assert got[1]["file"] is None


def test_an_answer_outside_cp1252_lands_in_its_step_file(tmp_path,
                                                         monkeypatch,
                                                         fake_cli, cp1252):
    a_flow(tmp_path, monkeypatch, "wide-chars", ["worker"])
    fake_cli(answer("saw " + SAID + "\n"))
    engine.main()
    folder = folders(tmp_path)[0]
    [line] = lines(folder)
    assert SAID in (folder / line["file"]).read_bytes().decode("utf-8")


def test_numbering_carries_on_past_a_line_cut_short(tmp_path):
    (tmp_path / trace.FILE).write_text('{"seq": 4, "step": "a.md"}\n{"seq": 5, "st',
                                       encoding="utf-8")
    t = trace.Trail(tmp_path)
    assert t.open("b.md", [], None, None).seq == 5


def gate_notes(folder):
    return (folder / "gates.md").read_text(encoding="utf-8")


def test_a_step_with_no_gates_leaves_a_line_saying_so(tmp_path, monkeypatch,
                                                      fake_cli):
    a_flow(tmp_path, monkeypatch, "two",
           ["worker\ngates:\n  - gate: length\n    max_lines: 5", "reviewer"])
    fake_cli(answer("did the thing\n"), answer("VERDICT: ok\n\nfine\n"))
    engine.main()
    [folder] = folders(tmp_path)
    assert gate_notes(folder) == ("## worker.md\nPASS length - 1 lines\n"
                                  "## reviewer.md\nno gates\n")
    first, second = lines(folder)
    assert (first["gates"] != [], first["ungated"]) == (True, False)
    assert (second["gates"], second["ungated"]) == ([], True)


def test_a_fanned_out_step_with_no_gates_says_so_once(tmp_path, monkeypatch,
                                                      fake_cli):
    a_flow(tmp_path, monkeypatch, "wide",
           ["planner", "worker\nfanout: true\nworkers: 2", "merge"])
    fake_cli(answer("a.py | look at a\nb.py | look at b\n"))
    engine.main()
    [folder] = folders(tmp_path)
    assert gate_notes(folder) == ("## planner.md\nno gates\n"
                                  "## worker.md\nno gates\n"
                                  "## merge.md\nno gates\n")
    assert [l["ungated"] for l in lines(folder)] == [True, True, True]


def test_a_failed_gate_is_not_ungated_and_the_run_stops_before_the_next(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated",
           ["worker\ngates:\n  - gate: length\n    max_lines: 1", "reviewer"])
    fake_cli(answer("one\ntwo\n"))
    engine.main()
    [folder] = folders(tmp_path)
    assert gate_notes(folder) == \
        "## worker.md\nFAIL length - 2 lines, cap is 1\n" * 2
    assert [line["ungated"] for line in lines(folder)] == [False, False]
    assert [line["step"] for line in lines(folder)] == ["worker.md"] * 2


def test_a_line_closed_before_the_gates_ran_does_not_claim_either(
        tmp_path, monkeypatch):
    """refused, paused at the cap and crashed lines never reached the check, so
    `gates: []` there says nothing about what the step declares."""
    a_flow(tmp_path, monkeypatch, "moved",
           ["worker", "reviewer\ngates:\n  - gate: length\n    max_lines: 5"],
           tail=FAKE)
    monkeypatch.setattr(engine.Run, "refused", lambda self, step:
                        "AGENTS.md changed" if step == "reviewer.md" else "")
    engine.main()
    [folder] = folders(tmp_path)
    got = lines(folder)
    assert [(l["outcome"], l["ungated"]) for l in got] == \
        [("ok", True), ("refused", None)]
    assert gate_notes(folder) == "## worker.md\nno gates\n"


def test_a_resumed_run_writes_its_own_no_gate_line(tmp_path, monkeypatch,
                                                   fake_cli):
    a_flow(tmp_path, monkeypatch, "picked", ["worker", "reviewer"])
    no_waiting(monkeypatch)
    fake_cli(answer("worked\n"), answer(""), answer(""), answer(""))
    engine.main()
    [first] = folders(tmp_path)
    fake_cli(answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "picked", "--force",
                                      "--resume", first.name])
    engine.main()
    # both runs can land in one folder when they start in the same second
    notes = "".join(gate_notes(f) for f in folders(tmp_path))
    # the first run's empty reviewer stopped before its gates were checked
    assert notes.count("## reviewer.md\nno gates\n") == 1
    assert notes.endswith("## reviewer.md\nno gates\n")
    assert every_line(tmp_path)[-1]["ungated"] is True


def test_the_server_reads_a_run_with_its_step_files(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "served", ["worker"], tail=FAKE)
    engine.main()
    run_id = folders(tmp_path)[0].name
    text = server.read_resource("flows://run/" + run_id)
    assert "## steps/001-worker.md" in text
    assert "## steps.jsonl" in text
