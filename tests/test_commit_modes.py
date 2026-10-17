"""a run commits per step and squashes per task, or never commits at all.

`commits: none` (the default) never commits. `wip` commits after each step
on a branch of the run's own, agentweft/<run id>, with a message naming the
step. `squash` does the same and folds the step commits into one for the
task once every step has passed. the gates read content, not commits, so a
representative set of them gives the same verdict with and without.
"""
import re
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec as flowspec
from agentweft.runner import engine, prompts, resume, state, stops

from test_red_order import RED_GATE, a_flow

NL = chr(10)
SPEC_LINE = "the report lists students in the order given."
SPEC = "# report" + NL + NL + SPEC_LINE + NL
SORTED = "def report(names):" + NL + "    return sorted(names)" + NL
GIVEN = "def report(names):" + NL + "    return list(names)" + NL
COUNTED = SORTED + NL + NL + "def count(names):" + NL \
    + "    return len(names)" + NL
BASELINE = ("from report import report" + NL + NL + NL
            + "def test_alphabetical():" + NL
            + "    assert report(['b', 'a']) == ['a', 'b']" + NL)
COUNT = ("import report" + NL + NL + NL + "def test_count():" + NL
         + "    assert hasattr(report, 'count')" + NL)
ROSTER = ("from report import report" + NL + NL + NL
          + "def test_roster_order():" + NL
          + "    assert report(['b', 'a']) == ['b', 'a']" + NL)
TESTER = ("  - role: tester" + NL + "    prompt: tester.md" + NL
          + "    writes: tests" + NL + RED_GATE)
WORKER = ("  - role: worker" + NL + "    prompt: worker.md" + NL
          + "    writes: product" + NL)
COUNT_SAID = "FAILS: assert False" + NL + "TEST: tests/test_count.py" + NL
ROSTER_SAID = "FAILS: assert ['a', 'b'] == ['b', 'a']" + NL \
    + "TEST: tests/test_roster.py" + NL
WORKER_SAID = "- report.py: count" + NL


def git(where, *args, check=True):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=check).stdout


def a_place(where, named=True):
    where.mkdir(parents=True)
    git(where, "init", "-q", "-b", "main")
    if named:
        git(where, "config", "user.email", "t@t")
        git(where, "config", "user.name", "t")
    git(where, "config", "commit.gpgsign", "false")
    for rel, text in (("TASK.md", SPEC), ("report.py", SORTED),
                      ("conftest.py", ""), ("tests/test_report.py", BASELINE)):
        (where / rel).parent.mkdir(parents=True, exist_ok=True)
        (where / rel).write_text(text, encoding="utf-8")
    git(where, "add", ".")
    git(where, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm",
        "start")
    return where


def running(tmp_path, monkeypatch, place, does, *args):
    """main() over the flow `build` in `place`; `does[step]` is (files it
    writes, what it answers), or a list of them, one per go. -> (exit code,
    steps called, the run's folder)."""
    called = []
    goes = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append(step)
        plan = does[step]
        if isinstance(plan, list):
            i = goes.get(step, 0)
            goes[step] = i + 1
            plan = plan[min(i, len(plan) - 1)]
        writes, said = plan
        for rel, text in writes.items():
            (place / rel).parent.mkdir(parents=True, exist_ok=True)
            (place / rel).write_text(text, encoding="utf-8")
        return said, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place)] + list(args))
    code = engine.main()
    found = sorted((p for p in state.RUNS.iterdir() if p.is_dir()),
                   key=lambda p: resume.order_of(p.name)) \
        if state.RUNS.is_dir() else []
    return code, called, found[-1] if found else None


def read(path):
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def with_mode(steps, mode):
    return steps + ("commits: " + mode + NL if mode else "")


def head(place):
    return git(place, "rev-parse", "HEAD").strip()


def branch(place):
    return git(place, "rev-parse", "--abbrev-ref", "HEAD").strip()


def subjects(place, since):
    return git(place, "log", "--reverse", "--format=%s",
               since + "..HEAD").splitlines()


# the representative gate set: each case is (flow steps, what the steps do)
CASES = {
    "red first, then the fix": (TESTER + WORKER, {
        "tester.md": ({"tests/test_count.py": COUNT}, COUNT_SAID),
        "worker.md": ({"report.py": COUNTED}, WORKER_SAID)}),
    "product code before a red test": (WORKER, {
        "worker.md": ({"report.py": COUNTED}, WORKER_SAID)}),
    "a tests step that edits product code": (TESTER + WORKER, {
        "tester.md": ({"tests/test_count.py": COUNT, "report.py": COUNTED},
                      COUNT_SAID)}),
    "a start test turned red": (TESTER + WORKER, {
        "tester.md": ({"tests/test_roster.py": ROSTER}, ROSTER_SAID),
        "worker.md": ({"report.py": GIVEN}, "- report.py: the order given"
                      + NL)}),
    "a read-only spec edited": (
        TESTER + WORKER + "spec_files: read-only" + NL, {
            "tester.md": ({"tests/test_count.py": COUNT}, COUNT_SAID),
            "worker.md": ({"report.py": COUNTED,
                           "TASK.md": SPEC + "and counts them." + NL},
                          WORKER_SAID)}),
    "a spec line rewritten": (
        TESTER + WORKER + "spec_files: additions" + NL, {
            "tester.md": ({"tests/test_count.py": COUNT}, COUNT_SAID),
            "worker.md": ({"report.py": COUNTED,
                           "TASK.md": "# report" + NL + NL + "sorted." + NL},
                          WORKER_SAID)}),
}


def verdict(tmp_path, monkeypatch, case, mode):
    steps, does = CASES[case]
    where = tmp_path / (mode or "unset")
    place = a_place(where / "repo")
    a_flow(where, "build", with_mode(steps, mode))
    code, called, folder = running(where, monkeypatch, place, does)
    why = read(folder / "why.md").replace(folder.name, "<run>") \
        .replace(str(place), "<place>")
    gates = re.sub(r"\(\d+(\.\d+)?s\)", "", read(folder / "gates.md")
                   .replace(folder.name, "<run>"))
    return {"code": code, "called": called, "why": why, "gates": gates,
            "outcome": read(folder / "manifest.json").count("stopped")}, \
        place, folder


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_gate_gives_the_same_verdict_with_commits_and_without(
        tmp_path, monkeypatch, case):
    without, place_n, _ = verdict(tmp_path, monkeypatch, case, "none")
    unset, _, _ = verdict(tmp_path, monkeypatch, case, "")
    with_wip, place_w, folder = verdict(tmp_path, monkeypatch, case, "wip")
    squashed, _, _ = verdict(tmp_path, monkeypatch, case, "squash")
    assert with_wip == without
    assert unset == without
    assert squashed == without
    # none never commits and never leaves the branch it started on
    assert branch(place_n) == "main"
    assert subjects(place_n, "main") == []
    assert git(place_n, "rev-list", "--count", "HEAD").strip() == "1"
    # wip keeps the start branch where it was and commits on the run's own
    assert branch(place_w) == "agentweft/" + folder.name
    assert git(place_w, "rev-list", "--count", "main").strip() == "1"


def test_wip_commits_each_step_on_the_run_branch_naming_it(tmp_path,
                                                           monkeypatch):
    place = a_place(tmp_path / "repo")
    start = head(place)
    a_flow(tmp_path, "build", with_mode(TESTER + WORKER, "wip"))
    code, called, folder = running(
        tmp_path, monkeypatch, place, CASES["red first, then the fix"][1])
    assert code == stops.EXIT_OK
    assert branch(place) == "agentweft/" + folder.name
    assert subjects(place, start) == ["wip(build): tester.md",
                                      "wip(build): worker.md"]
    first, second = git(place, "rev-list", "--reverse",
                        start + "..HEAD").split()
    assert git(place, "diff-tree", "--no-commit-id", "--name-only", "-r",
               first).split() == ["tests/test_count.py"]
    assert git(place, "diff-tree", "--no-commit-id", "--name-only", "-r",
               second).split() == ["report.py"]
    assert git(place, "status", "--porcelain") == ""
    author = git(place, "log", "-1", "--format=%an <%ae>|%cn <%ce>")
    assert author.strip() == "t <t@t>|t <t@t>"
    handoff = read(folder / "handoff.md")
    assert "- commits: wip on agentweft/" + folder.name in handoff
    assert ("tests in " + first[:12] + " before the first product code in "
            + second[:12]) in handoff


def test_squash_leaves_one_commit_for_the_task(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    start = head(place)
    a_flow(tmp_path, "build", with_mode(TESTER + WORKER, "squash"))
    (tmp_path / "flows" / "build" / "instructions.md").write_text(
        "the task: {TASK}" + NL, encoding="utf-8")
    code, _, folder = running(
        tmp_path, monkeypatch, place, CASES["red first, then the fix"][1],
        "--task", "count the students")
    assert code == stops.EXIT_OK
    assert branch(place) == "agentweft/" + folder.name
    assert subjects(place, start) == ["build: count the students"]
    body = git(place, "log", "-1", "--format=%b")
    assert "tester.md" in body and "worker.md" in body
    assert sorted(git(place, "diff", "--name-only", start, "HEAD").split()) \
        == ["report.py", "tests/test_count.py"]
    assert git(place, "status", "--porcelain") == ""
    handoff = read(folder / "handoff.md")
    assert "- commits: squashed into " + head(place)[:12] in handoff


def test_a_stopped_squash_run_keeps_its_step_commits_and_a_resume_squashes(
        tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    start = head(place)
    a_flow(tmp_path, "build", with_mode(TESTER + WORKER, "squash"))
    code, _, first = running(tmp_path, monkeypatch, place, {
        "tester.md": ({"tests/test_count.py": COUNT}, COUNT_SAID),
        "worker.md": ({}, "")})
    assert code != stops.EXIT_OK
    assert subjects(place, start) == ["wip(build): tester.md"]
    code, called, second = running(
        tmp_path, monkeypatch, place,
        {"worker.md": ({"report.py": COUNTED}, WORKER_SAID)},
        "--resume", first.name)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    assert branch(place) == "agentweft/" + first.name
    assert len(subjects(place, start)) == 1
    assert sorted(git(place, "diff", "--name-only", start, "HEAD").split()) \
        == ["report.py", "tests/test_count.py"]


def test_a_resume_on_another_branch_refuses(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", with_mode(TESTER + WORKER, "wip"))
    _, _, first = running(tmp_path, monkeypatch, place, {
        "tester.md": ({"tests/test_count.py": COUNT}, COUNT_SAID),
        "worker.md": ({}, "")})
    git(place, "checkout", "-q", "main")
    code, called, _ = running(
        tmp_path, monkeypatch, place,
        {"worker.md": ({"report.py": COUNTED}, WORKER_SAID)},
        "--resume", first.name)
    assert called == []
    assert code == 1
    assert subjects(place, "main") == []


def test_no_git_identity_refuses_before_any_step(tmp_path, monkeypatch,
                                                 capsys):
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                 "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    place = a_place(tmp_path / "repo", named=False)
    a_flow(tmp_path, "build", with_mode(TESTER + WORKER, "wip"))
    code, called, _ = running(tmp_path, monkeypatch, place,
                              CASES["red first, then the fix"][1])
    assert called == []
    assert code == 1
    said = capsys.readouterr().out
    assert "user.name" in said and "commits: none" in said
    assert branch(place) == "main"
    assert git(place, "rev-list", "--count", "HEAD").strip() == "1"


def test_only_what_the_steps_changed_is_committed_and_nothing_is_pushed(
        tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    place = a_place(tmp_path / "repo")
    git(place, "remote", "add", "origin", str(remote))
    git(place, "push", "-q", "origin", "main")
    start = head(place)
    (place / ".env").write_text("SECRET=1" + NL, encoding="utf-8")
    (place / "TASK.md").write_text(SPEC + "a note of mine." + NL,
                                   encoding="utf-8")
    git(place, "add", "TASK.md")
    a_flow(tmp_path, "build", with_mode(TESTER + WORKER, "wip"))
    code, _, _ = running(tmp_path, monkeypatch, place,
                         CASES["red first, then the fix"][1])
    assert code == stops.EXIT_OK
    touched = git(place, "diff", "--name-only", start, "HEAD").split()
    assert sorted(touched) == ["report.py", "tests/test_count.py"]
    left = git(place, "status", "--porcelain")
    assert "M  TASK.md" in left and "?? .env" in left
    assert git(remote, "branch", "--list").split() == ["main"]
    assert git(remote, "rev-parse", "main").strip() == start


def test_the_mode_is_a_flow_key_with_three_values():
    base = {"name": "x", "steps": [{"role": "worker"}]}
    for good in ("none", "wip", "squash"):
        assert flowspec.check(dict(base, commits=good)) == []
    bad = flowspec.check(dict(base, commits="always"))
    assert any("commits should be one of none, wip, squash" in b
               for b in bad), bad


def a_committer(place, how, run_id="run-1"):
    from agentweft.guardrails import snapshot
    from agentweft.runner import commits
    c = commits.Committer(how, snapshot.take(place))
    c.begin(run_id)
    return c


def test_squash_of_a_rename_commits_the_tree_the_steps_left(tmp_path):
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    c = a_committer(place, commits.SQUASH)
    git(place, "mv", "report.py", "listing.py")
    git(place, "reset", "-q")
    c.step("worker.md", "build")
    tip = git(place, "rev-parse", "HEAD^{tree}").strip()
    c.finish("build", "rename it")
    assert git(place, "rev-parse", "HEAD^{tree}").strip() == tip
    assert git(place, "status", "--porcelain") == ""
    assert len(git(place, "rev-list", "main..HEAD").split()) == 1


def test_a_step_commit_refuses_once_the_place_left_the_run_branch(tmp_path):
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    c = a_committer(place, commits.WIP)
    git(place, "checkout", "-q", "main")
    mine = head(place)
    (place / "report.py").write_text(COUNTED, encoding="utf-8")
    with pytest.raises(ValueError, match="agentweft/run-1"):
        c.step("worker.md", "build")
    assert head(place) == mine
    assert "M report.py" in git(place, "status", "--porcelain")


def test_the_squash_leaves_the_persons_branch_alone_after_a_switch(
        tmp_path):
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    c = a_committer(place, commits.SQUASH)
    (place / "report.py").write_text(COUNTED, encoding="utf-8")
    c.step("worker.md", "build")
    run_tip = head(place)
    git(place, "checkout", "-q", "main")
    (place / "mine.txt").write_text("mine" + NL, encoding="utf-8")
    git(place, "add", "mine.txt")
    git(place, "commit", "-qm", "my own work")
    mine = head(place)
    c.finish("build", "task")
    assert git(place, "rev-parse", "main").strip() == mine
    assert git(place, "rev-parse", "agentweft/run-1").strip() == run_tip
    assert c.squashed is None
    assert "not squashed" in c.said() and "main" in c.said()


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "CHERRY_PICK_HEAD",
                                    "REVERT_HEAD", "rebase-merge"])
def test_starting_the_run_branch_refuses_during_a_merge(tmp_path, marker):
    from agentweft.guardrails import snapshot
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    if marker == "MERGE_HEAD":
        git(place, "checkout", "-q", "-b", "side")
        (place / "report.py").write_text(GIVEN, encoding="utf-8")
        git(place, "commit", "-qam", "side")
        git(place, "checkout", "-q", "main")
        (place / "report.py").write_text(COUNTED, encoding="utf-8")
        git(place, "commit", "-qam", "main")
        git(place, "merge", "side", check=False)
        (place / "report.py").write_text(SORTED, encoding="utf-8")
        git(place, "add", "report.py")
    else:
        made = place / ".git" / marker
        if marker.startswith("rebase"):
            made.mkdir()
        else:
            made.write_text(head(place) + NL, encoding="utf-8")
    assert (place / ".git" / marker).exists()
    with pytest.raises(ValueError, match="in progress"):
        c = commits.Committer(commits.WIP, snapshot.take(place))
        c.begin("run-1")
    assert (place / ".git" / marker).exists(), "the merge was dropped"
    assert branch(place) == "main"


def test_a_commit_mode_from_the_environment_is_checked(monkeypatch):
    from agentweft.runner import commits
    monkeypatch.setenv("AGENTWEFT_COMMITS", "yes")
    with pytest.raises(ValueError, match="AGENTWEFT_COMMITS"):
        commits.mode({})
    monkeypatch.setenv("AGENTWEFT_COMMITS", "squash")
    assert commits.mode({}) == "squash"
    assert commits.mode({"commits": "none"}) == "none"


def test_a_resume_refuses_a_commit_mode_other_than_the_one_it_started_with(
        tmp_path):
    from agentweft.guardrails import snapshot
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    first = a_committer(place, commits.SQUASH)
    kept = {"mode": first.how, "branch": first.branch, "base": first.base}
    for now in (commits.NONE, commits.WIP):
        with pytest.raises(ValueError, match="squash"):
            commits.Committer(now, snapshot.take(place), kept)
    assert commits.Committer(commits.SQUASH, snapshot.take(place),
                             kept).branch == first.branch


def test_a_signer_that_cannot_sign_refuses_before_any_step(tmp_path):
    from agentweft.guardrails import snapshot
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    git(place, "config", "commit.gpgsign", "true")
    git(place, "config", "gpg.format", "openpgp")
    git(place, "config", "gpg.program", "false")
    with pytest.raises(ValueError, match="sign"):
        commits.Committer(commits.WIP, snapshot.take(place))
    assert branch(place) == "main"


def test_a_squash_git_refuses_keeps_the_step_commits_and_says_why(
        tmp_path, monkeypatch):
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    c = a_committer(place, commits.SQUASH)
    (place / "report.py").write_text(COUNTED, encoding="utf-8")
    c.step("worker.md", "build")
    tip = head(place)
    real = commits._git

    def no_commit_tree(where, *args, given=None):
        if "commit-tree" in args:
            return 128, "", "error: gpg failed to sign the data"
        return real(where, *args, given=given)
    monkeypatch.setattr(commits, "_git", no_commit_tree)
    c.finish("build", "task")
    assert head(place) == tip and c.squashed is None
    assert git(place, "status", "--porcelain") == ""
    assert "not squashed" in c.said() and "gpg failed" in c.said()


def test_the_repos_hooks_do_not_run_for_the_runs_git(tmp_path):
    from agentweft.runner import commits
    place = a_place(tmp_path / "repo")
    marker = tmp_path / "hooked"
    hooks = place / ".git" / "hooks"
    for name in ("pre-commit", "prepare-commit-msg", "commit-msg",
                 "post-commit", "post-checkout", "reference-transaction"):
        (hooks / name).write_text("#!/bin/sh" + NL + "echo " + name
                                  + " >> '" + str(marker) + "'" + NL,
                                  encoding="utf-8")
        (hooks / name).chmod(0o755)
    c = a_committer(place, commits.SQUASH)
    (place / "report.py").write_text(COUNTED, encoding="utf-8")
    c.step("worker.md", "build")
    c.finish("build", "task")
    assert c.squashed
    assert not marker.exists(), "a repo hook ran: " + read(marker)
