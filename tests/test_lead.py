"""a step's question goes to the flow's lead step first, and to the operator
only if the lead cannot decide.

`lead: <step>` in flow.yaml names the step that decides. a `NEEDS:` from any
other step goes to it with the question, its CITES and its OPTIONS at the end
of its prompt; `DECIDED: <option>` with a `why:` line under it goes into
decisions.md as the lead's, and the step that asked runs again with it. a
decision that changes the spec or a test the run started with, an
`ESCALATE:`, a second ask of the same question, or a flow with no lead parks
for the operator, the way a NEEDS always has. the shipped flows, on canned
answers and a real pytest in a git repo.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.orchestrate import decisions
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, resume, stops
from agentweft.runner.config import config

try:
    from agentweft.runner import lead
except ImportError:
    lead = None

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
TASK = "calc gets mul(a, b), as TASK.md says"
SPEC = "# calc" + NL + NL + "mul(a, b) returns a times b" + NL
BEFORE = "def add(a, b):" + NL + "    return a + b" + NL
AFTER = BEFORE + NL + NL + "def mul(a, b):" + NL + "    return a * b" + NL
TEST = ("def test_mul():" + NL + "    from calc import mul" + NL + NL
        + "    assert mul(2, 3) == 6" + NL)
PLAN = ("- behaviour: mul(2, 3) is 6" + NL + "  file: calc.py" + NL
        + "  spec: allows TASK.md:3" + NL)
TESTER = ("FAILS: ImportError: cannot import name 'mul' from 'calc'" + NL
          + "TEST: tests/test_mul.py" + NL)
WORKER = "- calc.py: mul(a, b) added" + NL
OK = "VERDICT: ok" + NL + NL + WORKER
NEEDS = ("NEEDS: should mul round a float product to an int?" + NL
         + "CITES:" + NL + "- TASK.md:3 - mul(a, b) returns a times b" + NL
         + "OPTIONS:" + NL + "- keep: return the product as it is" + NL
         + "- round: round it to an int" + NL)
DECIDED = ("DECIDED: keep: return the product as it is" + NL
           + "why: TASK.md:3 says a times b and nothing about rounding" + NL)


def git(where, *args):
    subprocess.run(["git", "-C", str(where), "-c", "user.email=t@t", "-c",
                    "user.name=t"] + list(args), check=True,
                   capture_output=True)


def run_it(tmp_path, monkeypatch, flow, answers, writes, task=TASK):
    """-> (steps asked, every prompt sent, exit code, the run's folder, the
    place)."""
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True, exist_ok=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(BEFORE, encoding="utf-8")
    (project / "TASK.md").write_text(SPEC, encoding="utf-8")
    git(project, "init", "-q")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "start")
    asked, sent = [], []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        n = asked.count(step)
        asked.append(step)
        sent.append(prompt)
        wrote = writes.get(step, [])
        if wrote:
            rel, text = wrote[min(n, len(wrote) - 1)]
            if rel:
                (project / rel).write_text(text, encoding="utf-8")
        said = answers.get(step, [""])
        return said[min(n, len(said) - 1)], False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", [
        "run.py", flow, "--force", "--flows", str(FLOWS),
        "--workdir", "project", "--task", task])
    code = engine.main()
    [folder] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    return asked, sent, code, folder, project


def build(tmp_path, monkeypatch, lead_says, worker_says=(NEEDS, WORKER)):
    answers = {"planner.md": [PLAN] + list(lead_says),
               "tester.md": [TESTER], "worker.md": list(worker_says),
               "reviewer.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", TEST)],
              "worker.md": [("", ""), ("calc.py", AFTER)]}
    return run_it(tmp_path, monkeypatch, "build-feature", answers, writes)


def test_the_planner_answers_a_workers_question_and_the_run_finishes(
        tmp_path, monkeypatch):
    asked, sent, code, folder, project = build(tmp_path, monkeypatch,
                                               [DECIDED])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "worker.md", "reviewer.md"]
    assert code == stops.EXIT_OK
    to_lead = sent[3]
    assert "# planner" in to_lead
    assert to_lead.rstrip().endswith("- round: round it to an int")
    assert "TASK.md:3 - mul(a, b) returns a times b" in to_lead
    again = sent[4]
    assert "# worker" in again
    assert again.rstrip().endswith(
        "why: TASK.md:3 says a times b and nothing about rounding")
    assert "keep: return the product as it is" in again
    [said] = decisions.read(project)
    assert said.decided.startswith("planner.md decided for worker.md: keep")
    assert "should mul round a float product" in said.why
    assert "why: TASK.md:3 says a times b" in said.why
    assert not (folder / "question.md").exists()


def test_a_decision_that_changes_task_md_parks_for_the_operator(
        tmp_path, monkeypatch):
    asked, _, code, folder, project = build(tmp_path, monkeypatch, [
        "DECIDED: round: change TASK.md:3 to say the product is rounded" + NL
        + "why: callers want ints" + NL])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert question.startswith("NEEDS: should mul round")
    assert "TASK.md" in question.split("OPTIONS:")[1]
    assert "the operator's" in question
    assert decisions.read(project) == []


def test_a_decision_that_changes_a_test_the_run_started_with_parks(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_add.py").write_text(
        "def test_add():" + NL + "    assert True" + NL, encoding="utf-8")
    lead_says = ["DECIDED: keep, and change tests/test_add.py::test_add to"
                 " match" + NL + "why: it pins the old shape" + NL]
    answers = {"planner.md": [PLAN] + lead_says, "tester.md": [TESTER],
               "worker.md": [NEEDS, WORKER], "reviewer.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", TEST)]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch,
                                       "build-feature", answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    assert "tests/test_add.py" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_escalate_parks_for_the_operator(tmp_path, monkeypatch):
    asked, _, code, folder, _ = build(tmp_path, monkeypatch, [
        "ESCALATE: the spec says nothing of floats and it is not mine" + NL])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert question.startswith("NEEDS: should mul round")
    assert "the spec says nothing of floats and it is not mine" in question


def test_a_second_ask_of_the_same_question_parks(tmp_path, monkeypatch):
    asked, _, code, folder, _ = build(tmp_path, monkeypatch, [DECIDED],
                                      worker_says=[NEEDS])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "worker.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert question.startswith("NEEDS: should mul round")
    assert "already" in question


def test_a_decision_with_no_why_parks(tmp_path, monkeypatch):
    asked, _, code, folder, _ = build(tmp_path, monkeypatch, [
        "DECIDED: keep: return the product as it is" + NL])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP
    assert "why:" in (folder / "question.md").read_text(encoding="utf-8")


def test_the_leads_own_question_goes_to_the_operator(tmp_path, monkeypatch):
    answers = {"planner.md": [NEEDS]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch,
                                       "build-feature", answers, {})
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP
    assert (folder / "question.md").is_file()


def test_a_conflict_never_goes_to_the_lead(tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN, DECIDED], "tester.md": [TESTER],
               "worker.md": ['CONFLICT: TASK.md:3 "mul(a, b) returns a times'
                             ' b"' + NL + "request: mul returns a plus b"
                             + NL]}
    writes = {"tester.md": [("tests/test_mul.py", TEST)]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch,
                                       "build-feature", answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_STOP
    assert "contradicts" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_fix_with_test_has_no_lead_and_parks_at_once(tmp_path, monkeypatch):
    answers = {"worker.md": [NEEDS]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch,
                                       "fix-with-test", answers, {},
                                       task="mul is missing from calc")
    assert asked == ["worker.md"]
    assert code == stops.EXIT_STOP
    assert (folder / "question.md").read_text(
        encoding="utf-8").startswith("NEEDS: should mul round")


def test_the_shipped_flows_name_their_lead():
    assert config("build-feature").get("lead") == "planner"
    assert config("fix-with-test").get("lead") == "none"


def base(**more):
    raw = {"name": "x", "steps": [{"role": "planner", "prompt": "planner.md"},
                                  {"role": "worker", "prompt": "worker.md"}]}
    raw.update(more)
    return raw


def test_lead_names_a_step_of_the_flow_or_none():
    assert spec.check(base(lead="planner")) == []
    assert spec.check(base(lead="planner.md")) == []
    assert spec.check(base(lead="none")) == []
    [said] = spec.check(base(lead="architect"))
    assert said.startswith("lead names no step of the flow: architect")


def test_a_fanned_step_cannot_lead():
    raw = base(lead="worker")
    raw["steps"][1]["fanout"] = True
    [said] = spec.check(raw)
    assert "fanned" in said


def test_the_decision_is_read_off_its_own_lines_and_never_split_on_a_pipe():
    assert lead is not None, "nothing reads the lead's answer"
    assert lead.read("DECIDED: a | b, the union" + NL + "why: TASK.md:4 says"
                     " a | b is either" + NL) == (
        "a | b, the union", "TASK.md:4 says a | b is either", None)
    assert lead.read("ESCALATE: not mine" + NL) == (None, "", "not mine")
    assert lead.read("```" + NL + "DECIDED: a" + NL + "```" + NL) == (
        None, "", None)


@pytest.mark.parametrize("decided, hit", [
    ("keep: return the product as it is", ""),
    ("change TASK.md:3 to say so", "TASK.md"),
    ("rewrite SPEC-calc.md", "SPEC-calc.md"),
    ("change tests/test_new.py, which is not there", ""),
])
def test_what_a_decision_would_change(tmp_path, decided, hit):
    assert lead is not None, "nothing reads the lead's answer"
    assert lead.changes(decided, tmp_path, None) == hit
