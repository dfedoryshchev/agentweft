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
INVERT = "- `--invert`: print the well-formed requests that do NOT meet" \
    " the conditions instead (malformed"
INVERTED = "  lines are still never printed)."
FILTERS = dict(LOGSIFT)
FILTERS.update({134: INVERT, 135: INVERTED, 136: ""})
SECTIONS = {5: LOGSIFT[5], 6: LOGSIFT[6], 138: INVERT, 139: INVERTED,
            140: "", 141: "## 6. Module layout (fixed)"}
PLACES = {"top-section": LOGSIFT, "time-range": LOGSIFT,
          "delimiter-newline": GRADEBOOK, "delimiter-escape": GRADEBOOK,
          "drop-lowest": GRADEBOOK, "error-order": LEDGERLITE,
          "cache-clear": {}, "invert-window": FILTERS,
          "top-placement": SECTIONS, "depth-key": {}}
QUESTION = {
    "top-section": "Where should the `top` section go in TASK.md",
    "delimiter-newline": "An LF or CR in `--delimiter` printed raw",
    "error-order": "When an earlier file has a currency error",
    "time-range": "Must T be a real date and time",
    "drop-lowest": "How should `--drop-lowest` combine with",
    "delimiter-escape": "What should `error: invalid --delimiter: <C>` print",
    "cache-clear": "Should createItem or moveItem on the same client",
    "invert-window": "With `--invert` and an `--until` at or before",
    "top-placement": "Where should the `top` section go in TASK.md?",
    "depth-key": "When `--by` is not `path` and the `--depth` value"}
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


def routed(tmp_path, name, text=None, request=None):
    """-> (what goes to the person or "", the rulings the lead wrote), on a
    run handed `request`."""
    ruled = []
    run = types.SimpleNamespace(
        workdir=a_place(tmp_path, PLACES[name]), lead=LEAD, led={},
        start=None, spec_line_covered=None, task_text=request,
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


LAST = 'SETTLED BY: TASK.md:5 "The last section fixes the module layout"'
NEGATED = ('SETTLED BY: TASK.md:134 "print the well-formed requests that do'
           ' NOT meet the conditions"')
OFFSET = ("QUESTION: Should a T offset beyond", "SIZE: a few lines in the T"
          " parser plus tests")


def in_the_new_shape(text):
    """-> the recorded invert-window answer with each question a line of the
    place answers carrying that line, the quote the planner itself put in
    the question, the way the handoff now asks for it."""
    text = typed(text, "SIZE: one test and one line in filters.py",
                 NEGATED + NL + "SIZE: one test and one line in filters.py")
    return typed(text, "SIZE: a TASK.md edit only",
                 LAST + NL + "SIZE: a TASK.md edit only")


def test_the_invert_questions_its_lines_settle_are_the_lead_s_and_the_gap_parks(
        tmp_path):
    said, ruled = routed(tmp_path, "invert-window",
                         in_the_new_shape(recorded("invert-window")))
    assert said.startswith("NEEDS: " + OFFSET[0][len("QUESTION: "):]), said
    assert ruled == []


def test_the_invert_gap_taken_as_assumed_leaves_two_lead_decisions(tmp_path):
    text = in_the_new_shape(recorded("invert-window"))
    start, end = text.index(OFFSET[0]), text.index(OFFSET[1])
    text = text[:start] + text[end + len(OFFSET[1]) + 1:]
    text = typed(text, "  if wrong: one test changes", NL.join([
        "  if wrong: one test changes",
        "- a T offset is held to 00-23 hours and 00-59 minutes",
        "  why: TASK.md:48 holds a log offset to them, the nearest like line",
        "  if wrong: the offset tests flip"]))
    said, ruled = routed(tmp_path, "invert-window", text)
    assert said == ""
    assert [w.split(", which ")[1].split(" settles")[0] for _, w, _ in ruled] \
        == [NEGATED[len("SETTLED BY: "):], LAST[len("SETTLED BY: "):]]
    assert all(by == rulings.LEAD for _, _, by in ruled)


def test_the_placement_question_its_line_settles_is_the_lead_s(tmp_path):
    rec = "RECOMMEND: Insert a new `## 5a. top` section between lines 139"
    text = recorded("top-placement")
    line = next(l for l in text.split(NL) if l.startswith(rec))
    said, ruled = routed(tmp_path, "top-placement",
                         typed(text, line, line + NL + LAST))
    assert said == ""
    [(decided, why, by)] = ruled
    assert decided.startswith(LEAD + " decided for " + LEAD + ": Insert a new")
    assert "TASK.md:5" in why and by == rulings.LEAD


DEPTH = NL.join([
    "# instructions",
    "- the request: Feature request: add `--depth N` to `count`, valid only"
    " with `--by path` (otherwise `error: --depth needs --by path`). It groups"
    " paths by their first N segments: the key is `/` followed by the first N"
    " non-empty segments of the path joined by `/` (fewer if the path has"
    " fewer; `/` alone if it has none), so with `--depth 1` both"
    " `/api/v1/users` and `/api//v2` count as `/api`. N is a whole number"
    " written in digits, 1 or more; any other value is `error: invalid"
    " --depth: <value>`. Update TASK.md to describe it, and add tests.",
    "- the spec is TASK.md in the directory you are working in.",
    "- standard library only; pytest for tests.", ""])
KEY_RULE = "the key is `/` followed by the first N non-empty segments of the" \
    " path joined by `/`"
ORDER = ("QUESTION: When `--by` is not `path`", "SIZE: one line ordering in"
         " logsift/cli.py plus one test")


def target_settled_by(settled):
    """-> the recorded depth-key answer with its error order question, the
    gap, taken out, and its target question carrying `settled`."""
    text = recorded("depth-key")
    start, end = text.index(ORDER[0]), text.index(ORDER[1])
    text = text[:start] + text[end + len(ORDER[1]) + 1:]
    return typed(text, "SIZE: no code beyond the rule; one test",
                 "SETTLED BY: " + settled + NL
                 + "SIZE: no code beyond the rule; one test")


def test_the_target_question_the_request_settles_is_the_lead_s(tmp_path):
    said, ruled = routed(tmp_path, "depth-key",
                         target_settled_by('the request "' + KEY_RULE + '"'),
                         DEPTH)
    assert said == ""
    [(decided, why, by)] = ruled
    assert decided == LEAD + " decided for " + LEAD + ": yes, apply the rule" \
        " as written, since the request defines the key purely from non-empty" \
        " segments"
    assert 'which the request "' + KEY_RULE + '" settles' in why
    assert by == rulings.LEAD


@pytest.mark.parametrize("settled", [
    'task.md:2 "' + KEY_RULE + '"', 'decisions.md:1 "' + KEY_RULE + '"',
    'the request "the key is the first N segments"'])
def test_the_target_question_citing_no_words_of_the_request_goes_to_the_person(
        tmp_path, settled):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "decisions.md").write_text(KEY_RULE + NL, encoding="utf-8")
    said, ruled = routed(tmp_path, "depth-key", target_settled_by(settled),
                         DEPTH)
    assert said.startswith("NEEDS: Is a target that does not start with")
    assert ruled == []


def test_a_request_cite_on_a_run_handed_no_request_settles_nothing(tmp_path):
    said, ruled = routed(tmp_path, "depth-key",
                         target_settled_by('the request "' + KEY_RULE + '"'))
    assert said.startswith("NEEDS: Is a target that does not start with")
    assert ruled == []
