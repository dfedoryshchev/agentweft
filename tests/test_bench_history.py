"""scores kept per commit, and one commit's scores held against another's."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentweft.bench import history
from agentweft.runner import cli, prompts

REPO = Path(__file__).resolve().parent.parent
BASE = "a" * 40
HEAD = "b" * 40


def bench(*args):
    old = sys.argv
    sys.argv = ["agentweft", "bench"] + [str(a) for a in args]
    try:
        return cli.entrypoint()
    finally:
        sys.argv = old


def record(sha, task, outcome, repeat=1, replayed=False, flow="build-feature",
           source="bench", dirty=False):
    return {"sha": sha, "dirty": dirty, "source": source, "set": "example",
            "flow": flow, "task": task, "repeat": repeat, "outcome": outcome,
            "score": 3 if outcome == "pass" else 1, "of": 3, "usd": 0.01,
            "tokens": 100, "seconds": 1.5, "replayed": replayed}


def kept(path, *records):
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def compare(scores, *args):
    return bench("--compare", "--scores", scores, *args)


def repeats(sha, task, outcomes, **kw):
    return [record(sha, task, o, repeat=i + 1, **kw)
            for i, o in enumerate(outcomes)]


def test_a_task_that_passed_on_the_base_and_fails_every_repeat_fails_compare(
        tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  *repeats(BASE, "total-spent", ["pass", "pass", "pass"])
                  + repeats(BASE, "blank-note", ["pass", "pass", "pass"])
                  + repeats(HEAD, "total-spent",
                            ["stopped", "finished", "stopped"])
                  + repeats(HEAD, "blank-note", ["pass", "pass", "pass"]))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 1
    out = capsys.readouterr().out
    worse = [l for l in out.splitlines() if "total-spent" in l and "worse" in l]
    assert worse, out
    assert "3/3 -> 0/3" in worse[0]
    assert any("blank-note" in l and "same" in l for l in out.splitlines())
    assert "N 2 tasks, k 3" in out
    assert "fails on every repeat" in out and "total-spent" in out


def test_an_improvement_does_not_fail_compare(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  *repeats(BASE, "total-spent", ["stopped"] * 3)
                  + repeats(HEAD, "total-spent", ["pass"] * 3))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 0
    out = capsys.readouterr().out
    assert any("total-spent" in l and "better" in l and "0/3 -> 3/3" in l
               for l in out.splitlines()), out


def test_a_base_with_no_records_says_so_and_fails(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  *repeats(HEAD, "total-spent", ["pass"] * 2))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 1
    out = capsys.readouterr().out
    assert "no record" in out and BASE[:7] in out


def test_no_scores_file_says_so_and_fails(tmp_path, capsys):
    assert compare(tmp_path / "nothing.jsonl", "--base", BASE,
                   "--head", HEAD) == 1
    assert "nothing.jsonl" in capsys.readouterr().out


def test_replayed_runs_are_labelled_and_have_no_noise(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  record(BASE, "red-then-green", "pass", replayed=True,
                         source="eval", flow="fix-with-test"),
                  record(HEAD, "red-then-green", "finished", replayed=True,
                         source="eval", flow="fix-with-test"))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 1
    line = [l for l in capsys.readouterr().out.splitlines()
            if "red-then-green" in l][0]
    assert "replayed, no noise" in line
    assert "worse" in line
    assert "noise of" not in line


def test_a_move_within_the_repeats_spread_is_called_noise(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  *repeats(BASE, "total-spent", ["pass", "stopped", "pass"])
                  + repeats(HEAD, "total-spent",
                            ["stopped", "pass", "stopped"]))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 0
    line = [l for l in capsys.readouterr().out.splitlines()
            if "total-spent" in l][0]
    assert "worse" in line and "inside the noise of k 3" in line


def test_a_single_repeat_is_never_printed_as_a_rate(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  record(BASE, "total-spent", "pass"),
                  record(HEAD, "total-spent", "stopped"))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 1
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "total-spent" in l][0]
    assert "pass -> stopped" in line
    assert "1/1" not in out and "0/1" not in out and "%" not in out
    assert "inside the noise of k 1" in line


def test_a_task_missing_on_the_head_is_not_a_pass(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  record(BASE, "total-spent", "pass"),
                  record(BASE, "blank-note", "pass"),
                  record(HEAD, "blank-note", "pass"))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 1
    line = [l for l in capsys.readouterr().out.splitlines()
            if "total-spent" in l][0]
    assert "no record on head" in line


def test_an_unreadable_line_is_named_and_fails(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  record(BASE, "total-spent", "pass"),
                  record(HEAD, "total-spent", "pass"))
    with scores.open("a", encoding="utf-8") as f:
        f.write('{"sha": "' + HEAD + '", "task": \n')
        f.write(json.dumps(dict(record(HEAD, "x", "pass"), outcome="won"))
                + "\n")
    assert compare(scores, "--base", BASE, "--head", HEAD) == 1
    out = capsys.readouterr().out
    assert "line 3" in out and "line 4" in out


def test_records_made_with_uncommitted_changes_are_not_counted(tmp_path,
                                                                capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  record(BASE, "total-spent", "pass"),
                  record(BASE, "total-spent", "stopped", repeat=2, dirty=True),
                  record(HEAD, "total-spent", "pass"))
    assert compare(scores, "--base", BASE, "--head", HEAD) == 0
    out = capsys.readouterr().out
    assert "pass -> pass" in out
    assert "1 record made with uncommitted changes" in out


def test_the_base_is_the_nearest_earlier_commit_with_records(tmp_path,
                                                             monkeypatch,
                                                             capsys):
    older, parent = "c" * 40, "d" * 40
    scores = kept(tmp_path / "scores.jsonl",
                  record(older, "total-spent", "stopped"),
                  record(parent, "total-spent", "pass"),
                  record(HEAD, "total-spent", "stopped"))
    monkeypatch.setattr(history, "ancestors",
                        lambda sha: [HEAD, "e" * 40, parent, older])
    assert compare(scores, "--head", HEAD) == 1
    assert "base " + parent[:7] in capsys.readouterr().out


def test_a_short_sha_names_its_commit(tmp_path, capsys):
    scores = kept(tmp_path / "scores.jsonl",
                  record(BASE, "total-spent", "stopped"),
                  record(HEAD, "total-spent", "pass"))
    assert compare(scores, "--base", BASE[:7], "--head", HEAD[:9]) == 0


@pytest.fixture
def example(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(REPO / "flows")])
    shutil.copytree(REPO / "bench" / "example", tmp_path / "set")
    return tmp_path / "set"


def test_a_bench_keeps_one_record_per_task_and_repeat(example, tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(history, "commit", lambda *a: (HEAD, False))
    scores = tmp_path / "kept" / "scores.jsonl"
    assert bench(example, "--k", 2, "--out", tmp_path / "s.json",
                 "--scores", scores) == 0
    got = [json.loads(l) for l in scores.read_text(encoding="utf-8")
           .splitlines()]
    assert sorted((r["task"], r["repeat"]) for r in got) == [
        ("blank-note", 1), ("blank-note", 2), ("total-spent", 1),
        ("total-spent", 2), ("zero-amount", 1), ("zero-amount", 2)]
    for r in got:
        assert set(r) == set(record(HEAD, "t", "pass"))
        assert r["sha"] == HEAD and r["source"] == "bench"
        assert r["flow"] == "build-feature" and r["set"] == "set"
        assert r["outcome"] in ("finished", "stopped")
        assert r["replayed"] is False
    total = [r for r in got if r["task"] == "total-spent"][0]
    assert (total["score"], total["of"]) == (1, 4)


def test_a_second_bench_appends(example, tmp_path, monkeypatch):
    monkeypatch.setattr(history, "commit", lambda *a: (HEAD, False))
    scores = tmp_path / "scores.jsonl"
    for _ in range(2):
        assert bench(example, "--out", tmp_path / "s.json",
                     "--scores", scores) == 0
    assert len(scores.read_text(encoding="utf-8").splitlines()) == 6


def test_the_default_scores_file_is_under_the_bench_folder():
    assert history.DEFAULT == Path("bench") / "scores.jsonl"


def test_scores_are_never_kept_inside_the_runs_folder(example, tmp_path,
                                                      capsys):
    from agentweft.runner import state

    assert bench(example, "--scores",
                 Path(state.RUNS) / "bench" / "s.jsonl") == 1
    assert "runs" in capsys.readouterr().out


def test_outside_a_git_tree_the_bench_says_nothing_is_kept(example, tmp_path,
                                                          monkeypatch,
                                                          capsys):
    monkeypatch.setattr(history, "commit", lambda *a: (None, False))
    scores = tmp_path / "scores.jsonl"
    assert bench(example, "--out", tmp_path / "s.json",
                 "--scores", scores) == 0
    assert not scores.exists()
    assert "no commit" in capsys.readouterr().out


def git(where, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false"] + list(args),
                   cwd=str(where), check=True, capture_output=True)


def test_the_commit_and_whether_tracked_files_changed(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "scores.jsonl").write_text("", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "one")
    monkeypatch.chdir(tmp_path)
    scores = Path("bench") / "scores.jsonl"
    sha, dirty = history.commit(scores)
    assert len(sha) == 40 and dirty is False
    (tmp_path / "loose.txt").write_text("untracked\n", encoding="utf-8")
    (tmp_path / "bench" / "scores.jsonl").write_text("{}\n", encoding="utf-8")
    assert history.commit(scores) == (sha, False)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert history.commit(scores) == (sha, True)
    assert history.ancestors(sha) == [sha]


def test_outside_git_there_is_no_commit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert history.commit() == (None, False)
    assert history.ancestors(HEAD) == []


@pytest.fixture
def digest(tmp_path, monkeypatch):
    import yaml

    from agentweft.evals import harness

    flow = "weekly-digest"
    flows = tmp_path / "flows"
    shutil.copytree(REPO / "flows" / flow, flows / flow)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    root = tmp_path / "evals"
    case = root / flow / "cases" / "two-files"
    shutil.copytree(REPO / "evals" / flow / "cases" / "busy-week" / "inbox",
                    case / "inbox")
    reply = ("VERDICT: ok\n\n## what changed\n- a.md | changed | x\n\n"
             "## needs me\n- b.md | needs-me | y\n")
    plan = ("TASK: a.md\nLIST: changed\nWHY: x\nFILES:\n- a.md\n\n"
            "TASK: b.md\nLIST: needs-me\nWHY: y\nFILES:\n- b.md\n")
    (case / "case.yaml").write_text(yaml.safe_dump(
        {"inbox": "inbox", "provider": {"provider": "fake", "reply": reply,
                                        "replies": {"planner.md": plan}},
         "expect": {"invariants": "all"}}), encoding="utf-8")
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "LAST", root / ".last.json")
    monkeypatch.setattr(history, "commit", lambda *a: (HEAD, False))
    return tmp_path / "scores.jsonl"


def evals(monkeypatch, *args):
    from agentweft.evals import __main__ as evals_main

    monkeypatch.setattr(sys, "argv", ["evals", "weekly-digest"] + list(args))
    return evals_main.main()


def test_an_eval_keeps_a_record_and_says_when_it_was_replayed(digest,
                                                             monkeypatch):
    scores = str(digest)
    assert evals(monkeypatch, "--case", "two-files", "--record", "--scores",
                 scores) == 0
    assert evals(monkeypatch, "--scores", scores) == 0
    got = [json.loads(l) for l in digest.read_text(encoding="utf-8")
           .splitlines()]
    assert [r["replayed"] for r in got] == [False, True]
    for r in got:
        assert set(r) == set(record(HEAD, "t", "pass"))
        assert (r["source"], r["flow"], r["task"], r["repeat"]) == (
            "eval", "weekly-digest", "two-files", 1)
        assert r["outcome"] == "pass" and r["score"] == r["of"] > 0


def test_an_eval_not_saved_keeps_no_record(digest, monkeypatch):
    assert evals(monkeypatch, "--no-save", "--scores", str(digest)) == 0
    assert not digest.exists()
