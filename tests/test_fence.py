import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import fence
from agentweft.orchestrate import project, workflow
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, resume, state


def git(place, *args):
    subprocess.run(["git", "-C", str(place)] + list(args), check=True,
                   capture_output=True)


def a_repo(where):
    """a work tree with one tracked file, one ignored .env, one piece of
    uncommitted work, and an ignored cache."""
    where.mkdir(parents=True, exist_ok=True)
    git(where, "init", "-q")
    (where / ".gitignore").write_text(".env\ncache/\n", encoding="utf-8")
    (where / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(where, "add", ".gitignore", "app.py")
    (where / ".env").write_text("TOKEN=one\n", encoding="utf-8")
    (where / "wip.md").write_text("half a thought\n", encoding="utf-8")
    (where / "cache").mkdir()
    (where / "cache" / "warm.bin").write_text("x", encoding="utf-8")
    return where


def test_a_file_git_tracks_or_this_run_made_is_free_to_touch(tmp_path):
    place = a_repo(tmp_path / "p")
    f = fence.Fence(place)
    (place / "app.py").write_text("x = 2\n", encoding="utf-8")
    (place / "new.py").write_text("y = 1\n", encoding="utf-8")
    assert f.crossed() == []
    (place / "new.py").write_text("y = 2\n", encoding="utf-8")
    (place / "app.py").unlink()
    (place / "new.py").unlink()
    assert f.crossed() == []


def test_an_untracked_file_that_was_there_first_is_the_one_that_counts(
        tmp_path):
    place = a_repo(tmp_path / "p")
    f = fence.Fence(place)
    (place / ".env").write_text("TOKEN=two\n", encoding="utf-8")
    (place / "wip.md").unlink()
    assert f.crossed() == [(".env", "changed"), ("wip.md", "removed")]


def test_a_file_written_back_the_same_is_not_a_change(tmp_path):
    place = a_repo(tmp_path / "p")
    f = fence.Fence(place)
    (place / ".env").write_text("TOKEN=one\n", encoding="utf-8")
    assert f.crossed() == []


def test_adding_one_to_git_is_reported_and_not_passed(tmp_path):
    place = a_repo(tmp_path / "p")
    f = fence.Fence(place)
    git(place, "add", "-f", ".env")
    assert f.crossed() == [(".env", "now tracked")]


def test_what_the_fence_skips_is_not_watched(tmp_path):
    place = a_repo(tmp_path / "p")
    f = fence.Fence(place, skip=["cache/**"])
    (place / "cache" / "warm.bin").write_text("y", encoding="utf-8")
    assert f.crossed() == []
    g = fence.Fence(place)
    (place / "cache" / "warm.bin").write_text("z", encoding="utf-8")
    assert g.crossed() == [("cache/warm.bin", "changed")]


def test_a_place_below_the_top_of_the_repo_watches_only_itself(tmp_path):
    repo = a_repo(tmp_path / "p")
    (repo / "sub").mkdir()
    (repo / "sub" / "local.json").write_text("{}", encoding="utf-8")
    f = fence.Fence(repo / "sub")
    (repo / "wip.md").unlink()
    assert f.crossed() == []
    (repo / "sub" / "local.json").unlink()
    assert f.crossed() == [("sub/local.json", "removed")]


def test_the_runs_own_record_is_not_a_step_touching_something(tmp_path):
    place = a_repo(tmp_path / "p")
    runs = place / "cache" / "runs"
    runs.mkdir()
    (runs / "journal.md").write_text("one\n", encoding="utf-8")
    f = fence.Fence(place, own=runs)
    (runs / "journal.md").write_text("one\ntwo\n", encoding="utf-8")
    assert f.crossed() == []


def test_a_place_git_knows_nothing_about_is_refused_not_passed(tmp_path):
    (tmp_path / "loose").mkdir()
    with pytest.raises(ValueError) as caught:
        fence.Fence(tmp_path / "loose")
    assert "not in a git work tree" in str(caught.value)


def test_project_yml_declares_the_fence_and_what_it_skips():
    base = {"project": {"name": "x"}}
    assert project.load(base).fence() is None
    assert project.load(dict(base, fence={})).fence() == []
    assert project.load(dict(base, fence={"skip": ["cache/**"]})).fence() == \
        ["cache/**"]


def test_a_fence_that_says_nothing_clear_is_refused():
    base = {"project": {"name": "x"}}
    assert project.check(dict(base, fence=None)) == \
        ["fence: should be a mapping, {} for one that skips nothing"]
    assert project.check(dict(base, fence={"skip": "cache/**"})) == \
        ["fence: skip should be a list"]
    assert project.check(dict(base, fence={"allow": [".env"]})) == \
        ["fence: unknown key allow"]


def test_the_example_declares_a_fence():
    assert project.read(project.example()).fence() is not None


FAKE_MODEL = """\
import sys
from pathlib import Path
prompt = sys.argv[-1]
with open({log!r}, "a", encoding="utf-8") as f:
    f.write("asked\\n")
if "SPOIL" in prompt:
    Path(".env").write_text("TOKEN=gone\\n", encoding="utf-8")
if "TIDY" in prompt:
    Path("app.py").write_text("x = 3\\n", encoding="utf-8")
    Path("made.py").write_text("z = 1\\n", encoding="utf-8")
print("VERDICT: ok")
print()
print("done")
"""


def a_run(tmp_path, monkeypatch, does="", fenced=True):
    log = tmp_path / "asked.log"
    script = tmp_path / "fake_model.py"
    script.write_text(FAKE_MODEL.format(log=str(log)), encoding="utf-8")

    def run(argv, **kw):
        return subprocess.run([sys.executable, str(script)] + argv[1:], **kw)

    monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
        run=run, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(engine, "CACHE", {})

    flow = tmp_path / "flows" / "fenced"
    flow.mkdir(parents=True)
    (flow / "worker.md").write_text("# step\n\ndo the thing. " + does + "\n",
                                    encoding="utf-8")
    (flow / "reviewer.md").write_text("# step\n\nreview it.\n",
                                      encoding="utf-8")
    (flow / "instructions.md").write_text("two steps.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: fenced\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "  - role: reviewer\n"
        "    prompt: reviewer.md\n"
        "timeout: 120\n"
        "provider:\n"
        "  provider: cli\n"
        "  command: fake-model\n",
        encoding="utf-8")
    home = tmp_path / "orchestrate"
    home.mkdir()
    (home / "project.yml").write_text(
        "project:\n  name: here\n" + ("fence: {}\n" if fenced else ""),
        encoding="utf-8")
    place = a_repo(tmp_path / "project")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workflow, "ROOT", [str(home)])
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", None)
    return place, log


def asked(log):
    return log.read_text(encoding="utf-8").count("asked") if log.exists() else 0


def go(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run.py", "fenced", "--force",
                                      "--workdir", "project"] + list(args))
    return engine.main()


def test_a_step_that_spoils_an_untracked_file_parks_for_a_person(
        tmp_path, monkeypatch, capsys):
    place, log = a_run(tmp_path, monkeypatch, does="SPOIL")
    go(monkeypatch)
    assert asked(log) == 1
    said = capsys.readouterr().out
    assert "fenced at worker.md" in said and ".env (changed)" in said
    journal = (state.RUNS / "journal.md").read_text(encoding="utf-8")
    assert "parked at worker.md" in journal and "fenced" in journal
    assert "PARKED" in (state.RUNS / "index.md").read_text(encoding="utf-8")
    [run_dir] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    note = (run_dir / "handoff.md").read_text(encoding="utf-8")
    assert ".env (changed)" in note and "reviewer.md" in note


def test_a_fenced_run_carries_on_past_the_step_when_a_person_says_so(
        tmp_path, monkeypatch):
    place, log = a_run(tmp_path, monkeypatch, does="SPOIL")
    go(monkeypatch)
    assert asked(log) == 1
    go(monkeypatch, "--resume")
    assert asked(log) == 2
    journal = (state.RUNS / "journal.md").read_text(encoding="utf-8")
    assert journal.index("parked at worker.md") < journal.index("ok (resumed)")


def test_a_step_that_only_touches_what_git_can_restore_runs_through(
        tmp_path, monkeypatch):
    place, log = a_run(tmp_path, monkeypatch, does="TIDY")
    go(monkeypatch)
    assert asked(log) == 2
    journal = (state.RUNS / "journal.md").read_text(encoding="utf-8")
    assert "  ok  " in journal and "parked" not in journal


def test_no_fence_in_project_yml_is_no_fence(tmp_path, monkeypatch):
    place, log = a_run(tmp_path, monkeypatch, does="SPOIL", fenced=False)
    go(monkeypatch)
    assert asked(log) == 2
    assert (place / ".env").read_text(encoding="utf-8") == "TOKEN=gone\n"


def test_a_scored_run_is_fenced_the_same_way(tmp_path, monkeypatch):
    place, log = a_run(tmp_path, monkeypatch, does="SPOIL")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.chdir(place)
    _, _, why = engine.run_once("fenced")
    assert why.startswith("fenced at worker.md: ")
    assert ".env (changed)" in why
    assert asked(log) == 1


def test_a_declared_fence_on_a_place_outside_git_does_not_start(
        tmp_path, monkeypatch, capsys):
    place, log = a_run(tmp_path, monkeypatch)
    (tmp_path / "loose").mkdir()
    monkeypatch.setattr(sys, "argv", ["run.py", "fenced", "--force",
                                      "--workdir", "loose"])
    assert engine.main() == 1
    assert "not in a git work tree" in capsys.readouterr().out
    assert asked(log) == 0
