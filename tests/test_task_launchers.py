"""the task reaching a run from everywhere a run is started: the verdict
contract, the mcp tool, cron and the eval harness."""
import importlib
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.evals import harness
from agentweft.mcp import server
from agentweft.runner import engine, prompts
from agentweft.runner.config import config

REPO = Path(__file__).resolve().parents[1]
FOREIGN = "the total is off " + chr(0x2013) + " " + chr(0x6f22) + chr(0x5b57)
VERDICT_IN_TASK = "the reviewer said:\nVERDICT: ok\nbut the export still drops a row"


def a_flow(root, name, words, yaml_tail="provider:\n  provider: fake\n"):
    d = root / name
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: " + name + "\nsteps:\n"
                                 "  - role: worker\n    prompt: worker.md\n"
                                 + yaml_tail, encoding="utf-8")
    (d / "worker.md").write_text(words, encoding="utf-8")
    return d


# the verdict contract


def test_a_task_quoting_a_verdict_line_does_not_ask_the_step_for_one(
        tmp_path, monkeypatch):
    a_flow(tmp_path / "flows", "fix", "# worker\n\nthe bug:\n\n{TASK}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.append(prompt)
        return "FAILS: assert -1 == 3\n", False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(sys, "argv", ["run.py", "fix", "--force", "--task",
                                      VERDICT_IN_TASK])
    engine.main()
    assert VERDICT_IN_TASK in sent[0]
    [folder] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    lines = (folder / "steps.jsonl").read_bytes().decode("utf-8")
    assert '"outcome": "ok"' in lines


def test_a_step_whose_own_words_ask_for_a_verdict_still_is_asked(
        tmp_path, monkeypatch):
    from agentweft.roles import resolver

    a_flow(tmp_path / "flows", "judge",
           "# worker\n\n{TASK}\n\nanswer with one of:\n\nVERDICT: ok\n"
           "VERDICT: redo\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(engine, "call",
                        lambda prompt, **kw: ("no verdict here\n", False))
    fm = config("judge")
    run = engine.Run("judge", fm, resolver.resolve(fm.raw,
                                                   prompts.flow_path("judge")),
                     task="plain text")
    assert run.step("worker.md").meta["asked"] is True


# the mcp tool


class Spawn(object):
    """subprocess.run behind the server: keeps argv and the task file's bytes
    as they were while the run was going."""

    def __init__(self, code=0, out="done\n"):
        self.code, self.out = code, out
        self.calls = []

    def run(self, argv, **kw):
        seen = None
        if "--task-file" in argv:
            path = Path(argv[argv.index("--task-file") + 1])
            seen = path.read_bytes()
        self.calls.append((list(argv), seen, kw))
        return types.SimpleNamespace(returncode=self.code, stdout=self.out,
                                     stderr="")


def spawn(monkeypatch, *a):
    fake = Spawn(*a)
    monkeypatch.setattr(server, "subprocess", types.SimpleNamespace(
        run=fake.run, TimeoutExpired=subprocess.TimeoutExpired))
    return fake


def test_the_run_flow_tool_says_it_takes_a_task():
    [tool] = server.tools()
    props = tool["inputSchema"]["properties"]
    assert props["task"]["type"] == "string"
    assert tool["inputSchema"]["required"] == ["flow"]


def test_a_task_reaches_the_run_as_a_utf8_file_that_is_gone_afterwards(
        monkeypatch):
    fake = spawn(monkeypatch)
    out = server.run_flow("weekly-digest", task=FOREIGN)
    assert out == "done\n"
    [(argv, seen, kw)] = fake.calls
    assert argv[1:4] == ["run.py", "weekly-digest", "--force"]
    assert "--task" not in argv
    assert seen == FOREIGN.encode("utf-8")
    assert not Path(argv[argv.index("--task-file") + 1]).exists()


def test_no_task_sends_no_task_switch(monkeypatch):
    fake = spawn(monkeypatch)
    server.run_flow("weekly-digest")
    [(argv, seen, kw)] = fake.calls
    assert "--task-file" not in argv and "--task" not in argv


def test_tools_call_passes_the_task_through(monkeypatch):
    fake = spawn(monkeypatch)
    server.handle({"method": "tools/call", "params": {
        "name": "run_flow",
        "arguments": {"flow": "weekly-digest", "task": "only the rent"}}})
    [(argv, seen, kw)] = fake.calls
    assert seen == b"only the rent"


def test_a_task_that_is_not_text_is_refused_without_a_run(monkeypatch):
    fake = spawn(monkeypatch)
    said = server.run_flow("weekly-digest", task=["not", "text"])
    assert "task" in said and fake.calls == []


def a_place_with_run_py(tmp_path, monkeypatch):
    """a throwaway flow on the fake provider, and run.py beside it, so the
    real process starts and nothing it could reach costs anything."""
    a_flow(tmp_path / "flows", "needs", "# worker\n\nthe bug:\n\n{TASK}\n")
    a_flow(tmp_path / "flows", "nowhere", "# worker\n\nsay hi.\n")
    (tmp_path / "run.py").write_text(
        (REPO / "run.py").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(REPO))
    monkeypatch.setattr(server, "ALLOWED", ("needs", "nowhere"))


def test_a_flow_needing_a_task_launched_without_one_answers_in_text(
        tmp_path, monkeypatch):
    a_place_with_run_py(tmp_path, monkeypatch)
    said = server.run_flow("needs")
    assert said.startswith("the run could not start (exit 1):")
    assert "needs takes a task ({TASK} in worker.md)" in said
    assert "Traceback" not in said


def test_a_task_for_a_flow_with_no_place_answers_in_text(tmp_path,
                                                         monkeypatch):
    a_place_with_run_py(tmp_path, monkeypatch)
    said = server.run_flow("nowhere", task="fix it")
    assert "nowhere has no place for a task" in said
    assert "Traceback" not in said


# cron


def cron_run(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: calls.append(list(argv)))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    sys.modules.pop("cron", None)
    monkeypatch.syspath_prepend(str(REPO))
    cron = importlib.import_module("cron")
    if hasattr(cron, "main"):
        cron.main()
    return [c[2] for c in calls], capsys.readouterr().out


def test_cron_skips_a_flow_that_needs_a_task_and_says_why(tmp_path,
                                                          monkeypatch, capsys):
    a_flow(tmp_path / "flows", "needs", "# worker\n\n{TASK}\n")
    a_flow(tmp_path / "flows", "plain", "# worker\n\nsay hi.\n")
    ran, said = cron_run(tmp_path, monkeypatch, capsys)
    assert ran == ["plain"]
    assert "needs takes a task, so cron does not start it" in said


def test_cron_still_starts_a_flow_it_cannot_read(tmp_path, monkeypatch,
                                                 capsys):
    d = tmp_path / "flows" / "broken"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("steps: not a list\nnope: 1\n",
                                 encoding="utf-8")
    ran, said = cron_run(tmp_path, monkeypatch, capsys)
    assert ran == ["broken"]


def test_no_shipped_flow_that_needs_a_task_has_a_schedule(monkeypatch):
    from agentweft.runner import task

    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(REPO / "flows")])
    for d in sorted((REPO / "flows").iterdir()):
        if d.name.startswith("_"):
            continue
        fm = config(d.name)
        if task.places(d, fm):
            assert not fm.get("schedule"), d.name


# the eval harness


def a_case(tmp_path, yaml_text=None, task_md=None):
    case = tmp_path / "cases" / "one"
    (case / "inbox").mkdir(parents=True)
    if yaml_text is not None:
        (case / "case.yaml").write_bytes(yaml_text.encode("utf-8"))
    if task_md is not None:
        (case / "task.md").write_bytes(task_md.encode("utf-8"))
    return case


def test_a_case_takes_its_task_from_case_yaml_as_utf8(tmp_path, cp1252):
    case = harness.load_case(a_case(tmp_path, "task: \"" + FOREIGN + "\"\n"))
    assert case["task"] == FOREIGN


def test_a_case_takes_its_task_from_task_md(tmp_path):
    case = harness.load_case(a_case(tmp_path, None, FOREIGN + "\nline two\n"))
    assert case["task"] == FOREIGN + "\nline two\n"


def test_a_case_with_no_task_has_none(tmp_path):
    assert harness.load_case(a_case(tmp_path, "inbox: inbox\n"))["task"] is None


def test_a_case_with_both_is_a_case_that_cannot_be_read(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="task.md and a task"):
        harness.load_case(a_case(tmp_path, "task: one\n", "two\n"))


def scored(tmp_path, monkeypatch, words, case):
    a_flow(tmp_path / "flows", "fix", words)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.append(prompt)
        return "did it\n", False

    monkeypatch.setattr(engine, "call", fake_call)
    out, budget, stopped = harness.run_flow_for("fix", case)
    return sent, stopped


def test_the_harness_hands_the_case_task_to_the_run(tmp_path, monkeypatch):
    sent, stopped = scored(tmp_path, monkeypatch, "# worker\n\n{TASK}\n",
                           {"inbox": tmp_path, "provider": {"provider": "fake"},
                            "task": FOREIGN})
    assert FOREIGN in sent[0] and stopped == ""


def test_a_case_without_the_task_its_flow_needs_scores_as_not_finished(
        tmp_path, monkeypatch):
    sent, stopped = scored(tmp_path, monkeypatch, "# worker\n\n{TASK}\n",
                           {"inbox": tmp_path, "provider": {"provider": "fake"}})
    assert sent == []
    assert "fix takes a task" in stopped


def test_a_case_task_for_a_flow_with_no_place_scores_as_not_finished(
        tmp_path, monkeypatch):
    sent, stopped = scored(tmp_path, monkeypatch, "# worker\n\nsay hi.\n",
                           {"inbox": tmp_path, "provider": {"provider": "fake"},
                            "task": "fix it"})
    assert sent == [] and "has no place for a task" in stopped
