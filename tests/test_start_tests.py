"""after a step writes product code, the tests the run started with run again.

the start commit's test files (and the test files already loose when the run
started) run against the product files as they are now, in a temporary
checkout, in one pytest run. a test that was green when the run started and
is red now stops the run as a spec conflict naming it and its assertion,
unless a ruling in decisions.md names that test or quotes the spec line that
decides it. a test that was red at the start is not the run's doing.

each case runs once with steps that commit nothing and once with steps that
commit their work.
"""
import datetime
import json
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot, worktree
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, resume, ruling, state, stops

from test_red_order import RED_GATE, a_flow

NL = chr(10)
SPEC = "# report" + NL + NL + "the report lists students in the order given." \
    + NL
SORTED = "def report(names):" + NL + "    return sorted(names)" + NL
GIVEN = "def report(names):" + NL + "    return list(names)" + NL
BASELINE = ("from report import report" + NL + NL + NL
            + "def test_alphabetical():" + NL
            + "    assert report(['b', 'a']) == ['a', 'b']" + NL + NL + NL
            + "def test_empty():" + NL + "    assert report([]) == []" + NL)
KNOWN_RED = ("from report import report" + NL + NL + NL
             + "def test_known():" + NL + "    assert report(['a']) == []"
             + NL)
ROSTER = ("from report import report" + NL + NL + NL
          + "def test_roster_order():" + NL
          + "    assert report(['b', 'a']) == ['b', 'a']" + NL)
COUNT = ("import report" + NL + NL + NL + "def test_count():" + NL
         + "    assert hasattr(report, 'count')" + NL)
TESTER_SAID = "FAILS: assert ['a', 'b'] == ['b', 'a']" + NL + \
    "TEST: tests/test_roster.py" + NL
TESTER = ("  - role: tester" + NL + "    prompt: tester.md" + NL
          + "    writes: tests" + NL + RED_GATE)
WORKER = ("  - role: worker" + NL + "    prompt: worker.md" + NL
          + "    writes: product" + NL)
GONE = "tests/test_report.py::test_alphabetical"
SPEC_LINE = "the report lists students in the order given"


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_place(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    git(where, "config", "commit.gpgsign", "false")
    for rel, text in (("TASK.md", SPEC), ("report.py", SORTED),
                      ("conftest.py", ""), ("tests/test_report.py", BASELINE),
                      ("tests/test_known.py", KNOWN_RED)):
        (where / rel).parent.mkdir(parents=True, exist_ok=True)
        (where / rel).write_text(text, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def running(tmp_path, monkeypatch, place, does, commits, *args):
    """main() over the flow `build` in `place`; `does[step]` is (files it
    writes, what it answers). a step that commits adds and commits what it
    wrote. -> (exit code, steps called)."""
    called = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append(step)
        writes, said = does[step]
        for rel, text in writes.items():
            (place / rel).parent.mkdir(parents=True, exist_ok=True)
            (place / rel).write_text(text, encoding="utf-8")
        if commits and writes:
            git(place, "add", "--", *sorted(writes))
            git(place, "commit", "-qm", step)
        return said, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place)] + list(args))
    return engine.main(), called


def folders():
    return sorted((p for p in state.RUNS.iterdir() if p.is_dir()),
                  key=lambda p: resume.order_of(p.name))


def read(path):
    return path.read_text(encoding="utf-8")


def no_checkout_left(place):
    listed = [l for l in git(place, "worktree", "list", "--porcelain")
              .split(NL) if l.startswith("worktree ")]
    return len(listed) == 1 and worktree.leftovers(place) == []


BREAKS = {"tester.md": ({"tests/test_roster.py": ROSTER}, TESTER_SAID),
          "worker.md": ({"report.py": GIVEN}, "- report.py: the order given"
                        + NL)}


@pytest.mark.parametrize("commits", [False, True])
def test_a_product_step_that_turns_a_start_test_red_stops_naming_it(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, BREAKS, commits)
    assert called == ["tester.md", "worker.md"]
    assert code == stops.exit_code(stops.CONFLICT)
    folder = folders()[-1]
    kept = json.loads(read(folder / "manifest.json"))
    assert kept["outcome"] == "stopped: spec conflict"
    why = read(folder / "why.md")
    assert "cause      conflict" in why
    assert GONE in why
    assert "['b', 'a'] == ['a', 'b']" in why
    # red when the run started, so not the run's doing
    assert "test_known" not in why
    assert "test_empty" not in why
    question = read(folder / "question.md")
    assert GONE in question
    handoff = read(folder / "handoff.md")
    assert "contradicts the spec" not in handoff
    assert '--answer "override: <why the change holds>"' in handoff
    assert "- worker.md: FAIL start tests - run again against worker.md," \
        " not all green as they were" in handoff
    assert "1 check failed (run again against worker.md" in handoff
    assert no_checkout_left(place)


@pytest.mark.parametrize("commits", [False, True])
def test_a_ruling_that_names_the_test_lets_the_change_stand(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    decisions.record(place, "the order given replaces the alphabetical test",
                     GONE + " pinned the order the spec dropped")
    if commits:
        git(place, "add", "decisions.md")
        git(place, "commit", "-qm", "ruling")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, BREAKS, commits)
    assert called == ["tester.md", "worker.md"]
    assert code == 0
    assert no_checkout_left(place)


@pytest.mark.parametrize("commits", [False, True])
def test_a_test_red_at_the_start_does_not_stop_the_run(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    counted = SORTED + NL + NL + "def count(names):" + NL \
        + "    return len(names)" + NL
    code, called = running(tmp_path, monkeypatch, place, {
        "tester.md": ({"tests/test_count.py": COUNT},
                      "FAILS: assert False" + NL + "TEST: tests/test_count.py"
                      + NL),
        "worker.md": ({"report.py": counted}, "- report.py: count" + NL)},
        commits)
    assert called == ["tester.md", "worker.md"]
    assert code == 0
    gates = read(folders()[-1] / "gates.md")
    assert "start-tests" in gates
    assert no_checkout_left(place)


def test_an_answer_that_quotes_the_spec_line_carries_the_run_on(
        tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, _ = running(tmp_path, monkeypatch, place, BREAKS, False)
    assert code == stops.exit_code(stops.CONFLICT)
    first = folders()[-1]
    code, called = running(tmp_path, monkeypatch, place, BREAKS, False,
                           "--resume", first.name, "--answer",
                           'override: "' + SPEC_LINE + '" decides it')
    assert called == ["worker.md"]
    assert code == 0
    assert no_checkout_left(place)


# the ruling check on its own


def entry(decided, why):
    return decisions.Decision(decided, why, datetime.datetime(2026, 1, 1))


def asked_and_answered(answer):
    return entry(ruling.decided("worker.md", answer),
                 ruling.why("worker.md", "build-1", "NEEDS: " + GONE
                            + " was green when the run started", answer,
                            "someone"))


def covering(decided, test, place, start):
    assert hasattr(ruling, "covering"), "nothing reads a ruling for a test"
    return ruling.covering(decided, test, place, start)


def started(tmp_path):
    place = a_place(tmp_path / "repo")
    return place, snapshot.take(place)


def test_a_ruling_naming_the_test_covers_it(tmp_path):
    place, start = started(tmp_path)
    hand = entry("drop the alphabetical test", "test_report.py::"
                 "test_alphabetical pinned the old order")
    assert covering([hand], GONE, place, start) is hand
    other = entry("drop a test", "test_report.py::test_alphabetically_x")
    assert covering([other], GONE, place, start) is None


def test_the_question_naming_the_test_is_not_the_ruling_naming_it(tmp_path):
    place, start = started(tmp_path)
    bare = asked_and_answered("override: the new order wins")
    assert covering([bare], GONE, place, start) is None


def test_a_quote_of_the_spec_as_the_run_found_it_covers_the_test_asked_of(
        tmp_path):
    place, start = started(tmp_path)
    quoted = asked_and_answered('override: "' + SPEC_LINE + '" decides it')
    assert covering([quoted], GONE, place, start) is quoted
    assert covering([quoted], "tests/test_report.py::test_empty",
                           place, start) is None
    (place / "TASK.md").write_text("the report is sorted by name, always"
                                   + NL, encoding="utf-8")
    made_up = asked_and_answered('override: "the report is sorted by name,'
                                 ' always" decides it')
    assert covering([made_up], GONE, place, start) is None


def test_a_request_answer_never_covers_a_test(tmp_path):
    place, start = started(tmp_path)
    kept = asked_and_answered("request: keep " + GONE + ' as "' + SPEC_LINE
                              + '" says')
    assert covering([kept], GONE, place, start) is None
