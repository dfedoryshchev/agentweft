"""a step that finds a test it was given wrong says so, and where it goes
depends on who wrote the test.

`WRONG TEST: <node id>`, then `why:` and `spec:` lines. a test the run wrote
goes back to the step that wrote it, with the claim at the end of its prompt,
once (send_backs), and has to be red again; a test the run started with is a
ruling, the same park a NEEDS line is. the shipped build-feature flow, on
canned answers and a real pytest in a git repo.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.providers import cli_provider, fake_provider
from agentweft.runner import engine, prompts, resume, stops

try:
    from agentweft.runner import wrongtest
except ImportError:
    wrongtest = None

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
# the shipped flow looks back after every run that ends, once, last; a park
# for a ruling holds it
RETRO = "retro.md"
TASK ="calc gets mul(a, b), as TASK.md says"
SPEC = "# calc" + NL + NL + "mul(a, b) returns a times b" + NL
BEFORE = "def add(a, b):" + NL + "    return a + b" + NL
AFTER = BEFORE + NL + NL + "def mul(a, b):" + NL + "    return a * b" + NL


def a_test(want):
    return ("def test_mul():" + NL + "    from calc import mul" + NL + NL
            + "    assert mul(2, 3) == " + str(want) + NL)


WRONG = a_test(5)
RIGHT = a_test(6)
OLD = ("def test_old():" + NL + "    from calc import add" + NL + NL
       + "    assert add(2, 2) == 5" + NL)
PLAN = ("- behaviour: mul(2, 3) is 6" + NL + "  file: calc.py" + NL
        + "  spec: nothing in the spec" + NL)
TESTER = ("FAILS: ImportError: cannot import name 'mul' from 'calc'" + NL
          + "TEST: tests/test_mul.py" + NL)
WORKER = "- calc.py: mul(a, b) added" + NL
OK = "VERDICT: ok" + NL + NL + WORKER


def claim(node, spec='TASK.md:3 "mul(a, b) returns a times b"'):
    return ("WRONG TEST: " + node + NL + "why: 2 times 3 is 6, and the test"
            " wants 5" + NL + "spec: " + spec + NL)


def git(where, *args):
    subprocess.run(["git", "-C", str(where), "-c", "user.email=t@t", "-c",
                    "user.name=t"] + list(args), check=True,
                   capture_output=True)


def run_it(tmp_path, monkeypatch, answers, writes, old=False):
    """-> (steps asked, every prompt sent, exit code, the run's folder)."""
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(BEFORE, encoding="utf-8")
    (project / "TASK.md").write_text(SPEC, encoding="utf-8")
    if old:
        (project / "tests" / "test_old.py").write_text(OLD, encoding="utf-8")
    git(project, "init", "-q")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "start")
    asked, sent = [], []
    answers = dict({RETRO: [fake_provider.NOTHING_TO_KEEP]}, **answers)

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
        "run.py", "build-feature", "--force", "--flows", str(FLOWS),
        "--workdir", "project", "--task", TASK])
    code = engine.main()
    [folder] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    return asked, sent, code, folder, project


def test_a_wrong_test_the_tester_wrote_goes_back_to_it_and_is_red_again(
        tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_mul.py::test_mul"), WORKER],
               "reviewer.md": [OK], "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", WRONG),
                            ("tests/test_mul.py", RIGHT)],
              "worker.md": [("", ""), ("calc.py", AFTER)]}
    asked, sent, code, folder, project = run_it(tmp_path, monkeypatch,
                                                answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "tester.md",
                     "worker.md", "reviewer.md", "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    again = sent[3]
    assert "# tester" in again
    assert again.rstrip().endswith('TASK.md:3 "mul(a, b) returns a times b"')
    assert "tests/test_mul.py::test_mul" in again
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    second = gates.split("## tester.md")[2].split("##")[0]
    assert "PASS red-test - red, exit 1" in second
    assert "PASS red-first - 1 of 1 new test red without the fix" in gates
    assert (project / "tests" / "test_mul.py").read_text(
        encoding="utf-8") == RIGHT


def test_a_wrong_test_the_run_started_with_parks_for_a_ruling(tmp_path,
                                                             monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_old.py::test_old")]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch, answers,
                                       writes, old=True)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert question.startswith("NEEDS: ")
    assert "tests/test_old.py::test_old" in question
    assert 'TASK.md:3 "mul(a, b) returns a times b"' in question


def test_a_park_after_the_fix_is_in_says_the_run_did_the_work(tmp_path,
                                                              monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_old.py::test_old")]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("calc.py", AFTER)]}
    _, _, code, folder, _ = run_it(tmp_path, monkeypatch, answers, writes,
                                   old=True)
    assert code == stops.EXIT_STOP
    page = (folder / "handoff.md").read_text(encoding="utf-8")
    assert "instead of doing the work" not in page
    assert ("the run did the work, then worker.md asked for a ruling: the"
            " place holds its change to calc.py.") in page


def test_a_second_wrong_test_on_the_same_test_parks(tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_mul.py::test_mul")],
               "reviewer.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", WRONG),
                            ("tests/test_mul.py", a_test(7))]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch, answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "tester.md",
                     "worker.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert "tests/test_mul.py::test_mul" in question
    assert "went back" in question


def test_a_spec_line_that_is_not_there_is_no_spec(tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_mul.py::test_mul",
                                   spec='TASK.md:40 "mul is a product"')]}
    writes = {"tester.md": [("tests/test_mul.py", WRONG)]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch, answers, writes)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_STOP
    assert "no line of the spec" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_an_invented_spec_quote_fails_the_step_and_never_reaches_the_writer(
        tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_mul.py::test_mul",
                                   spec='TASK.md:3 "mul(a, b) returns a plus'
                                   ' b"'), WORKER],
               "reviewer.md": [OK], "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", RIGHT)],
              "worker.md": [("", ""), ("calc.py", AFTER)]}
    asked, sent, code, folder, _ = run_it(tmp_path, monkeypatch, answers,
                                          writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "worker.md",
                     "reviewer.md", "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    first = gates.split("## worker.md")[1].split("##")[0]
    assert "FAIL quote" in first
    assert '"mul(a, b) returns a plus b"' in first and "TASK.md:3" in first
    assert "mul(a, b) returns a plus b" in sent[3]


def two_tests(first, second):
    return (a_test(first) + NL + NL + "def test_mul_zero():" + NL
            + "    from calc import mul" + NL + NL
            + "    assert mul(4, 0) == " + str(second) + NL)


def two_claims():
    return (claim("tests/test_mul.py::test_mul") + NL
            + "WRONG TEST: tests/test_mul.py::test_mul_zero" + NL
            + "why: anything times 0 is 0, and the test wants 1" + NL
            + 'spec: TASK.md:3 "mul(a, b) returns a times b"' + NL)


def test_several_wrong_tests_go_back_to_their_writer_in_one_round(
        tmp_path, monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [two_claims(), WORKER],
               "reviewer.md": [OK], "reviewer-runs.md": [OK]}
    writes = {"tester.md": [("tests/test_mul.py", two_tests(5, 1)),
                            ("tests/test_mul.py", two_tests(6, 0))],
              "worker.md": [("", ""), ("calc.py", AFTER)]}
    asked, sent, code, folder, _ = run_it(tmp_path, monkeypatch, answers,
                                          writes)
    assert asked == ["planner.md", "tester.md", "worker.md", "tester.md",
                     "worker.md", "reviewer.md", "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    again = sent[3]
    assert "tests/test_mul.py::test_mul" + NL in again
    assert "tests/test_mul.py::test_mul_zero" in again
    assert "anything times 0 is 0" in again
    assert "tests/test_mul.py::test_mul_zero" in sent[4]
    steps = (folder / "steps.jsonl").read_text(encoding="utf-8")
    assert "test_mul_zero" in steps


def test_one_claim_that_cannot_go_back_parks_the_whole_answer(tmp_path,
                                                            monkeypatch):
    answers = {"planner.md": [PLAN], "tester.md": [TESTER],
               "worker.md": [claim("tests/test_mul.py::test_mul") + NL
                             + claim("tests/test_old.py::test_old")]}
    writes = {"tester.md": [("tests/test_mul.py", WRONG)]}
    asked, _, code, folder, _ = run_it(tmp_path, monkeypatch, answers,
                                       writes, old=True)
    assert asked == ["planner.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_STOP
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert "tests/test_old.py::test_old" in question


def test_every_claim_is_read_each_with_its_own_why_and_spec():
    said = wrongtest.claims(
        "WRONG TEST: tests/test_a.py::test_one" + NL + "why: one" + NL
        + 'spec: TASK.md:1 "a"' + NL + NL
        + "WRONG TEST: `tests/test_b.py::test_two`" + NL
        + 'spec: TASK.md:2 "b"' + NL
        + "WRONG TEST: tests/test_a.py::test_one" + NL + "why: again" + NL)
    assert said == [("tests/test_a.py::test_one", "one", 'TASK.md:1 "a"'),
                    ("tests/test_b.py::test_two", "", 'TASK.md:2 "b"')]
    assert wrongtest.claims("nothing wrong" + NL) == []


def test_a_misquote_on_any_claim_fails_the_step(tmp_path):
    (tmp_path / "TASK.md").write_text(SPEC, encoding="utf-8")
    said = wrongtest.misquoted(
        claim("tests/test_mul.py::test_mul") + NL
        + claim("tests/test_mul.py::test_two",
                spec='TASK.md:3 "mul(a, b) returns a plus b"'), tmp_path)
    assert "returns a plus b" in said


def test_the_claim_is_read_off_its_own_lines_and_never_split_on_a_pipe():
    assert wrongtest is not None, "nothing reads a WRONG TEST answer"
    said =wrongtest.read(
        "- calc.py: nothing changed" + NL + NL
        + "WRONG TEST: tests/test_a.py::test_or" + NL
        + "why: a | b is the union, the test wants the intersection" + NL
        + 'spec: TASK.md:4 "a | b is every key in either"' + NL)
    assert said == ("tests/test_a.py::test_or",
                    "a | b is the union, the test wants the intersection",
                    'TASK.md:4 "a | b is every key in either"')
    assert wrongtest.read("```" + NL + "WRONG TEST: x" + NL + "```" + NL) \
        is None
