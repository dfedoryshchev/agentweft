"""a `spec: contradicts` mark on lines a `request:` answer already held is
that question, answered, and needs no CONFLICT line of its own.

the runner asked which holds on a spec line, and the person answered
`request:`: the spec holds and the request is amended. a later planner
answer that marks a behaviour it leaves unbuilt `spec: contradicts` on that
line names
the question already asked; typing it as a CONFLICT again would ask the
person a question they have ruled on. a mark on a line no answered question
of the runner's named still needs its CONFLICT line.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import ruling

from test_named_spec_files import NAMED, RULE_LINE, TESTER, first_plan
from test_ruled_start_tests import NAMES_LINE, entry, place_of
from test_spec_conflict import folders, go, plain

NL = chr(10)
REQUEST = ("request: keep the page envelope and offset paging; cursor"
           " paging is later work, note it.")
HELD = "rules/api-shape.md:1"


def deferred(cite):
    return NL.join([
        "- behaviour: listing([1]) keeps {items, page, total}",
        "  file: pages.py",
        "  spec: allows docs/api.md:4",
        "- behaviour: cursor paging is later work under the ruling; nothing"
        " is built for it",
        "  file: pages.py",
        "  spec: contradicts " + cite + ". a person already ruled on this"
        " (spec holds)", ""])


def answered(tmp_path, monkeypatch, said):
    """the planner stops on the rule's line, the person answers `request:`,
    and the second leg's planner answers `said`. -> (steps asked on the
    second leg, what the planner's gates said)."""
    place_of(tmp_path, monkeypatch)
    asked, _, _ = go(tmp_path, monkeypatch, "build-feature",
                     plain({"planner.md": [first_plan(NAMED)]}),
                     lambda s, n: None, "--task", NAMED)
    assert asked == ["planner.md"]
    [leg] = folders(tmp_path)
    asked, _, _ = go(tmp_path, monkeypatch, "build-feature",
                     plain({"planner.md": [said], "tester.md": [TESTER]}),
                     lambda s, n: None, "--resume", leg.name,
                     "--answer", REQUEST)
    gates = (folders(tmp_path)[-1] / "gates.md").read_text(encoding="utf-8")
    first = gates.split("## planner.md")[1].split("## ")[0]
    return asked, first


def test_a_mark_on_a_line_a_request_answer_held_needs_no_conflict_line(
        tmp_path, monkeypatch):
    asked, said = answered(tmp_path, monkeypatch, deferred(HELD))
    assert "FAIL conflict" not in said, said
    assert asked.count("planner.md") == 1, asked


def test_a_mark_on_a_line_no_answered_question_named_still_fails(
        tmp_path, monkeypatch):
    asked, said = answered(tmp_path, monkeypatch,
                           deferred(HELD + ", docs/names.md:3"))
    assert "FAIL conflict" in said, said
    assert "docs/names.md:3" in said


def held_by(answer, run_id="build-1", kind=None):
    return entry("planner.md: " + answer, ruling.why(
        "planner.md", run_id, "NEEDS: which holds?", answer, "someone",
        kind=kind))


def test_a_line_holds_by_a_request_answer_to_the_runner_s_question_on_it():
    asked = {"build-1": [ruling.flat(RULE_LINE)]}
    held = held_by(REQUEST, kind=ruling.REQUEST)
    assert ruling.holds_line(held, RULE_LINE, asked)
    assert not ruling.holds_line(held, NAMES_LINE, asked)
    assert not ruling.holds_line(held_by(REQUEST, "build-2",
                                         kind=ruling.REQUEST),
                                 RULE_LINE, asked)
    assert not ruling.holds_line(held_by("override: cursor paging",
                                         kind=ruling.OVERRIDE),
                                 RULE_LINE, asked)
    assert not ruling.holds_line(entry("planner.md: " + REQUEST, REQUEST),
                                 RULE_LINE, asked)
    assert ruling.spec_line_ruled([held], RULE_LINE, asked) is None
