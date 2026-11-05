"""a conflict names every spec line the request contradicts, and one
override covers each.

a step may answer one CONFLICT line per spec line the request contradicts.
the run stops once, on a question citing every one of them, each quote
checked against the line as the run found it; an `override:` answer lets
each cited line change, so the next go does not stop again on the second
line. a line no CONFLICT line cited still parks when it is rewritten, and a
`request:` answer covers nothing.
"""
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops

from test_named_spec_files import (API, CURSOR_API, CURSOR_RULE, CURSOR_TEST,
                                   CURSORED, ENVELOPE_LINE, PAGE_LINE,
                                   REVIEWED, RULE, RULE_LINE, TESTER, UNNAMED,
                                   conflict, paging_place)
from test_spec_conflict import RETRO, end, folders, go, plain

NL = chr(10)
BOTH = (conflict("docs/api.md:3", PAGE_LINE, UNNAMED)
        + conflict("docs/api.md:4", ENVELOPE_LINE, UNNAMED))
BEHAVIOUR = NL.join(["- behaviour: cursor([1, 2, 3], 1, 1) is [2]",
                "  file: pages.py", ""])
BUILT = "- pages.py: cursor paging" + NL + "- docs/api.md: cursor paging" + NL
OVERRIDE = "override: cursor paging on every list, as the request says"


def edits_of(place, rule=False):
    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_cursor.py").write_text(
                CURSOR_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "pages.py").write_text(CURSORED, encoding="utf-8")
            (place / "docs" / "api.md").write_text(CURSOR_API,
                                                   encoding="utf-8")
            if rule:
                (place / "rules" / "api-shape.md").write_text(
                    CURSOR_RULE, encoding="utf-8")
    return edits


def two_legs(tmp_path, monkeypatch, answer=OVERRIDE, second=BOTH,
             rule=False):
    place = paging_place(tmp_path, monkeypatch)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [BOTH]}), lambda s, n: None,
                        "--task", UNNAMED)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    question = (leg / "question.md").read_text(encoding="utf-8")
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [second + BEHAVIOUR],
                               "tester.md": [TESTER], "worker.md": [BUILT],
                               "reviewer.md": [REVIEWED],
                               "reviewer-runs.md": [REVIEWED]}),
                        edits_of(place, rule), "--resume", leg.name,
                        "--answer", answer)
    return question, asked, code


def test_one_stop_cites_both_lines_and_one_override_covers_each(
        tmp_path, monkeypatch):
    question, asked, code = two_legs(tmp_path, monkeypatch)
    assert "docs/api.md:3" in question and "docs/api.md:4" in question, \
        question
    assert end(tmp_path).cause != "conflict", \
        "the run stopped again on the second line the request contradicts"
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    [ruled] = decisions.read(tmp_path / "project")
    assert "this authorises changing docs/api.md:3, docs/api.md:4, and" \
        " nothing else" in " ".join(ruled.why.split())


def test_a_line_no_conflict_line_cited_still_parks(tmp_path, monkeypatch):
    _, asked, code = two_legs(tmp_path, monkeypatch, rule=True)
    assert code == stops.EXIT_STOP
    question = (folders(tmp_path)[-1] / "question.md").read_text(
        encoding="utf-8")
    assert 'rules/api-shape.md:1 - was "' + RULE_LINE + '"' in question


def test_a_request_answer_covers_neither_line(tmp_path, monkeypatch):
    _, asked, code = two_legs(tmp_path, monkeypatch,
                              answer="request: keep the paging as it is")
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    assert end(tmp_path).cause == "conflict"


def test_every_quote_is_checked_and_every_line_is_on_the_record(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "docs" / "api.md").write_text(API, encoding="utf-8")
    (tmp_path / "rules" / "api-shape.md").write_text(RULE, encoding="utf-8")
    question, wrong = ruling.conflict_of(BOTH, tmp_path)
    assert wrong == ""
    assert question.split(NL)[0] == ("NEEDS: the request contradicts"
                                     " docs/api.md:3 and docs/api.md:4."
                                     " which one holds?")
    assert ruling.authorised(question) == ["docs/api.md:3", "docs/api.md:4"]
    assert ruling.asked_lines({"runner": ruling.conflict_asked(
        BOTH, tmp_path)}) == (PAGE_LINE, ENVELOPE_LINE)
    second_wrong = (conflict("docs/api.md:3", PAGE_LINE, UNNAMED)
                    + conflict("docs/api.md:4", "not the line", UNNAMED))
    question, wrong = ruling.conflict_of(second_wrong, tmp_path)
    assert question == "" and "docs/api.md:4" in wrong


def page_only(rel, line):
    return "a ruling" if line == PAGE_LINE else None


def test_the_request_words_stay_when_the_first_conflict_line_is_ruled(
        tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(API, encoding="utf-8")
    said = (conflict("docs/api.md:3", PAGE_LINE, "cursor paging")
            + 'CONFLICT: docs/api.md:4 "' + ENVELOPE_LINE + '"' + NL)
    question, wrong = ruling.conflict_of(said, tmp_path, ruled=page_only)
    assert wrong == ""
    assert "docs/api.md:4" in question and "docs/api.md:3" not in question
    assert '- the request - "cursor paging"' in question, question
    piped = ('CONFLICT: docs/api.md:3 "' + PAGE_LINE + '" | cursor paging'
             + NL + 'CONFLICT: docs/api.md:4 "' + ENVELOPE_LINE + '"' + NL)
    question, _ = ruling.conflict_of(piped, tmp_path, ruled=page_only)
    assert '- the request - "cursor paging"' in question, question
    own = (conflict("docs/api.md:3", PAGE_LINE, "cursor paging")
           + conflict("docs/api.md:4", ENVELOPE_LINE, "a next cursor"))
    question, _ = ruling.conflict_of(own, tmp_path, ruled=page_only)
    assert '- the request - "a next cursor"' in question, question
