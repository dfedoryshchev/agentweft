"""an override that names a spec file to change covers that file's lines.

a request that says which spec files change, `update docs/api.md and
rules/api-shape.md to say so`, and an `override:` answer to the conflict it
stops on, let every line of those files change for the run, not only the
line the conflict cited. a file is named by its exact path, in a sentence of
the request or the answer that asks for the change; a folder, a glob, a
negated sentence or a `request:` answer names none, and a line of a file
nobody named still stops. a plan line that marks covered lines `spec:
contradicts` needs no CONFLICT line for them; a mark on any other line does.
"""
import datetime
import json
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops

from test_spec_conflict import RETRO, a_place, end, folders, go, plain

NL = chr(10)
GLOBS = "docs/*.md,rules/*.md"
OTHER = "docs/" + chr(0x430) + chr(0x43F) + chr(0x456) + ".md"

PAGE_LINE = "- Every list takes `?page=&per_page=`."
ENVELOPE_LINE = "- Every list returns `{items, page, total}`."
API = "# api" + NL + NL + PAGE_LINE + NL + ENVELOPE_LINE + NL
RULE_LINE = ("Every list pages with `?page=&per_page=` and returns"
             " `{items, page, total}`.")
RULE = RULE_LINE + NL
CURSOR_API = ("# api" + NL + NL + "- Every list takes `?after=&limit=`." + NL
              + "- Every list returns `{items, next}`." + NL)
CURSOR_RULE = ("Every list pages with `?after=&limit=` and returns"
               " `{items, next}`." + NL)

PAGES = ("def page(items, n, per):" + NL
         + "    return items[(n - 1) * per:n * per]" + NL)
CURSORED = PAGES + NL + NL + ("def cursor(items, after, limit):" + NL
                              + "    return [i for i in items if i > after]"
                              "[:limit]" + NL)
BASELINE = ("from pages import page" + NL + NL + NL + "def test_page():" + NL
            + "    assert page([1, 2, 3], 2, 2) == [3]" + NL)
CURSOR_TEST = ("def test_cursor():" + NL + "    from pages import cursor" + NL
               + NL + "    assert cursor([1, 2, 3], 1, 1) == [2]" + NL)

NAMED = ("This changes the paging: every list takes `?after=&limit=` and"
         " returns `{items, next}`. Update docs/api.md and rules/api-shape.md"
         " to say so.")
RULE_ONLY = ("This changes the paging: every list takes `?after=&limit=` and"
             " returns `{items, next}`. Update rules/api-shape.md to say so.")
UNNAMED = "I want cursor paging: `?after=&limit=` and `{items, next}`."
OVERRIDE = ("override: cursor paging on every list; the envelope is {items,"
            " next}; the api doc and the rule change to say so.")


def conflict(cite, quote, request):
    return 'CONFLICT: ' + cite + ' "' + quote + '"' + NL + "request: " \
        + request + NL


def first_plan(request):
    return conflict("rules/api-shape.md:1", RULE_LINE, request)


def second_plan(request):
    return NL.join([
        "- behaviour: cursor([1, 2, 3], 1, 1) is [2]",
        "  file: pages.py",
        "  spec: contradicts docs/api.md:3", ""]) \
        + conflict("docs/api.md:3", PAGE_LINE, request) \
        + conflict("docs/api.md:4", ENVELOPE_LINE, request)


TESTER = ("FAILS: ImportError: cannot import name 'cursor'" + NL
          + "TEST: tests/test_cursor.py" + NL)
BUILT = ("- pages.py: cursor paging" + NL + "- docs/api.md: cursor paging" + NL
         + "- rules/api-shape.md: cursor paging" + NL)
REVIEWED = "VERDICT: ok" + NL + NL + "- the change" + NL


def paging_place(tmp_path, monkeypatch, api="docs/api.md"):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", GLOBS)
    a_place(tmp_path / "project", {
        api: API, "rules/api-shape.md": RULE, "pages.py": PAGES,
        "conftest.py": "", "tests/test_pages.py": BASELINE})
    return tmp_path / "project"


def paging_edits(place, api="docs/api.md"):
    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_cursor.py").write_text(
                CURSOR_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "pages.py").write_text(CURSORED, encoding="utf-8")
            (place / api).write_text(CURSOR_API, encoding="utf-8")
            (place / "rules" / "api-shape.md").write_text(
                CURSOR_RULE, encoding="utf-8")
    return edits


def two_legs(tmp_path, monkeypatch, request, answer=OVERRIDE,
             api="docs/api.md", plan=None):
    """two legs: the planner stops on the rule's line, the answer goes
    in, and the planner's next go (`plan`, or one citing lines of the api
    doc) is read. -> (steps asked on the second leg, the prompts sent, its
    exit code)."""
    place = paging_place(tmp_path, monkeypatch, api)
    first = plain({"planner.md": [first_plan(request)]})
    asked, _, code = go(tmp_path, monkeypatch, "build-feature", first,
                        lambda s, n: None, "--task", request)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    second = plain({"planner.md": [plan or second_plan(request)
                                   .replace("docs/api.md", api)],
                    "tester.md": [TESTER], "worker.md": [BUILT],
                    "reviewer.md": [REVIEWED],
                    "reviewer-runs.md": [REVIEWED]})
    return go(tmp_path, monkeypatch, "build-feature", second,
              paging_edits(place, api), "--resume", leg.name, "--answer",
              answer)


def test_an_override_on_a_request_that_names_the_files_covers_their_lines(
        tmp_path, monkeypatch):
    asked, sent, code = two_legs(tmp_path, monkeypatch, NAMED)
    assert end(tmp_path).cause != "conflict", \
        "the run stopped again on a line of a file the request names"
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    told = " ".join(sent[0].split())
    assert "every line of docs/api.md and rules/api-shape.md" in told
    folder = folders(tmp_path)[-1]
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    [ruled] = decisions.read(tmp_path / "project")
    stamp = ruled.at.strftime(stops.STAMP) + " " + ruled.decided
    for cite in ("docs/api.md:3", "docs/api.md:4", "rules/api-shape.md:1"):
        assert cite + " (ruling " + stamp in handoff, cite
    assert "UNRULED" not in handoff
    assert "every line of docs/api.md and rules/api-shape.md" in ruled.why


def test_a_line_of_a_file_the_override_does_not_name_still_stops(
        tmp_path, monkeypatch):
    asked, _, code = two_legs(tmp_path, monkeypatch, RULE_ONLY)
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP
    assert end(tmp_path).cause == "conflict"
    question = (folders(tmp_path)[-1] / "question.md").read_text(
        encoding="utf-8")
    assert "docs/api.md:3" in question


def test_a_request_that_names_no_file_still_stops_on_the_next_spec_line(
        tmp_path, monkeypatch):
    asked, _, code = two_legs(tmp_path, monkeypatch, UNNAMED)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    assert end(tmp_path).cause == "conflict"


def test_a_request_answer_covers_nothing_new(tmp_path, monkeypatch):
    place = paging_place(tmp_path, monkeypatch)
    go(tmp_path, monkeypatch, "build-feature",
       plain({"planner.md": [first_plan(NAMED)]}), lambda s, n: None,
       "--task", NAMED)
    [leg] = folders(tmp_path)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [second_plan(NAMED)]}),
                        paging_edits(place), "--resume", leg.name,
                        "--answer", "request: keep the paging, and update"
                        " docs/api.md to say the page starts at 1")
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    assert end(tmp_path).cause == "conflict"


def test_a_file_named_with_windows_separators_and_a_non_ascii_name_reads(
        tmp_path, monkeypatch):
    api = OTHER
    request = NAMED.replace("docs/api.md", OTHER.replace("/", "\\"))
    asked, _, code = two_legs(tmp_path, monkeypatch, request, api=api)
    assert end(tmp_path).cause != "conflict"
    assert code == stops.EXIT_OK
    handoff = (folders(tmp_path)[-1] / "handoff.md").read_text(
        encoding="utf-8")
    assert api + ":3 (ruling " in handoff


# the pieces

SPECS = ("docs/api.md", "rules/api-shape.md", OTHER)


def named(text):
    return ruling.named_to_change(text, SPECS)


def test_a_file_is_named_by_its_exact_path_in_a_sentence_asking_for_a_change():
    assert named(NAMED) == {"docs/api.md", "rules/api-shape.md"}
    assert named("Rewrite `docs/api.md`.") == {"docs/api.md"}
    assert named("docs/api.md and rules/api-shape.md change to say so.") == \
        {"docs/api.md", "rules/api-shape.md"}
    assert named("update docs\\api.md") == {"docs/api.md"}
    assert named("update ./" + OTHER) == {OTHER}


def test_a_folder_a_glob_a_reference_or_a_negated_sentence_names_nothing():
    assert named("Update docs/ and rules/ to say so.") == set()
    assert named("Update docs/*.md to say so.") == set()
    assert named("Update docs to say so.") == set()
    assert named("Change the code so it matches docs/api.md.") == set()
    assert named("Do not update docs/api.md.") == set()
    assert named("Update the api doc to say so.") == set()
    assert named("Update docs/API.md to say so.") == set()
    assert named("Update docs/api.md.bak to say so.") == set()
    assert named("docs/api.md says the page starts at 1.") == set()


def test_a_list_of_names_stops_at_its_clause():
    assert named("Update the handler and docs/api.md stays as it is.") \
        == set()
    assert named("Update rules/api-shape.md, docs/api.md is the reference.") \
        == {"rules/api-shape.md"}
    assert named("Make the change rules/api-shape.md asks for.") == set()
    assert named("Keep rules/api-shape.md, docs/api.md must change.") \
        == {"docs/api.md"}
    assert named("Make the docs/api.md change the request asks for.") \
        == set()


def test_a_list_of_names_reads_on_through_its_own_clause():
    assert named("Update docs/api.md, and rules/api-shape.md as well.") \
        == {"docs/api.md", "rules/api-shape.md"}
    assert named("Update docs/api.md and the handler.") == {"docs/api.md"}
    assert named("Update docs/api.md, then run the tests.") == {"docs/api.md"}
    assert named("Cursor paging wins, docs/api.md and rules/api-shape.md"
                 " should be updated.") == {"docs/api.md",
                                            "rules/api-shape.md"}
    assert named("Update docs/api.md: cursor paging.") == {"docs/api.md"}


def test_a_named_file_followed_by_an_ordinary_word_stays_named():
    assert named("Switch to cursor paging and update docs/api.md as"
                 " needed.") == {"docs/api.md"}
    assert named("Update the docs/api.md file to say so.") == {"docs/api.md"}
    assert named("Update docs/api.md where it names the page.") \
        == {"docs/api.md"}
    assert named("Update docs/api.md if it names the page.") \
        == {"docs/api.md"}
    assert named("Update docs/api.md and rules/api-shape.md accordingly.") \
        == {"docs/api.md", "rules/api-shape.md"}
    assert named("Update docs/api.md to match.") == {"docs/api.md"}


def test_a_list_of_names_stops_at_a_verb_a_modal_or_which():
    assert named("Update docs/api.md and rules/api-shape.md, which stays the"
                 " reference.") == {"docs/api.md"}
    for said in ("Update rules/api-shape.md, docs/api.md lists the pages.",
                 "Update rules/api-shape.md, docs/api.md should stay.",
                 "Update rules/api-shape.md, docs/api.md has the pages.",
                 "Update rules/api-shape.md, docs/api.md that names them.",
                 "Update rules/api-shape.md, docs/api.md changed already."):
        assert named(said) == {"rules/api-shape.md"}, said


def test_the_first_name_after_the_verb_is_its_object_whatever_follows():
    for said in ("Update docs/api.md examples to match.",
                 "Fix the paging and update docs/api.md typos too.",
                 "Update docs/api.md headings for the new paging.",
                 "Update docs/api.md sections on paging.",
                 "Update docs/api.md afterwards.",
                 "Update docs/api.md always, it is the reference.",
                 "Update docs/api.md and tests to match.",
                 "Update docs/api.md and examples accordingly.",
                 "Update docs/api.md and keep the handler as it is."):
        assert named(said) == {"docs/api.md"}, said


def test_a_later_name_stays_in_the_list_only_before_words_that_go_on_with_it():
    for said in ("Update docs/api.md and rules/api-shape.md went stale.",
                 "Update docs/api.md and rules/api-shape.md got it right.",
                 "Update docs/api.md and rules/api-shape.md said so already.",
                 "Update docs/api.md and rules/api-shape.md examples follow."):
        assert named(said) == {"docs/api.md"}, said
    for said in ("Update docs/api.md and rules/api-shape.md as needed.",
                 "Update docs/api.md and rules/api-shape.md where needed.",
                 "Update docs/api.md and rules/api-shape.md to match.",
                 "Update docs/api.md, rules/api-shape.md, and the handler."):
        assert named(said) == {"docs/api.md", "rules/api-shape.md"}, said


def test_an_answer_that_keeps_a_file_covers_none_of_its_lines():
    kept = answered("override: cursor paging wins, update the handler and"
                    " docs/api.md stays the reference", ruling.OVERRIDE)
    assert ruling.spec_line_ruled([kept], PAGE_LINE, ASKED, rel="docs/api.md",
                                  request=UNNAMED, specs=SPECS) is None


def test_the_run_stops_on_the_first_conflict_line_no_ruling_covers(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "docs" / "api.md").write_text(API, encoding="utf-8")
    (tmp_path / "rules" / "api-shape.md").write_text(RULE, encoding="utf-8")
    said = (conflict("docs/api.md:3", PAGE_LINE, NAMED)
            + conflict("rules/api-shape.md:1", RULE_LINE, NAMED))

    def docs_only(rel, line):
        return "a ruling" if rel == "docs/api.md" else None

    question, wrong = ruling.conflict_of(said, tmp_path, ruled=docs_only)
    assert wrong == ""
    assert question.split(NL)[0] == ("NEEDS: the request contradicts"
                                     " rules/api-shape.md:1. which one holds?")
    assert ruling.asked_lines({"runner": ruling.conflict_asked(
        said, tmp_path, ruled=docs_only)}) == (RULE_LINE,)
    assert ruling.conflict_of(said, tmp_path,
                              ruled=lambda rel, line: "a ruling") is None
    assert ruling.conflict_of(said, tmp_path)[0].split(NL)[0] == (
        "NEEDS: the request contradicts docs/api.md:3 and"
        " rules/api-shape.md:1. which one holds?")
    misquoted = conflict("docs/api.md:3", "not the line", NAMED)
    assert ruling.conflict_of(misquoted, tmp_path,
                              ruled=lambda rel, line: "a ruling")[1]


MARKED = NL.join([
    "- behaviour: cursor([1, 2, 3], 1, 1) is [2]",
    "  file: pages.py",
    "  spec: contradicts docs/api.md:3 and docs/api.md:4 (ruling)",
    "  spec: contradicts rules/api-shape.md:1 (ruling)", ""])


def test_a_plan_marking_lines_the_override_covers_needs_no_conflict_line(
        tmp_path, monkeypatch):
    asked, _, code = two_legs(tmp_path, monkeypatch, NAMED, plan=MARKED)
    gates = (folders(tmp_path)[-1] / "gates.md").read_text(encoding="utf-8")
    assert "FAIL conflict" not in gates
    assert code == stops.EXIT_OK


def test_a_mark_needs_a_conflict_line_unless_a_ruling_covers_each_line(
        tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "docs" / "api.md").write_text(API, encoding="utf-8")
    (tmp_path / "rules" / "api-shape.md").write_text(RULE, encoding="utf-8")

    def docs_only(rel, line):
        return "a ruling" if rel == "docs/api.md" else None

    def mark(*cites):
        return "- behaviour: x" + NL + "  spec: contradicts " \
            + " and ".join(cites) + " (ruling)" + NL

    assert ruling.conflict_of(mark("docs/api.md:3", "docs/api.md:4"),
                              tmp_path, ruled=docs_only) is None
    assert ruling.conflict_of(mark("docs/api.md:3-4"), tmp_path,
                              ruled=docs_only) is None
    for plan in (mark("rules/api-shape.md:1"),
                 mark("docs/api.md:3", "rules/api-shape.md:1"),
                 mark("docs/api.md:3") + mark("rules/api-shape.md:1"),
                 mark("the api doc"), mark("docs/api.md:40")):
        said = ruling.conflict_of(plan, tmp_path, ruled=docs_only)
        assert said and "has no CONFLICT line" in said[1], plan
    assert ruling.conflict_of(mark("docs/api.md:3"), tmp_path)[1]


def entry(decided, why):
    return decisions.Decision(decided, why, datetime.datetime(2026, 1, 1))


def answered(answer, kind):
    return entry(ruling.decided("planner.md", answer),
                 ruling.why("planner.md", "build-1", "NEEDS: which holds?",
                            answer, "someone", kind=kind))


ASKED = {"build-1": ("a line",)}


def test_only_an_override_to_the_runners_spec_question_covers_a_named_file():
    over = answered(OVERRIDE, ruling.OVERRIDE)
    kept = answered("request: update docs/api.md", ruling.REQUEST)
    line = PAGE_LINE

    def ruled(d, rel, request=NAMED, asked=ASKED):
        return ruling.spec_line_ruled([d], line, asked, rel=rel,
                                      request=request, specs=SPECS)

    assert ruled(over, "docs/api.md") is over
    assert ruled(over, "rules/api-shape.md") is over
    assert ruled(over, "docs/other.md") is None
    assert ruled(over, "docs/api.md", request=UNNAMED) is None
    assert ruled(over, "docs/api.md", asked={}) is None
    assert ruled(over, "docs/api.md", asked={"build-1": ()}) is None
    assert ruled(kept, "docs/api.md") is None
    by_answer = answered("override: update docs/api.md to say so",
                         ruling.OVERRIDE)
    assert ruled(by_answer, "docs/api.md", request=UNNAMED) is by_answer
    amended = ruling.amended(UNNAMED, "request: update docs/api.md")
    assert ruled(over, "docs/api.md", request=amended) is None


STEP_ASKS = NL.join(["NEEDS: does the page paging stay beside the cursor?",
                     "CITES:", "- docs/api.md:3", "OPTIONS:", "- it stays",
                     "- it goes", ""])


def test_an_override_to_a_steps_own_question_writes_no_scope_sentence(
        tmp_path, monkeypatch):
    paging_place(tmp_path, monkeypatch)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [STEP_ASKS]}), lambda s, n: None,
                        "--task", UNNAMED)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    _, sent, _ = go(tmp_path, monkeypatch, "build-feature",
                    plain({"planner.md": [STEP_ASKS]}), lambda s, n: None,
                    "--resume", leg.name, "--answer",
                    "override: update docs/api.md, the cursor replaces it")
    [ruled] = decisions.read(tmp_path / "project")
    assert "authorises" not in ruled.why, ruled.why
    assert "the cursor replaces it" in sent[0]
    assert "authorises" not in sent[0]
    assert ruling.spec_line_ruled([ruled], PAGE_LINE, {}, rel="docs/api.md",
                                  request=UNNAMED, specs=SPECS) is None
