"""a run pointed at a task from the command line, without editing the flow.

`--task "<text>"` or `--task-file <path>` puts the text wherever the flow wrote
{TASK}, records it beside the run, and a resume carries on with it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import park
from agentweft.runner import cli, engine, prompts

FLOWS = Path(__file__).resolve().parents[1] / "flows"
# an en dash, a CJK word and a Cyrillic word: cp1252 has no byte for the last two
FOREIGN = "the total is off by one " + chr(0x2013) + " " + chr(0x6f22) \
    + chr(0x5b57) + " " + chr(0x41f) + chr(0x440) + chr(0x438)


def a_flow(tmp_path, monkeypatch, name, files, steps=None, yaml_tail="",
           instructions="one flow, many tasks.\n"):
    """a throwaway flow under tmp_path/flows, run from tmp_path.

    `files` maps a prompt file to its words; `steps` is the yaml under
    `steps:` (default: one step per file, role taken from the file name)."""
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    if steps is None:
        steps = "".join("  - role: " + f[:-3] + "\n    prompt: " + f + "\n"
                        for f in files)
    (d / "flow.yaml").write_text("name: " + name + "\nsteps:\n" + steps
                                 + yaml_tail, encoding="utf-8")
    for f, words in files.items():
        (d / f).write_text(words, encoding="utf-8")
    if instructions is not None:
        (d / "instructions.md").write_text(instructions, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    return d


def asking(monkeypatch, answers=None):
    """-> [(step, prompt)] every call the run made, answered from `answers`."""
    asked = []
    answers = answers or {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        return answers.get(step, "VERDICT: ok\n\ndone\n"), False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def folders(tmp_path):
    runs = tmp_path / "runs"
    if not runs.exists():
        return []
    return sorted(p for p in runs.iterdir() if p.is_dir())


WORKER = "# worker\n\nhere is the bug:\n\n{TASK}\n\nwrite a test for it.\n"


def test_the_task_reaches_the_step_that_says_where_it_goes(tmp_path,
                                                           monkeypatch):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER,
                                          "reviewer.md": "# reviewer\n"})
    asked = asking(monkeypatch)
    run(monkeypatch, "fix", "--force", "--task", "add(1, 2) returns -1")
    prompt = dict(asked)["worker.md"]
    assert "here is the bug:\n\nadd(1, 2) returns -1\n\nwrite a test" in prompt
    assert "{TASK}" not in prompt
    assert "add(1, 2)" not in dict(asked)["reviewer.md"]


def test_a_task_file_is_read_as_utf8_whatever_the_locale(tmp_path, monkeypatch,
                                                          cp1252):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    (tmp_path / "bug.md").write_bytes(FOREIGN.encode("utf-8"))
    asked = asking(monkeypatch)
    run(monkeypatch, "fix", "--force", "--task-file", "bug.md")
    assert FOREIGN in dict(asked)["worker.md"]
    [folder] = folders(tmp_path)
    assert (folder / "task.md").read_bytes() == FOREIGN.encode("utf-8")


def test_a_task_file_saved_with_a_bom_and_crlf_arrives_as_the_text(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    (tmp_path / "bug.md").write_bytes(b"\xef\xbb\xbfline one\r\nline two\r\n")
    asked = asking(monkeypatch)
    run(monkeypatch, "fix", "--force", "--task-file", "bug.md")
    prompt = dict(asked)["worker.md"]
    assert "here is the bug:\n\nline one\nline two\n" in prompt
    assert chr(0xfeff) not in prompt and "\r" not in prompt


def test_a_long_task_arrives_whole_and_the_step_record_names_the_file(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    long = "".join("line " + str(i) + " of the report\n" for i in range(5000))
    (tmp_path / "bug.md").write_text(long, encoding="utf-8")
    asked = asking(monkeypatch)
    run(monkeypatch, "fix", "--force", "--task-file", "bug.md")
    assert long in dict(asked)["worker.md"]
    [folder] = folders(tmp_path)
    assert (folder / "task.md").read_bytes().decode("utf-8") == long
    [line] = [json.loads(l) for l in (folder / "steps.jsonl").read_bytes()
              .decode("utf-8").split("\n") if l.strip()]
    assert line["task_file"] == "task.md"
    assert len(json.dumps(line)) < 2000


def test_a_run_with_no_task_records_none(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "plain", {"worker.md": "# worker\n"})
    asking(monkeypatch)
    run(monkeypatch, "plain", "--force")
    [folder] = folders(tmp_path)
    assert not (folder / "task.md").exists()
    [line] = [json.loads(l) for l in (folder / "steps.jsonl").read_bytes()
              .decode("utf-8").split("\n") if l.strip()]
    assert line["task_file"] is None


@pytest.mark.parametrize("argv,says", [
    (["--task", "a", "--task-file", "bug.md"], "give one"),
    (["--task", ""], "is empty"),
    (["--task", "  \n\t "], "is empty"),
    (["--task"], "--task needs"),
    (["--task-file"], "--task-file needs"),
    (["--task-file", "nowhere.md"], "no such file"),
    (["--task-file", "empty.md"], "is empty"),
    (["--task-file", "latin1.md"], "not UTF-8"),
])
def test_a_task_given_wrongly_is_refused_before_any_call(tmp_path, monkeypatch,
                                                         capsys, argv, says):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    (tmp_path / "bug.md").write_text("a bug\n", encoding="utf-8")
    (tmp_path / "empty.md").write_bytes(b"")
    (tmp_path / "latin1.md").write_bytes("caf\xe9 crashes".encode("latin-1"))
    asked = asking(monkeypatch)
    assert run(monkeypatch, "fix", "--force", *argv) == 1
    assert says in capsys.readouterr().out
    assert asked == []
    assert folders(tmp_path) == []


def test_a_task_for_a_flow_with_nowhere_to_put_it_is_refused(tmp_path,
                                                            monkeypatch,
                                                            capsys):
    a_flow(tmp_path, monkeypatch, "plain", {"worker.md": "# worker\n"})
    asked = asking(monkeypatch)
    assert run(monkeypatch, "plain", "--force", "--task", "fix it") == 1
    said = capsys.readouterr().out
    assert "plain has no place for a task" in said
    assert "{TASK}" in said and "instructions.md" in said
    assert asked == [] and folders(tmp_path) == []


def test_a_flow_with_a_place_for_a_task_will_not_start_without_one(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    asked = asking(monkeypatch)
    assert run(monkeypatch, "fix", "--force") == 1
    said = capsys.readouterr().out
    assert "fix takes a task" in said and "worker.md" in said
    assert "--task" in said and "--task-file" in said
    assert asked == [] and folders(tmp_path) == []


FAN = ("  - role: planner\n    prompt: planner.md\n"
       "  - role: worker\n    prompt: worker.md\n    fanout: true\n"
       "  - role: reviewer\n    prompt: reviewer.md\n")
PLAN = "a.py | the entry point\nb.py | the settings\n"


def test_in_a_fanout_the_task_goes_where_the_flow_put_it_and_no_further(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fan",
           {"planner.md": "# planner\n\nthe ask:\n\n{TASK}\n",
            "worker.md": "# worker\n", "reviewer.md": "# reviewer\n"},
           steps=FAN)
    asked = asking(monkeypatch, {"planner.md": PLAN})
    run(monkeypatch, "fan", "--force", "--task", "audit the settings code")
    steps = [s for s, _ in asked]
    assert steps.count("worker.md") == 2
    for step, prompt in asked:
        assert ("audit the settings code" in prompt) == (step == "planner.md")


def test_a_task_in_instructions_md_reaches_every_step(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fan",
           {"planner.md": "# planner\n", "worker.md": "# worker\n",
            "reviewer.md": "# reviewer\n"},
           steps=FAN, instructions="the ask, for everyone: {TASK}\n")
    asked = asking(monkeypatch, {"planner.md": PLAN})
    run(monkeypatch, "fan", "--force", "--task", "audit the settings code")
    assert len(asked) == 4
    assert all("for everyone: audit the settings code" in p for _, p in asked)


def test_a_task_is_put_in_as_written_not_substituted_again(tmp_path,
                                                           monkeypatch):
    monkeypatch.setenv("INBOX", "/the/inbox")
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    asked = asking(monkeypatch)
    run(monkeypatch, "fix", "--force", "--task", "the {INBOX} path and {TASK}")
    assert "here is the bug:\n\nthe {INBOX} path and {TASK}\n" in \
        dict(asked)["worker.md"]


PARKS = ("  - role: worker\n    prompt: worker.md\n    pause: user\n"
         "  - role: reviewer\n    prompt: reviewer.md\n")


def test_a_parked_run_names_its_task_and_resumes_on_it_without_being_told(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "held",
           {"worker.md": "# worker\n", "reviewer.md": "# reviewer\n"},
           steps=PARKS, instructions="the ask: {TASK}\n")
    asked = asking(monkeypatch, {"worker.md": "did it\n"})
    run(monkeypatch, "held", "--force", "--task", FOREIGN + "\nmore detail")
    [first] = folders(tmp_path)
    handoff = (first / "handoff.md").read_text(encoding="utf-8")
    assert "- task: " + FOREIGN + " (all of it in runs/" + first.name \
        + "/task.md)\n" in handoff
    assert " on: " + FOREIGN + ".\n" in handoff
    needs = handoff.split("## needs you\n")[1].split("\n## ")[0]
    assert needs.rstrip("\n").split("\n")[-2] == "to carry on"

    asked.clear()
    run(monkeypatch, "held", "--force", "--resume", first.name)
    assert [s for s, _ in asked] == ["reviewer.md"]
    assert "the ask: " + FOREIGN + "\nmore detail" in asked[0][1]
    for folder in folders(tmp_path):
        assert (folder / "task.md").read_bytes().decode("utf-8") == \
            FOREIGN + "\nmore detail"


def test_a_resume_told_a_different_task_is_refused(tmp_path, monkeypatch,
                                                   capsys):
    a_flow(tmp_path, monkeypatch, "held",
           {"worker.md": "# worker\n", "reviewer.md": "# reviewer\n"},
           steps=PARKS, instructions="the ask: {TASK}\n")
    asked = asking(monkeypatch, {"worker.md": "did it\n"})
    run(monkeypatch, "held", "--force", "--task", "the first ask")
    [first] = folders(tmp_path)
    asked.clear()
    capsys.readouterr()
    assert run(monkeypatch, "held", "--force", "--resume", first.name,
               "--task", "another ask") == 1
    assert "started on another task" in capsys.readouterr().out
    assert asked == []


def test_the_same_task_on_a_resume_is_not_a_conflict(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "held",
           {"worker.md": "# worker\n", "reviewer.md": "# reviewer\n"},
           steps=PARKS, instructions="the ask: {TASK}\n")
    asked = asking(monkeypatch, {"worker.md": "did it\n"})
    run(monkeypatch, "held", "--force", "--task", "the first ask")
    [first] = folders(tmp_path)
    asked.clear()
    run(monkeypatch, "held", "--force", "--resume", first.name, "--task",
        "the first ask")
    assert [s for s, _ in asked] == ["reviewer.md"]


def test_a_flow_folder_with_no_instructions_md_runs(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "bare", {"worker.md": WORKER},
           instructions=None)
    asked = asking(monkeypatch)
    run(monkeypatch, "bare", "--force", "--task", "it crashes on empty input")
    assert "it crashes on empty input" in dict(asked)["worker.md"]


def test_instructions_md_is_read_as_utf8(tmp_path, monkeypatch, cp1252):
    a_flow(tmp_path, monkeypatch, "plain", {"worker.md": "# worker\n"},
           instructions=FOREIGN + "\n")
    asked = asking(monkeypatch)
    run(monkeypatch, "plain", "--force")
    assert FOREIGN in dict(asked)["worker.md"]


def test_the_shipped_fix_with_test_worker_is_where_its_bug_goes(monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    from agentweft.runner import task
    from agentweft.runner.config import config
    assert task.places(prompts.flow_path("fix-with-test"),
                       config("fix-with-test")) == ["worker.md"]
    words = prompts.load_prompt("fix-with-test", "worker.md", "", "worker",
                                task="add(1, 2) returns -1")
    assert "add(1, 2) returns -1" in words.split("do not fix it")[1]


def test_show_says_where_a_flow_takes_its_task(monkeypatch, capsys):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(sys, "argv", ["run.py", "show", "fix-with-test"])
    cli.cmd_show()
    assert "  task: {TASK} in worker.md" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["run.py", "show", "code-review"])
    cli.cmd_show()
    assert "task:" not in capsys.readouterr().out


def test_help_names_both_switches(capsys):
    cli.cmd_help()
    said = capsys.readouterr().out
    assert "--task" in said and "--task-file" in said and "{TASK}" in said


def test_one_step_on_its_own_takes_a_task_too(tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    asked = asking(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run.py", "step", "fix", "worker",
                                      "--task", "it rounds down"])
    # nothing piped in: the step is not handed an earlier step's output
    monkeypatch.setattr("os.isatty", lambda fd: True)
    cli.cmd_step()
    assert "here is the bug:\n\nit rounds down\n" in dict(asked)["worker.md"]


def test_the_handoff_lines_leave_out_a_task_the_run_did_not_have():
    from agentweft.runner import summary

    needs = park.lines("worker.md", "user", [], [],
                       "python run.py demo --resume demo-1")
    text = "\n".join(summary.build(
        "demo-1", "demo", None, [], {"git": False}, [], "",
        stopped={"cause": "parked", "why": "waiting for user",
                 "at": "worker.md"}, needs=needs))
    assert "task" not in text
    assert "to carry on\n  python run.py demo --resume demo-1\n" in text


def test_run_once_takes_a_task(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "fix", {"worker.md": WORKER})
    asked = asking(monkeypatch)
    engine.run_once("fix", task="the export drops a row")
    assert "the export drops a row" in dict(asked)["worker.md"]
