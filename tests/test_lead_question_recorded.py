"""the lead's own QUESTION, on planner answers as they were recorded.

each file under tests/lead_questions/ is an excerpt of a planner answer a
build-feature run gave, the lines the route reads kept word for word: the
plan lines around the question and the handoff's question. none was written
with a `SETTLED BY:` line or a `spec: breaks` mark, so as recorded each one
is a question the context leaves open and goes to the person. the same
answer with the typed line the planner is now taught is decided by the lead
when the line it cites settles it, and goes to the person, with the marked
line beside the question, when the plan marks a spec line broken.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import rulings
from agentweft.runner import asking
from agentweft.runner.handoff import Handoff

NL = chr(10)
LEAD = "planner.md"
HERE = Path(__file__).resolve().parent / "lead_questions"
FILLER = "- a line the question does not read"
LOGSIFT = {5: "the repository root; the package is the `logsift/` folder"
              " there. The last section fixes the module",
           6: "layout.",
           137: "## 6. Module layout (fixed)"}
GRADEBOOK = {11: "- Every command exits 0 on success and 2 on any error. On an"
                 " error it prints exactly one line to",
             12: "  stderr, starting with `error: `, and prints nothing to"
                 " stdout. Usage errors (an unknown command or",
             43: "- Fields are separated by commas."}
LEDGERLITE = {80: "- Every other line must have exactly 4 fields with valid"
                  " values. The first line that does not is an",
              81: "  error naming it: `error: line <n>: <reason>` (the reason"
                  " text is free)."}
PLACES = {"top-section": LOGSIFT, "time-range": LOGSIFT,
          "delimiter-newline": GRADEBOOK, "delimiter-escape": GRADEBOOK,
          "drop-lowest": GRADEBOOK, "error-order": LEDGERLITE,
          "cache-clear": {}}
QUESTION = {
    "top-section": "Where should the `top` section go in TASK.md",
    "delimiter-newline": "An LF or CR in `--delimiter` printed raw",
    "error-order": "When an earlier file has a currency error",
    "time-range": "Must T be a real date and time",
    "drop-lowest": "How should `--drop-lowest` combine with",
    "delimiter-escape": "What should `error: invalid --delimiter: <C>` print",
    "cache-clear": "Should createItem or moveItem on the same client"}
SETTLED = 'SETTLED BY: TASK.md:5-6 "The last section fixes the module layout."'
CR_LF = ("for LF stderr is no longer exactly one line)" + NL
         + "  file: gradebook/cli.py" + NL + "  spec: adds to TASK.md:23")


def recorded(name):
    return (HERE / (name + ".md")).read_text(encoding="utf-8")


def typed(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def a_place(tmp_path, lines):
    tmp_path.mkdir(parents=True, exist_ok=True)
    spec = [lines.get(n, FILLER) for n in range(1, 151)]
    (tmp_path / "TASK.md").write_text(NL.join(spec) + NL, encoding="utf-8")
    api = tmp_path / "frontend" / "src" / "api.js"
    api.parent.mkdir(parents=True, exist_ok=True)
    api.write_text(NL.join("// line " + str(n) for n in range(1, 41)) + NL,
                   encoding="utf-8")
    return tmp_path


def routed(tmp_path, name, text=None):
    """-> (what goes to the person or "", the rulings the lead wrote)."""
    ruled = []
    run = types.SimpleNamespace(
        workdir=a_place(tmp_path, PLACES[name]), lead=LEAD, led={},
        start=None, spec_line_covered=None,
        rule=lambda decided, why, by: ruled.append((decided, why, by)),
        rulings=lambda: [])
    out = Handoff("planner", recorded(name) if text is None else text)
    said = asking.lead_escalates(run, LEAD, out)
    if not said:
        asking.lead_decides(run, LEAD, out, "the-run")
    return said, ruled


@pytest.mark.parametrize("name", sorted(QUESTION))
def test_a_recorded_question_with_no_settling_line_goes_to_the_person(
        tmp_path, name):
    said, ruled = routed(tmp_path, name)
    assert said.startswith("NEEDS: " + QUESTION[name]), said
    assert "RECOMMEND: " in said
    assert ruled == []


def test_the_section_question_its_spec_line_settles_is_the_lead_s(tmp_path):
    rec = ("Insert it before line 137 as `## 5a. top`. Then no existing line"
           " changes and line 5 stays true.")
    text = typed(recorded("top-section"), "RECOMMEND: " + rec,
                 "RECOMMEND: " + rec + NL + SETTLED)
    said, ruled = routed(tmp_path, "top-section", text)
    assert said == ""
    [(decided, why, by)] = ruled
    assert decided == LEAD + " decided for " + LEAD + ": " + rec
    assert "TASK.md:5-6" in why
    assert by == rulings.LEAD


def test_the_newline_question_on_a_line_marked_broken_goes_to_the_person(
        tmp_path):
    broken = typed(recorded("delimiter-newline"), CR_LF,
                   CR_LF.replace("spec: adds to TASK.md:23",
                                 "spec: breaks TASK.md:11"))
    settled = typed(broken, "SIZE: one test assertion",
                    'SETTLED BY: TASK.md:43 "- Fields are separated by'
                    ' commas."' + NL + "SIZE: one test assertion")
    for text in (broken, settled):
        said, ruled = routed(tmp_path / str(len(text)), "delimiter-newline",
                             text)
        assert said.startswith("NEEDS: " + QUESTION["delimiter-newline"])
        assert "- spec: breaks TASK.md:11" in said.split(NL), said
        assert ruled == []
