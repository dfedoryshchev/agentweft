"""a gate that could not do its job says so in the run record: an `issue`
on its line in gates.jsonl and steps.jsonl, beside a result that stays what it
was. the retro is handed every issue, and the handoff's retro tally says it."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import shellwrite
from agentweft.guardrails.gates import base
from agentweft.guardrails.gates.base import Result
from agentweft.runner import engine, retro
from test_stops import CLAUDE, a_flow, answer, steps_of, the_folder

MISSING = "agentweft-no-such-program-here"
NOT_THERE = ("worker\ngates:\n  - gate: command\n    command: [" + MISSING
             + "]")


def gate_lines(folder):
    text = (folder / "gates.jsonl").read_text(encoding="utf-8")
    return [json.loads(l) for l in text.split("\n") if l.strip()]


def asked(fake):
    return [c["stdin"].decode("utf-8") for c in fake.calls]


def test_a_command_gate_whose_program_is_missing_records_an_issue(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "missing", [NOT_THERE], tail=CLAUDE)
    fake_cli(answer("done\n"), answer("done again\n"))
    engine.main()
    folder = the_folder()
    lines = gate_lines(folder)
    assert lines, "no gate line"
    assert all(l["issue"] == "command could not run: not on PATH: " + MISSING
               for l in lines), lines
    assert not lines[0]["ok"]
    [first] = steps_of(folder)[0]["gates"]
    assert first["issue"] == lines[0]["issue"]
    assert first["broke"] is True


def test_a_command_gate_that_times_out_records_an_issue_and_still_fails(
        tmp_path, monkeypatch, fake_cli):
    slow = ("worker\ngates:\n  - gate: command\n    command: [" + sys.executable
            .replace("\\", "/") + ", -c, 'import time; time.sleep(5)']\n"
            "    timeout: 1")
    a_flow(tmp_path, monkeypatch, "slow", [slow],
           tail="send_backs: 0\n" + CLAUDE)
    fake_cli(answer("done\n"))
    engine.main()
    [line] = gate_lines(the_folder())
    assert line["ok"] is False
    assert line["issue"] == "command could not finish: timed out after 1s"


def test_a_red_first_gate_that_could_not_replay_passes_and_says_so(
        tmp_path, monkeypatch, fake_cli):
    red = ("worker\ngates:\n  - gate: red-first\n    command: [python, -m,"
           " pytest, '{test}']")
    a_flow(tmp_path, monkeypatch, "noreplay", [red], tail=CLAUDE)
    fake_cli(answer("done\n"))
    assert engine.main() == 0
    [line] = gate_lines(the_folder())
    assert line["ok"] is True
    assert line["issue"] == ("red-first could not replay: the place is not in"
                             " a git work tree")


def test_a_gate_that_did_its_job_has_no_issue(tmp_path, monkeypatch,
                                              fake_cli):
    ok = ("worker\ngates:\n  - gate: command\n    command: ["
          + sys.executable.replace("\\", "/") + ", -c, 'pass']")
    a_flow(tmp_path, monkeypatch, "fine", [ok], tail=CLAUDE)
    fake_cli(answer("done\n"))
    assert engine.main() == 0
    [line] = gate_lines(the_folder())
    assert "issue" not in line
    assert "issue" not in steps_of(the_folder())[0]["gates"][0]


def test_an_issue_is_named_from_a_broke_flag_set_after_the_fact():
    r = Result("red-first", False, "t.py::x did not run without the fix:"
               " not on PATH")
    assert base.issue_of(r) == ""
    r.broke = True
    assert base.issue_of(r) == ("red-first could not run: t.py::x did not run"
                           " without the fix: not on PATH")
    said = Result("coverage", False, "could not read cov.xml: bad")
    said.broke = True
    assert base.issue_of(said) == "coverage could not read cov.xml: bad"


def test_the_retro_is_handed_each_gate_issue(tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "missing", [NOT_THERE],
           tail="retro: true\n" + CLAUDE)
    fake = fake_cli(answer("done\n"), answer("done again\n"),
                    answer("## change first\n"))
    engine.main()
    prompt = asked(fake)[-1]
    assert "gates that could not do their job, from steps.jsonl:" in prompt
    assert ("- seq 1 worker.md: command could not run: not on PATH: "
            + MISSING) in prompt


def test_a_run_whose_only_trouble_is_a_gate_issue_still_gets_a_retro(
        tmp_path, monkeypatch, fake_cli):
    red = ("worker\ngates:\n  - gate: red-first\n    command: [python, -m,"
           " pytest, '{test}']")
    a_flow(tmp_path, monkeypatch, "noreplay", [red],
           tail="retro: true\n" + CLAUDE)
    fake = fake_cli(answer("done\n"), answer("## change first\n"))
    assert engine.main() == 0
    assert len(fake.calls) == 2
    prompt = asked(fake)[-1]
    assert ("- seq 1 worker.md: red-first could not replay: the place is not"
            " in a git work tree") in prompt


def test_the_handoff_tally_names_the_issue(tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "missing", [NOT_THERE], tail=CLAUDE)
    fake_cli(answer("done\n"), answer("done again\n"))
    engine.main()
    note = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    retro_part = note.split("## retro")[1].split("## run")[0]
    assert ("issue: command could not run: not on PATH: " + MISSING
            in retro_part), retro_part


def test_a_step_that_went_on_after_a_refused_shell_write_is_a_workaround(
        tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    with open(folder / shellwrite.FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps({"session": "s-1", "tool": "Bash",
                            "command": "echo x > a.txt",
                            "refused": "echo x > a.txt"}) + "\n")
        f.write(json.dumps({"session": "s-other", "tool": "Bash",
                            "command": "cp a b", "refused": "cp a b"}) + "\n")
    lines = [({"seq": 3, "step": "worker.md", "outcome": "ok",
               "session": "s-1", "tasks": None}, folder),
             ({"seq": 4, "step": "reviewer.md", "outcome": "ok",
               "session": "s-2", "tasks": None}, folder)]
    assert retro.workarounds(lines) == [
        "- seq 3 worker.md went on after the shell write `echo x > a.txt`"
        " was refused"]
