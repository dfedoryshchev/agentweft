"""the shipped code-review flow takes the diff to review as the run's task.

its promise says its input is a unified diff, so the diff is given the way
every task is, `--task "<text>"` or `--task-file <path>`, and reaches the
worker that reviews it and the reviewer that holds each finding to a line of
it. a run with no diff is refused before anything is called, and the caps
are the flow's own.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.guardrails import budget, defaults
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
    assert fm.raw["max_calls"] == 7
    assert "max_tokens" not in fm.raw
    assert defaults.for_flow(fm) == (7, 0)


def spent(fm, *steps, max_tokens=None):
    calls, tokens = defaults.for_flow(fm)
    b = budget.Budget(calls, tokens if max_tokens is None else max_tokens)
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


def test_a_review_twice_the_measured_size_still_reaches_its_reviewer(
        monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    b = spent(config("code-review"), WORKER_BIG, WORKER_BIG)
    assert b.capped == 141056
    assert b.ahead() is None
    assert b.ahead(retro=True) is None


def test_a_token_cap_the_operator_gives_still_pauses_a_review(monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    b = spent(config("code-review"), WORKER_BIG, WORKER_BIG,
              max_tokens=128000)
    word, why = b.ahead()
    assert word == budget.REACHED
    assert why.startswith("token cap: 141056 of 128000 ")


def a_call(text, counted):
    said = {"type": "result", "is_error": False, "result": text,
            "session_id": "s-1", "total_cost_usd": 0.25,
            "modelUsage": {"m-1": {}},
            "usage": {"input_tokens": counted, "output_tokens": 0}}
    return (0, json.dumps(said).encode("utf-8"), b"")


RETRO = "TICKETS: none\nFACTS: none\n"


def handoff(tmp_path):
    [folder] = folders(tmp_path)
    return (folder / "handoff.md").read_text(encoding="utf-8")


def test_a_review_counting_200k_tokens_reaches_its_reviewer_and_retro(
        tmp_path, monkeypatch, fake_cli):
    shipped(tmp_path, monkeypatch)
    cli = fake_cli(a_call(FINDING, 200000),
                   a_call("VERDICT: ok\n\n" + FINDING, 1000),
                   a_call(RETRO, 1000))
    code = run(monkeypatch, "code-review", "--force", "--task", DIFF)
    said = handoff(tmp_path)
    assert "token cap" not in said
    assert code == 0, said
    assert len(cli.calls) == 3
    [folder] = folders(tmp_path)
    lines = (folder / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    assert [(json.loads(x)["step"], json.loads(x)["outcome"])
            for x in lines] == [("worker.md", "ok"), ("reviewer.md", "ok"),
                                ("retro.md", "ok")]


def test_a_review_given_a_token_cap_still_pauses_before_its_reviewer(
        tmp_path, monkeypatch, fake_cli):
    shipped(tmp_path, monkeypatch)
    cli = fake_cli(a_call(FINDING, 200000),
                   a_call("VERDICT: ok\n\n" + FINDING, 1000),
                   a_call(RETRO, 1000))
    code = run(monkeypatch, "code-review", "--force", "--task", DIFF,
               "--max-tokens", "150000")
    said = handoff(tmp_path)
    assert code == 2
    assert "token cap: 200000 of 150000 spent" in said
    assert len(cli.calls) == 1
