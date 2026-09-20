"""two stances of one role disagree, and the judge is what ends it.

both of them reaching the judge is half of it. the other half is what comes
back, and nothing has held a run to that yet: a judge handed one report reads
exactly like a judge handed two, right up to the point where the verdict is the
last report with a heading on it.

so these drive a pair through the provider the examples ship with, a canned
answer per step, and hold the run against what it produced. the two stances are
kept apart under the names that tell them apart, a judge that names the ROLE is
handed both of them, and the judgement takes the side of the one that did NOT
run last, on a rule it names from the table.
"""
import pathlib
import sys

sys.path.insert(0, ".")
from agentweft.flow.spec import step_id
from agentweft.orchestrate import synthesise, workflow
from agentweft.roles import resolver
from agentweft.runner import engine, prompts
from agentweft.runner.config import config
from agentweft.runner.handoff import EMPTY

NL = chr(10)

# resolved before any test changes directory. `workflow.ROOT` is relative, and
# a run judged from a tmp dir would read an empty conflict table from it and
# pass every citation for want of anything to hold it against.
ORCHESTRATE = str(pathlib.Path("orchestrate").resolve())

WORKER = ("a.py - reads the flow file" + NL
          + "b.py - walks the steps" + NL
          + "the folder is where the runner lives")
DECISION = "drop the lines that name no file"
MINIMAL = ("two of the three lines name a file and one does not." + NL
           + DECISION + ".")
MAXIMAL = "keep all three lines, and say what each of them is for."

JUDGEMENT = NL.join([
    "VERDICT: ok",
    "",
    "## Rulings",
    "- one drops the lines that name no file and one keeps them -> "
    + DECISION + " -> the change only serves elegance",
    "",
    "## Deliberately not fixing",
    "- what the lines that stay are called. neither of them raised it.",
    ""])


def a_step(role, prompt, reply, reports=None):
    """a step with its own canned answer, so the pair can differ for real."""
    out = ["  - role: " + role, "    prompt: " + prompt]
    if reports:
        out.append("    reports: [" + ", ".join(reports) + "]")
    out = out + ["    provider:", "      provider: fake",
                 "      reply: " + repr(reply).replace("'", '"')]
    return NL.join(out) + NL


def a_flow(tmp_path, reports):
    root = tmp_path / "flows"
    d = root / "split"
    d.mkdir(parents=True)
    (d / "instructions.md").write_text("one list, and two readings of it." + NL,
                                       encoding="utf-8")
    (d / "worker.md").write_text("list what you read, a line a file." + NL,
                                 encoding="utf-8")
    (d / "reviewer-minimalist.md").write_text(
        "the list is too long. say less." + NL, encoding="utf-8")
    (d / "reviewer-maximalist.md").write_text(
        "the list is too thin. say what else it could have been." + NL,
        encoding="utf-8")
    (d / "flow.yaml").write_text(
        "name: split" + NL + "steps:" + NL
        + a_step("worker", "worker.md", WORKER)
        + a_step("reviewer", "reviewer-minimalist.md", MINIMAL)
        + a_step("reviewer", "reviewer-maximalist.md", MAXIMAL)
        + a_step("judge", "judge.md", JUDGEMENT, reports)
        + "timeout: 120" + NL + "journal: false" + NL
        + "provider:" + NL + "  provider: fake" + NL,
        encoding="utf-8")
    return root


def a_run(tmp_path, monkeypatch, reports):
    """the flow run step by step, handing back the Run that did it.

    `run_once` keeps its own and gives back the last output, and what each step
    produced is the thing being held here.
    """
    root = a_flow(tmp_path, reports)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(workflow, "ROOT", [ORCHESTRATE])
    monkeypatch.chdir(tmp_path)
    fm = config("split")
    by_role = resolver.resolve(fm.raw, prompts.flow_path("split"),
                               fm.promises.as_prompt())
    run = engine.Run("split", fm, by_role)
    out = EMPTY
    for step in [step_id(s) for s in fm.steps]:
        out = run.step(step, previous=out)
    return run


def test_the_pair_is_two_reports_and_not_one_written_over(tmp_path, monkeypatch):
    """the stance is in the step, so the record of what ran has to be too. one
    key for the role is the second reviewer landing on the first."""
    run = a_run(tmp_path, monkeypatch, ["reviewer"])
    assert sorted(run.produced) == ["judge.md", "reviewer-maximalist.md",
                                    "reviewer-minimalist.md", "worker.md"]
    assert DECISION in run.produced["reviewer-minimalist.md"]
    assert DECISION not in run.produced["reviewer-maximalist.md"]


def test_a_judge_that_names_the_role_is_handed_both_of_its_stances(tmp_path,
                                                                   monkeypatch):
    """`reports: [reviewer]` is a person naming the pair, not one of them."""
    run = a_run(tmp_path, monkeypatch, ["reviewer"])
    reports = run.reports_for("judge.md")
    assert [r.source for r in reports] == ["reviewer-minimalist",
                                           "reviewer-maximalist"]
    assert reports[0].text != reports[1].text
    brief = synthesise.brief(reports)
    assert "--- reviewer-minimalist ---" in brief
    assert "--- reviewer-maximalist ---" in brief


def test_the_judgement_takes_a_side_and_names_the_rule_it_took_it_on(
        tmp_path, monkeypatch):
    """the verdict is read back against the reports it was reached from.

    the side it takes is the stance that ran FIRST, which is the one a run that
    kept only the last report could not have got it from.
    """
    run = a_run(tmp_path, monkeypatch, ["reviewer"])
    sides = dict((r.source, r.text) for r in run.reports_for("judge.md"))
    assert DECISION in sides["reviewer-minimalist"]
    assert DECISION not in sides["reviewer-maximalist"]
    v = synthesise.read(run.produced["judge.md"])
    assert v.verdict() == "ok"
    assert synthesise.faults(v) == []
    assert len(v.rulings) == 1
    assert v.rulings[0].decision == DECISION
    assert v.rulings[0].rule().ruling == "scope creep, drop it"


def test_a_role_and_one_of_its_stances_are_one_report_not_two(tmp_path,
                                                              monkeypatch):
    """the role already stands for the step, so naming both is one report and
    a pair that is still a pair."""
    run = a_run(tmp_path, monkeypatch, ["reviewer", "reviewer-minimalist"])
    reports = run.reports_for("judge.md")
    assert [r.source for r in reports] == ["reviewer-minimalist",
                                           "reviewer-maximalist"]
    assert synthesise.brief(reports).count(DECISION) == 1


def test_the_last_word_of_a_finished_run_is_the_judgement(tmp_path, monkeypatch):
    """the same flow through main(), because the parts above are held one at a
    time and a run is the four of them in a row: both stances are written down
    under their own names, and what the run saved is what the judge decided
    rather than the reading that happened to be last.
    """
    root = a_flow(tmp_path, ["worker", "reviewer"])
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(workflow, "ROOT", [ORCHESTRATE])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "split", "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    where = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]
    assert DECISION in (where / "reviewer-minimalist.md").read_text(
        encoding="utf-8")
    assert DECISION not in (where / "reviewer-maximalist.md").read_text(
        encoding="utf-8")
    saved = [p for p in (tmp_path / "runs").iterdir()
             if p.is_file() and p.name.startswith("split-")]
    v = synthesise.read(saved[0].read_text(encoding="utf-8"))
    assert v.verdict() == "ok"
    assert synthesise.faults(v) == []
