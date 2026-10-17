"""the spec files a run started with, held to the flow's `spec_files:` rule.

`read-only` fails any step that changes a spec file, like a gate: the step
goes back once and the run stops when it changes it again. `additions` lets
a step add lines, and stops the run for a ruling when a line the run started
with is removed or rewritten, with the line quoted as it was and as it is,
unless a ruling in decisions.md quotes that line.

the files are read by content against the start, so each case runs once with
steps that commit nothing and once with steps that commit their work.
"""
import datetime
import json
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec as flowspec
from agentweft.guardrails import snapshot
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, resume, ruling, state, stops

from test_red_order import RED_GATE, a_flow

NL = chr(10)
LINE = "the report lists students in the order given."
SPEC = "# report" + NL + NL + LINE + NL
SORTED = "def report(names):" + NL + "    return sorted(names)" + NL
COUNTED = SORTED + NL + NL + "def count(names):" + NL \
    + "    return len(names)" + NL
BASELINE = ("from report import report" + NL + NL + NL
            + "def test_alphabetical():" + NL
            + "    assert report(['b', 'a']) == ['a', 'b']" + NL)
COUNT = ("import report" + NL + NL + NL + "def test_count():" + NL
         + "    assert hasattr(report, 'count')" + NL)
TESTER = ("  - role: tester" + NL + "    prompt: tester.md" + NL
          + "    writes: tests" + NL + RED_GATE)
WORKER = ("  - role: worker" + NL + "    prompt: worker.md" + NL
          + "    writes: product" + NL)
TESTER_SAID = "FAILS: assert False" + NL + "TEST: tests/test_count.py" + NL
WORKER_SAID = "- report.py: count" + NL
REWRITTEN = "the report lists students alphabetically."
APPENDED = SPEC + "the report also counts them." + NL


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
                      ("conftest.py", ""), ("tests/test_report.py", BASELINE)):
        (where / rel).parent.mkdir(parents=True, exist_ok=True)
        (where / rel).write_text(text, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def flow_with(tmp_path, rule):
    a_flow(tmp_path, "build", TESTER + WORKER + "spec_files: " + rule + NL)


def running(tmp_path, monkeypatch, place, does, commits, *args):
    """main() over the flow `build` in `place`; `does[step]` is (files it
    writes, what it answers or raises), or a list of them, one per go. a
    step that
    commits adds and commits what it wrote. -> (exit code, steps called)."""
    called = []
    goes = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append(step)
        plan = does[step]
        if isinstance(plan, list):
            i = goes.get(step, 0)
            goes[step] = i + 1
            plan = plan[min(i, len(plan) - 1)]
        writes, said = plan
        for rel, text in writes.items():
            (place / rel).parent.mkdir(parents=True, exist_ok=True)
            (place / rel).write_text(text, encoding="utf-8")
        if commits and writes:
            git(place, "add", "--", *sorted(writes))
            git(place, "commit", "-qm", step, "--allow-empty")
        if isinstance(said, Exception):
            raise said
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


def worker_writes(task):
    return {"tester.md": ({"tests/test_count.py": COUNT}, TESTER_SAID),
            "worker.md": ({"report.py": COUNTED, "TASK.md": task},
                          WORKER_SAID)}


@pytest.mark.parametrize("commits", [False, True])
def test_a_read_only_spec_edited_by_a_step_fails_it_and_it_goes_back_once(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "read-only")
    code, called = running(tmp_path, monkeypatch, place,
                           worker_writes(APPENDED), commits)
    assert called == ["tester.md", "worker.md", "worker.md"]
    assert code == stops.exit_code(stops.GATE)
    folder = folders()[-1]
    assert "cause      gate" in read(folder / "why.md")
    gates = read(folder / "gates.md")
    assert "spec-files" in gates
    assert "TASK.md" in gates
    assert "read-only" in gates


@pytest.mark.parametrize("commits", [False, True])
def test_a_read_only_spec_put_back_on_the_second_go_passes(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "read-only")
    does = worker_writes(APPENDED)
    does["worker.md"] = [does["worker.md"],
                         ({"report.py": COUNTED, "TASK.md": SPEC},
                          WORKER_SAID)]
    code, called = running(tmp_path, monkeypatch, place, does, commits)
    assert called == ["tester.md", "worker.md", "worker.md"]
    assert code == 0


@pytest.mark.parametrize("commits", [False, True])
def test_a_spec_line_added_passes(tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "additions")
    code, called = running(tmp_path, monkeypatch, place,
                           worker_writes(APPENDED), commits)
    assert called == ["tester.md", "worker.md"]
    assert code == 0
    gates = read(folders()[-1] / "gates.md")
    assert "spec-files" in gates
    assert "1 line added" in gates


@pytest.mark.parametrize("commits", [False, True])
def test_a_rewritten_spec_line_parks_for_a_ruling_quoting_it(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "additions")
    code, called = running(tmp_path, monkeypatch, place,
                           worker_writes(SPEC.replace(LINE, REWRITTEN)),
                           commits)
    assert called == ["tester.md", "worker.md"]
    assert code == stops.exit_code(stops.PARKED)
    folder = folders()[-1]
    kept = json.loads(read(folder / "manifest.json"))
    assert kept["outcome"] == "needs you: ruling"
    assert "cause      parked" in read(folder / "why.md")
    question = read(folder / "question.md")
    assert 'TASK.md:3 - was "' + LINE + '"' in question
    assert 'now "' + REWRITTEN + '"' in question
    assert "override:" in read(folder / "handoff.md")


@pytest.mark.parametrize("commits", [False, True])
def test_a_removed_spec_line_parks_saying_it_is_gone(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "additions")
    code, _ = running(tmp_path, monkeypatch, place,
                      worker_writes("# report" + NL), commits)
    assert code == stops.exit_code(stops.PARKED)
    question = read(folders()[-1] / "question.md")
    assert 'TASK.md:3 - was "' + LINE + '", now removed' in question


@pytest.mark.parametrize("commits", [False, True])
def test_a_ruling_that_quotes_the_line_lets_the_rewrite_stand(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    decisions.record(place, "the order changes",
                     '"' + LINE + '" gives way to sorted output')
    if commits:
        git(place, "add", "decisions.md")
        git(place, "commit", "-qm", "ruling")
    flow_with(tmp_path, "additions")
    code, called = running(tmp_path, monkeypatch, place,
                           worker_writes(SPEC.replace(LINE, REWRITTEN)),
                           commits)
    assert called == ["tester.md", "worker.md"]
    assert code == 0


def test_an_override_answer_to_the_park_carries_the_run_on(
        tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "additions")
    does = worker_writes(SPEC.replace(LINE, REWRITTEN))
    code, _ = running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.PARKED)
    first = folders()[-1]
    code, called = running(tmp_path, monkeypatch, place, does, False,
                           "--resume", first.name, "--answer",
                           "override: sorted output was asked for")
    assert called == ["worker.md"]
    assert code == 0


def test_any_other_answer_leaves_the_line_unruled(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    flow_with(tmp_path, "additions")
    does = worker_writes(SPEC.replace(LINE, REWRITTEN))
    code, _ = running(tmp_path, monkeypatch, place, does, False)
    first = folders()[-1]
    code, _ = running(tmp_path, monkeypatch, place, does, False,
                      "--resume", first.name, "--answer", "put it back")
    assert code == stops.exit_code(stops.PARKED)


# the ruling check on its own

def entry(decided, why):
    return decisions.Decision(decided, why, datetime.datetime(2026, 1, 1))


def ruled(decided, line):
    assert hasattr(ruling, "spec_line_ruled"), \
        "nothing reads a ruling for a spec line"
    return ruling.spec_line_ruled(decided, line)


def test_a_quote_of_the_whole_line_or_three_words_of_it_rules_it():
    whole = entry("the order changes", '"' + LINE + '" goes')
    part = entry("the order changes", '"students in the order" goes')
    short = entry("the order changes", '"the order" goes')
    assert ruled([whole], LINE) is whole
    assert ruled([part], LINE) is part
    assert ruled([short], LINE) is None


def test_a_request_answer_never_rules_a_line():
    kept = entry(ruling.decided("worker.md", "request: keep it"),
                 ruling.why("worker.md", "build-1", "NEEDS: may it?",
                            'request: keep "' + LINE + '"', "someone"))
    assert ruled([kept], LINE) is None


def test_the_rule_is_a_flow_key_with_two_values():
    base = {"name": "x", "steps": [{"role": "a"}]}
    assert flowspec.check(dict(base, spec_files="read-only")) == []
    assert flowspec.check(dict(base, spec_files="additions")) == []
    assert flowspec.check(dict(base, spec_files="loose")) != []


def test_a_place_outside_git_keeps_its_spec_text(tmp_path):
    place = tmp_path / "plain"
    place.mkdir()
    (place / "TASK.md").write_text(SPEC, encoding="utf-8")
    shot = snapshot.take(place)
    assert shot.before("TASK.md") == (place / "TASK.md").read_bytes()
    (place / "TASK.md").write_text("changed" + NL, encoding="utf-8")
    assert ruling.as_found(place, "TASK.md", shot).split() == SPEC.split()
