"""a reviewer that sends a fanned-out step back gets the planner's tasks again.

the redo used to hand the fanned step the reviewer's words as if they were the
plan. no line of a review has a | in it, so the step split it into no tasks,
produced nothing, and the run stopped at the worker on the first redo it saw.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, prompts, trace

NL = chr(10)
PLAN = "a.py | look at a" + NL + "b.py | look at b" + NL
FINDING = "b.py: the line number is missing"


def flow(tmp_path, name, workers=2):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = ("name: " + name + NL
            + "steps:" + NL
            + "  - role: planner" + NL
            + "    prompt: planner.md" + NL
            + "  - role: worker" + NL
            + "    prompt: worker.md" + NL
            + "    fanout: true" + NL
            + "    workers: " + str(workers) + NL
            + "  - role: reviewer" + NL
            + "    prompt: reviewer.md" + NL
            + "provider:" + NL
            + "  provider: fake" + NL)
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (d / "instructions.md").write_text("look at the files." + NL,
                                       encoding="utf-8")
    for role in ("planner", "worker"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "reviewer.md").write_text("you are the reviewer." + NL + NL
                                   + "VERDICT: ok" + NL + "VERDICT: redo" + NL,
                                   encoding="utf-8")
    return tmp_path / "flows"


def go(tmp_path, monkeypatch, plan, reviews, workers=2):
    """run main() with a planner that says `plan` and a reviewer that says each
    of `reviews` in turn. -> every (step, prompt) asked, in order."""
    root = flow(tmp_path, "fan-redo", workers)
    asked = []
    said = list(reviews)

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        if step == "planner.md":
            return plan, False
        if step == "reviewer.md":
            return said.pop(0), False
        task = prompt.split("your task, only this one:")[1].strip().split(NL)[0]
        round_ = sum(1 for s, _ in asked if s == "reviewer.md") + 1
        return "- " + task + " done, round " + str(round_) + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "fan-redo", "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    return asked


def steps_of(asked):
    return [s for s, _ in asked]


def workers_in_round(asked, n):
    """-> the worker prompts between reviewer n-1 and reviewer n."""
    rounds = [[]]
    for s, p in asked:
        if s == "reviewer.md":
            rounds.append([])
        elif s == "worker.md":
            rounds[-1].append(p)
    return rounds[n - 1]


def journal(tmp_path):
    lines = (tmp_path / "runs" / "journal.md").read_text(
        encoding="utf-8").strip().split(NL)
    return lines[-1].split("  ")[2]


def trail(tmp_path):
    run = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    return [json.loads(l) for l in (run / trace.FILE).read_text(
        encoding="utf-8").split(NL) if l.strip()]


def test_a_redo_runs_the_plans_tasks_again_and_reaches_the_reviewer(
        tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, PLAN,
               ["VERDICT: redo" + NL + NL + FINDING + NL,
                "VERDICT: ok" + NL + NL + "fine" + NL])
    assert steps_of(asked) == ["planner.md", "worker.md", "worker.md",
                               "reviewer.md", "worker.md", "worker.md",
                               "reviewer.md"]
    again = workers_in_round(asked, 2)
    assert sorted(p.split("your task, only this one:")[1].strip().split(NL)[0]
                  for p in again) == ["a.py | look at a", "b.py | look at b"]
    assert all(FINDING in p for p in again)
    assert not any(FINDING in p for p in workers_in_round(asked, 1))
    assert journal(tmp_path) == "ok"
    assert [l["step"] + " " + l["outcome"] for l in trail(tmp_path)] == [
        "planner.md ok", "worker.md ok", "reviewer.md redo", "worker.md ok",
        "reviewer.md ok"]
    reviewed = [p for s, p in asked if s == "reviewer.md"][1]
    assert "round 2" in reviewed and "round 1" not in reviewed


def test_redos_go_round_until_the_cap_then_park(tmp_path, monkeypatch):
    first = "a.py: says nothing about the loop"
    asked = go(tmp_path, monkeypatch, PLAN,
               ["VERDICT: redo" + NL + NL + first + NL,
                "VERDICT: redo" + NL + NL + FINDING + NL,
                "VERDICT: redo" + NL + NL + "still not right" + NL])
    assert steps_of(asked).count("planner.md") == 1
    assert steps_of(asked).count("worker.md") == 6
    assert steps_of(asked).count("reviewer.md") == 3
    assert all(first in p for p in workers_in_round(asked, 2))
    third = workers_in_round(asked, 3)
    assert all(FINDING in p and first not in p for p in third)
    assert journal(tmp_path) == "parked at reviewer.md"


def test_a_plan_with_one_task_redoes_that_one_task(tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, "a.py | look at a" + NL,
               ["VERDICT: redo" + NL + NL + FINDING + NL,
                "VERDICT: ok" + NL + NL + "fine" + NL])
    assert steps_of(asked) == ["planner.md", "worker.md", "reviewer.md",
                               "worker.md", "reviewer.md"]
    assert FINDING in workers_in_round(asked, 2)[0]
    assert journal(tmp_path) == "ok"


def test_more_workers_than_tasks_still_runs_each_task_once_a_round(
        tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, PLAN,
               ["VERDICT: redo" + NL + NL + FINDING + NL,
                "VERDICT: ok" + NL + NL + "fine" + NL], workers=5)
    assert len(workers_in_round(asked, 1)) == 2
    assert len(workers_in_round(asked, 2)) == 2
    assert journal(tmp_path) == "ok"


def test_a_plan_with_no_tasks_stops_and_says_why(tmp_path, monkeypatch,
                                                 capsys):
    asked = go(tmp_path, monkeypatch, "nothing changed this week" + NL, [])
    assert steps_of(asked) == ["planner.md"]
    assert journal(tmp_path) == "failed at worker.md"
    last = trail(tmp_path)[-1]
    assert last["step"] == "worker.md" and last["outcome"] == "failed"
    assert last["cause"] == "no answer"
    assert "what planner handed it has none" in last["why"]
    assert "run stopped at worker.md: worker.md is fanned out" \
        in capsys.readouterr().out


def test_the_first_pass_does_not_hand_the_workers_anything_but_their_task(
        tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, PLAN,
               ["VERDICT: ok" + NL + NL + "fine" + NL])
    assert all("here is what" not in p for p in workers_in_round(asked, 1))
