"""agentweft's own git: started with the place's fsmonitor and hooks switched
off, and no step tool writing inside the place's `.git/`."""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.bench import history
from agentweft.evals import harness
from agentweft.guardrails import fence, shellwrite, signoff, snapshot, worktree
from agentweft.guardrails.gates import redfirst_gate
from agentweft.runner import brief, commits, fan, manifest, summary

from test_grant import claude
from test_outside_writes import edit, hook_of
from test_trace import answer

REPO = Path(__file__).resolve().parent.parent
SAFE = ["git", "-c", "core.fsmonitor=false", "-c",
        "core.hooksPath=" + os.devnull]

SITES = {
    "snapshot": lambda p: snapshot._git(p, "status"),
    "manifest": lambda p: manifest._git(p, "status"),
    "summary": lambda p: summary._git(p, "status"),
    "fence": lambda p: fence._git(p, "status"),
    "worktree": lambda p: worktree._git(p, "status"),
    "fan": lambda p: fan._listed(p),
    "brief": lambda p: brief.ignored(p, "x.py"),
    "commits": lambda p: commits._git(p, "status"),
    "redfirst_gate": lambda p: redfirst_gate.py_files(p),
    "harness": lambda p: harness.committed(p),
    "history": lambda p: history.git("status"),
    "signoff": lambda p: signoff._git(p, "status"),
}


@pytest.mark.parametrize("site", sorted(SITES))
def test_every_git_agentweft_runs_switches_off_fsmonitor_and_hooks(
        site, tmp_path, monkeypatch):
    seen = []

    def fake(argv, **kw):
        seen.append(list(argv))
        texty = kw.get("text") or kw.get("encoding")
        return types.SimpleNamespace(returncode=0,
                                     stdout="" if texty else b"",
                                     stderr="" if texty else b"")

    monkeypatch.setattr(subprocess, "run", fake)
    SITES[site](tmp_path)
    assert seen
    for argv in seen:
        assert argv[:5] == SAFE, argv


def test_no_git_command_is_started_outside_the_one_start():
    found = sorted(p.relative_to(REPO).as_posix()
                   for p in (REPO / "agentweft").rglob("*.py")
                   if '["git"' in p.read_text(encoding="utf-8"))
    assert found == ["agentweft/guardrails/owngit.py"]


def the_hook(fake_cli, tmp_path, grant=None):
    cli_ = fake_cli(answer("ok\n"))
    p = claude(grant=grant)
    p.where = tmp_path
    p.ask("x")
    _, args = hook_of(cli_.calls[0]["argv"])
    return args[2:]


@pytest.mark.parametrize("rel", [
    ".git/config", ".git/hooks/pre-commit",
    pytest.param(".git\\info\\attributes", marks=pytest.mark.skipif(
        sys.platform != "win32",
        reason="a backslash only separates paths on windows"))])
@pytest.mark.parametrize("grant", [None, ["read", "edit"]])
def test_no_edit_tool_writes_inside_the_place_s_git_folder(
        fake_cli, tmp_path, rel, grant):
    argv = the_hook(fake_cli, tmp_path, grant)
    code, said = shellwrite.decide(argv, edit(str(tmp_path) + os.sep + rel,
                                              tool="Edit", cwd=tmp_path))
    assert code == 2 and ".git/" in said
    assert shellwrite.decide(argv, edit(str(tmp_path / "gitconfig.md"),
                                        cwd=tmp_path)) == (0, "")


def git_bash(path):
    p = Path(path).as_posix()
    return "/" + p[0].lower() + p[2:]


SPELLINGS = {
    "git bash": git_bash,
    "upper case": lambda p: p.replace(".git", ".GIT").replace(
        "decisions.md", "DECISIONS.md"),
    "climbs back in": lambda p: p.replace(
        os.sep + ".git" + os.sep, os.sep + ".git" + os.sep + ".."
        + os.sep + ".git" + os.sep).replace(
        os.sep + "decisions.md", os.sep + "x" + os.sep + ".."
        + os.sep + "decisions.md"),
}


@pytest.mark.parametrize("kind", sorted(SPELLINGS))
@pytest.mark.parametrize("rel", [".git/config", "decisions.md"])
def test_every_spelling_of_a_kept_path_is_kept(fake_cli, tmp_path, kind,
                                               rel):
    if sys.platform != "win32":
        pytest.skip("drive letters and case-blind paths are windows'")
    (tmp_path / ".git").mkdir()
    argv = the_hook(fake_cli, tmp_path)
    path = SPELLINGS[kind](str((tmp_path / rel).resolve()))
    code, _ = shellwrite.decide(argv, edit(path, cwd=tmp_path))
    assert code == 2, path


def test_a_shell_redirect_into_the_git_folder_is_refused(fake_cli, tmp_path):
    argv = the_hook(fake_cli, tmp_path)
    data = json.dumps({"session_id": "s-1", "tool_name": "Bash",
                       "cwd": str(tmp_path),
                       "tool_input": {"command": "echo x >> .git/config"}})
    code, _ = shellwrite.decide(argv, data)
    assert code == 2
