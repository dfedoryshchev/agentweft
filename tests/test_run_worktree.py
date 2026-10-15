import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.providers import fake_provider
from agentweft.providers.base import Reply
from agentweft.runner import cli, engine, prompts, resume, state

REPLY = "VERDICT: ok\n\n- made.txt | added | the step's work\n"


def git(where, *args):
    r = subprocess.run(["git", "-C", str(where), "-c", "user.name=t",
                        "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
                       + list(args), capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def a_repo(tmp_path):
    """a repo with one commit and a loose change on top of it."""
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "-q")
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(project, "add", "app.py")
    git(project, "commit", "-q", "-m", "start")
    (project / "app.py").write_text("x = 2\n", encoding="utf-8")
    (project / "loose.txt").write_text("not committed\n", encoding="utf-8")
    return project


def a_flow(tmp_path, monkeypatch, pause=False, extra=""):
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
        + extra
        + "timeout: 120\n"
        "provider:\n"
        "  provider: fake\n"
        '  reply: "VERDICT: ok\\n"\n',
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")

    def ask(self, prompt, timeout=None):
        (Path(self.where) / "made.txt").write_text("made\n", encoding="utf-8")
        return Reply(REPLY)

    monkeypatch.setattr(fake_provider.FakeProvider, "ask", ask)


def go(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run.py", "placed", "--force"]
                        + list(args))
    return engine.main()


def command(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(args))
    return cli.entrypoint()


def bytes_of(tree):
    """-> {path: sha256} of every file in the work tree, .git left out."""
    out = {}
    for p in sorted(Path(tree).rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(tree).parts:
            out[p.relative_to(tree).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run_folders(tmp_path):
    return sorted(p for p in (tmp_path / "runs").iterdir()
                  if p.is_dir() and (p / "manifest.json").exists())


def kept(tmp_path):
    return json.loads((run_folders(tmp_path)[-1] / "manifest.json")
                      .read_text(encoding="utf-8"))


def test_a_run_in_its_own_worktree_leaves_the_tree_byte_identical(
        tmp_path, monkeypatch):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch)
    before = bytes_of(project)
    status = git(project, "status", "--porcelain")
    head = git(project, "rev-parse", "HEAD")
    assert go(monkeypatch, "--workdir", "project", "--worktree") == 0
    assert bytes_of(project) == before
    assert git(project, "status", "--porcelain") == status
    assert git(project, "rev-parse", "HEAD") == head
    made = kept(tmp_path)["worktree"]
    tree = Path(made["path"])
    assert (tree / "made.txt").read_text(encoding="utf-8") == "made\n"
    assert made["base"] == head.strip()
    # it is made from the commit, so the loose change stays where it was
    assert (tree / "app.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (tree / "loose.txt").exists()
    assert Path(kept(tmp_path)["workdir"]) == tree.resolve()


def test_the_handoff_names_the_worktree_and_how_to_bring_it_back(
        tmp_path, monkeypatch, capsys):
    a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch)
    go(monkeypatch, "--workdir", "project", "--worktree")
    tree = kept(tmp_path)["worktree"]["path"]
    handoff = (run_folders(tmp_path)[-1] / "handoff.md").read_text(
        encoding="utf-8")
    assert "## worktree" in handoff
    assert tree in handoff
    assert "git -C " + tree + " switch -c " in handoff
    assert "python run.py worktree remove " in handoff
    assert tree in capsys.readouterr().out


def test_the_gates_watch_the_worktree(tmp_path, monkeypatch):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch, extra="spec_files: read-only\n")
    go(monkeypatch, "--workdir", "project", "--worktree")
    tree = Path(kept(tmp_path)["worktree"]["path"]).resolve()
    shot = json.loads((run_folders(tmp_path)[-1] / "start-snapshot.json")
                      .read_text(encoding="utf-8"))
    assert Path(shot["root"]).resolve() == tree
    assert "loose.txt" not in shot["product"]
    handoff = (run_folders(tmp_path)[-1] / "handoff.md").read_text(
        encoding="utf-8")
    changed = handoff.split("## changed")[1].split("##")[0]
    assert "made.txt" in changed
    assert "loose.txt" not in changed and "app.py" not in changed
    assert not (project / "made.txt").exists()


def test_without_the_flag_nothing_changes(tmp_path, monkeypatch):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch)
    assert go(monkeypatch, "--workdir", "project") == 0
    assert (project / "made.txt").exists()
    assert "worktree" not in kept(tmp_path)
    assert not (tmp_path / "runs" / "worktrees").exists()
    assert len(git(project, "worktree", "list").strip().split("\n")) == 1


def test_the_flow_can_turn_it_on(tmp_path, monkeypatch):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch, extra="worktree: true\n")
    before = bytes_of(project)
    go(monkeypatch, "--workdir", "project")
    assert bytes_of(project) == before
    assert (Path(kept(tmp_path)["worktree"]["path"]) / "made.txt").exists()


def test_a_resume_carries_on_in_the_same_worktree(tmp_path, monkeypatch):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch, pause=True)
    before = bytes_of(project)
    go(monkeypatch, "--workdir", "project", "--worktree")
    first = kept(tmp_path)
    go(monkeypatch, "--resume", first["run"])
    second = kept(tmp_path)
    assert second["resumes"] == first["run"]
    assert second["worktree"] == first["worktree"]
    assert second["workdir"] == first["workdir"]
    assert len(list((tmp_path / "runs" / "worktrees").iterdir())) == 1
    assert bytes_of(project) == before


def test_a_place_outside_git_is_refused(tmp_path, monkeypatch, capsys):
    (tmp_path / "plain").mkdir()
    a_flow(tmp_path, monkeypatch)
    assert go(monkeypatch, "--workdir", "plain", "--worktree") == 1
    assert "git" in capsys.readouterr().out
    assert not (tmp_path / "plain" / "made.txt").exists()


def test_a_worktree_holding_work_is_removed_only_when_forced(
        tmp_path, monkeypatch, capsys):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch)
    go(monkeypatch, "--workdir", "project", "--worktree")
    run_id = kept(tmp_path)["run"]
    tree = Path(kept(tmp_path)["worktree"]["path"])
    capsys.readouterr()
    assert command(monkeypatch, "worktree") == 0
    assert run_id in capsys.readouterr().out
    assert command(monkeypatch, "worktree", "remove", run_id) == 1
    assert "made.txt" in capsys.readouterr().out
    assert tree.exists()
    assert command(monkeypatch, "worktree", "remove", run_id, "--force") == 0
    assert not tree.exists()
    assert len(git(project, "worktree", "list").strip().split("\n")) == 1
    assert (project / "loose.txt").exists()


def test_a_clean_worktree_is_removed_without_force(tmp_path, monkeypatch):
    project = a_repo(tmp_path)
    a_flow(tmp_path, monkeypatch)
    go(monkeypatch, "--workdir", "project", "--worktree")
    run_id = kept(tmp_path)["run"]
    tree = Path(kept(tmp_path)["worktree"]["path"])
    (tree / "made.txt").unlink()
    assert command(monkeypatch, "worktree", "remove", run_id) == 0
    assert not tree.exists()
    assert len(git(project, "worktree", "list").strip().split("\n")) == 1
