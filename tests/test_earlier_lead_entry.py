"""a lead decides inside the spec, never over it, in a later run too.

an entry the lead wrote in an earlier run is in decisions.md when the next
run starts. entries there at the start count as rulings, but one in the
form the lead's decision is written in is read like the lead's own: its
quote of a spec line lets that line change no more than it did in the run
that wrote it. an entry written by hand and an earlier `--answer` still
rule the line they quote.
"""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import rulings
from agentweft.orchestrate import decisions
from agentweft.runner import lead, ruling, stops

import test_spec_files as sf

NL = chr(10)
REWRITE = sf.SPEC.replace(sf.LINE, sf.REWRITTEN)
CONFLICT = ('CONFLICT: TASK.md:3 "' + sf.LINE + '"' + NL
            + "request: sort by name" + NL)


def lead_entry(place):
    decisions.record(place, *lead.recorded(
        "planner.md", "worker.md", "build-1",
        "NEEDS: which order does the list keep?" + NL + "OPTIONS:" + NL
        + "- as given" + NL + "- sorted" + NL,
        "as given", 'the spec says "' + sf.LINE + '"'))


def hand_entry(place):
    decisions.record(place, "the order changes",
                     '"' + sf.LINE + '" gives way to sorted output')


def answer_entry(place):
    question = ruling.question_of_spec_lines(
        "worker.md", [("TASK.md", 3, sf.LINE, sf.REWRITTEN)])
    decisions.record(place, ruling.decided("worker.md", "override: sort"),
                     ruling.why("worker.md", "build-1", question,
                                'override: "' + sf.LINE + '" gives way',
                                "someone", kind=ruling.OVERRIDE))


def started_with(tmp_path, write):
    place = sf.a_place(tmp_path / "repo")
    write(place)
    sf.git(place, "add", "decisions.md")
    sf.git(place, "commit", "-qm", "earlier run")
    sf.flow_with(tmp_path, "additions")
    return place


def test_a_conflict_on_a_line_an_earlier_leads_entry_quotes_stops_the_run(
        tmp_path, monkeypatch):
    place = started_with(tmp_path, lead_entry)
    does = sf.worker_writes(sf.SPEC)
    does["worker.md"] = ({}, CONFLICT)
    code, called = sf.running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.CONFLICT), \
        "the run went on past a conflict an earlier lead decision covered"
    assert called == ["tester.md", "worker.md"]
    assert "TASK.md:3" in sf.read(sf.folders()[-1] / "question.md")


def test_a_rewrite_of_a_line_an_earlier_leads_entry_quotes_parks(
        tmp_path, monkeypatch):
    place = started_with(tmp_path, lead_entry)
    code, called = sf.running(tmp_path, monkeypatch, place,
                              sf.worker_writes(REWRITE), False)
    assert code != 0, "an earlier lead decision let a spec line change"
    assert called == ["tester.md", "worker.md"]
    folder = sf.folders()[-1]
    assert json.loads(sf.read(folder / "manifest.json"))["outcome"] == \
        "needs you: ruling"
    question = sf.read(folder / "question.md")
    assert 'TASK.md:3 - was "' + sf.LINE + '"' in question


@pytest.mark.parametrize("write", [hand_entry, answer_entry],
                         ids=["by-hand", "answer"])
def test_an_earlier_entry_not_the_leads_still_lets_the_line_change(
        tmp_path, monkeypatch, write):
    place = started_with(tmp_path, write)
    code, called = sf.running(tmp_path, monkeypatch, place,
                              sf.worker_writes(REWRITE), False)
    assert code == 0
    assert "covered by a ruling" in sf.read(sf.folders()[-1] / "gates.md")


def test_the_record_reads_an_entry_there_at_the_start_in_the_leads_form_as_the_leads(
        tmp_path):
    lead_entry(tmp_path)
    hand_entry(tmp_path)
    kept = rulings.Kept(tmp_path)
    assert [d.decided for d in kept.read()] == [
        "planner.md decided for worker.md: as given", "the order changes"]
    assert [d.decided for d in kept.read(but=(rulings.LEAD,))] == [
        "the order changes"]
