"""a stopped run is picked up from its own folder, not from the journal.

`runs/<run id>/manifest.json` says which steps passed, what the run spent,
what the flow and the place looked like, and which run the task started as.
`--resume <run id>` reads that folder and nothing else.
"""
import json
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.guardrails.budget import Budget
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, stops

NL = chr(10)
CHECK = [sys.executable, "-c",
         "import os, sys; sys.exit(0 if os.path.exists('ok') else 1)"]


def a_flow(tmp_path, monkeypatch, name, steps, tail="", instructions=None):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + NL + "steps:" + NL
    for role, extra in steps:
        body = body + "  - role: " + role + NL + "    prompt: " + role + ".md" + NL
        for line in extra:
            body = body + "    " + line + NL
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    if instructions is not None:
        (d / "instructions.md").write_text(instructions, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    return d


def asking(monkeypatch, answer=None):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        if answer is not None:
            return answer(step, prompt), False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def folders(tmp_path):
    runs = tmp_path / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() \
        else []


def newest(tmp_path, before):
    [made] = [p for p in folders(tmp_path) if p not in before]
    return made


def journal(tmp_path):
    return [l for l in (tmp_path / "runs" / "journal.md")
            .read_text(encoding="utf-8").split(NL) if l.strip()]


def steps_of(asked):
    return [s for s, _ in asked]


PARK_AFTER_A = [("a", ["pause: user"]), ("b", []), ("c", [])]


def test_a_gate_failing_at_step_three_and_passing_on_resume_runs_one_and_two_once(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "gated",
           [("a", []), ("b", []),
            ("c", ["gates:", "  - gate: command",
                   "    command: " + json.dumps(CHECK)])])
    asked = asking(monkeypatch)
    assert run(monkeypatch, "gated", "--force") == stops.EXIT_STOP
    [first] = folders(tmp_path)
    (tmp_path / "ok").write_text("", encoding="utf-8")
    assert run(monkeypatch, "gated", "--force", "--resume",
               first.name) == stops.EXIT_OK
    assert steps_of(asked) == ["a.md", "b.md", "c.md", "c.md", "c.md"]


def test_two_parked_runs_of_one_flow_resume_each_at_its_own_step(tmp_path,
                                                                monkeypatch):
    a_flow(tmp_path, monkeypatch, "twice",
           [("a", ["pause: user"]), ("b", ["pause: user"]), ("c", [])])
    asked = asking(monkeypatch)
    run(monkeypatch, "twice", "--force")
    older = newest(tmp_path, [])
    run(monkeypatch, "twice", "--force")
    second = newest(tmp_path, [older])
    seen = folders(tmp_path)
    run(monkeypatch, "twice", "--force", "--resume", second.name)
    # the journal's newest stop of this flow is now `parked at b.md`
    assert newest(tmp_path, seen) not in (older, second)
    asked.clear()
    run(monkeypatch, "twice", "--force", "--resume", older.name)
    assert steps_of(asked) == ["b.md"]


def test_a_later_good_run_does_not_turn_a_resume_into_a_whole_new_run(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "later",
           [("a", []), ("b", []),
            ("c", ["gates:", "  - gate: command",
                   "    command: " + json.dumps(CHECK)])])
    asked = asking(monkeypatch)
    run(monkeypatch, "later", "--force")
    stopped = newest(tmp_path, [])
    (tmp_path / "ok").write_text("", encoding="utf-8")
    # the newest line for the flow is now an ok, which used to read as
    # "nothing stopped" and rerun every step under the stopped run's name
    assert run(monkeypatch, "later", "--force") == stops.EXIT_OK
    asked.clear()
    run(monkeypatch, "later", "--force", "--resume", stopped.name)
    assert steps_of(asked) == ["c.md"]


def test_a_finished_run_has_nothing_to_pick_up(tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "done", [("a", []), ("b", [])])
    asked = asking(monkeypatch)
    run(monkeypatch, "done", "--force")
    [first] = folders(tmp_path)
    asked.clear()
    capsys.readouterr()
    assert run(monkeypatch, "done", "--force", "--resume", first.name) == 1
    assert "finished" in capsys.readouterr().out
    assert asked == []


def test_a_resume_starts_at_what_the_run_had_spent(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "capped",
           [("a", []), ("b", ["pause: user"]), ("c", [])],
           tail="max_calls: 2" + NL)
    asked = asking(monkeypatch)
    run(monkeypatch, "capped", "--force")
    [first] = folders(tmp_path)
    asked.clear()
    assert run(monkeypatch, "capped", "--force", "--resume",
               first.name) == stops.EXIT_STOP
    assert steps_of(asked) == ["c.md"]
    last = stops.read(journal(tmp_path)[-1])
    assert last.cause == stops.BUDGET
    assert last.spend.startswith("3 calls")


def test_a_run_over_its_cap_is_not_resumed_until_the_cap_moves(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    d = a_flow(tmp_path, monkeypatch, "over", [("a", []), ("b", []), ("c", [])],
               tail="max_calls: 1" + NL)
    asked = asking(monkeypatch)
    assert run(monkeypatch, "over", "--force") == stops.EXIT_STOP
    [first] = folders(tmp_path)
    asked.clear()
    capsys.readouterr()
    assert run(monkeypatch, "over", "--resume", first.name) == 1
    said = capsys.readouterr().out
    assert "max_calls" in said
    assert asked == []
    yaml = (d / "flow.yaml").read_text(encoding="utf-8")
    (d / "flow.yaml").write_text(yaml.replace("max_calls: 1", "max_calls: 9"),
                                 encoding="utf-8")
    assert run(monkeypatch, "over", "--force", "--resume",
               first.name) == stops.EXIT_OK
    # the step that went over is asked again: its answer was never checked
    assert steps_of(asked) == ["b.md", "c.md"]


def test_a_budget_stop_leaves_a_handoff(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "spent", [("a", []), ("b", [])],
           tail="max_calls: 1" + NL)
    asking(monkeypatch)
    run(monkeypatch, "spent", "--force")
    [first] = folders(tmp_path)
    note = (first / "handoff.md").read_text(encoding="utf-8")
    assert "call cap: 2 > 1" in note
    assert note.rstrip(NL).split(NL)[-1].strip() == \
        "python run.py spent --resume " + first.name + " --force"


def test_resume_followed_by_another_switch_is_not_a_run_id(tmp_path,
                                                           monkeypatch):
    a_flow(tmp_path, monkeypatch, "asks", PARK_AFTER_A,
           instructions="the ask: {TASK}" + NL)
    asked = asking(monkeypatch)
    run(monkeypatch, "asks", "--force", "--task", "the first ask")
    asked.clear()
    assert run(monkeypatch, "asks", "--resume", "--force") == stops.EXIT_OK
    assert steps_of(asked) == ["b.md", "c.md"]
    assert all("the ask: the first ask" in p for _, p in asked)


def test_an_edited_flow_is_not_resumed_without_force(tmp_path, monkeypatch,
                                                     capsys):
    d = a_flow(tmp_path, monkeypatch, "edited", PARK_AFTER_A)
    asked = asking(monkeypatch)
    run(monkeypatch, "edited")
    [first] = folders(tmp_path)
    (d / "b.md").write_text("you are a different b." + NL, encoding="utf-8")
    asked.clear()
    capsys.readouterr()
    assert run(monkeypatch, "edited", "--resume", first.name) == 1
    said = capsys.readouterr().out
    assert "b.md" in said and "--force" in said
    assert asked == []
    assert run(monkeypatch, "edited", "--resume", first.name,
               "--force") == stops.EXIT_OK
    assert steps_of(asked) == ["b.md", "c.md"]
    resumed = [p for p in folders(tmp_path) if p != first][-1]
    [said] = decisions.read(resumed)
    assert "flow" in said.decided and "b.md" in said.why


def test_an_edited_parked_output_is_written_down_as_the_operators(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fixed", PARK_AFTER_A)
    asked = asking(monkeypatch)
    run(monkeypatch, "fixed", "--force")
    [first] = folders(tmp_path)
    (first / "a.md").write_text("what the person wants instead" + NL,
                                encoding="utf-8")
    asked.clear()
    run(monkeypatch, "fixed", "--force", "--resume", first.name)
    assert "what the person wants instead" in dict(asked)["b.md"]
    resumed = [p for p in folders(tmp_path) if p != first][-1]
    [said] = decisions.read(resumed)
    assert "a.md" in said.decided


def test_the_resumed_legs_carry_the_id_the_task_started_as(tmp_path,
                                                          monkeypatch):
    a_flow(tmp_path, monkeypatch, "legs",
           [("a", ["pause: user"]), ("b", ["pause: user"]), ("c", [])])
    asking(monkeypatch)
    run(monkeypatch, "legs", "--force")
    first = newest(tmp_path, [])
    run(monkeypatch, "legs", "--force", "--resume", first.name)
    second = newest(tmp_path, [first])
    run(monkeypatch, "legs", "--force", "--resume", second.name)
    third = newest(tmp_path, [first, second])
    from agentweft.runner import manifest

    lines =[stops.read(l) for l in journal(tmp_path)]
    for line in lines:
        assert line.origin == (None if line.run == first.name else first.name)
    assert {l.run for l in lines} == {first.name, second.name, third.name}
    m = manifest.load(third)
    assert (m.origin, m.resumes) == (first.name, second.name)


def test_the_manifest_says_what_ran_what_it_cost_and_what_it_ran_on(
        tmp_path, monkeypatch):
    d = a_flow(tmp_path, monkeypatch, "kept", PARK_AFTER_A,
               instructions="the ask: {TASK}" + NL)
    asking(monkeypatch)
    run(monkeypatch, "kept", "--force", "--task", "the ask itself")
    [first] = folders(tmp_path)
    from agentweft.runner import manifest

    m = json.loads((first / manifest.FILE).read_text(encoding="utf-8"))
    assert m["run"] == first.name
    assert m["task"] == "the ask itself"
    assert [(s["step"], s["state"]) for s in m["steps"]] == \
        [("a.md", "parked"), ("b.md", "not run"), ("c.md", "not run")]
    assert m["state"] == "stopped"
    assert m["stopped"]["step"] == "a.md"
    assert m["flow_digest"] == manifest.flow_digest(d)[0]
    assert Budget().restore(m["spend"]).calls == 1


def test_a_fanned_step_that_died_runs_only_the_tasks_that_did_not_finish(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fan",
           [("planner", []), ("worker", ["fanout: true", "workers: 1"]),
            ("reviewer", [])])
    dying = [True]

    def answer(step, prompt):
        if step == "planner.md":
            return "a.py | look at a" + NL + "b.py | look at b" + NL
        if step == "worker.md":
            task = prompt.split("your task, only this one:")[1].strip()
            if task.startswith("b.py") and dying[0]:
                dying[0] = False
                raise RuntimeError("the process died")
            return "- " + task.split(" |")[0] + " looked at" + NL
        return "VERDICT: ok" + NL + NL + "done" + NL

    asked = asking(monkeypatch, answer)
    assert run(monkeypatch, "fan", "--force") == stops.EXIT_STOP
    [first] = folders(tmp_path)
    asked.clear()
    assert run(monkeypatch, "fan", "--force", "--resume",
               first.name) == stops.EXIT_OK
    assert steps_of(asked) == ["worker.md", "reviewer.md"]
    assert "b.py | look at b" in asked[0][1]
    assert "- a.py looked at" in asked[1][1]


def git(place, *args):
    subprocess.run(["git", "-C", str(place), "-c", "user.email=t@t",
                    "-c", "user.name=t"] + list(args), check=True,
                   capture_output=True)


def test_a_place_that_moved_since_the_stop_is_named_before_carrying_on(
        tmp_path, monkeypatch, capsys):
    place = tmp_path / "place"
    place.mkdir()
    git(place, "init", "-q")
    (place / "app.py").write_text("x = 1" + NL, encoding="utf-8")
    git(place, "add", "app.py")
    git(place, "commit", "-q", "-m", "one")
    a_flow(tmp_path, monkeypatch, "moved", PARK_AFTER_A)
    asking(monkeypatch)
    run(monkeypatch, "moved", "--force", "--workdir", str(place))
    [first] = folders(tmp_path)
    (place / "app.py").write_text("x = 2" + NL, encoding="utf-8")
    capsys.readouterr()
    run(monkeypatch, "moved", "--force", "--resume", first.name)
    said = capsys.readouterr().out
    assert "app.py" in said.split("picking")[0]


def test_a_journal_line_reads_back_the_run_it_resumes():
    import datetime

    when = datetime.datetime(2026, 1, 2, 3, 4)
    ran = stops.line(when, "x", stops.RUNNING, 0, run="x-2", origin="x-1")
    ok = stops.line(when, "x", "ok (resumed)", 3, run="x-2", saved="x-1.md",
                    spend="1 call", origin="x-1")
    stop = stops.line(when, "x", "failed at a.md", 3, run="x-2",
                      cause=stops.GATE, spend="1 call", why="it failed",
                      origin="x-1")
    for text in (ran, ok, stop):
        assert stops.read(text).origin == "x-1"
        assert stops.read(text).run == "x-2"
    assert stops.read(stop).why == "it failed"
    assert stops.read(ok).spend == "1 call"
