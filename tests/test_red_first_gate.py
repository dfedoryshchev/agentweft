import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parent.parent / "flows"

BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
WITH_ADD_ALL = FIXED + NL + NL + "def add_all(xs):" + NL + "    return sum(xs)" + NL
RED_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
            + "    assert add(1, 2) == 3" + NL)
GUARD = ("from calc import add" + NL + NL + NL + "def test_zero():" + NL
         + "    assert add(0, 0) == 0" + NL)
NEEDS_ADD_ALL = ("def test_add_all():" + NL + "    from calc import add_all"
                 + NL + NL + "    assert add_all([1, 2]) == 3" + NL)
WORKER_SAID = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
MODES = ["no commits", "steps commit"]


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where, old="def test_old():" + NL + "    assert True" + NL):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text(BUGGY, encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_old.py").write_text(old, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def write(place, rel, text, mode, message):
    (place / rel).write_text(text, encoding="utf-8")
    if mode == "steps commit":
        git(place, "add", rel)
        git(place, "commit", "-qm", message)


def started(place):
    fm = runner.config("fix-with-test")
    by_role = resolver.resolve(fm.raw, runner.flow_path("fix-with-test"))
    run = runner.Run("fix-with-test", fm, by_role, workdir=str(place))
    assert getattr(run, "start", None) is not None, \
        "the run took no snapshot of the place it started in"
    return run


def replayed(run, worker_said=WORKER_SAID, answer="patched it"):
    run.produced["worker.md"] = worker_said
    found = [g for g in run.gates_for("patcher.md") if g.name == "red-first"]
    assert found, "fix-with-test's patcher has no red-first gate"
    return found[0].run(answer)


def replays_left(place):
    return [l for l in git(place, "worktree", "list", "--porcelain").split(NL)
            if l.startswith("worktree ") and "agentweft-replay-" in l]


@pytest.mark.parametrize("mode", MODES)
def test_a_new_test_red_without_the_fix_and_green_with_it_passes(tmp_path,
                                                                 mode):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", RED_TEST, mode, "a failing test")
    write(place, "calc.py", FIXED, mode, "the fix")
    r = replayed(run)
    assert r, r.detail
    assert r.tests == [{"test": "tests/test_calc.py::test_add",
                        "before": "red", "kind": "assertion",
                        "after": "green"}]
    assert "red without the fix" in r.detail


@pytest.mark.parametrize("mode", MODES)
def test_a_new_test_that_passes_without_the_fix_fails_the_gate(tmp_path,
                                                               mode):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", GUARD, mode, "a test")
    write(place, "calc.py", FIXED, mode, "the fix")
    r = replayed(run)
    assert not r
    assert "passes without the fix" in r.detail
    assert [t["before"] for t in r.tests] == ["green"]


def test_a_red_only_by_import_error_fails(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", NEEDS_ADD_ALL, "no commits", "")
    write(place, "calc.py", WITH_ADD_ALL, "no commits", "")
    r = replayed(run)
    assert not r
    assert "ImportError" in r.detail
    assert "assertion" in r.detail
    assert r.tests[0]["before"] == "error"


def test_an_error_the_red_step_named_counts_as_its_red(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", NEEDS_ADD_ALL, "no commits", "")
    write(place, "calc.py", WITH_ADD_ALL, "no commits", "")
    r = replayed(run, worker_said="FAILS: ImportError: cannot import name"
                 " 'add_all'" + NL + "TEST: tests/test_calc.py" + NL)
    assert r, r.detail
    assert r.tests[0]["before"] == "red"
    assert r.tests[0]["kind"] == "ImportError"


def test_a_killed_run_leaves_no_worktree_after_the_next_start(tmp_path):
    place = a_repo(tmp_path / "repo")
    left = tmp_path / "agentweft-replay-killed"
    git(place, "worktree", "add", "--detach", str(left), "HEAD")
    own = tmp_path / "someone-elses"
    git(place, "worktree", "add", "--detach", str(own), "HEAD")
    assert replays_left(place)
    started(place)
    assert replays_left(place) == []
    assert not left.exists()
    assert own.exists(), "a worktree the run did not make was removed"


def test_the_replay_leaves_no_worktree_and_the_place_as_it_was(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", RED_TEST, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    status = git(place, "status", "--porcelain")
    head = git(place, "rev-parse", "HEAD")
    assert replayed(run)
    assert replays_left(place) == []
    assert git(place, "status", "--porcelain") == status
    assert git(place, "rev-parse", "HEAD") == head
    assert git(place, "stash", "list") == ""
    assert (place / "calc.py").read_text(encoding="utf-8") == FIXED


def test_a_fix_with_no_new_test_fails(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "calc.py", FIXED, "no commits", "")
    r = replayed(run)
    assert not r
    assert "no test was added or changed" in r.detail


def test_a_failing_old_test_in_the_same_file_does_not_make_a_new_one_red(
        tmp_path):
    """run as a file, the old test's failure would read as the new one's."""
    old = "def test_old():" + NL + "    assert False" + NL
    place = a_repo(tmp_path / "repo", old=old)
    run = started(place)
    write(place, "tests/test_old.py", GUARD + NL + NL + old, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    r = replayed(run, worker_said="FAILS: x" + NL + "TEST: tests/test_old.py")
    assert not r
    assert [t["test"] for t in r.tests] == ["tests/test_old.py::test_zero"]
    assert r.tests[0]["before"] == "green"


def test_a_place_outside_git_passes_saying_it_was_not_replayed(tmp_path):
    place = tmp_path / "plain"
    place.mkdir()
    run = started(place)
    r = replayed(run)
    assert r, r.detail
    assert r.detail.startswith("not replayed")


def a_flow_run(tmp_path, monkeypatch, place, mode):
    """the shipped fix-with-test on the fake provider, each step writing what
    a model would, and committing it when the steps commit."""
    flows = tmp_path / "flows"
    shutil.copytree(FLOWS / "fix-with-test", flows / "fix-with-test")
    yml = flows / "fix-with-test" / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8") + "provider:" + NL
                   + "  provider: fake" + NL, encoding="utf-8")
    prompts_seen = {}
    answers = {
        "worker.md": WORKER_SAID,
        "patcher.md": "TEST: tests/test_calc.py" + NL + "patched it" + NL,
        "verify.md": "PASS the test is written before the patch" + NL
                     + "PASS the test fails on the unpatched code" + NL
                     + "PASS the patch is the smallest thing" + NL}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        prompts_seen[step] = prompt
        if step == "worker.md":
            write(place, "tests/test_calc.py", RED_TEST, mode, "a test")
        if step == "patcher.md":
            write(place, "calc.py", FIXED, mode, "the fix")
        return answers[step], False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--workdir", str(place),
                                      "--task", "add(1, 2) returns -1"])
    return prompts_seen


@pytest.mark.parametrize("mode", MODES)
def test_a_correct_fix_gets_its_red_first_proof_from_the_gate_record(
        tmp_path, monkeypatch, mode):
    """a correct fix whose verify step could not see the order for itself:
    the runner shows it and hands it on, and the handoff reads it from the
    gate record."""
    place = a_repo(tmp_path / "repo")
    seen = a_flow_run(tmp_path, monkeypatch, place, mode)
    engine.main()
    folder = [p for p in state.RUNS.iterdir() if p.is_dir()][0]
    gates_md = (folder / "gates.md").read_text(encoding="utf-8")
    assert "PASS red-first" in gates_md
    lines = [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]
    patcher = [l for l in lines if l["step"] == "patcher.md"][0]
    record = [g for g in patcher["gates"] if g["gate"] == "red-first"][0]
    assert record["tests"] == [{"test": "tests/test_calc.py::test_add",
                                "before": "red", "kind": "assertion",
                                "after": "green"}]
    told = seen["verify.md"]
    assert "tests/test_calc.py::test_add" in told
    assert "without the fix" in told
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "red first: shown on patcher.md" in handoff
    assert ("- tests/test_calc.py::test_add: red without the fix (assertion),"
            " green with it") in handoff
    assert replays_left(place) == []


LOOKUP_BUGGY = "def get(d, k):" + NL + "    return d[k]" + NL
LOOKUP_FIXED = "def get(d, k):" + NL + "    return d.get(k)" + NL
LOOKUP_TEST = ("from calc import get" + NL + NL + NL + "def test_get_missing():"
               + NL + "    assert get({}, 'x') is None" + NL)


def test_a_crash_the_fix_removes_is_red(tmp_path):
    """the bug is the crash: the unfixed code raises KeyError."""
    place = a_repo(tmp_path / "repo")
    (place / "calc.py").write_text(LOOKUP_BUGGY, encoding="utf-8")
    git(place, "commit", "-qam", "lookup")
    run = started(place)
    write(place, "tests/test_calc.py", LOOKUP_TEST, "no commits", "")
    write(place, "calc.py", LOOKUP_FIXED, "no commits", "")
    r = replayed(run, worker_said="FAILS: assert" + NL
                 + "TEST: tests/test_calc.py" + NL)
    assert r, r.detail
    assert r.tests[0]["before"] == "red"
    assert r.tests[0]["kind"] == "KeyError"


def test_a_name_error_in_the_test_is_still_not_red(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", "def test_add():" + NL
          + "    assert ad(1, 2) == 3" + NL, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    r = replayed(run)
    assert not r
    assert r.tests[0]["before"] == "error"
    assert r.tests[0]["kind"] == "NameError"


def test_the_replay_imports_its_own_tree_not_an_installed_one(tmp_path,
                                                              monkeypatch):
    """an editable install puts the person's src/ on sys.path, so the
    unfixed checkout would import the fixed package."""
    place = tmp_path / "repo"
    place.mkdir()
    git(place, "init", "-q")
    git(place, "config", "user.email", "t@t")
    git(place, "config", "user.name", "t")
    (place / "src" / "calcpkg").mkdir(parents=True)
    (place / "src" / "calcpkg" / "__init__.py").write_text(BUGGY,
                                                           encoding="utf-8")
    (place / "tests").mkdir()
    (place / "tests" / "test_old.py").write_text(
        "def test_old():" + NL + "    assert True" + NL, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "start")
    monkeypatch.setenv("PYTHONPATH", str(place / "src"))
    run = started(place)
    write(place, "tests/test_calc.py", RED_TEST.replace("from calc",
                                                        "from calcpkg"),
          "no commits", "")
    write(place, "src/calcpkg/__init__.py", FIXED, "no commits", "")
    r = replayed(run)
    assert r, r.detail
    assert r.tests[0]["before"] == "red"


def test_a_unittest_case_and_a_nested_class_are_new_tests(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py",
          "import unittest" + NL + NL + "from calc import add" + NL + NL + NL
          + "class AddCase(unittest.TestCase):" + NL
          + "    def test_add(self):" + NL
          + "        self.assertEqual(add(1, 2), 3)" + NL + NL + NL
          + "class TestOuter:" + NL
          + "    class TestInner:" + NL
          + "        def test_two(self):" + NL
          + "            assert add(2, 2) == 4" + NL, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    r = replayed(run)
    assert r, r.detail
    assert [t["test"] for t in r.tests] == [
        "tests/test_calc.py::AddCase::test_add",
        "tests/test_calc.py::TestOuter::TestInner::test_two"]


def test_a_test_file_whose_tests_are_not_read_is_one_test(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py",
          "from calc import add" + NL + NL + NL + "def _made():" + NL
          + "    def check():" + NL + "        assert add(1, 2) == 3" + NL
          + "    return check" + NL + NL + NL + "test_add = _made()" + NL,
          "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    r = replayed(run)
    assert r, r.detail
    assert [t["test"] for t in r.tests] == ["tests/test_calc.py"]


def test_the_fix_step_cannot_declare_its_own_error(tmp_path):
    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", NEEDS_ADD_ALL, "no commits", "")
    write(place, "calc.py", WITH_ADD_ALL, "no commits", "")
    r = replayed(run, answer="FAILS: ImportError" + NL + "patched it" + NL)
    assert not r
    assert r.tests[0]["before"] == "error"


def test_a_post_checkout_hook_in_the_repo_never_runs(tmp_path):
    place = a_repo(tmp_path / "repo")
    marker = tmp_path / "hook-ran"
    hook = place / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh" + NL + "echo ran > '" + marker.as_posix()
                    + "'" + NL, encoding="utf-8")
    hook.chmod(0o755)
    run = started(place)
    write(place, "tests/test_calc.py", RED_TEST, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    assert replayed(run)
    assert not marker.exists()


def test_the_replay_worktree_is_locked_while_it_runs(tmp_path, monkeypatch):
    from agentweft.guardrails.gates import redfirst_gate

    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", RED_TEST, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")
    seen = []
    real = redfirst_gate.RedFirstGate.one

    def one(self, cmd, test, where, said):
        seen.append(git(place, "worktree", "list", "--porcelain"))
        return real(self, cmd, test, where, said)

    monkeypatch.setattr(redfirst_gate.RedFirstGate, "one", one)
    assert replayed(run)
    assert "locked" in seen[0]


def test_a_replay_locked_by_a_live_run_survives_another_start(tmp_path):
    import os

    place = a_repo(tmp_path / "repo")
    live = tmp_path / "agentweft-replay-live"
    git(place, "worktree", "add", "--detach", str(live), "HEAD")
    git(place, "worktree", "lock", "--reason",
        "agentweft pid " + str(os.getpid()), str(live))
    started(place)
    assert live.exists()
    assert len(replays_left(place)) == 1


def test_a_replay_locked_by_a_dead_run_is_removed_at_the_next_start(tmp_path):
    place = a_repo(tmp_path / "repo")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    dead = tmp_path / "agentweft-replay-dead"
    git(place, "worktree", "add", "--detach", str(dead), "HEAD")
    git(place, "worktree", "lock", "--reason",
        "agentweft pid " + str(gone.pid), str(dead))
    started(place)
    assert replays_left(place) == []
    assert not dead.exists()


def test_a_replay_whose_folder_went_away_fails_rather_than_crashing(
        tmp_path, monkeypatch):
    import types

    from agentweft.guardrails.gates import redfirst_gate

    place = a_repo(tmp_path / "repo")
    run = started(place)
    write(place, "tests/test_calc.py", RED_TEST, "no commits", "")
    write(place, "calc.py", FIXED, "no commits", "")

    def gone(*a, **kw):
        raise NotADirectoryError("the folder is gone")

    monkeypatch.setattr(redfirst_gate, "subprocess", types.SimpleNamespace(
        run=gone, TimeoutExpired=subprocess.TimeoutExpired))
    r = replayed(run)
    assert not r
    assert "the folder is gone" in r.detail


def test_a_resumed_run_replays_from_the_snapshot_it_started_with(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow_run(tmp_path, monkeypatch, place, "no commits")
    goes = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        goes.append(step)
        if step == "worker.md":
            write(place, "tests/test_calc.py", RED_TEST, "no commits", "")
            return WORKER_SAID, False
        if step == "patcher.md" and goes.count("patcher.md") == 1:
            return "", False
        if step == "patcher.md":
            write(place, "calc.py", FIXED, "no commits", "")
            return "TEST: tests/test_calc.py" + NL + "patched it" + NL, False
        return ("PASS a" + NL + "PASS b" + NL + "PASS c" + NL), False

    monkeypatch.setattr(engine, "call", fake_call)
    engine.main()
    [first] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--resume", first.name])
    engine.main()
    assert goes == ["worker.md", "patcher.md", "patcher.md", "verify.md"]
    second = [p for p in state.RUNS.iterdir() if p.is_dir() and p != first][0]
    handoff = (second / "handoff.md").read_text(encoding="utf-8")
    assert "red first: shown on patcher.md" in handoff
    assert ("- tests/test_calc.py::test_add: red without the fix (assertion),"
            " green with it") in handoff


def test_a_resumed_run_with_no_kept_snapshot_does_not_replay(tmp_path,
                                                             monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow_run(tmp_path, monkeypatch, place, "no commits")
    goes = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        goes.append(step)
        if step == "worker.md":
            write(place, "tests/test_calc.py", RED_TEST, "no commits", "")
            return WORKER_SAID, False
        return "", False

    monkeypatch.setattr(engine, "call", fake_call)
    engine.main()
    [first] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    (first / "start-snapshot.json").unlink()
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--resume", first.name])
    engine.main()
    assert goes == ["worker.md", "patcher.md"]
    second = [p for p in state.RUNS.iterdir() if p.is_dir() and p != first][0]
    assert "no start snapshot" in (second / "why.md").read_text(
        encoding="utf-8")
