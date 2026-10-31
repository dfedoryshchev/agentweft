"""a nice-to-do the retro labels `critical` reaches the flow's lead, who
re-iterates now or accepts it as later. the decision goes into decisions.md
as the lead's, the handoff says it, and nothing in the tree changes for it;
a flow with no lead, or a lead that does not decide, leaves it yours."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard
from agentweft.orchestrate import decisions, facts
from agentweft.runner import engine, lead
from test_retro_maintains import CODE, block, put
from test_stops import CLAUDE, a_flow, answer, steps_of, the_folder

NL = chr(10)
CRITICAL = NL.join([
    "fact:", "  scope: pkg/a.py", "  kind: nice-to-do", "  label: critical",
    "  claim: raise a ValueError naming the line in parse, not a bare one",
    "  why: the caller prints the error as it is, and an empty one says"
    " nothing",
    '  source: seq 1 worker.md; evidence: pkg/a.py:5 "raise ValueError"'])
LATER = "DECIDED: accept as later" + NL + "why: the message is not in the spec"
NOW = "DECIDED: re-iterate now" + NL + "why: TASK.md asks for the line number"


def a_led_run(tmp_path, monkeypatch, fake_cli, said, lead=None,
              steps=("planner", "worker")):
    a_flow(tmp_path, monkeypatch, "keeps", list(steps),
           tail="retro: true\n" + ("lead: planner\n" if lead else "")
           + CLAUDE)
    put(tmp_path, "pkg/a.py", CODE)
    replies = [answer("done\n")] * len(steps) + [answer(said)]
    if lead is not None:
        replies.append(answer(lead))
    return fake_cli(*replies)


def handoff():
    return (the_folder() / "handoff.md").read_text(encoding="utf-8")


def ticket(tmp_path):
    [fact] = [f for f in facts.read(tmp_path) if f.kind == "nice-to-do"]
    return fact


def test_a_critical_ticket_goes_to_the_lead_and_its_decision_is_on_record(
        tmp_path, monkeypatch, fake_cli):
    fake = a_led_run(tmp_path, monkeypatch, fake_cli, block(CRITICAL), LATER)
    assert engine.main() == 0
    asked = fake.calls[-1]["stdin"].decode("utf-8")
    assert "QUESTION FOR THE LEAD" in asked
    assert "raise a ValueError naming the line in parse" in asked
    assert "re-iterate now" in asked and "accept as later" in asked
    [ruled] = decisions.read(tmp_path)
    assert ruled.decided == "planner.md decided for retro.md: accept as later"
    fact = ticket(tmp_path)
    assert fact.label != "critical"
    note = handoff()
    assert "## critical tickets, for the lead" in note
    assert ("- " + fact.id + " (pkg/a.py): raise a ValueError naming the line"
            in note)
    assert ("the lead, planner.md, decided: accept as later - the message is"
            " not in the spec (on record in decisions.md)") in note
    assert (tmp_path / "pkg" / "a.py").read_text(encoding="utf-8") == CODE
    lines = steps_of(the_folder())
    assert [l["step"] for l in lines][-2:] == ["retro.md", "planner.md"]
    assert lines[-1]["outcome"] == "decided"


def test_re_iterate_now_keeps_the_ticket_first_for_the_next_planner(
        tmp_path, monkeypatch, fake_cli):
    a_led_run(tmp_path, monkeypatch, fake_cli, block(CRITICAL), NOW)
    assert engine.main() == 0
    assert ticket(tmp_path).label == "important"
    assert "the lead, planner.md, decided: re-iterate now" in handoff()


def test_with_no_lead_a_critical_ticket_is_yours_and_nothing_is_ruled(
        tmp_path, monkeypatch, fake_cli):
    fake = a_led_run(tmp_path, monkeypatch, fake_cli, block(CRITICAL))
    assert engine.main() == 0
    assert len(fake.calls) == 3
    assert decisions.read(tmp_path) == []
    fact = ticket(tmp_path)
    assert fact.label == "critical"
    note = handoff()
    assert "- " + fact.id + " (pkg/a.py): " in note
    assert ("the flow has no lead, so it is yours: re-iterate now or accept it"
            " as later") in note


def test_a_lead_that_escalates_leaves_the_ticket_critical_and_yours(
        tmp_path, monkeypatch, fake_cli):
    a_led_run(tmp_path, monkeypatch, fake_cli, block(CRITICAL),
              "ESCALATE: not mine to judge")
    assert engine.main() == 0
    assert decisions.read(tmp_path) == []
    assert ticket(tmp_path).label == "critical"
    assert "planner.md escalated it: not mine to judge" in handoff()


def test_a_lead_that_picks_neither_option_does_not_decide_it(
        tmp_path, monkeypatch, fake_cli):
    a_led_run(tmp_path, monkeypatch, fake_cli, block(CRITICAL),
              "DECIDED: rewrite parse" + NL + "why: it is ugly")
    assert engine.main() == 0
    assert decisions.read(tmp_path) == []
    assert ticket(tmp_path).label == "critical"
    assert "neither re-iterate now nor accept as later" in handoff()


@pytest.mark.parametrize("decided", [
    "there is no need to re-iterate now, the work stands",
    "I do not accept this as it is",
    "not re-iterate now",
    "accept as later? no, re-iterate now",
    "re-iterate nowhere near this file",
    "reiterate now",
])
def test_a_decision_that_does_not_open_on_one_option_decides_nothing(decided):
    picked, why = lead.ticket_pick("planner.md")(decided)
    assert picked is None, picked
    assert "neither re-iterate now nor accept as later" in why


@pytest.mark.parametrize("decided, want", [
    ("re-iterate now", lead.NOW),
    ("re-iterate now - the empty line must name itself", lead.NOW),
    ("`accept as later`: cosmetic", lead.LATER),
    ("Accept as later.", lead.LATER),
])
def test_a_decision_that_opens_on_one_option_is_that_option(decided, want):
    assert lead.ticket_pick("planner.md")(decided) == (want, "")


def test_the_lead_is_asked_for_an_options_exact_words_first(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    fields = {"scope": "pkg/a.py", "kind": "nice-to-do", "label": "critical",
              "claim": "name the line in the raise",
              "why": "the caller prints it",
              "source": 'seq 1 worker.md; evidence: pkg/a.py:5 "raise'
                        ' ValueError"'}
    fact, why = factsguard.Store(tmp_path).add(factsguard.Proposal(fields),
                                               factsguard.Record(tmp_path))
    asked = lead.ticket_question(fact)
    assert ("start DECIDED: with the exact words of one option, `re-iterate"
            " now` or `accept as later`") in asked


def test_a_lead_that_refuses_an_option_does_not_decide_it(
        tmp_path, monkeypatch, fake_cli):
    a_led_run(tmp_path, monkeypatch, fake_cli, block(CRITICAL),
              "DECIDED: there is no need to re-iterate now" + NL
              + "why: the work stands")
    assert engine.main() == 0
    assert decisions.read(tmp_path) == []
    assert ticket(tmp_path).label == "critical"
    assert "neither re-iterate now nor accept as later" in handoff()


def test_critical_marks_only_a_nice_to_do(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    fields = {"scope": "pkg/a.py", "kind": "why", "label": "critical",
              "claim": "parse raises", "why": "the caller counts on it",
              "source": 'seq 1 worker.md; evidence: pkg/a.py:5 "raise'
                        ' ValueError"'}
    fact, why = factsguard.Store(tmp_path).add(factsguard.Proposal(fields),
                                               factsguard.Record(tmp_path))
    assert fact is None and "critical marks a nice-to-do" in why, why
