"""a reviewer reads the spec as the run found it, and the diff against it.

a reviewer called after a step edited the spec, and handed only the spec as
it is now, reviews the change against the edit it was meant to catch. so a
step's prompt can name {SPEC_AT_START} and {SPEC_DIFF}, filled when the step
is called, and a step that reads them and answers ok while the spec has moved
with no ruling in decisions.md quoting the moved lines is a redo.

each case runs once with steps that commit nothing and once with steps that
commit their work.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, resume, stops

from test_red_order import a_flow
from test_spec_files import (APPENDED, COUNT, COUNTED, LINE, SPEC, TESTER,
                             TESTER_SAID, WORKER, WORKER_SAID, a_place, git)

NL = chr(10)
ADDED = "the report also counts them."
REVIEWER = ("  - role: reviewer" + NL + "    prompt: reviewer.md" + NL
            + "    writes: none" + NL + "    on_redo: worker" + NL)
REVIEW = ("# reviewer" + NL + NL + "AT START" + NL + "{SPEC_AT_START}" + NL
          + "END START" + NL + "DIFF" + NL + "{SPEC_DIFF}" + NL + "END DIFF"
          + NL)
OK = "VERDICT: ok" + NL + NL + "- report.py: count" + NL


def a_reviewed_flow(tmp_path, rule="spec_files: additions" + NL):
    a_flow(tmp_path, "build", TESTER + WORKER + REVIEWER + rule)
    (tmp_path / "flows" / "build" / "reviewer.md").write_text(
        REVIEW, encoding="utf-8")


def running(tmp_path, monkeypatch, place, does, commits):
    """main() over the flow `build` in `place`; `does[step]` is (files it
    writes, what it answers), or a list of them, one per go.
    -> (exit code, [(step, the prompt it was sent)])."""
    called = []
    goes = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append((step, prompt))
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
        return said, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place)])
    return engine.main(), called


def between(prompt, head, tail):
    return prompt.split(NL + head + NL, 1)[1].split(NL + tail + NL, 1)[0]


def steps(called):
    return [step for step, _ in called]


def prompt_of(called, step, go=0):
    return [p for s, p in called if s == step][go]


def edits_the_spec(then=None):
    worker = ({"report.py": COUNTED, "TASK.md": APPENDED}, WORKER_SAID)
    return {"tester.md": ({"tests/test_count.py": COUNT}, TESTER_SAID),
            "worker.md": [worker] + ([then] if then else []),
            "reviewer.md": ({}, OK)}


@pytest.mark.parametrize("commits", [False, True])
def test_the_reviewer_reads_the_spec_as_the_run_found_it_after_an_edit(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    a_reviewed_flow(tmp_path)
    put_back = ({"report.py": COUNTED, "TASK.md": SPEC}, WORKER_SAID)
    _, called = running(tmp_path, monkeypatch, place,
                        edits_the_spec(put_back), commits)
    prompt = prompt_of(called, "reviewer.md")
    start = between(prompt, "AT START", "END START")
    assert "{SPEC_AT_START}" not in prompt
    assert LINE in start
    assert ADDED not in start
    assert "TASK.md" in start
    diff = between(prompt, "DIFF", "END DIFF")
    assert "+" + ADDED in diff.split(NL)
    assert "TASK.md" in diff


@pytest.mark.parametrize("commits", [False, True])
def test_an_ok_review_of_a_spec_edit_no_ruling_covers_is_a_redo(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    a_reviewed_flow(tmp_path, rule="")
    put_back = ({"report.py": COUNTED, "TASK.md": SPEC}, WORKER_SAID)
    code, called = running(tmp_path, monkeypatch, place,
                           edits_the_spec(put_back), commits)
    assert steps(called) == ["tester.md", "worker.md", "reviewer.md",
                             "worker.md", "reviewer.md"]
    assert code == 0
    back = prompt_of(called, "worker.md", 1)
    assert "TASK.md:4" in back
    assert "decisions.md" in back
    second = prompt_of(called, "reviewer.md", 1)
    assert "+" + ADDED not in between(second, "DIFF", "END DIFF").split(NL)


@pytest.mark.parametrize("commits", [False, True])
def test_a_ruling_that_quotes_the_added_line_keeps_the_review_ok(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    decisions.record(place, "the report counts", '"' + ADDED + '" is asked'
                     " for")
    if commits:
        git(place, "add", "decisions.md")
        git(place, "commit", "-qm", "ruling")
    a_reviewed_flow(tmp_path, rule="")
    code, called = running(tmp_path, monkeypatch, place, edits_the_spec(),
                           commits)
    assert steps(called) == ["tester.md", "worker.md", "reviewer.md"]
    assert code == 0


@pytest.mark.parametrize("commits", [False, True])
def test_an_added_line_in_an_additions_flow_keeps_the_review_ok(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    a_reviewed_flow(tmp_path)
    code, called = running(tmp_path, monkeypatch, place, edits_the_spec(),
                           commits)
    assert steps(called) == ["tester.md", "worker.md", "reviewer.md"]
    assert code == 0


def a_run(place, rule):
    run = object.__new__(engine.Run)
    run.fm = {"spec_files": rule} if rule else {}
    run.workdir = place
    run.start = snapshot.take(place)
    return run


@pytest.mark.parametrize("commits", [False, True])
@pytest.mark.parametrize("rule", ["additions", "read-only", ""])
def test_a_rewritten_line_is_unruled_under_every_rule(tmp_path, commits,
                                                       rule):
    place = a_place(tmp_path / "repo")
    run = a_run(place, rule)
    (place / "TASK.md").write_text(SPEC.replace(LINE, "the report sorts."),
                                   encoding="utf-8")
    if commits:
        git(place, "commit", "-qam", "edit")
    assert run.spec_unruled() == ["TASK.md:3"]


@pytest.mark.parametrize("commits", [False, True])
@pytest.mark.parametrize("rule,left", [("additions", []),
                                       ("read-only", ["TASK.md:4"]),
                                       ("", ["TASK.md:4"])])
def test_an_added_line_is_unruled_only_outside_an_additions_flow(
        tmp_path, commits, rule, left):
    place = a_place(tmp_path / "repo")
    run = a_run(place, rule)
    (place / "TASK.md").write_text(APPENDED, encoding="utf-8")
    if commits:
        git(place, "commit", "-qam", "edit")
    assert run.spec_unruled() == left


@pytest.mark.parametrize("commits", [False, True])
def test_an_untouched_spec_reads_as_no_change_and_the_review_stays_ok(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo")
    a_reviewed_flow(tmp_path, rule="")
    does = {"tester.md": ({"tests/test_count.py": COUNT}, TESTER_SAID),
            "worker.md": ({"report.py": COUNTED}, WORKER_SAID),
            "reviewer.md": ({}, OK)}
    code, called = running(tmp_path, monkeypatch, place, does, commits)
    assert steps(called) == ["tester.md", "worker.md", "reviewer.md"]
    assert code == 0
    prompt = prompt_of(called, "reviewer.md")
    assert LINE in between(prompt, "AT START", "END START")
    assert "no change" in between(prompt, "DIFF", "END DIFF")


def test_the_shipped_reviewers_read_the_start_spec_and_the_diff():
    for flow in ("build-feature", "code-review"):
        text = (Path("flows") / flow / "reviewer.md").read_text(
            encoding="utf-8")
        assert "{SPEC_AT_START}" in text, flow
        assert "{SPEC_DIFF}" in text, flow
