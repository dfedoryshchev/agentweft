import sys

sys.path.insert(0, ".")
from agentweft.mcp import server
from agentweft.runner import engine, prompts, state


def a_target(tmp_path, monkeypatch, pause=False):
    """a flow kept in one directory, started from inside another one that
    stands in for a repo agentweft was pointed at."""
    flow = tmp_path / "home" / "flows" / "pointed"
    flow.mkdir(parents=True)
    for step in ["worker.md", "reviewer.md"]:
        (flow / step).write_text("# step\n\ndo the thing.\n", encoding="utf-8")
    (flow / "instructions.md").write_text("two steps.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: pointed\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        + ("    pause: user\n" if pause else "")
        + "  - role: reviewer\n"
        "    prompt: reviewer.md\n"
        "provider:\n"
        "  provider: fake\n"
        '  reply: "VERDICT: ok\\n\\n- notes.md | changed | moved\\n"\n',
        encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.chdir(target)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "home" / "flows")])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    return target


def go(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run.py", "pointed", "--force"]
                        + list(args))
    return engine.main()


def test_a_run_started_inside_another_repo_leaves_nothing_in_it(tmp_path,
                                                                monkeypatch):
    target = a_target(tmp_path, monkeypatch)
    go(monkeypatch)
    assert list(target.iterdir()) == []
    kept = state.RUNS
    assert (kept / "journal.md").exists()
    assert [p for p in kept.iterdir() if p.is_dir()]


def test_a_park_is_picked_up_from_wherever_the_resume_is_typed(tmp_path,
                                                               monkeypatch,
                                                               capsys):
    target = a_target(tmp_path, monkeypatch, pause=True)
    go(monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    capsys.readouterr()
    go(monkeypatch, "--resume")
    assert "picking" in capsys.readouterr().out
    assert list(target.iterdir()) == []
    assert list(elsewhere.iterdir()) == []


def test_the_server_reads_the_same_runs_the_runner_wrote(tmp_path,
                                                         monkeypatch):
    a_target(tmp_path, monkeypatch)
    go(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert "pointed" in server.read_resource("flows://journal")
    assert any(r["uri"].startswith("flows://run/pointed-")
               for r in server.resources())
