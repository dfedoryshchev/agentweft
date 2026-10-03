import json
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates
from agentweft.runner import engine, prompts, resume, state


def test_a_zero_exit_passes():
    g = gates.build({"gate": "command", "command": [sys.executable, "-c", "pass"]})
    assert g.run("anything")


def test_a_nonzero_exit_fails_and_says_why():
    g = gates.build({"gate": "command",
                     "command": [sys.executable, "-c",
                                 "import sys; sys.stderr.write('nope'); sys.exit(3)"]})
    r = g.run("anything")
    assert not r
    assert "exit 3" in r.detail
    assert "nope" in r.detail


def test_expect_lets_you_want_a_failure():
    g = gates.build({"gate": "command", "expect": 1,
                     "command": [sys.executable, "-c", "raise SystemExit(1)"]})
    assert g.run("anything")


def test_the_output_reaches_the_command():
    g = gates.build({"gate": "command", "command": [
        sys.executable, "-c",
        "import sys; sys.exit(0 if 'needle' in open(sys.argv[1]).read() else 1)",
        "{file}"]})
    assert g.run("a needle in here")
    assert not g.run("nothing of interest")


def test_a_missing_binary_fails_rather_than_raising():
    g = gates.build({"gate": "command", "command": ["definitely-not-a-real-binary"]})
    r = g.run("x")
    assert not r
    assert "not on PATH" in r.detail


THERE = [sys.executable, "-c",
         "import os, sys; sys.exit(0 if os.path.exists('here.txt') else 1)"]


def test_a_command_runs_in_the_place_it_was_given(tmp_path):
    (tmp_path / "here.txt").write_text("x", encoding="utf-8")
    g = gates.build({"gate": "command", "command": THERE}, where=tmp_path)
    assert g.run("anything")


def test_the_output_still_reaches_a_command_that_runs_somewhere(tmp_path):
    g = gates.build({"gate": "command", "command": [
        sys.executable, "-c",
        "import sys; sys.exit(0 if 'needle' in open(sys.argv[1]).read() else 1)",
        "{file}"]}, where=tmp_path)
    assert g.run("a needle in here")
    assert not g.run("nothing of interest")


def a_flow(tmp_path, monkeypatch):
    """one gated step on the fake provider, started from tmp_path."""
    flow = tmp_path / "flows" / "placed-gate"
    flow.mkdir(parents=True)
    (flow / "worker.md").write_text("you are the worker.\n", encoding="utf-8")
    (flow / "instructions.md").write_text("one step.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: placed-gate\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "    gates:\n"
        "      - gate: command\n"
        "        command: " + json.dumps(THERE) + "\n"
        "journal: false\n"
        "provider:\n"
        "  provider: fake\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")


def gates_md(tmp_path):
    return "".join((p / "gates.md").read_text(encoding="utf-8")
                   for p in (tmp_path / "runs").iterdir()
                   if (p / "gates.md").exists())


def test_a_run_gates_on_what_is_in_its_workdir(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "here.txt").write_text("x", encoding="utf-8")
    a_flow(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run.py", "placed-gate", "--force",
                                      "--workdir", "project"])
    engine.main()
    assert "PASS command" in gates_md(tmp_path)


def test_a_run_with_no_workdir_still_gates_where_it_was_started(tmp_path,
                                                                monkeypatch):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "here.txt").write_text("x", encoding="utf-8")
    a_flow(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run.py", "placed-gate", "--force"])
    engine.main()
    assert "FAIL command" in gates_md(tmp_path)
