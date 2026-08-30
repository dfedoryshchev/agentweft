import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.orchestrate import park
from agentweft.roles import resolver
from agentweft.runner import engine

DONE = [("planner.md", 3), ("worker.md", 12)]


def a_handoff(left=None, command="python run.py demo --resume demo-1"):
    return park.lines("demo-1", "demo flow", "worker.md", "user", DONE,
                      ["reviewer.md"] if left is None else left, command)


def test_the_handoff_says_what_ran_where_it_stopped_and_why():
    text = "\n".join(a_handoff())
    assert "# parked: demo-1" in text
    assert "waiting for    user" in text
    assert "flow           demo flow" in text
    assert "stopped after  worker.md" in text
    # the whole reason the file exists: this is a stop, not a failure
    assert "nothing failed." in text


def test_it_lists_what_ran_and_what_is_left():
    text = "\n".join(a_handoff())
    assert "  planner.md      3s" in text
    assert "  worker.md       12s" in text
    assert "  reviewer.md" in text


def test_nothing_left_is_still_written_as_a_word():
    assert "  nothing" in "\n".join(a_handoff(left=[]))


def test_it_points_at_the_file_the_next_step_would_have_been_handed():
    assert "runs/demo-1/worker.md" in "\n".join(a_handoff())


def test_the_last_thing_it_says_is_the_command_to_type():
    lines = a_handoff(command="python run.py demo --resume demo-1 --force")
    assert lines[-2] == "to carry on"
    assert lines[-1] == "  python run.py demo --resume demo-1 --force"


def test_it_lands_beside_the_step_outputs(tmp_path):
    path = park.write("demo-1", "demo flow", "worker.md", "user", DONE,
                      ["reviewer.md"], "python run.py demo --resume demo-1",
                      runs=tmp_path)
    assert path == tmp_path / "demo-1" / "handoff.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# parked: demo-1")
    assert text.endswith("\n")


def test_the_command_carries_the_switches_the_run_was_started_with(monkeypatch):
    """it is printed to be typed, so a switch this run needs has to come along
    or the command in the handoff is one you have to fix before you can use it.
    """
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "demo", "--force", "--flows", "tmp/flows"])
    assert engine.resume_command("demo", "demo-1") == \
        "python run.py demo --resume demo-1 --force --flows tmp/flows"
    monkeypatch.setattr(sys, "argv", ["run.py", "demo"])
    assert engine.resume_command("demo", "demo-1") == \
        "python run.py demo --resume demo-1"


def test_a_step_says_who_the_run_waits_for_once_it_is_done():
    fm = runner.config("summarise-and-check")
    by_role = resolver.resolve(fm.raw, runner.flow_path("summarise-and-check"))
    run = runner.Run("summarise-and-check", fm, by_role)
    run.fm = spec.load({"name": "x", "steps": [
        {"role": "worker"},
        {"role": "reviewer", "pause": "user"},
    ]})
    assert run.pause_for("reviewer.md") == "user"
    assert run.pause_for("worker.md") is None
    assert run.pause_for("gone.md") is None
