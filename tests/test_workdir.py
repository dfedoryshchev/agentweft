import sys

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.runner import engine, prompts, resume, state
from agentweft.runner.config import where


def a_spec(**extra):
    raw = {"name": "x", "steps": [{"role": "worker"}]}
    raw.update(extra)
    return spec.load(raw)


def test_workdir_is_a_flow_key_and_it_is_a_string():
    assert spec.check({"name": "x", "steps": [{"role": "worker"}],
                       "workdir": "."}) == []
    assert "workdir should be str" in spec.check(
        {"name": "x", "steps": [{"role": "worker"}], "workdir": 3})


def test_a_run_that_says_nothing_works_where_it_was_started(tmp_path,
                                                           monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert where(a_spec()) == tmp_path.resolve()


def test_a_relative_workdir_is_made_absolute_once(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(tmp_path)
    got = where(a_spec(workdir="project"))
    assert got.is_absolute()
    assert got == (tmp_path / "project").resolve()


def test_a_named_place_beats_the_flow_file(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.chdir(tmp_path)
    assert where(a_spec(workdir="a"), "b") == (tmp_path / "b").resolve()


def test_a_place_that_is_not_there_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="gone"):
        where(a_spec(workdir="gone"))
    with pytest.raises(ValueError, match="notes.md"):
        where(a_spec(), "notes.md")


def a_flow(tmp_path, monkeypatch, pause=False, workdir=None):
    """a two step flow on the fake provider, started from tmp_path."""
    flow = tmp_path / "flows" / "placed"
    flow.mkdir(parents=True)
    for step in ["worker.md", "reviewer.md"]:
        (flow / step).write_text("# step\n\ndo the thing.\n", encoding="utf-8")
    (flow / "instructions.md").write_text("two steps.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: placed\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        + ("    pause: user\n" if pause else "")
        + "  - role: reviewer\n"
        "    prompt: reviewer.md\n"
        + ("workdir: " + workdir + "\n" if workdir else "")
        + "timeout: 120\n"
        "provider:\n"
        "  provider: fake\n"
        '  reply: "VERDICT: ok\\n\\n- notes.md | changed | moved\\n"\n',
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")


def test_the_run_carries_its_place(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir()
    a_flow(tmp_path, monkeypatch)
    fm = runner.config("placed")
    assert runner.Run("placed", fm, {}).workdir == tmp_path.resolve()
    assert runner.Run("placed", fm, {}, workdir="project").workdir == \
        (tmp_path / "project").resolve()


def go(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run.py", "placed", "--force"]
                        + list(args))
    return engine.main()


def recorded(tmp_path):
    return [(p / "workdir").read_text(encoding="utf-8")
            for p in sorted((tmp_path / "runs").iterdir())
            if (p / "workdir").exists()]


def test_the_place_is_written_down_beside_the_step_outputs(tmp_path,
                                                          monkeypatch):
    (tmp_path / "project").mkdir()
    a_flow(tmp_path, monkeypatch)
    go(monkeypatch, "--workdir", "project")
    assert recorded(tmp_path) == [str((tmp_path / "project").resolve())]
    assert state.load_state("placed")["workdir"] == \
        str((tmp_path / "project").resolve())


def test_a_missing_place_stops_the_run_before_anything_is_asked(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, workdir="gone")
    assert go(monkeypatch) == 1
    assert "gone" in capsys.readouterr().out
    assert not (tmp_path / "runs").exists()


def test_a_resumed_run_carries_on_in_the_place_it_started(tmp_path,
                                                          monkeypatch):
    (tmp_path / "project").mkdir()
    a_flow(tmp_path, monkeypatch, pause=True)
    go(monkeypatch, "--workdir", "project")
    first = recorded(tmp_path)
    assert first == [str((tmp_path / "project").resolve())]

    for p in (tmp_path / "runs").iterdir():
        if p.is_dir():
            p.rename(tmp_path / "runs" / "placed-2000-01-01-000000")
    go(monkeypatch, "--resume")
    assert set(recorded(tmp_path)) == set(first)
    assert len(recorded(tmp_path)) == 2


def test_a_resume_told_to_work_somewhere_else_is_refused(tmp_path,
                                                         monkeypatch, capsys):
    (tmp_path / "project").mkdir()
    (tmp_path / "other").mkdir()
    a_flow(tmp_path, monkeypatch, pause=True)
    go(monkeypatch, "--workdir", "project")
    capsys.readouterr()
    assert go(monkeypatch, "--workdir", "other", "--resume") == 1
    said = capsys.readouterr().out
    assert "picking" not in said
    assert str((tmp_path / "project").resolve()) in said
