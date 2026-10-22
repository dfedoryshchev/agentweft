"""the shipped build-feature flow's second reviewer holds the change to the
project's own way as well as running it: the facts the runner hands it for
the files it is handed, the spec as the run found it and the code beside the
change are its yardstick, and a change done a way they rule out is a redo
with the convention quoted. canned answers, a real pytest in a git repo, as
`test_wrong_test.py` runs them.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.flow import reader
from agentweft.flow import spec as flowspec
from agentweft.orchestrate import facts
from agentweft.runner import stops

from test_wrong_test import AFTER, OK, PLAN, RIGHT, TESTER, NL, run_it

FLOWS = Path(__file__).resolve().parents[1] / "flows"
RETRO = "retro.md"
CLAIM = "calc raises ValueError on bad input, never prints"
WHY = "one error line on stderr, said by the caller"
WORKER = ("- calc.py: mul(a, b) added" + NL + NL + "HANDOFF" + NL + "DID:" + NL
          + "- calc.py:4-5 - mul added beside add" + NL + "END HANDOFF" + NL)
RAISES = WORKER.replace("mul added beside add", "mul raises, as calc does")
BREACH = ("VERDICT: redo" + NL + "CONVENTION: F-0001 \"" + CLAIM + "\": mul"
          " prints its error at calc.py:6" + NL + NL + WORKER)


def the_fact():
    return NL.join(["## F-0001 live", "scope: calc.py", "kind: convention",
                    "claim: " + CLAIM, "why: " + WHY,
                    "source: run r-1 step worker.md seq 2; evidence: TASK.md:3"
                    ' "mul(a, b) returns a times b"', ""])


def with_a_fact(project):
    where = project / "facts" / "calc.py.md"
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(the_fact(), encoding="utf-8", newline=NL)


def runs_with_a_fact(tmp_path, monkeypatch, answers, writes):
    from test_wrong_test import git

    real = git

    def seeded(where, *args):
        if args[:1] == ("add",):
            with_a_fact(Path(where))
        return real(where, *args)

    monkeypatch.setattr(sys.modules["test_wrong_test"], "git", seeded)
    return run_it(tmp_path, monkeypatch, answers, writes)


def second_of(flow):
    return [s for s in flow.steps if s["role"] == "reviewer"][1]


def test_the_shipped_second_reviewer_reads_for_the_projects_own_way():
    flow = flowspec.load(reader.read((FLOWS / "build-feature" / "flow.yaml")
                                     .read_text(encoding="utf-8")))
    assert "the project's own way" in second_of(flow)["lens"]
    words = " ".join((FLOWS / "build-feature" / "reviewer-runs.md").read_text(
        encoding="utf-8").split())
    assert "facts for the files you are handed" in words
    assert "CONVENTION:" in words


def test_the_second_reviewer_is_handed_the_facts_and_the_lens(tmp_path,
                                                              monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER], "reviewer.md": [OK],
               "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER)]}
    asked, sent, code, _, project = runs_with_a_fact(tmp_path, monkeypatch,
                                                     answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    second = sent[4]
    assert "# reviewer" in second
    assert "you read for: what the tests do not run, and the project's own" \
        " way" in second
    assert "F-0001 calc.py (convention): " + CLAIM in second
    assert "why: " + WHY in second
    assert [f.id for f in facts.read(project)] == ["F-0001"]


def test_a_breach_quoted_sends_the_worker_back_with_it(tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER, RAISES], "reviewer.md": [OK],
               "reviewer-runs.md": [BREACH, OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER), ("", "")]}
    asked, sent, code, folder, _ = runs_with_a_fact(tmp_path, monkeypatch,
                                                    answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    again = sent[5]
    assert "# worker" in again
    assert "CONVENTION: F-0001" in again
    steps = (folder / "steps.jsonl").read_text(encoding="utf-8")
    assert '"to": "worker.md"' in steps


def test_a_breach_the_reviewer_names_counts_against_the_fact(tmp_path,
                                                             monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER, RAISES], "reviewer.md": [OK],
               "reviewer-runs.md": [BREACH, OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER), ("", "")]}
    _, _, code, _, project = runs_with_a_fact(tmp_path, monkeypatch, answers,
                                              writes)
    assert code == stops.EXIT_OK
    seen = [f.get("seen") for f in facts.read(project)]
    assert len(seen) == 1 and "contradicted 1" in seen[0]


def test_only_a_pass_sent_back_on_its_own_redo_names_breaches(tmp_path):
    from agentweft.guardrails import factsguard

    (tmp_path / "a.md").write_text(BREACH + "CONVENTION: F-0001 again" + NL
                                   + "CONVENTION: F-0002 \"x\": y" + NL,
                                   encoding="utf-8")
    (tmp_path / "b.md").write_text(OK + "WOULD PASS: mul(a, b) = a + a" + NL
                                   + "CONVENTION: F-0001 \"x\": y" + NL,
                                   encoding="utf-8")
    redo = {"outcome": "redo", "file": "a.md"}
    assert factsguard.breaches(redo, tmp_path) == ["F-0001", "F-0002"]
    assert factsguard.breaches(dict(redo, outcome="ok"), tmp_path) == []
    assert factsguard.breaches(dict(redo, file="b.md"), tmp_path) == []
    assert factsguard.breaches(dict(redo, file="gone.md"), tmp_path) == []


def test_a_convention_line_on_a_verdict_that_is_no_redo_counts_nothing(
        tmp_path, monkeypatch):
    said = OK + "CONVENTION: F-0001 \"" + CLAIM + "\": held" + NL
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [WORKER], "reviewer.md": [OK],
               "reviewer-runs.md": [said]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER)]}
    _, _, code, _, project = runs_with_a_fact(tmp_path, monkeypatch, answers,
                                              writes)
    assert code == stops.EXIT_OK
    assert "contradicted 0" in facts.read(project)[0].get("seen")
