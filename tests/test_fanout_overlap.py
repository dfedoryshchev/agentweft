"""a fanned step's tasks say which files each one touches, and the runner holds
them to it.

the tasks of a fanned step run side by side in one place. nothing knew which
files each one touched, so two tasks editing one file could overwrite each
other and nobody would hear of it. a task now names its files under FILES,
tasks that name the same file run one after another in plan order, and after
the fan the runner reads what changed while each task ran: a file a task did
not name, or a file two tasks wrote, stops the run and names both.
"""
import json
import sys
import threading
import time

sys.path.insert(0, ".")
from agentweft.runner import engine, fan, prompts, stops

NL = chr(10)


def block(text, *files):
    return NL.join(["TASK: " + text, "FILES:"] + ["- " + f for f in files])


def flow(tmp_path, name, workers=3):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = ("name: " + name + NL
            + "steps:" + NL
            + "  - role: planner" + NL
            + "    prompt: planner.md" + NL
            + "  - role: worker" + NL
            + "    prompt: worker.md" + NL
            + "    fanout: true" + NL
            + "    workers: " + str(workers) + NL
            + "  - role: merge" + NL
            + "    prompt: merge.md" + NL
            + "journal: true" + NL
            + "provider:" + NL
            + "  provider: fake" + NL)
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (d / "instructions.md").write_text("do the tasks." + NL, encoding="utf-8")
    for role in ("planner", "worker", "merge"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return tmp_path / "flows"


def go(tmp_path, monkeypatch, plan, work, name="fan-files", workers=3):
    """run main() with a planner that says `plan`, and a worker whose task
    `n` calls work[n](place). -> the exit code."""
    root = flow(tmp_path, name, workers)
    place = tmp_path / "place"
    place.mkdir()
    (place / "a.py").write_text("a = 1" + NL, encoding="utf-8")

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if step == "planner.md":
            return plan, False
        if step == "merge.md":
            return "merged" + NL, False
        text = prompt.split("your task, only this one:")[1].strip()
        n = int(text.split(NL)[0].split("task ")[1].split()[0])
        work.get(n, lambda p: None)(place)
        return "- task " + str(n) + " done" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force", "--flows",
                                      str(root), "--workdir", str(place)])
    monkeypatch.chdir(tmp_path)
    return engine.main()


def manifest(tmp_path):
    run = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    return json.loads((run / "manifest.json").read_text(encoding="utf-8"))


def last_line(tmp_path):
    run = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    lines = [json.loads(l) for l in (run / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]
    return lines[-1]


def test_a_task_is_a_block_with_its_files_one_per_line():
    plan = ("the plan" + NL + NL
            + block("task 1 look at a", "a.py", "./src/b.py") + NL + NL
            + block("task 2 nothing to write") + NL
            + "TASK: task 3 tidy c" + NL + "FILES:" + NL + "- c.py" + NL
            + NL + "HANDOFF" + NL + "DID:" + NL + "- planned" + NL
            + "END HANDOFF" + NL)
    got = fan.tasks(plan)
    assert [t.files for t in got] == [("a.py", "src/b.py"), (), ("c.py",)]
    assert got[0].text == block("task 1 look at a", "a.py", "./src/b.py")
    assert got[2].text == block("task 3 tidy c", "c.py")


def test_a_line_with_a_bar_is_not_a_task_any_more():
    assert fan.tasks("a.py | look at a" + NL + "b.py | look at b" + NL) == []


def test_tasks_that_name_one_file_run_in_turn_in_plan_order(
        tmp_path, monkeypatch):
    seen = []
    both = threading.Barrier(2, timeout=5)

    def task(n, wait=False):
        def run(place):
            seen.append(("start", n))
            if wait:
                # the task on c.py has to be running beside this one
                both.wait()
            time.sleep(0.2)
            seen.append(("end", n))
        return run

    plan = (block("task 1 a", "a.py") + NL + NL
            + block("task 2 a again", "a.py") + NL + NL
            + block("task 3 c", "c.py") + NL)
    code = go(tmp_path, monkeypatch, plan,
              {1: task(1, wait=True), 2: task(2), 3: task(3, wait=True)})
    assert code == stops.EXIT_OK
    ones = [e for e in seen if e[1] in (1, 2)]
    assert ones == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]
    assert manifest(tmp_path)["outcome"] == "done"


def test_a_task_that_writes_a_file_it_did_not_name_fails_the_run(
        tmp_path, monkeypatch, capsys):
    def writes(place):
        (place / "a.py").write_text("a = 2" + NL, encoding="utf-8")
        (place / "c.py").write_text("c = 1" + NL, encoding="utf-8")

    plan = block("task 1 a", "a.py") + NL + NL + block("task 2 b", "b.py") + NL
    code = go(tmp_path, monkeypatch, plan, {1: writes}, workers=1)
    assert code == stops.EXIT_STOP
    assert manifest(tmp_path)["outcome"] == "stopped: tasks overlap"
    last = last_line(tmp_path)
    assert last["step"] == "worker.md" and last["cause"] == stops.OVERLAP
    assert "task 1 wrote c.py, which it did not name" in last["why"]
    assert "a.py" not in last["why"]
    assert "merge.md" not in capsys.readouterr().out.split("tasks overlap")[0]


def test_two_tasks_that_write_one_file_fail_the_run(tmp_path, monkeypatch):
    def writes(n):
        def run(place):
            (place / "a.py").write_text("a = " + str(n + 10) + NL,
                                        encoding="utf-8")
        return run

    plan = (block("task 1 a", "a.py") + NL + NL
            + block("task 2 a too", "a.py") + NL)
    code = go(tmp_path, monkeypatch, plan, {1: writes(1), 2: writes(2)})
    assert code == stops.EXIT_STOP
    assert manifest(tmp_path)["outcome"] == "stopped: tasks overlap"
    assert "a.py was written by task 1 and task 2" in last_line(tmp_path)["why"]


def test_tasks_that_keep_to_their_files_get_through(tmp_path, monkeypatch):
    """one worker runs one task at a time, so every write is its own task's.
    side by side, which task wrote a file cannot be told."""
    def writes(name):
        def run(place):
            (place / name).write_text("x = 1" + NL, encoding="utf-8")
        return run

    plan = block("task 1 a", "a.py") + NL + NL + block("task 2 b", "b.py") + NL
    code = go(tmp_path, monkeypatch, plan,
              {1: writes("a.py"), 2: writes("b.py")}, workers=1)
    assert code == stops.EXIT_OK
    assert manifest(tmp_path)["outcome"] == "done"


def test_an_unnamed_write_to_a_file_a_task_beside_it_named_is_caught(
        tmp_path, monkeypatch):
    """hashes cannot say which of two tasks running side by side wrote a
    file, so the change is not put on the one that named it."""
    both = threading.Barrier(2, timeout=5)

    def one(place):
        both.wait()
        both.wait()

    def two(place):
        both.wait()
        (place / "a.py").write_text("a = 99" + NL, encoding="utf-8")
        both.wait()

    plan = block("task 1 a", "a.py") + NL + NL + block("task 2 b", "b.py") + NL
    code = go(tmp_path, monkeypatch, plan, {1: one, 2: two})
    assert code == stops.EXIT_STOP, manifest(tmp_path)["outcome"]
    why = last_line(tmp_path)["why"]
    assert ("a.py changed while task 1 and task 2 ran side by side, and task 2"
            " did not name it") in why


def test_an_unnamed_write_while_two_tasks_ran_names_both_once(
        tmp_path, monkeypatch):
    both = threading.Barrier(2, timeout=5)

    def one(place):
        both.wait()
        both.wait()

    def two(place):
        both.wait()
        (place / "c.py").write_text("c = 1" + NL, encoding="utf-8")
        both.wait()

    plan = block("task 1 a", "a.py") + NL + NL + block("task 2 b", "b.py") + NL
    assert go(tmp_path, monkeypatch, plan, {1: one, 2: two}) == stops.EXIT_STOP
    assert last_line(tmp_path)["why"] == (
        "c.py changed while task 1 and task 2 ran side by side, and neither"
        " named it")


def test_a_resumed_fan_does_not_wave_through_an_overlap(tmp_path, monkeypatch):
    def writes(place):
        (place / "c.py").write_text("c = 1" + NL, encoding="utf-8")

    plan = block("task 1 a", "a.py") + NL
    assert go(tmp_path, monkeypatch, plan, {1: writes}) == stops.EXIT_STOP
    first = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    monkeypatch.setattr(sys, "argv", list(sys.argv) + ["--resume", first.name])
    code = engine.main()
    assert (tmp_path / "place" / "c.py").exists()
    assert code == stops.EXIT_STOP
    assert "c.py changed since worker.md first started" in last_line_of(
        tmp_path, newest=True)["why"]


def test_a_resumed_fan_whose_stray_file_was_taken_out_gets_through(
        tmp_path, monkeypatch):
    def writes(place):
        (place / "c.py").write_text("c = 1" + NL, encoding="utf-8")

    plan = block("task 1 a", "a.py") + NL
    work = {1: writes}
    assert go(tmp_path, monkeypatch, plan, work) == stops.EXIT_STOP
    first = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    (tmp_path / "place" / "c.py").unlink()
    work.clear()
    monkeypatch.setattr(sys, "argv", list(sys.argv) + ["--resume", first.name])
    assert engine.main() == stops.EXIT_OK


def last_line_of(tmp_path, newest=False):
    runs = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())
    run = runs[-1] if newest else runs[0]
    lines = [json.loads(l) for l in (run / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]
    return lines[-1]


def test_files_name_the_same_path_however_they_spell_it(monkeypatch):
    plan = (block("task 1", "src/../a.py") + NL + NL + block("task 2", "a.py")
            + NL)
    assert len(fan.turns(fan.tasks(plan))) == 1
    monkeypatch.setattr(fan, "FOLD", True)
    plan = (block("task 1", "src/A.py") + NL + NL + block("task 2", "src/a.py")
            + NL)
    assert len(fan.turns(fan.tasks(plan))) == 1


def test_a_write_is_held_to_the_file_as_the_place_spells_it(monkeypatch):
    monkeypatch.setattr(fan, "FOLD", True)
    [t] = fan.tasks(block("task 1", "src/A.py"))
    w = fan.Window(t, 0, {"src/a.py": "x"})
    w.after, w.ended = {"src/a.py": "y"}, 1
    assert fan.check([w]) == ""


def test_files_after_a_blank_line_still_belong_to_their_task():
    plan = "TASK: tidy a" + NL + NL + "FILES:" + NL + "- a.py" + NL
    [t] = fan.tasks(plan)
    assert t.files == ("a.py",)


def test_the_eval_path_stops_on_an_overlap_too(tmp_path, monkeypatch):
    root = flow(tmp_path, "fan-once")
    place = tmp_path / "place"
    place.mkdir()

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if step == "planner.md":
            return block("task 1 a", "a.py") + NL, False
        (place / "c.py").write_text("c = 1" + NL, encoding="utf-8")
        return "done" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.chdir(tmp_path)
    _, _, why = engine.run_once("fan-once", workdir=str(place))
    assert why == ("tasks overlap at worker.md: task 1 wrote c.py, which it"
                   " did not name")


def test_the_audit_planner_caps_tasks_not_lines():
    said = (fan_repo() / "flows" / "repo-audit" / "planner.md").read_text(
        encoding="utf-8")
    assert "at most 20 tasks" in said
    assert "20 lines" not in said


def fan_repo():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent
