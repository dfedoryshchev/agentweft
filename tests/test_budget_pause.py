"""a run near its cap pauses before the step that would cross it, says how
far it got, and carries on only once the cap is raised."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.guardrails.budget import Budget
from agentweft.orchestrate import decisions
from agentweft.runner import engine, manifest, prompts, stops

NL = chr(10)
THREE = [("a", []), ("b", []), ("c", [])]


def a_flow(tmp_path, monkeypatch, name, steps, tail=""):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + NL + "steps:" + NL
    for role, extra in steps:
        body = body + "  - role: " + role + NL + "    prompt: " + role + ".md" + NL
        for line in extra:
            body = body + "    " + line + NL
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    return d


def asking(monkeypatch, answer=None):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if answer is not None:
            return answer(step, prompt), False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def folders(tmp_path):
    runs = tmp_path / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() \
        else []


def last_line(tmp_path):
    lines = [l for l in (tmp_path / "runs" / "journal.md")
             .read_text(encoding="utf-8").split(NL) if l.strip()]
    return stops.read(lines[-1])


def test_two_calls_of_two_park_before_the_third_step(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "capped", THREE, tail="max_calls: 2" + NL)
    asked = asking(monkeypatch)
    assert run(monkeypatch, "capped", "--force") == stops.EXIT_STOP
    assert asked == ["a.md", "b.md"]
    [first] = folders(tmp_path)
    line = last_line(tmp_path)
    assert (line.status, line.cause) == ("parked at c.md", stops.BUDGET)
    assert line.spend.startswith("2 calls")
    note = (first / "handoff.md").read_text(encoding="utf-8")
    assert "reached" in note and "completion 2/3" in note
    assert "stopped before c.md" in note and "c.md has not run" in note
    m = manifest.load(first)
    assert m.data["outcome"] == "needs you: budget"
    assert m.step("c.md")["state"] == manifest.NOT_RUN


def test_a_run_at_eighty_percent_of_its_token_cap_parks_reaching(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "near", THREE,
           tail="max_tokens: 12000" + NL)
    # forty thousand characters are ten thousand estimated tokens: past 80%
    # of the cap before the prompt is counted, under the cap with it
    asked = asking(monkeypatch, lambda step, prompt: "x" * 40000)
    assert run(monkeypatch, "near", "--force") == stops.EXIT_STOP
    assert asked == ["a.md"]
    [first] = folders(tmp_path)
    note = (first / "handoff.md").read_text(encoding="utf-8")
    assert "reaching" in note and "completion 1/3" in note
    assert last_line(tmp_path).cause == stops.BUDGET


def test_a_budget_park_is_not_carried_on_without_a_raised_cap(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "same", THREE, tail="max_calls: 2" + NL)
    asked = asking(monkeypatch)
    run(monkeypatch, "same", "--force")
    assert asked == ["a.md", "b.md"]
    [first] = folders(tmp_path)
    asked.clear()
    capsys.readouterr()
    assert run(monkeypatch, "same", "--resume", first.name) == 1
    assert "--max-calls" in capsys.readouterr().out
    assert asked == []
    assert folders(tmp_path) == [first]


def test_a_raised_cap_carries_on_at_the_step_that_did_not_run(tmp_path,
                                                              monkeypatch):
    a_flow(tmp_path, monkeypatch, "raised", THREE, tail="max_calls: 2" + NL)
    asked = asking(monkeypatch)
    run(monkeypatch, "raised", "--force")
    [first] = folders(tmp_path)
    asked.clear()
    assert run(monkeypatch, "raised", "--resume", first.name,
               "--max-calls", "3") == stops.EXIT_OK
    assert asked == ["c.md"]
    [resumed] = [p for p in folders(tmp_path) if p != first]
    assert Budget().restore(manifest.load(resumed).spend).calls == 3
    [said] = decisions.read(tmp_path)
    assert "call cap" in said.decided
    assert "2" in said.decided and "3" in said.decided


def test_a_fanned_step_wider_than_what_is_left_parks_before_it(tmp_path,
                                                               monkeypatch):
    a_flow(tmp_path, monkeypatch, "wide",
           [("planner", []), ("worker", ["fanout: true"]), ("merge", [])],
           tail="max_calls: 3" + NL)

    def answer(step, prompt):
        if step == "planner.md":
            return NL.join("TASK: look at " + f + NL + "FILES:" + NL + "- "
                           + f + ".py" + NL for f in "abc")
        return "looked" + NL

    asked = asking(monkeypatch, answer)
    assert run(monkeypatch, "wide", "--force") == stops.EXIT_STOP
    assert asked == ["planner.md"]
    note = (folders(tmp_path)[0] / "handoff.md").read_text(encoding="utf-8")
    assert "completion 1/3" in note


def test_the_call_cap_is_checked_before_the_call_not_after():
    b = Budget(max_calls=2)
    assert b.ahead() is None
    b.calls = 2
    word, why = b.ahead()
    assert word == "reached" and "call cap" in why
    assert Budget(max_calls=4).ahead(charge=5)[0] == "reached"


def test_the_token_cap_says_reaching_at_eighty_percent_and_reached_at_it():
    b = Budget(max_tokens=100)
    b.estimated, b.estimated_calls = 79, 1
    assert b.ahead() is None
    b.estimated = 80
    assert b.ahead()[0] == "reaching"
    b.estimated = 100
    assert b.ahead()[0] == "reached"


def test_the_caps_are_kept_with_the_spend_and_not_restored_from_it():
    b = Budget(max_calls=2, max_tokens=50)
    kept = json.loads(json.dumps(b.saved()))
    assert (kept.get("max_calls"), kept.get("max_tokens")) == (2, 50)
    assert Budget(max_calls=9).restore(kept).max_calls == 9
