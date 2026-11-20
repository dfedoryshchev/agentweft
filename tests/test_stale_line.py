"""a stale spec or doc line a step or the retro finds is a question on the
head, with the line as the run found it and the text proposed for it.

a later step's finding reaches the flow's lead (the finding rung), which may
answer that the spec line is out of date and the code is right: `STALE <n>:
<file>:<line> "<the line>" -> "<the proposed line>"`. the program holds it
only when the line is a spec file's and reads as quoted; the run goes on and
the head lists it among the questions. the retro may not ticket a spec file,
so its nice-to-do on one, with its evidence on the line, is put on the head
the same way after the run, and the run's outcome stands.
"""
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.guardrails import factsguard
from agentweft.runner import asking, front, stops, summary, upkeep

import test_finding_rung as fr
from test_retro_maintains import block, put

NL = chr(10)
SPEC_LINE = "mul(a, b) returns a times b"
PROPOSED = "mul(a, b) returns a times b; add(a, b) returns a minus b"
STALE = ('STALE 1: TASK.md:3 "' + SPEC_LINE + '" -> "' + PROPOSED + '"' + NL)


def head_of(folder):
    lines = (folder / "handoff.md").read_text(encoding="utf-8").split(NL)
    first = lines.index("## the one decision") + 1
    end = next(n for n in range(first, len(lines))
               if lines[n].startswith("## "))
    return NL.join(lines[first:end])


def test_a_finding_the_lead_calls_a_stale_spec_line_is_a_question_on_the_head(
        tmp_path, monkeypatch):
    asked, sent, code, folder, _ = fr.found_by_the_worker(
        tmp_path, monkeypatch, [STALE])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md",
                     "reviewer.md", "reviewer-runs.md", fr.tl.RETRO]
    assert code == stops.EXIT_OK
    assert "STALE <n>:" in sent[3]
    head = head_of(folder)
    assert 'TASK.md:3 "' + SPEC_LINE + '"' in head
    assert 'proposed: "' + PROPOSED + '"' in head
    assert "nothing waits on you" not in head


def test_a_stale_line_by_a_windows_path_on_a_non_ascii_line(tmp_path,
                                                             monkeypatch):
    line = "mul(a, b) returns a times b, caf" + chr(0xE9)
    monkeypatch.setattr(fr.tl, "SPEC", "# calc" + NL + NL + line + NL)
    said = ('STALE 1: .\\TASK.md:3 "' + line + '" -> "' + line + ' or more"'
            + NL)
    asked, _, code, folder, _ = fr.found_by_the_worker(tmp_path, monkeypatch,
                                                       [said])
    assert code == stops.EXIT_OK
    assert 'TASK.md:3 "' + line + '"' in head_of(folder)


def test_a_stale_line_whose_quote_is_not_the_line_parks(tmp_path,
                                                         monkeypatch):
    asked, _, code, _, _ = fr.found_by_the_worker(
        tmp_path, monkeypatch, [STALE.replace("a times b\"", "a plus b\"", 1)])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP


def test_a_stale_line_on_a_file_that_is_no_spec_parks(tmp_path, monkeypatch):
    asked, _, code, _, _ = fr.found_by_the_worker(
        tmp_path, monkeypatch,
        ['STALE 1: calc.py:2 "return a - b" -> "return a + b"' + NL])
    assert asked == ["planner.md", "tester.md", "worker.md", "planner.md"]
    assert code == stops.EXIT_STOP


def test_the_stale_lines_a_run_holds_are_carried_by_its_record(tmp_path):
    kept = types.SimpleNamespace(state=None, save=lambda: None)
    item = {"at": "TASK.md:3", "line": SPEC_LINE, "proposed": PROPOSED,
            "quoted": True, "by": "planner.md, for what worker.md found"}
    run = types.SimpleNamespace(kept=kept, stale=[item])
    asking.keep_state(run)
    assert kept.state["stale"] == [item]
    again = types.SimpleNamespace(kept=kept)
    asking.carry_state(again)
    assert again.stale == [item]
    kept.state = {"stale": [{"at": 3}]}
    broken = types.SimpleNamespace(kept=kept)
    asking.carry_state(broken)
    assert "could not be read" in broken.state_unread


# a measured run's retro FACTS item on a stale doc line, in its shape
TABLE_LINE = "| `pantry/services/moves.py` | move rules and the move log |"
TICKET = NL.join([
    "fact:", "  scope: docs/architecture.md", "  kind: nice-to-do",
    "  label: none",
    "  claim: In the Modules table, change the line `pantry/services/moves.py`"
    " to `pantry/services/stock_moves.py`, the file the move rules now live"
    " in",
    "  why: Commit 35d65a2 renamed the service, and planner seq 1 flagged this"
    " line as stale; this run changed pantry/services/stock_moves.py",
    '  source: seq 1 planner.md; evidence: docs/architecture.md:40 "' + TABLE_LINE
    + '"',
    "  anchor: docs/architecture.md:40-40",
    '  check: grep -n -F "pantry/services/moves.py" docs/architecture.md'
    " exits 0"])


def architecture(tmp_path, monkeypatch, line=TABLE_LINE):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", "TASK.md,docs/architecture.md")
    put(tmp_path, "docs/architecture.md",
        NL.join(["# architecture"] + ["x"] * 38 + [line, ""]))
    put(tmp_path, "pantry/services/stock_moves.py", "x = 1" + NL)


def kept_up(tmp_path, said):
    return upkeep.maintain(factsguard.Store(tmp_path),
                           factsguard.Record(tmp_path), said, "r")


def test_the_retro_s_ticket_on_a_spec_line_is_put_to_the_operator(
        tmp_path, monkeypatch):
    architecture(tmp_path, monkeypatch)
    done = kept_up(tmp_path, block(TICKET))
    assert done.tickets == []
    assert "docs/architecture.md is a spec file" in done.refused[0][1]
    assert done.stale == [{
        "at": "docs/architecture.md:40", "line": TABLE_LINE,
        "proposed": "In the Modules table, change the line"
        " `pantry/services/moves.py` to `pantry/services/stock_moves.py`, the"
        " file the move rules now live in", "quoted": False,
        "by": "the retro, after the run"}]
    assert done.record()["stale"] == done.stale
    assert "a question on the head" in done.lines[0]


def test_a_replace_claim_proposes_the_line_as_it_would_read(tmp_path,
                                                             monkeypatch):
    architecture(tmp_path, monkeypatch)
    claim = ('  claim: replace "pantry/services/moves.py" with'
             ' "pantry/services/stock_moves.py"')
    item = NL.join(l if not l.startswith("  claim:") else claim
                   for l in TICKET.split(NL))
    done = kept_up(tmp_path, block(item))
    assert done.stale[0]["proposed"] == TABLE_LINE.replace("moves.py",
                                                    "stock_moves.py")
    assert done.stale[0]["quoted"] is True


def test_an_edit_of_a_spec_line_is_put_to_the_operator_too(tmp_path,
                                                            monkeypatch):
    architecture(tmp_path, monkeypatch)
    done = kept_up(tmp_path, block(NL.join([
        "edit: docs/architecture.md", "  now: pantry/services/moves.py",
        "  after: pantry/services/stock_moves.py",
        "  because: the service was renamed"])))
    assert done.stale[0]["at"] == "docs/architecture.md:40"
    assert done.stale[0]["proposed"] == TABLE_LINE.replace("moves.py",
                                                    "stock_moves.py")


def test_a_ticket_whose_evidence_is_not_on_the_line_puts_nothing(
        tmp_path, monkeypatch):
    architecture(tmp_path, monkeypatch, line="| something else |")
    done = kept_up(tmp_path, block(TICKET))
    assert done.stale == [] and "stale" not in done.record()
    architecture(tmp_path, monkeypatch)
    done = kept_up(tmp_path, block(TICKET.replace(":40 \"", ":41 \"")))
    assert done.stale == []


HANDOFF = NL.join(["# f r: done - mul added", "", "suite: 1 of 1 gates passed.",
                   "", "## the one decision", "- none: nothing waits on you.",
                   "", "## why", "- x", ""])


def test_after_the_retro_its_stale_line_is_on_the_head_and_the_outcome_stands(
        tmp_path):
    path = tmp_path / "handoff.md"
    path.write_text(HANDOFF, encoding="utf-8")
    item = {"at": "docs/architecture.md:40", "line": TABLE_LINE,
            "proposed": "change the line", "quoted": False,
            "by": "the retro, after the run"}
    retro_pass = {"step": "retro.md", "facts": {"kept_facts": {
        "stale": [item]}}}
    summary.after_retro(path, [retro_pass], "$0.01")
    text = path.read_text(encoding="utf-8")
    assert text.split(NL)[0] == "# f r: done - mul added"
    head = head_of(tmp_path)
    assert 'docs/architecture.md:40 "' + TABLE_LINE + '"' in head
    assert "proposed: change the line" in head
    assert "nothing waits on you" not in head


def test_the_view_lists_a_stale_line_among_the_questions():
    item = {"at": "TASK.md:3", "line": SPEC_LINE, "proposed": PROPOSED,
            "quoted": True, "by": "planner.md, for what worker.md found"}
    out = front.view(["# f r: done"], [], [], [], [], stale=[item])
    head = NL.join(out[out.index("## the one decision"):out.index("## why")])
    assert front.STALE_LINE.format(at="TASK.md:3", line=SPEC_LINE) in head
    assert "nothing waits on you" not in head
