"""the shipped code-review flow takes the diff to review as the run's task.

its promise says its input is a unified diff, so the diff is given the way
every task is, `--task "<text>"` or `--task-file <path>`, and reaches the
worker that reviews it and the reviewer that holds each finding to a line of
it. a run with no diff is refused before anything is called, and the caps
are the flow's own.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.guardrails import budget
from agentweft.runner import cli, prompts, task
from agentweft.runner.config import config

from test_task import asking, folders, run

FLOWS = Path(__file__).resolve().parents[1] / "flows"
# a path with a backslash and a word cp1252 has no byte for
DIFF = ("--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def last(items):\n"
        "-    return items[-1]\n+    return items[len(items)]  # "
        + chr(0x41f) + chr(0x440) + chr(0x438) + "\n"
        "--- a/docs\\notes.md\n+++ b/docs\\notes.md\n@@ -1 +1 @@\n-one\n+two\n")
FINDING = "- [high] app.py:2 the loop reads one past the end of items\n"


def shipped(tmp_path, monkeypatch):
    flow = tmp_path / "flows" / "code-review"
    shutil.copytree(FLOWS / "code-review", flow)
    # a step with tools goes to the cli provider; without them the call the
    # test answers sees the same prompt
    yml = flow / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8").replace(
        "    tools: [read, grep, shell]\n", ""), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])


def test_a_diff_file_reaches_the_worker_and_the_reviewer(tmp_path,
                                                         monkeypatch):
    shipped(tmp_path, monkeypatch)
    (tmp_path / "change.diff").write_bytes(DIFF.encode("utf-8"))
    asked = asking(monkeypatch, {"worker.md": FINDING,
                                 "reviewer.md": "VERDICT: ok\n\n" + FINDING})
    run(monkeypatch, "code-review", "--force", "--task-file", "change.diff")
    said = dict(asked)
    for step in ("worker.md", "reviewer.md"):
        assert DIFF in said[step], step
        assert task.MARK not in said[step], step
    [folder] = folders(tmp_path)
    assert (folder / task.FILE).read_bytes() == DIFF.encode("utf-8")


def test_a_diff_given_as_text_reaches_the_worker(tmp_path, monkeypatch):
    shipped(tmp_path, monkeypatch)
    asked = asking(monkeypatch, {"worker.md": FINDING,
                                 "reviewer.md": "VERDICT: ok\n\n" + FINDING})
    run(monkeypatch, "code-review", "--force", "--task", DIFF)
    assert DIFF in dict(asked)["worker.md"]


def test_a_review_with_no_diff_is_refused_before_any_call(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    shipped(tmp_path, monkeypatch)
    asked = asking(monkeypatch)
    code = run(monkeypatch, "code-review", "--force")
    assert code != 0
    assert asked == []
    assert "code-review takes a task" in capsys.readouterr().out


def test_show_says_where_code_review_takes_its_diff(monkeypatch, capsys):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(sys, "argv", ["run.py", "show", "code-review"])
    cli.cmd_show()
    assert "  task: {TASK} in instructions.md" in capsys.readouterr().out


def test_the_code_review_caps_are_the_flow_s_own(monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    fm = config("code-review")
    assert (fm.raw["max_calls"], fm.raw["max_tokens"]) == (7, 160000)


def spent(fm, *steps):
    b = budget.Budget(fm.raw["max_calls"], fm.raw["max_tokens"])
    b.retro = True
    counted = dict.fromkeys(budget.SPLIT, 0)
    for step in steps:
        for k, v in step.items():
            counted[k] += v
    return b.restore({"counted": counted, "counted_calls": len(steps),
                      "calls": len(steps)})


# `input` holds the cache reads, as a provider reports it
WORKER_BIG = {"input": 861918, "output": 8920, "cache_read": 800310,
              "cache_creation": 61584}
WORKER = {"input": 139239, "output": 5772, "cache_read": 105142,
          "cache_creation": 34091}
REVIEWER = {"input": 418579, "output": 7401, "cache_read": 360571,
            "cache_creation": 57992}


def test_a_review_s_worker_at_its_measured_size_leaves_the_reviewer_room(
        monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    b = spent(config("code-review"), WORKER_BIG)
    assert b.capped == 70528
    assert b.ahead() is None


def test_a_measured_review_leaves_its_retro_room(monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    b = spent(config("code-review"), WORKER, REVIEWER)
    assert b.capped == 105278
    assert b.ahead(retro=True) is None


def test_the_code_review_cap_still_stops_a_runaway(monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    b = spent(config("code-review"), WORKER_BIG, WORKER_BIG)
    word, why = b.ahead()
    assert word in (budget.REACHED, budget.REACHING)
    assert why.startswith("token cap: 141056 of ")
