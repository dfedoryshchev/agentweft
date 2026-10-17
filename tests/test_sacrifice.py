"""a flow says in `sacrifice:` what it gives up when its budget is short. the
run cuts in that order, one at a time, only until the plan fits, and says
each cut as a named skip with its reason. the red test, the tests the run
started with and the suite gate are never on the list."""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import engine, prompts, stops

NL = chr(10)
GUARDED = [
    {"role": "tester", "prompt": "tester.md", "writes": "tests",
     "gates": [{"gate": "red-test", "red": True,
                "command": ["python", "-m", "pytest", "{test}"]}]},
    {"role": "worker", "prompt": "worker.md", "writes": "product",
     "gates": [{"gate": "command", "command": ["python", "-m", "pytest"]}]},
    {"role": "reviewer", "prompt": "reviewer.md", "writes": "none"},
    {"role": "reviewer", "prompt": "reviewer-wide.md", "writes": "none"},
    {"role": "verify", "prompt": "verify.md", "writes": "none"},
]


def said(sacrifice, steps=GUARDED, **more):
    raw = dict({"name": "f", "steps": steps, "sacrifice": sacrifice}, **more)
    return "; ".join(spec.check(raw))


def test_a_list_of_steps_and_roles_to_cut_is_taken():
    assert said(["reviewer-wide", "verify", "reviewer"]) == ""


def test_the_cause_step_can_be_on_the_list():
    assert said(["investigator"], investigate="cause") == ""


@pytest.mark.parametrize("name, what", [
    ("tester", "the red test"),
    ("worker", "the suite gate"),
    ("red-test", "the red test"),
    ("red-first", "the red test"),
    ("tests", "the red test"),
    ("start-tests", "the tests the run started with"),
    ("command", "the suite gate"),
])
def test_what_guards_the_tests_is_never_on_the_list(name, what):
    got = said([name])
    assert "never" in got and what in got and name in got


def test_a_step_that_writes_product_guards_the_tests_it_started_with():
    steps = [{"role": "worker", "prompt": "worker.md", "writes": "product"},
             {"role": "reviewer", "prompt": "reviewer.md", "writes": "none"}]
    got = said(["worker"], steps=steps)
    assert "never" in got and "the tests the run started with" in got


def test_a_name_that_is_no_step_is_refused_with_the_steps_there_are():
    got = said(["reviewr"])
    assert "reviewr" in got and "did you mean reviewer" in got


def test_the_list_is_one_name_per_item():
    assert "a list" in said("verify")
    assert "twice" in said(["verify", "verify"])
    assert "a step or a role" in said([{"effort": "reviewer"}])


def a_flow(tmp_path, monkeypatch, name, roles, tail):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + NL + "steps:" + NL
    for role, prompt in roles:
        body = body + "  - role: " + role + NL + "    prompt: " + prompt + NL
        (d / prompt).write_text("you are the " + role + "." + NL,
                                encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])


def asking(monkeypatch, answer=None):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if answer is not None:
            return answer(step), False
        return "VERDICT: ok" + NL + NL + "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def the_run(tmp_path):
    [folder] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    return folder


def listed(*names):
    return "sacrifice:" + NL + "".join("  - " + n + NL for n in names)


FOUR = [("a", "a.md"), ("reviewer", "reviewer.md"),
        ("reviewer", "reviewer-wide.md"), ("verify", "verify.md")]


def test_a_short_plan_cuts_in_the_order_given_and_only_until_it_fits(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "short", FOUR, "max_calls: 2" + NL
           + listed("reviewer-wide", "verify", "reviewer"))
    asked = asking(monkeypatch)
    assert run(monkeypatch, "short", "--force") == stops.EXIT_OK
    assert asked == ["a.md", "reviewer.md"]
    out = capsys.readouterr().out
    assert "RISKY" not in out
    assert "cut reviewer-wide.md" in out and "cut verify.md" in out
    folder = the_run(tmp_path)
    skipped = json.loads((folder / "skips.json").read_text(encoding="utf-8"))
    assert sorted(skipped) == ["reviewer-wide", "verify"]
    assert all(r.startswith("budget: ") for r in skipped.values())
    assert "4 calls" in skipped["reviewer-wide"]
    assert "3 calls" in skipped["verify"]
    plan = (folder / "budget-plan.md").read_text(encoding="utf-8")
    assert "reviewer-wide.md" in plan and "cut" in plan
    hand = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "verify skipped: budget: " in hand
    assert "(--skip)" not in hand
    assert "verify cut for the budget" in (
        folder / "decisions.md").read_text(encoding="utf-8")


def test_a_plan_that_fits_cuts_nothing(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "roomy", FOUR, "max_calls: 9" + NL
           + listed("reviewer-wide", "verify"))
    asked = asking(monkeypatch)
    assert run(monkeypatch, "roomy", "--force") == stops.EXIT_OK
    assert asked == [s for _, s in FOUR]
    assert not (the_run(tmp_path) / "skips.json").exists()


def test_a_list_that_cannot_make_it_fit_cuts_nothing_and_still_says_risky(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "tight", FOUR, "max_calls: 1" + NL
           + listed("verify"))
    asking(monkeypatch)
    run(monkeypatch, "tight", "--force")
    out = capsys.readouterr().out
    assert "RISKY" in out and "cut verify.md" not in out
    assert not (the_run(tmp_path) / "skips.json").exists()


FIVE = [(n, n + ".md") for n in ("a", "b", "c", "d", "e")]


def big_first(step):
    # ~81000 tokens on a cap of 100000: past the 80% the cap warns at
    return ("x" * 324000 if step == "a.md" else "ok") + NL


def ran_before(tmp_path, flow, tokens):
    """the record of an earlier run of `flow` here in which each step took
    `tokens`, so the plan's blocks are an estimate and not a split of the
    cap."""
    d = tmp_path / "runs" / (flow + "-1")
    d.mkdir(parents=True)
    (d / "workdir").write_text(str(tmp_path.resolve()), encoding="utf-8")
    lines = [json.dumps({"step": s, "tokens": {
        "counted": True, "input": tokens, "output": 0, "cache_read": 0}})
        for _, s in FIVE]
    (d / "steps.jsonl").write_text(NL.join(lines) + NL, encoding="utf-8")


def the_runs(tmp_path):
    return sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())


def test_near_the_cap_the_rest_is_cut_in_order_until_it_fits(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "near", FIVE, "max_tokens: 100000" + NL
           + listed("e", "d", "c", "b"))
    ran_before(tmp_path, "near", 6000)
    asked = asking(monkeypatch, big_first)
    run(monkeypatch, "near", "--force")
    assert asked[:2] == ["a.md", "b.md"] and "e.md" not in asked
    skipped = json.loads((the_runs(tmp_path)[-1] / "skips.json")
                         .read_text(encoding="utf-8"))
    assert sorted(skipped) == ["e"]
    assert skipped["e"].startswith("budget: token cap")


def test_near_the_cap_a_list_that_cannot_make_it_fit_parks_and_cuts_nothing(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "parks", FIVE, "max_tokens: 100000" + NL
           + listed("e"))
    ran_before(tmp_path, "parks", 8000)
    asked = asking(monkeypatch, big_first)
    assert run(monkeypatch, "parks", "--force") == stops.EXIT_STOP
    assert asked == ["a.md"]
    assert "paused before b.md" in capsys.readouterr().out
    assert not (the_runs(tmp_path)[-1] / "skips.json").exists()


def test_a_run_picked_up_later_cuts_again_what_still_does_not_fit(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "again", FOUR, "max_calls: 3" + NL
           + listed("verify"))
    asked = asking(monkeypatch, lambda step: "" if not asked[:-1] else
                   "VERDICT: ok" + NL + NL + "done" + NL)
    run(monkeypatch, "again", "--force")
    assert asked == ["a.md"]
    [first] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    run(monkeypatch, "again", "--force", "--resume", first.name,
        "--max-calls", "4")
    assert asked[1:] == ["a.md", "reviewer.md", "reviewer-wide.md"]
    assert "verify.md" not in asked
    [later] = [p for p in (tmp_path / "runs").iterdir()
               if p.is_dir() and p != first]
    skipped = json.loads((later / "skips.json").read_text(encoding="utf-8"))
    assert skipped["verify"].startswith("budget: ")
    assert "the call cap leaves 3" in skipped["verify"]
    assert "verify.md" in (later / "budget-plan.md").read_text(
        encoding="utf-8")


def test_a_resume_with_room_runs_what_the_first_leg_cut(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "raised", FOUR, "max_calls: 1" + NL
           + listed("verify"))
    asked = asking(monkeypatch)
    run(monkeypatch, "raised", "--force")
    assert "verify.md" not in asked
    [first] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    del asked[:]
    run(monkeypatch, "raised", "--force", "--resume", first.name,
        "--max-calls", "20")
    assert "verify.md" in asked


def test_a_resume_plans_the_cuts_again_against_its_cap(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "replan", FOUR, "max_calls: 3" + NL
           + listed("verify"))
    asked = asking(monkeypatch, lambda step: "" if not asked[:-1] else
                   "VERDICT: ok" + NL + NL + "done" + NL)
    run(monkeypatch, "replan", "--force")
    [first] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    assert "verify" in json.loads((first / "skips.json").read_text(
        encoding="utf-8"))
    run(monkeypatch, "replan", "--force", "--resume", first.name,
        "--max-calls", "20")
    assert asked[1:] == [s for _, s in FOUR]
    [later] = [p for p in (tmp_path / "runs").iterdir()
               if p.is_dir() and p != first]
    assert not (later / "skips.json").exists()
    assert "verify runs: no longer cut" in (later / "decisions.md").read_text(
        encoding="utf-8")


@pytest.mark.parametrize("gate", [
    {"gate": "project", "name": "tests"},
    {"gate": "coverage"},
    {"gate": "reject"},
])
def test_a_step_carrying_a_check_project_yml_declares_is_never_cut(gate):
    steps = [{"role": "worker", "prompt": "worker.md", "writes": "product"},
             {"role": "suite", "prompt": "suite.md", "writes": "none",
              "gates": [gate]}]
    got = said(["suite"], steps=steps)
    assert "never" in got and "project.yml" in got and "suite" in got


NEEDS = ("NEEDS: should the list be sorted?" + NL + "OPTIONS:" + NL
         + "- yes: sort it" + NL + "- no: keep the order given" + NL)


def test_a_cut_lead_is_not_called_to_decide_and_the_person_gets_the_question(
        tmp_path, monkeypatch, capsys):
    three = [("a", "a.md"), ("reviewer", "reviewer.md"),
             ("verify", "verify.md")]
    a_flow(tmp_path, monkeypatch, "led", three, "lead: a" + NL
           + "max_calls: 2" + NL + listed("a"))
    asked = asking(monkeypatch, lambda step: NEEDS if step == "reviewer.md"
                   else "VERDICT: ok" + NL + NL + "done" + NL)
    code = run(monkeypatch, "led", "--force")
    out = capsys.readouterr().out
    assert "cut a.md" in out
    assert "a.md" not in asked
    assert code == stops.EXIT_STOP
    assert "should the list be sorted?" in out


def test_near_the_cap_a_split_of_the_cap_is_no_estimate_to_cut_on(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "split", FIVE, "max_tokens: 100000" + NL
           + listed("e", "d", "c", "b"))
    asked = asking(monkeypatch, big_first)
    assert run(monkeypatch, "split", "--force") == stops.EXIT_STOP
    assert asked == ["a.md"]
    assert "paused before b.md" in capsys.readouterr().out
    assert not (the_run(tmp_path) / "skips.json").exists()


def test_near_the_cap_the_step_about_to_run_can_be_the_one_cut(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "next", FIVE, "max_tokens: 100000" + NL
           + listed("b"))
    ran_before(tmp_path, "next", 6000)
    asked = asking(monkeypatch, big_first)
    run(monkeypatch, "next", "--force")
    assert asked[:2] == ["a.md", "c.md"] and "b.md" not in asked


def test_a_run_with_cut_steps_says_they_were_not_done(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "partial", FOUR, "max_calls: 2" + NL
           + listed("reviewer-wide", "verify"))
    asking(monkeypatch)
    assert run(monkeypatch, "partial", "--force") == stops.EXIT_OK
    folder = the_run(tmp_path)
    hand = (folder / "handoff.md").read_text(encoding="utf-8")
    left = hand.split("## not done", 1)[1].split("## ", 1)[0]
    assert "cut for the budget" in left
    assert "verify: " in left and "reviewer-wide: " in left
    steps = json.loads((folder / "manifest.json").read_text(
        encoding="utf-8"))["steps"]
    state = dict((s["step"], s["state"]) for s in steps)
    assert state["verify.md"] == "not run"
