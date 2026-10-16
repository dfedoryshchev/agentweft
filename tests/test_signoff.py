"""a run that changed files signs off only if its change still merges onto the
branch it is for, as that branch is at the end of the run.

the branch can move while a run works: a run of an hour on main as it was at
nine hands back a change made against a main that is gone. the check reads the
branch's head again at the end and asks git whether the change merges onto it,
read only: the person's tree, index, HEAD and branches are as they were, and
nothing is staged or committed.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.guardrails import signoff
from agentweft.runner import engine, prompts, stops

NL = chr(10)
WHO = ["-c", "user.name=t", "-c", "user.email=t@t", "-c",
       "commit.gpgsign=false"]


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + WHO + list(args),
                          capture_output=True, encoding="utf-8",
                          check=True).stdout.strip()


def repo(tmp_path):
    """-> (the place, on branch work; a second checkout of main beside it)."""
    place = tmp_path / "place"
    place.mkdir()
    git(place, "init", "-q", "-b", "main")
    (place / "calc.py").write_text("a = 1" + NL + "b = 2" + NL + "c = 3" + NL,
                                   encoding="utf-8")
    (place / "other.py").write_text("x = 1" + NL, encoding="utf-8")
    git(place, "add", "-A")
    git(place, "commit", "-q", "-m", "start")
    git(place, "checkout", "-q", "-b", "work")
    other = tmp_path / "other"
    git(place, "worktree", "add", "-q", str(other), "main")
    return place, other


def move(other, name, text):
    (other / name).write_text(text, encoding="utf-8")
    git(other, "commit", "-q", "-am", "moved")
    return git(other, "rev-parse", "HEAD")


def edit(place):
    (place / "calc.py").write_text("a = 1" + NL + "b = 20" + NL + "c = 3" + NL,
                                   encoding="utf-8")
    (place / "new.py").write_text("n = 1" + NL, encoding="utf-8")


def held(place):
    """-> every byte of the repo's own folder and of the tree, by path."""
    out = {}
    for top, dirs, names in os.walk(str(place)):
        for n in names:
            p = os.path.join(top, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, str(place))] = hashlib.sha256(
                    f.read()).hexdigest()
    return out


def test_a_target_that_did_not_move_says_nothing(tmp_path):
    place, _ = repo(tmp_path)
    mark = signoff.mark(place, "main")
    edit(place)
    got = signoff.check(place, mark)
    assert got.state == signoff.SAME
    assert got.lines() == []


def test_a_target_moved_with_a_conflicting_edit_names_the_file(tmp_path):
    place, other = repo(tmp_path)
    mark = signoff.mark(place, "main")
    edit(place)
    sha = move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    got = signoff.check(place, mark)
    assert got.state == signoff.CONFLICT
    assert got.files == ["calc.py"]
    assert got.head == sha
    assert "calc.py" in got.why and "rebase" in got.why


def test_a_target_moved_without_a_conflict_is_checked_again(tmp_path):
    place, other = repo(tmp_path)
    mark = signoff.mark(place, "main")
    edit(place)
    sha = move(other, "other.py", "x = 2" + NL)
    got = signoff.check(place, mark)
    assert got.state == signoff.MERGES
    assert got.lines() == ["- sign-off: main moved to " + sha + " since the"
                           " run started; the change was re-checked on it and"
                           " merges with no conflict"]


def test_the_check_leaves_the_tree_index_head_and_branches_as_they_were(
        tmp_path):
    place, other = repo(tmp_path)
    (place / "staged.py").write_text("s = 1" + NL, encoding="utf-8")
    git(place, "add", "staged.py")
    mark = signoff.mark(place, "main")
    edit(place)
    move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    before = held(place)
    common = git(place, "rev-parse", "--path-format=absolute",
                 "--git-common-dir")
    shared = held(common)
    assert signoff.check(place, mark).state == signoff.CONFLICT
    assert held(place) == before
    assert held(common) == shared


def test_a_target_that_cannot_be_read_stops_for_the_operator(tmp_path):
    place, other = repo(tmp_path)
    mark = signoff.mark(place, "main")
    edit(place)
    git(other, "checkout", "-q", "--detach")
    git(place, "branch", "-q", "-D", "main")
    got = signoff.check(place, mark)
    assert got.state == signoff.UNCHECKED
    assert "main" in got.why and "by hand" in got.why


def flow(tmp_path):
    d = tmp_path / "flows" / "edit"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(
        "name: edit" + NL + "steps:" + NL + "  - role: worker" + NL
        + "    prompt: worker.md" + NL + "provider:" + NL
        + "  provider: fake" + NL, encoding="utf-8")
    (d / "instructions.md").write_text("edit calc." + NL, encoding="utf-8")
    (d / "worker.md").write_text("you are the worker." + NL, encoding="utf-8")
    return tmp_path / "flows"


def go(tmp_path, monkeypatch, theirs):
    """run main() on a worker that edits calc.py while main moves to
    `theirs` (name, text). -> (exit code, manifest, handoff.md, new sha)."""
    place, other = repo(tmp_path)
    root = flow(tmp_path)
    moved = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        edit(place)
        moved.append(move(other, *theirs))
        return "- calc.py: b is 20" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv", ["run.py", "edit", "--force", "--flows",
                                      str(root), "--workdir", str(place),
                                      "--target", "main"])
    monkeypatch.chdir(tmp_path)
    code = engine.main()
    run = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    record = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    return code, record, (run / "handoff.md").read_text(encoding="utf-8"), \
        moved[0]


def test_a_run_whose_target_moved_into_a_conflict_stops(tmp_path, monkeypatch):
    code, record, handoff, sha = go(
        tmp_path, monkeypatch,
        ("calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL))
    assert code == stops.EXIT_STOP
    assert record["outcome"] == "stopped: target moved"
    assert "stopped: target moved" in handoff.split(NL)[0]
    assert "rebase onto main (" + sha + ")" in handoff
    assert "calc.py" in handoff


def test_a_run_whose_target_moved_cleanly_signs_off_and_says_so(
        tmp_path, monkeypatch):
    code, record, handoff, sha = go(tmp_path, monkeypatch,
                                    ("other.py", "x = 2" + NL))
    assert code == stops.EXIT_OK
    assert record["outcome"] == "done"
    assert "main moved to " + sha + " since the run started" in handoff


def test_a_file_behind_a_filter_program_is_left_to_the_operator(tmp_path):
    place, other = repo(tmp_path)
    (place / ".gitattributes").write_text("*.py filter=lfs" + NL,
                                          encoding="utf-8")
    mark = signoff.mark(place, "main")
    edit(place)
    move(other, "other.py", "x = 2" + NL)
    got = signoff.check(place, mark)
    assert got.state == signoff.UNCHECKED
    assert "lfs filter" in got.why and "by hand" in got.why


def test_git_failing_at_the_end_is_not_a_silent_sign_off(tmp_path,
                                                         monkeypatch):
    place, other = repo(tmp_path)
    mark = signoff.mark(place, "main")
    edit(place)
    move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    got = signoff.check(place, mark)
    assert got.state == signoff.UNCHECKED, (got.state, got.why)
    assert "by hand" in got.why


def test_the_persons_own_loose_edits_are_not_the_runs_change(tmp_path):
    place, other = repo(tmp_path)
    edit(place)
    mark = signoff.mark(place, "main")
    move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    got = signoff.check(place, mark)
    assert got.state == signoff.NOTHING, got.why


def test_a_loose_file_the_run_then_changed_is_the_runs(tmp_path):
    place, other = repo(tmp_path)
    (place / "calc.py").write_text("a = 1" + NL + "b = 5" + NL + "c = 3" + NL,
                                   encoding="utf-8")
    mark = signoff.mark(place, "main")
    edit(place)
    move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    assert signoff.check(place, mark).state == signoff.CONFLICT


def test_a_target_moved_while_the_run_changed_nothing_says_nothing(tmp_path):
    place, other = repo(tmp_path)
    mark = signoff.mark(place, "main")
    move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    got = signoff.check(place, mark)
    assert got.state == signoff.NOTHING
    assert got.lines() == []


def test_a_target_moved_only_by_the_runs_own_commits_has_not_moved(tmp_path):
    place, _ = repo(tmp_path)
    mark = signoff.mark(place, "work")
    edit(place)
    git(place, "add", "-A")
    git(place, "commit", "-q", "-m", "the run's own")
    got = signoff.check(place, mark)
    assert got.state == signoff.SAME
    assert got.lines() == []


def test_without_target_the_branch_upstream_is_the_target(tmp_path):
    place, other = repo(tmp_path)
    git(place, "branch", "-q", "--set-upstream-to", "main", "work")
    mark = signoff.mark(place)
    assert mark["target"] == "main"
    edit(place)
    move(other, "calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)
    assert signoff.check(place, mark).state == signoff.CONFLICT


def test_a_run_in_its_own_worktree_is_for_the_branch_the_person_is_on(
        tmp_path):
    place, _ = repo(tmp_path)
    inside = tmp_path / "inside"
    git(place, "worktree", "add", "-q", "--detach", str(inside), "work")
    mark = signoff.mark(inside, origin=place)
    assert mark["target"] == "work"
    edit(inside)
    (place / "calc.py").write_text("a = 1" + NL + "b = 7" + NL + "c = 3" + NL,
                                   encoding="utf-8")
    git(place, "commit", "-q", "-am", "the person kept working")
    got = signoff.check(inside, mark)
    assert got.state == signoff.CONFLICT
    assert got.files == ["calc.py"]


def test_with_no_target_to_find_the_handoff_says_it_was_not_checked(tmp_path):
    place, _ = repo(tmp_path)
    mark = signoff.mark(place)
    assert mark["target"] is None
    edit(place)
    got = signoff.check(place, mark)
    assert got.lines() == ["- sign-off: not checked, work has no upstream"
                           " and no --target was named"]


def run_edit(tmp_path, monkeypatch, extra, theirs=None, place=None):
    """run main() on a worker that edits calc.py, moving main to `theirs`
    on its first call. -> (exit code, what it printed is in capsys)."""
    if place is None:
        place, other = repo(tmp_path)
    else:
        other = tmp_path / "other"
    root = tmp_path / "flows"
    if not root.exists():
        flow(tmp_path)
    calls = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        calls.append(step)
        edit(place)
        if theirs and len(calls) == 1:
            move(other, *theirs)
        return "- calc.py: b is 20" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv", ["run.py", "edit", "--force", "--flows",
                                      str(root), "--workdir", str(place)]
                        + list(extra))
    monkeypatch.chdir(tmp_path)
    return engine.main(), calls, place


CLASH = ("calc.py", "a = 1" + NL + "b = 99" + NL + "c = 3" + NL)


def test_a_target_that_does_not_exist_is_refused_before_any_step(
        tmp_path, monkeypatch, capsys):
    code, calls, _ = run_edit(tmp_path, monkeypatch, ["--target", "mian"])
    assert code == 1 and calls == []
    assert "--target mian" in capsys.readouterr().out


def test_a_target_outside_git_is_refused_before_any_step(
        tmp_path, monkeypatch, capsys):
    place = tmp_path / "loose"
    place.mkdir()
    code, calls, _ = run_edit(tmp_path, monkeypatch, ["--target", "main"],
                              place=place)
    assert code == 1 and calls == []
    assert "not a git work tree" in capsys.readouterr().out


def test_a_target_with_no_branch_is_refused(tmp_path, monkeypatch, capsys):
    code, calls, _ = run_edit(tmp_path, monkeypatch, ["--target"])
    assert code == 1 and calls == []
    assert "--target needs the branch" in capsys.readouterr().out


def stopped_run(tmp_path, monkeypatch):
    code, _, place = run_edit(tmp_path, monkeypatch, ["--target", "main"],
                              theirs=CLASH)
    assert code == stops.EXIT_STOP
    return [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0], place


def test_a_resume_for_another_branch_is_refused(tmp_path, monkeypatch, capsys):
    first, place = stopped_run(tmp_path, monkeypatch)
    capsys.readouterr()
    code, calls, _ = run_edit(tmp_path, monkeypatch,
                              ["--resume", first.name, "--target", "work"],
                              place=place)
    assert code == 1 and calls == []
    assert "was started for main, not work" in capsys.readouterr().out


def test_a_resume_checks_against_the_head_the_first_leg_started_from(
        tmp_path, monkeypatch):
    first, place = stopped_run(tmp_path, monkeypatch)
    code, _, _ = run_edit(tmp_path, monkeypatch, ["--resume", first.name],
                          place=place)
    assert code == stops.EXIT_STOP
    newest = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]
    record = json.loads((newest / "manifest.json").read_text(encoding="utf-8"))
    assert record["outcome"] == "stopped: target moved"


def test_a_worktree_run_stops_when_the_persons_branch_moves_into_it(
        tmp_path, monkeypatch):
    place, _ = repo(tmp_path)
    root = flow(tmp_path)

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        edit(Path(provider.where))
        (place / "calc.py").write_text("a = 1" + NL + "b = 7" + NL + "c = 3"
                                       + NL, encoding="utf-8")
        git(place, "commit", "-q", "-am", "the person kept working")
        return "- calc.py: b is 20" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv", ["run.py", "edit", "--force", "--flows",
                                      str(root), "--workdir", str(place),
                                      "--worktree"])
    monkeypatch.chdir(tmp_path)
    assert engine.main() == stops.EXIT_STOP
    run = [p for p in (tmp_path / "runs").iterdir()
           if p.is_dir() and p.name != "worktrees"][0]
    record = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert record["signoff"]["target"] == "work"
    assert record["outcome"] == "stopped: target moved"
