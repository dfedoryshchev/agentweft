"""the runway: a nice-to-do ticket is handed to a step on its file under a
header of its own, never as a rule; the planner names the ones the run takes
in on a `fold:` line, or none and why; the steps after it are told which
were folded, so the run's own review holds them; the runner retires a ticket
once a step's DID line says it did it and its own lines changed, and one
handed in five
runs and never taken goes stale."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard
from agentweft.orchestrate import facts
from agentweft.runner import brief, engine
from test_facts_attached import a_run, asked, put
from test_stops import answer, steps_of, the_folder

NL = chr(10)
CODE = NL.join(["import os", "", "def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])
CLAIM = "raise a ValueError naming the line in parse, not a bare one"


def ticket(id="F-0001", untaken=None, label=""):
    lines = ["## " + id + " live", "scope: pkg/a.py", "kind: nice-to-do"]
    if label:
        lines.append("label: " + label)
    lines.extend(["claim: " + CLAIM,
                  "why: the caller prints the error as it is",
                  'source: run r-1 step worker.md seq 2; evidence: pkg/a.py:5'
                  ' "raise ValueError"'])
    if untaken is not None:
        lines.append("untaken: " + str(untaken))
    return NL.join(lines) + NL


def a_place(tmp_path, **kw):
    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "facts/pkg/a.py.md", ticket(**kw))


def test_a_ticket_is_handed_under_a_header_of_its_own_never_as_a_rule(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/a.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert brief.TICKETS_HEAD in prompt
    assert brief.FACTS_HEAD not in prompt
    assert CLAIM in prompt.split(brief.TICKETS_HEAD)[1]
    assert "fold:" in brief.TICKETS_HEAD
    assert steps_of(the_folder())[0]["facts_attached"] == ["F-0001"]


def test_the_plans_fold_line_is_kept_and_the_steps_after_are_told(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    plan = ("- behaviour: an empty line raises" + NL + "  file: pkg/a.py" + NL
            + NL + "fold: F-0001" + NL + NL + "HANDOFF" + NL + "READ:" + NL
            + "- pkg/a.py - parse" + NL + "END HANDOFF" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner", "worker"],
                 answer(plan), answer("done" + NL),
                 task="make pkg/a.py stricter")
    assert engine.main() == 0
    planner, worker = steps_of(the_folder())
    assert planner["folded"] == ["F-0001"]
    later = asked(fake)[1].split(brief.TICKETS_HEAD)[1]
    assert "F-0001 (folded into this run's plan)" in later


def test_only_the_planners_fold_line_folds(tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    done = "done" + NL + NL + "fold: F-0001" + NL
    fake = a_run(tmp_path, monkeypatch, fake_cli,
                 ["planner", "worker", "reviewer"], answer("a plan" + NL),
                 answer(done), answer("VERDICT: ok" + NL),
                 task="make pkg/a.py stricter")
    assert engine.main() == 0
    assert [l.get("folded") for l in steps_of(the_folder())] == [None] * 3
    assert all(brief.FOLDED not in p for p in asked(fake))


def test_a_fold_keeps_only_the_tickets_it_was_handed(tmp_path, monkeypatch,
                                                     fake_cli):
    a_place(tmp_path)
    put(tmp_path, "facts/pkg/a.py.md", ticket() + NL + NL.join([
        "## F-0002 live", "scope: pkg/a.py", "kind: why",
        "claim: parse raises on an empty line",
        "why: the caller counts on it",
        'source: run r-1 step worker.md seq 2; evidence: pkg/a.py:5'
        ' "raise ValueError"']) + NL)
    plan = "- behaviour: an empty line raises" + NL + NL + "fold: F-0001, F-0002"
    a_run(tmp_path, monkeypatch, fake_cli, ["planner", "worker"],
          answer(plan + NL), answer("done" + NL),
          task="make pkg/a.py stricter")
    assert engine.main() == 0
    planner = steps_of(the_folder())[0]
    assert sorted(planner["facts_attached"]) == ["F-0001", "F-0002"]
    assert planner["folded"] == ["F-0001"]


def test_a_fold_of_none_says_why_and_folds_nothing(tmp_path, monkeypatch,
                                                   fake_cli):
    a_place(tmp_path)
    plan = ("- behaviour: an empty line raises" + NL + NL
            + "fold: none - the message is another feature" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner", "worker"],
                 answer(plan), answer("done" + NL),
                 task="make pkg/a.py stricter")
    assert engine.main() == 0
    planner = steps_of(the_folder())[0]
    assert planner["folded"] == []
    assert planner["fold_why"] == "the message is another feature"
    assert "folded into this run's plan" not in asked(fake)[1]


def test_a_ticket_a_step_did_on_its_changed_file_is_retired(tmp_path):
    a_place(tmp_path)
    store = factsguard.Store(tmp_path)
    put(tmp_path, "pkg/a.py", CODE.replace("raise ValueError('empty')",
                                           "raise ValueError('empty line')"))
    lines = [{"facts_attached": ["F-0001"], "folded": ["F-0001"]},
             {"facts_attached": ["F-0001"],
              "handoff": {"did": ["F-0001: the raise names the line"]}}]
    assert store.runway(lines, "run-9", today="2026-11-01") == (
        ["F-0001"], [])
    [fact] = facts.read(tmp_path)
    assert fact.status == facts.RETIRED
    assert fact.get("retired") == "2026-11-01 done in run run-9"


@pytest.mark.parametrize("did, change", [
    ("F-0001: not done, left for a later run",
     ("raise ValueError('empty')", "raise ValueError('empty line')")),
    ("F-0001 was not taken in", ("import os", "import sys")),
    ("F-0001: the raise names the line", ("import os", "import sys")),
    ("F-0001: the raise names the line", ("import os", "import os" + NL)),
])
def test_a_ticket_not_done_on_its_own_lines_is_not_retired(tmp_path, did,
                                                           change):
    a_place(tmp_path)
    store = factsguard.Store(tmp_path)
    put(tmp_path, "pkg/a.py", CODE.replace(*change))
    lines = [{"facts_attached": ["F-0001"], "handoff": {"did": [did]}}]
    assert store.runway(lines, "run-9", today="2026-11-01") == ([], [])
    [fact] = facts.read(tmp_path)
    assert fact.status == facts.LIVE and fact.get("untaken") == "1"


def test_a_ticket_done_on_its_own_line_after_a_shift_is_retired(tmp_path):
    a_place(tmp_path)
    store = factsguard.Store(tmp_path)
    put(tmp_path, "pkg/a.py", "import sys" + NL + CODE.replace(
        "raise ValueError('empty')", "raise ValueError('empty line')"))
    lines = [{"facts_attached": ["F-0001"],
              "handoff": {"did": ["F-0001: the raise names the line"]}}]
    assert store.runway(lines, "run-9") == (["F-0001"], [])


def test_a_ticket_whose_check_stops_holding_is_retired_on_no_did(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "facts/pkg/a.py.md", ticket().replace(
        "source:", "check: grep -n \"ValueError('empty')\" pkg/a.py" + NL
        + "source:"))
    store = factsguard.Store(tmp_path)
    put(tmp_path, "pkg/a.py", CODE.replace("('empty')", "('empty line')"))
    assert store.runway([{"facts_attached": ["F-0001"]}], "run-9") == (
        ["F-0001"], [])


def test_a_did_line_with_its_file_unchanged_retires_nothing(tmp_path):
    a_place(tmp_path)
    store = factsguard.Store(tmp_path)
    lines = [{"facts_attached": ["F-0001"],
              "handoff": {"did": ["F-0001: done"]}}]
    assert store.runway(lines, "run-9") == ([], [])
    [fact] = facts.read(tmp_path)
    assert fact.status == facts.LIVE and fact.get("untaken") == "1"


def test_a_ticket_handed_five_times_and_never_taken_goes_stale(tmp_path):
    a_place(tmp_path, untaken=4)
    store = factsguard.Store(tmp_path)
    assert store.runway([{"facts_attached": ["F-0001"]}], "run-9",
                        today="2026-11-01") == ([], ["F-0001"])
    [fact] = facts.read(tmp_path)
    assert fact.status == facts.STALE
    assert fact.get("stale") == ("2026-11-01 not taken in 5 runs it was"
                                 " handed to")


def test_the_end_of_a_run_counts_a_ticket_it_handed_and_did_not_take(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path, untaken=4)
    a_run(tmp_path, monkeypatch, fake_cli, ["planner"], answer("done" + NL),
          task="make pkg/a.py stricter")
    assert engine.main() == 0
    [fact] = facts.read(tmp_path)
    assert fact.status == facts.STALE and fact.get("untaken") == "5"


def test_a_ticket_not_handed_in_the_run_is_left_as_it_is(tmp_path):
    a_place(tmp_path, untaken=4)
    store = factsguard.Store(tmp_path)
    assert store.runway([{"facts_attached": []}], "run-9") == ([], [])
    assert facts.read(tmp_path)[0].get("untaken") == "4"
