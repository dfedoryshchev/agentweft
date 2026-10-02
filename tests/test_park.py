import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.orchestrate import park
from agentweft.roles import resolver
from agentweft.runner import engine, prompts

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


def a_stubborn_reviewer(tmp_path, monkeypatch, name, after=()):
    """a worker that answers, a reviewer that says redo every time, and
    whatever steps come after it. run through main() the way it is typed."""
    flow = tmp_path / "flows" / name
    flow.mkdir(parents=True)
    body = ("name: " + name + "\n"
            "steps:\n"
            "  - role: worker\n"
            "    prompt: worker.md\n"
            "    provider:\n"
            "      provider: fake\n"
            '      reply: "- notes.md | changed\\n"\n'
            "  - role: reviewer\n"
            "    prompt: reviewer.md\n"
            "    provider:\n"
            "      provider: fake\n"
            '      reply: "VERDICT: redo\\n\\nstill wrong\\n"\n')
    for role in after:
        body = body + "  - role: " + role + "\n    prompt: " + role + ".md\n"
    (flow / "flow.yaml").write_text(body + "provider:\n  provider: fake\n",
                                    encoding="utf-8")
    (flow / "instructions.md").write_text("the " + name + " flow.\n",
                                          encoding="utf-8")
    for role in ("worker", "reviewer") + tuple(after):
        (flow / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                           encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force",
                                      "--flows", "flows"])
    engine.main()
    run_dir = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]
    journal = (tmp_path / "runs" / "journal.md").read_text().strip().split("\n")
    return run_dir, journal[-1]


def test_a_redo_past_the_cap_parks_instead_of_walking_on(tmp_path, monkeypatch):
    run_dir, line = a_stubborn_reviewer(tmp_path, monkeypatch, "stubborn",
                                        after=("merge",))
    assert line.split("  ")[2] == "parked at reviewer.md"
    assert "out of redos" in line
    assert line.split("  ")[-1] == run_dir.name
    assert not (run_dir / "merge.md").exists()
    handoff = (run_dir / park.FILE).read_text(encoding="utf-8")
    assert "stopped after  reviewer.md" in handoff
    assert "nothing failed." not in handoff
    assert "redo" in handoff


def test_a_redo_past_the_cap_on_the_last_step_is_not_an_ok_run(tmp_path,
                                                               monkeypatch):
    run_dir, line = a_stubborn_reviewer(tmp_path, monkeypatch, "stubborn-last")
    assert line.split("  ")[2] == "parked at reviewer.md"
    assert (run_dir / park.FILE).exists()
