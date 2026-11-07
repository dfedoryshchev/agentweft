"""a start test that pins a spec line an override rules may change with it.

once an `override:` answer lets spec lines change, a test the run started
with that pins exactly those lines is wrong with them. a step may change it
when its answer names it on a WRONG TEST line whose `spec:` line quotes a
line the ruling covers, as the run found it or as the run's own ruled edit
left it, and the claim ties the test (`Run.tied`: red as found against the
product now, red as left against the product as found, and its found code
sharing a word with the line as found; a field moved into a nested shape
ties by its name), and the handoff lists each such test under that ruling
with the line its claim quoted. a ruled line quoted for a test that pins an
unruled line covers nothing, loosened or rewritten. a plan that marks a
ruled line `spec: contradicts` needs no new CONFLICT line for it. the
start-tests replay lays out a start test file every change of which a
ruling covers as the run left it, and one that runs an unruled one is not.
a claimed test file read by line is tied when the python test that runs it,
red against the product now, turns green with the file as left, stays red
without it and is red on the start state with it alone as left; an emptied
file (beside an honest claimed file or not), one the turn does not need and
one whose layout turns no test still park. a test changed with no WRONG TEST line, a
test on a line no
ruling covers, code a file's tests share with a test that reads it unnamed,
a quote of neither the found line nor the ruled edit, a `request:` answer
and an entry a step wrote in decisions.md itself let nothing change, and a
claim on a start test the step left as it was still asks.
"""
import datetime
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot, starttests, testedits, worktree
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops, wrongtest

from test_named_spec_files import (API, CURSOR_API, CURSOR_RULE, CURSOR_TEST,
                                   ENVELOPE_LINE, GLOBS, NAMED, OVERRIDE,
                                   PAGE_LINE, PAGES, REVIEWED, RULE,
                                   RULE_LINE, TESTER, first_plan)
from test_spec_conflict import a_place, end, folders, go, plain

NL = chr(10)

NAMES_LINE = "Names list in the order they were added."
NAMES = "# names" + NL + NL + NAMES_LINE + NL
LISTING = (PAGES + NL + NL + "def listing(items):" + NL
           + '    return {"items": items, "page": 1, "total": len(items)}' + NL
           + NL + NL + "def names(items):" + NL + "    return list(items)"
           + NL)
CURSOR_LISTING = (PAGES + NL + NL + "def cursor(items, after, limit):" + NL
                  + "    return [i for i in items if i > after][:limit]" + NL
                  + NL + NL + "def listing(items):" + NL
                  + '    return {"items": items, "next": None}' + NL + NL + NL
                  + "def names(items):" + NL + "    return sorted(items)" + NL)
ENVELOPE_TEST = "tests/test_envelope.py::test_a_list_carries_the_page_envelope"
FIRST_PAGE_TEST = "tests/test_envelope.py::test_a_list_starts_at_page_one"
NAMES_TEST = "tests/test_names.py::test_names_keep_their_order"
ENVELOPE = ("from pages import listing" + NL + NL + NL
            + "def test_a_list_carries_the_page_envelope():" + NL
            + '    assert set(listing([1])) == {"items", "page", "total"}' + NL
            + NL + NL + "def test_a_list_starts_at_page_one():" + NL
            + '    assert listing([1])["page"] == 1' + NL)
CURSOR_ENVELOPE = ENVELOPE.replace(
    '{"items", "page", "total"}', '{"items", "next"}').replace(
    'listing([1])["page"] == 1', 'listing([1])["next"] is None')
SHARED = ("from pages import listing" + NL + NL
          + 'KEYS = {"items", "page", "total"}' + NL + NL + NL
          + "def test_a_list_carries_the_page_envelope():" + NL
          + "    assert set(listing([1])) == KEYS" + NL
          + NL + NL + "def test_a_list_starts_at_page_one():" + NL
          + '    assert listing([1])["page"] == 1' + NL)
CURSOR_SHARED = SHARED.replace(
    '{"items", "page", "total"}', '{"items", "next"}').replace(
    'listing([1])["page"] == 1', 'listing([1])["next"] is None')
# a third test that reads the shared keys and stays green on the moved
# product: the ruled edit does not decide it
KEPT_ITEMS = (NL + NL + "def test_a_list_keeps_its_items():" + NL
              + '    assert "items" in KEYS' + NL)
SHARED_KEPT = SHARED + KEPT_ITEMS
CURSOR_SHARED_KEPT = CURSOR_SHARED + KEPT_ITEMS
# a test whose lines hold a word the edit took out, green as found against
# the moved product too: a claim can cover it, the edit does not decide it
COUNT_TEST = "tests/test_envelope.py::test_a_list_counts_one_item"
ENVELOPE_COUNT = (ENVELOPE + NL + NL + "def test_a_list_counts_one_item():"
                  + NL + '    assert listing([1]).get("total", 1) == 1' + NL)
CURSOR_ENVELOPE_COUNT = (CURSOR_ENVELOPE + NL + NL
                         + "def test_a_list_counts_one_item():" + NL
                         + '    assert listing([1]).get("next") is None' + NL)
NAMES_START = ("from pages import names" + NL + NL + NL
               + "def test_names_keep_their_order():" + NL
               + "    assert names(['b', 'a']) == ['b', 'a']" + NL)
NAMES_SORTED = NAMES_START.replace("== ['b', 'a']", "== ['a', 'b']")
# a test file read by line, and a python test that runs it: the shape of a
# pytest test that runs a node suite over a folder of js tests
JS_FILE = "tests/envelope.test.js"
JS_TEST = JS_FILE + "::expects the envelope"
BRIDGE_TEST = "tests/test_bridge.py::test_the_js_suite_passes"
JS = "expect items" + NL + "expect page" + NL + "expect total" + NL
CURSOR_JS = "expect items" + NL + "expect next" + NL
BRIDGE = ("from pathlib import Path" + NL + NL + "from pages import listing"
          + NL + NL + NL + "def test_the_js_suite_passes():" + NL
          + '    js = Path(__file__).parent / "envelope.test.js"' + NL
          + '    for line in js.read_text(encoding="utf-8").splitlines():' + NL
          + "        assert line.split()[1] in listing([1]), line" + NL)
# pytest runs the js file by itself too, as a js runner would
JS_RUNNER = NL.join([
    "import pytest", "", "",
    "def pytest_collect_file(parent, file_path):",
    '    if file_path.name.endswith(".test.js"):',
    "        return JsFile.from_parent(parent, path=file_path)", "", "",
    "class JsFile(pytest.File):",
    "    def collect(self):",
    '        yield JsCase.from_parent(self, name="expects the envelope")',
    "", "",
    "class JsCase(pytest.Item):",
    "    def runtest(self):",
    "        from pages import listing",
    '        for line in self.path.read_text(encoding="utf-8").splitlines():',
    "            assert line.split()[1] in listing([1]), line", ""])

# a planner's plan on the leg after the override: each ruled line marked,
# and no CONFLICT line
MARKED_PLAN = NL.join([
    "- behaviour: listing([1]) is {items, next}",
    "  file: pages.py",
    "  spec: contradicts docs/api.md:4 (ruling)",
    "- behaviour: cursor([1, 2, 3], 1, 1) is [2]",
    "  file: pages.py",
    "  spec: contradicts rules/api-shape.md:1 and docs/api.md:3 (ruling)", ""])
TYPED_PLAN = NL.join([
    "- behaviour: cursor([1, 2, 3], 1, 1) is [2]",
    "  file: pages.py", ""])

FOUND = ('docs/api.md:4 "' + ENVELOPE_LINE + '"', 'docs/api.md:3 "'
         + PAGE_LINE + '"')
EDITED = ('rules/api-shape.md:1 "' + CURSOR_RULE.strip() + '"',
          'docs/api.md:4 "- Every list returns `{items, next}`."')


def wrong(test, spec):
    return NL.join(["WRONG TEST: " + test,
                    "why: it pins the envelope the ruling replaced",
                    "spec: " + spec, ""])


def built(*claims):
    return (NL.join(claims) + NL + "- pages.py: cursor paging" + NL
            + "- docs/api.md: cursor paging" + NL
            + "- rules/api-shape.md: cursor paging" + NL
            + "- tests/test_envelope.py: the envelope is {items, next}" + NL)


def place_of(tmp_path, monkeypatch, envelope=ENVELOPE, bridge=False,
             names_start=NAMES_START):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", GLOBS)
    files = {
        "docs/api.md": API, "docs/names.md": NAMES,
        "rules/api-shape.md": RULE, "pages.py": LISTING, "conftest.py": "",
        "tests/test_envelope.py": envelope,
        "tests/test_names.py": names_start}
    if bridge:
        files.update({JS_FILE: JS, "tests/test_bridge.py": BRIDGE,
                      "conftest.py": JS_RUNNER})
    a_place(tmp_path / "project", files)
    return tmp_path / "project"


def edits_of(place, names=False, forge=None, rewrite=CURSOR_ENVELOPE,
             js=None):
    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_cursor.py").write_text(
                CURSOR_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "pages.py").write_text(
                CURSOR_LISTING if names else
                CURSOR_LISTING.replace("sorted(items)", "list(items)"),
                encoding="utf-8")
            (place / "docs" / "api.md").write_text(CURSOR_API,
                                                   encoding="utf-8")
            (place / "rules" / "api-shape.md").write_text(
                CURSOR_RULE, encoding="utf-8")
            if rewrite:
                (place / "tests" / "test_envelope.py").write_text(
                    rewrite, encoding="utf-8")
            if names:
                (place / "tests" / "test_names.py").write_text(
                    NAMES_SORTED, encoding="utf-8")
            if js is not None:
                (place / JS_FILE).write_text(js, encoding="utf-8")
            if forge is not None:
                forge(place)
    return edits


def overridden(tmp_path, monkeypatch, plan, worker, names=False,
               rewrite=CURSOR_ENVELOPE, envelope=ENVELOPE, js=None,
               forge=None, names_start=NAMES_START):
    """an override run on two legs: the planner stops on the rule's line, the
    override goes in, and the second leg's worker changes the start tests
    that pin the old envelope. `js` puts a test file read by line and a
    python test that runs it in the start state, and is what the worker
    rewrites that file to; `names_start` is the names test the run starts
    with. -> (steps asked on the second leg, its exit code)."""
    place = place_of(tmp_path, monkeypatch, envelope, bridge=js is not None,
                     names_start=names_start)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [first_plan(NAMED)]}),
                        lambda s, n: None, "--task", NAMED)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [plan], "tester.md": [TESTER],
                               "worker.md": [worker],
                               "reviewer.md": [REVIEWED],
                               "reviewer-runs.md": [REVIEWED]}),
                        edits_of(place, names, forge=forge, rewrite=rewrite,
                                 js=js), "--resume",
                        leg.name,
                        "--answer", OVERRIDE)
    return asked, code


def record(tmp_path, name):
    return (folders(tmp_path)[-1] / name).read_text(encoding="utf-8")


def stamp_of(tmp_path):
    [ruled] = decisions.read(tmp_path / "project")
    return ruled.at.strftime(stops.STAMP) + " " + ruled.decided


def test_an_override_run_finishes_with_its_pinned_tests_under_the_ruling(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, MARKED_PLAN, built(
        wrong(ENVELOPE_TEST, EDITED[0]), wrong(FIRST_PAGE_TEST, FOUND[1])))
    gates = record(tmp_path, "gates.md")
    assert "FAIL conflict" not in gates
    assert "FAIL quote" not in gates
    assert "FAIL test-edits" not in gates
    assert code == stops.EXIT_OK, gates
    assert asked.count("worker.md") == 1
    handoff = record(tmp_path, "handoff.md")
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        assert test + " <- ruling " + stamp_of(tmp_path) in handoff, test
    assert "UNRULED" not in handoff


WHERE_PLAN = MARKED_PLAN.replace(
    "docs/api.md:4 (ruling)",
    "docs/api.md:4, ruled override at decisions.md:3")


def test_a_mark_that_names_where_its_ruling_sits_is_still_read_as_ruled(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, WHERE_PLAN, built(
        wrong(ENVELOPE_TEST, EDITED[0]), wrong(FIRST_PAGE_TEST, FOUND[1])))
    gates = record(tmp_path, "gates.md")
    assert "FAIL conflict" not in gates, gates
    assert code == stops.EXIT_OK, gates


def test_a_mark_is_read_as_ruled_only_on_the_spec_lines_it_cites(tmp_path):
    specs_at(tmp_path)
    (tmp_path / decisions.FILE).write_text(
        "# decisions" + NL + NL + "## an entry" + NL, encoding="utf-8")
    assert ruling.mark_ruled("docs/api.md:4, ruled override at decisions.md:3",
                             tmp_path, ruled=named_only)
    for mark in ("decisions.md:3 (ruling)", "the envelope (ruling)",
                 "docs/names.md:3, ruled override at decisions.md:3",
                 "docs/api.md:4 and decisions.md:3 and docs/names.md:3"):
        assert not ruling.mark_ruled(mark, tmp_path, ruled=named_only), mark

    def everything(rel, line):
        return "a ruling"

    assert not ruling.mark_ruled("decisions.md:3", tmp_path,
                                 ruled=everything), \
        "decisions.md became a line a ruling covers"


def test_a_claim_quoting_the_line_as_the_run_found_it_lets_the_test_change(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1])))
    assert code == stops.EXIT_OK, record(tmp_path, "gates.md")


def test_a_claim_quoting_the_line_as_the_ruled_edit_left_it_lets_it_change(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, EDITED[1]), wrong(FIRST_PAGE_TEST, EDITED[0])))
    assert code == stops.EXIT_OK, record(tmp_path, "gates.md")


def test_a_start_test_changed_with_no_wrong_test_line_still_refuses(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0])), names=True)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL test-edits" in gates
    assert NAMES_TEST + " (changed)" in gates
    assert "and so does a WRONG TEST line for the test" in gates


def test_a_start_test_the_ruled_edit_moved_with_no_claim_is_asked_about(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0])))
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    left = gates.split("FAIL test-edits")[-1].split(NL)[0]
    assert FIRST_PAGE_TEST + " (changed)" in left
    assert ENVELOPE_TEST not in left
    assert FIRST_PAGE_TEST + " <- ruling" not in record(tmp_path,
                                                        "handoff.md")
    assert "- " + FIRST_PAGE_TEST + " - changed; red as found; reads page of" \
        " docs/api.md:3 (ruled); rewrite red on the start product" in \
        record(tmp_path, "question.md").split(NL)


def test_a_claim_on_a_ruled_start_test_the_step_left_as_it_was_still_asks(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1])),
        rewrite=None)
    assert code == stops.EXIT_STOP
    question = record(tmp_path, "question.md")
    assert question.startswith("NEEDS: worker.md says " + ENVELOPE_TEST)
    assert FIRST_PAGE_TEST + " (" in question and " are wrong" in question


def test_code_a_file_s_tests_share_changes_when_each_of_them_is_claimed(
        tmp_path, monkeypatch):
    both = built(wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST,
                                                       FOUND[1]))
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, both,
                             rewrite=CURSOR_SHARED, envelope=SHARED)
    assert code == stops.EXIT_OK, record(tmp_path, "gates.md")


def test_code_a_file_s_tests_share_does_not_change_on_one_claim(
        tmp_path, monkeypatch):
    one = built(wrong(FIRST_PAGE_TEST, FOUND[1]))
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, one,
                             rewrite=CURSOR_SHARED_KEPT, envelope=SHARED_KEPT)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "tests/test_envelope.py (the code its tests share changed)" in gates


def test_code_tests_share_does_not_change_on_one_claim_when_the_rest_moved(
        tmp_path, monkeypatch):
    one = built(wrong(FIRST_PAGE_TEST, FOUND[1]))
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, one,
                             rewrite=CURSOR_SHARED, envelope=SHARED)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert "tests/test_envelope.py (the code its tests share changed)" in \
        gates.split("FAIL test-edits")[-1].split(NL)[0]


def test_a_start_test_on_a_line_no_ruling_covers_still_refuses(
        tmp_path, monkeypatch):
    names = wrong(NAMES_TEST, 'docs/names.md:3 "' + NAMES_LINE + '"')
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]),
        names), names=True)
    assert code != stops.EXIT_OK
    assert "worker.md says " + NAMES_TEST + " is wrong" in record(
        tmp_path, "question.md")


LOOSENED = NAMES_START.replace("assert names(['b', 'a']) == ['b', 'a']",
                               "assert names(['b', 'a'])")


def loosen(place):
    (place / "tests" / "test_names.py").write_text(LOOSENED, encoding="utf-8")


def test_an_unrelated_start_test_loosened_under_a_ruled_quote_is_refused(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]),
        wrong(NAMES_TEST, FOUND[0])), forge=loosen)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert "FAIL test-edits" in gates
    assert NAMES_TEST + " (changed)" in gates
    assert "- " + NAMES_TEST + " - changed" in record(tmp_path,
                                                       "question.md")


def test_an_unrelated_behaviour_broken_with_its_test_rewritten_is_refused(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]),
        wrong(NAMES_TEST, FOUND[0])), names=True)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert NAMES_TEST + " (changed)" in gates
    assert NAMES_TEST + " <- ruling" not in record(tmp_path, "handoff.md")


def test_the_handoff_shows_the_line_each_claim_was_made_on(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1])))
    assert code == stops.EXIT_OK, record(tmp_path, "gates.md")
    handoff = record(tmp_path, "handoff.md")
    stamp = stamp_of(tmp_path)
    assert ENVELOPE_TEST + " <- ruling " + stamp \
        + " (claimed on docs/api.md:4)" in handoff, handoff
    assert FIRST_PAGE_TEST + " <- ruling " + stamp \
        + " (claimed on docs/api.md:3)" in handoff, handoff


MAGIC = 'rules/api-shape.md:1 "Every list pages by magic and returns what' \
    ' it likes."'


def test_a_quote_of_neither_the_found_line_nor_the_ruled_edit_still_fails(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(COUNT_TEST, MAGIC), wrong(ENVELOPE_TEST, FOUND[0]),
        wrong(FIRST_PAGE_TEST, FOUND[1])), rewrite=CURSOR_ENVELOPE_COUNT,
        envelope=ENVELOPE_COUNT)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL quote" in gates
    assert "FAIL test-edits" in gates
    assert COUNT_TEST + " (changed)" in gates.split("FAIL test-edits")[-1]


def test_a_misquoted_claim_on_a_test_the_ruled_edit_moved_still_fails_quote(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, MAGIC), wrong(FIRST_PAGE_TEST, FOUND[1])))
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL quote" in gates
    assert ENVELOPE_TEST + " (changed)" in gates.split(
        "FAIL test-edits")[-1].split(NL)[0]
    assert ENVELOPE_TEST + " (ruling " not in gates


def test_an_entry_a_step_wrote_in_decisions_md_rules_nothing(
        tmp_path, monkeypatch):
    place = place_of(tmp_path, monkeypatch)

    def forge(where):
        decisions.record(where, ruling.decided("planner.md", OVERRIDE),
                         ruling.why("planner.md", "build-1", "NEEDS: which"
                                    " holds?", OVERRIDE, "someone",
                                    kind=ruling.OVERRIDE))

    worker = built(wrong(ENVELOPE_TEST, FOUND[0]),
                   wrong(FIRST_PAGE_TEST, FOUND[1]))
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [TYPED_PLAN],
                               "tester.md": [TESTER], "worker.md": [worker],
                               "reviewer.md": [REVIEWED],
                               "reviewer-runs.md": [REVIEWED]}),
                        edits_of(place, forge=forge), "--task", NAMED)
    assert code != stops.EXIT_OK
    assert end(tmp_path).cause != "ok"


def laid_out(monkeypatch):
    """-> the `as_left` sets the start-tests replay is handed, as the run
    calls it."""
    seen = []
    real = starttests.replay

    def spy(*args, **kw):
        seen.append(set(kw.get("as_left", ())))
        return real(*args, **kw)

    monkeypatch.setattr(starttests, "replay", spy)
    return seen


JS_CLAIMED = built(wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST,
                                                         FOUND[1]),
                   wrong(JS_TEST, EDITED[1]))


def test_a_bridge_over_a_ruled_test_file_is_green_in_the_replay(
        tmp_path, monkeypatch):
    seen = laid_out(monkeypatch)
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, JS_CLAIMED,
                             js=CURSOR_JS)
    gates = record(tmp_path, "gates.md")
    assert "was green when the run started and is red now" not in gates
    assert code == stops.EXIT_OK, gates
    edits = [l for l in gates.split(NL) if "PASS test-edits" in l]
    assert edits and all(JS_FILE + " (ruling " in l for l in edits), edits
    assert "PASS start-tests" in gates
    assert asked.count("worker.md") == 1
    assert {JS_FILE, "tests/test_envelope.py"} in seen
    handoff = record(tmp_path, "handoff.md")
    assert JS_FILE + " <- ruling " + stamp_of(tmp_path) in handoff
    assert "UNRULED" not in handoff


def test_a_claimed_test_file_whose_layout_turns_no_python_test_asks(
        tmp_path, monkeypatch):
    # the bridge stays red with the file as left, so nothing ties the file
    # to the ruled edit
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, JS_CLAIMED,
                             js="expect items" + NL + "expect page" + NL)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    left = gates.split("FAIL test-edits")[-1].split(NL)[0]
    assert JS_FILE in left
    assert ENVELOPE_TEST not in left and FIRST_PAGE_TEST not in left


def test_a_claimed_test_file_emptied_ties_nothing_by_the_turn(tmp_path,
                                                              monkeypatch):
    # an empty file turns the bridge green on any product: the start product
    # passes it too, so the file as left pins nothing
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, JS_CLAIMED,
                             js="")
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert JS_FILE in gates.split("FAIL test-edits")[-1].split(NL)[0]
    assert JS_FILE + " <- ruling" not in record(tmp_path, "handoff.md")


OTHER_JS = "tests/other.test.js"


def test_a_claimed_test_file_the_turn_does_not_need_ties_nothing(
        tmp_path, monkeypatch):
    # a second file read by line, green as found and now, emptied and claimed
    # beside the honest one: the turn goes green without it
    real = a_place

    def with_other(where, files):
        if JS_FILE in files:
            files = dict(files, **{OTHER_JS: "expect items" + NL})
        return real(where, files)
    monkeypatch.setattr(sys.modules[__name__], "a_place", with_other)

    def empty(place):
        (place / OTHER_JS).write_text("", encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]),
        wrong(JS_TEST, EDITED[1]),
        wrong(OTHER_JS + "::expects the envelope", FOUND[0])),
        js=CURSOR_JS, forge=empty)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    left = gates.split("FAIL test-edits")[-1].split(NL)[0]
    assert OTHER_JS in left and JS_FILE + " " not in left, left
    assert OTHER_JS + " <- ruling" not in record(tmp_path, "handoff.md")


# a python test over a folder of js tests: every file read by line is read,
# so a second claimed file can be needed for the turn
FOLDER_BRIDGE = NL.join([
    "from pathlib import Path", "", "from pages import listing, names", "", "",
    "def test_the_js_suite_passes():",
    "    for js in sorted(Path(__file__).parent.glob('*.test.js')):",
    "        for line in js.read_text(encoding='utf-8').splitlines():",
    "            w = line.split()",
    "            if w[0] == 'order':",
    "                assert names(['b', 'a']) == ['b', 'a'], line",
    "            else:",
    "                assert w[1] in listing([1]), line", ""])
FOLDER_RUNNER = JS_RUNNER.replace(
    "        from pages import listing",
    "        from pages import listing, names").replace(
    "            assert line.split()[1] in listing([1]), line",
    "            w = line.split()" + NL
    + "            if w[0] == 'order':" + NL
    + "                assert names(['b', 'a']) == ['b', 'a'], line" + NL
    + "            else:" + NL
    + "                assert w[1] in listing([1]), line")
ORDER_JS = "order names" + NL
NO_NAMES = "def test_nothing():" + NL + "    assert True" + NL


def a_folder(monkeypatch, other):
    real = a_place

    def with_other(where, files):
        if JS_FILE in files:
            files = dict(files, **{OTHER_JS: other,
                                   "tests/test_bridge.py": FOLDER_BRIDGE,
                                   "conftest.py": FOLDER_RUNNER})
        return real(where, files)
    monkeypatch.setattr(sys.modules[__name__], "a_place", with_other)


FOLDER_CLAIMED = built(
    wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]),
    wrong(JS_TEST, EDITED[1]),
    wrong(OTHER_JS + "::expects the envelope", FOUND[0]))


def folder_run(tmp_path, monkeypatch, other, left, product=None):
    a_folder(monkeypatch, other)

    def forge(place):
        if product is not None:
            (place / "pages.py").write_text(product, encoding="utf-8")
        (place / OTHER_JS).write_text(left, encoding="utf-8")
    return overridden(tmp_path, monkeypatch, TYPED_PLAN, FOLDER_CLAIMED,
                      js=CURSOR_JS, forge=forge,
                      names_start=NO_NAMES if product else NAMES_START)


def folder_refused(tmp_path, code):
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    left = gates.split("FAIL test-edits")[-1].split(NL)[0]
    assert OTHER_JS in left and JS_FILE + " " not in left, left
    assert OTHER_JS + " <- ruling" not in record(tmp_path, "handoff.md")


def test_a_second_claimed_file_the_turn_needs_ties_when_rewritten_honestly(
        tmp_path, monkeypatch):
    _, code = folder_run(tmp_path, monkeypatch, "expect total" + NL,
                         "expect next" + NL)
    assert code == stops.EXIT_OK, record(tmp_path, "gates.md")
    assert OTHER_JS + " <- ruling" in record(tmp_path, "handoff.md")


def test_an_emptied_file_the_turn_needs_ties_nothing_beside_an_honest_one(
        tmp_path, monkeypatch):
    # the honest file as left is red on the start state; the emptied one
    # alone is green there
    _, code = folder_run(tmp_path, monkeypatch, "expect total" + NL, "")
    folder_refused(tmp_path, code)


def test_an_unruled_broken_file_emptied_beside_an_honest_one_ties_nothing(
        tmp_path, monkeypatch):
    # the step also sorts names, which no ruling covers, and empties the
    # order test it broke
    _, code = folder_run(tmp_path, monkeypatch, ORDER_JS, "",
                         product=CURSOR_LISTING)
    folder_refused(tmp_path, code)


def test_a_bridge_over_an_unruled_test_file_still_parks(
        tmp_path, monkeypatch):
    seen = laid_out(monkeypatch)
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1])),
        js=CURSOR_JS)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL test-edits" in gates
    assert JS_FILE in gates
    assert "PASS start-tests" not in gates
    assert all(JS_FILE not in s for s in seen)


def test_a_bridge_over_a_half_ruled_test_file_still_parks(
        tmp_path, monkeypatch):
    seen = laid_out(monkeypatch)
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(FIRST_PAGE_TEST, FOUND[1])), rewrite=CURSOR_SHARED_KEPT,
        envelope=SHARED_KEPT)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "PASS start-tests" not in gates
    assert all(not s for s in seen)


def test_a_test_file_claimed_whole_is_laid_out_as_left(tmp_path,
                                                        monkeypatch):
    seen = laid_out(monkeypatch)
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1])),
        rewrite=CURSOR_SHARED, envelope=SHARED)
    gates = record(tmp_path, "gates.md")
    assert code == stops.EXIT_OK, gates
    assert "PASS start-tests" in gates
    assert {"tests/test_envelope.py"} in seen


def as_found(path):
    return path.read_text(encoding="utf-8").replace(chr(13), "")


def test_a_ruled_test_file_is_laid_out_as_the_run_left_it(
        tmp_path, monkeypatch):
    place = place_of(tmp_path, monkeypatch, bridge=True)
    start = snapshot.take(place)
    (place / JS_FILE).write_text(CURSOR_JS, encoding="utf-8")
    (place / "tests" / "test_envelope.py").write_text(CURSOR_ENVELOPE,
                                                      encoding="utf-8")
    fixed = CURSOR_LISTING.replace("sorted(items)", "list(items)")
    (place / "pages.py").write_text(fixed, encoding="utf-8")
    with worktree.temporary(start.root, start.start) as tree:
        starttests.lay_out_now(start, tree, as_left={JS_FILE})
        there = start.place_in(tree)
        assert as_found(there / JS_FILE) == CURSOR_JS
        assert as_found(there / "tests" / "test_envelope.py") == ENVELOPE
        assert as_found(there / "pages.py") == fixed
    both = {JS_FILE, "tests/test_envelope.py"}
    found = starttests.replay(start)
    assert BRIDGE_TEST in [t for t, _ in found.red]
    found = starttests.replay(start, as_left=both)
    assert found.red == [], found.result.detail
    (place / "pages.py").write_text(CURSOR_LISTING, encoding="utf-8")
    found = starttests.replay(start, as_left=both)
    assert [t for t, _ in found.red] == [NAMES_TEST]


# the pieces

def entry(decided, why):
    return decisions.Decision(decided, why, datetime.datetime(2026, 1, 1))


def specs_at(tmp_path, api=API, rule=RULE):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "rules").mkdir(exist_ok=True)
    (tmp_path / "docs" / "api.md").write_text(api, encoding="utf-8")
    (tmp_path / "docs" / "names.md").write_text(NAMES, encoding="utf-8")
    (tmp_path / "rules" / "api-shape.md").write_text(rule, encoding="utf-8")


def named_only(rel, line):
    return "a ruling" if rel in ("docs/api.md", "rules/api-shape.md") \
        else None


def test_a_quote_is_held_to_the_found_line_or_the_ruled_edit(tmp_path):
    specs_at(tmp_path)
    found = 'docs/api.md:4 "' + ENVELOPE_LINE + '"'
    assert ruling.ruled_quote(found, tmp_path, ruled=named_only) == "a ruling"
    assert ruling.ruled_quote(found, tmp_path) is None
    names = 'docs/names.md:3 "' + NAMES_LINE + '"'
    assert ruling.ruled_quote(names, tmp_path, ruled=named_only) is None
    for spec in ('rules/api-shape.md:1 "Every list pages by magic."',
                 'docs/api.md:9 "' + ENVELOPE_LINE + '"'):
        assert ruling.ruled_quote(spec, tmp_path, ruled=named_only) is None


def by(answer, kind):
    d = entry(ruling.decided("planner.md", answer),
              ruling.why("planner.md", "build-1", "NEEDS: which holds?",
                         answer, "someone", kind=kind))

    def ruled(rel, line):
        return ruling.spec_line_ruled([d], line, {"build-1": (RULE_LINE,)},
                                      rel, NAMED, ("docs/api.md",
                                                   "rules/api-shape.md"))
    return ruled


def edited_place(tmp_path, monkeypatch):
    """-> (the place with the run's ruled edit made, its start)."""
    place = place_of(tmp_path, monkeypatch)
    start = snapshot.take(place)
    (place / "docs" / "api.md").write_text(CURSOR_API, encoding="utf-8")
    (place / "rules" / "api-shape.md").write_text(CURSOR_RULE,
                                                  encoding="utf-8")
    return place, start


def tied_by(seen):
    """-> a `tied` that records (test, lines) and ties every test."""
    def tied(test, lines, said=()):
        seen.append((test, lines))
        return True
    return tied


def test_a_request_answer_covers_no_claim(tmp_path, monkeypatch):
    place, start = edited_place(tmp_path, monkeypatch)
    said = [wrong(ENVELOPE_TEST, FOUND[0]) + wrong(
        FIRST_PAGE_TEST, 'rules/api-shape.md:1 "' + RULE_LINE + '"')]
    over = by(OVERRIDE, ruling.OVERRIDE)
    kept = by("request: keep the envelope, and update docs/api.md",
              ruling.REQUEST)
    every = tied_by([])
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        assert wrongtest.ruled_claim(said, test, place, start, over, every)
        assert wrongtest.ruled_claim(said, test, place, start, kept,
                                     every) is None
        assert wrongtest.ruled_claim([built()], test, place, start, over,
                                     every) is None
    assert wrongtest.ruled_claim(said, NAMES_TEST, place, start, over,
                                 every) is None


def test_a_claim_hands_the_tie_the_quoted_lines_as_the_run_found_them(
        tmp_path, monkeypatch):
    place, start = edited_place(tmp_path, monkeypatch)
    over = by(OVERRIDE, ruling.OVERRIDE)
    seen = []
    for spec in (FOUND[0], EDITED[1]):
        d, cite = wrongtest.ruled_claim([wrong(ENVELOPE_TEST, spec)],
                                        ENVELOPE_TEST, place, start, over,
                                        tied_by(seen))
        assert d is not None and cite == "docs/api.md:4"
    assert seen == [(ENVELOPE_TEST, [ENVELOPE_LINE])] * 2
    said = [wrong(ENVELOPE_TEST, FOUND[0])]
    assert wrongtest.ruled_claim(said, ENVELOPE_TEST, place, start,
                                 over) is None, "no tie, no cover"
    assert wrongtest.ruled_claim(said, ENVELOPE_TEST, place, start, over,
                                 lambda t, l, s: False) is None
    (place / "docs" / "api.md").write_text(
        "# api" + NL + NL + "- Every list has a cursor." + NL + PAGE_LINE + NL
        + ENVELOPE_LINE + NL, encoding="utf-8")
    added = 'docs/api.md:3 "- Every list has a cursor."'
    assert ruling.ruled_quote(added, place, start, named_only)
    seen[:] = []
    assert wrongtest.ruled_claim([wrong(ENVELOPE_TEST, added)], ENVELOPE_TEST,
                                 place, start, named_only,
                                 tied_by(seen)) is None
    assert seen == [], "a quote of a line the run added reached the tie"


def only_the_envelope(rel, line):
    return "the envelope ruling" if line.rstrip() == ENVELOPE_LINE else None


def test_a_range_cite_is_read_at_the_line_its_quote_stands_on(tmp_path,
                                                              monkeypatch):
    place, start = edited_place(tmp_path, monkeypatch)
    ranged = 'docs/api.md:3-4 "' + ENVELOPE_LINE + '"'
    assert ruling.ruled_quote(ranged, place, start, only_the_envelope) == \
        "the envelope ruling", "a range cite read a line its quote is not on"
    assert ruling.quoted_as_found(ranged, place, start) == [ENVELOPE_LINE]
    edited = 'docs/api.md:3-4 "- Every list returns `{items, next}`."'
    assert ruling.quoted_as_found(edited, place, start) == [ENVELOPE_LINE]


def test_a_range_cite_whose_quote_stands_twice_is_still_read_whole(tmp_path):
    twice = "# api" + NL + NL + ENVELOPE_LINE + NL + PAGE_LINE + NL \
        + ENVELOPE_LINE + NL
    specs_at(tmp_path, api=twice)
    ranged = 'docs/api.md:3-5 "' + ENVELOPE_LINE + '"'
    assert ruling.ruled_quote(ranged, tmp_path, ruled=only_the_envelope) \
        is None
    assert ruling.ruled_quote(ranged, tmp_path, ruled=named_only) == \
        "a ruling"
    wrong_quote = 'docs/api.md:3-4 "- Every list returns nothing."'
    assert ruling.ruled_quote(wrong_quote, tmp_path, ruled=named_only) is None
    assert ruling.quoted_as_found(wrong_quote, tmp_path) is None


def test_a_test_reads_the_shared_code_it_runs_against():
    read = testedits.read_by(SHARED, "tests/test_envelope.py", ENVELOPE_TEST)
    assert 'KEYS = {"items", "page", "total"}' in read
    assert {"items", "page", "total", "keys", "listing"} <= \
        ruling.code_words(read)
    read = testedits.read_by(SHARED, "tests/test_envelope.py",
                             FIRST_PAGE_TEST)
    assert "KEYS" not in read


HELPED = NL.join([
    "import subprocess", "", "SCRIPT = 'page'", "", "",
    "def run():", "    return SCRIPT", "", "",
    "def test_reads_through_a_helper():", "    assert run() == 'page'", "",
    "", "def test_reads_it_itself():", "    assert SCRIPT", "", "",
    "def test_reads_neither():", "    assert subprocess", ""])


def sharing(now, was=HELPED):
    return sorted(t.rsplit("::", 1)[-1]
                  for t in testedits.sharing("t.py", was, now))


def test_code_tests_share_is_held_to_the_tests_that_run_against_it():
    everyone = ["test_reads_it_itself", "test_reads_neither",
                "test_reads_through_a_helper"]
    assert sharing(HELPED.replace("'page'", "'next'", 1)) == [
        "test_reads_it_itself", "test_reads_through_a_helper"]
    assert sharing(HELPED.replace("    return SCRIPT", "    return 1")) == [
        "test_reads_through_a_helper"]
    assert sharing(HELPED.replace("import subprocess", "import subprocess"
                                  + NL + "subprocess.run(['x'])")) == everyone
    assert sharing(HELPED.replace("def run():", "@pytest.fixture(autouse"
                                  "=True)" + NL + "def run():")) == everyone
    assert sharing(HELPED + NL + "pytestmark = []" + NL) == everyone
    classed = NL.join(["class TestIt:", "    x = 1", "",
                       "    def test_a(self):", "        assert self.x", ""])
    assert sharing(classed.replace("x = 1", "x = 2"), classed) == ["test_a"]


QTY_LINE = "- `qty`: integer, in the base unit of the item's unit"
UNIT_LINE = "- `unit`: one of g, kg"
ITEMS_DOC = "# items" + NL + NL + QTY_LINE + NL + UNIT_LINE + NL
NESTED_DOC = ("# items" + NL + NL
              + "- `locations`: a list of `{location_id, qty}`, one entry per"
              " location" + NL + UNIT_LINE + NL
              + "- in each entry, `qty` is an integer in the base unit of the"
              " item's unit" + NL)
ITEM = 'def item():' + NL + '    return {"qty": 2000, "unit": "g"}' + NL
NESTED_ITEM = ('def item():' + NL + '    return {"locations": [{"location_id":'
               ' None, "qty": 2000}], "unit": "g"}' + NL)
QTY_TEST = "tests/test_items.py::test_an_item_reads_its_qty"
UNIT_TEST = "tests/test_items.py::test_an_item_has_a_unit"
ITEM_TESTS = ("from items import item" + NL + NL + NL
              + "def test_an_item_reads_its_qty():" + NL
              + '    assert item()["qty"] == 2000' + NL + NL + NL
              + "def test_an_item_has_a_unit():" + NL
              + '    assert item()["unit"] == "g"' + NL)
NESTED_TESTS = ITEM_TESTS.replace('item()["qty"]',
                                  'item()["locations"][0]["qty"]')
LOOSE_UNIT = NESTED_TESTS.replace('assert item()["unit"] == "g"',
                                  'assert item()["unit"]')
SHAPE = ("This changes the item shape: an item reads `locations`, a list of"
         " `{location_id, qty}`. Update docs/items.md to say so.")
SHAPE_OVERRIDE = ("override: an item reads locations, a list of {location_id,"
                  " qty}; the items doc changes to say so.")
SHAPE_TEST = ("def test_an_item_lists_its_locations():" + NL
              + "    from items import item" + NL + NL
              + '    assert item()["locations"][0]["qty"] == 2000' + NL)
SHAPE_TESTER = ("FAILS: KeyError: 'locations'" + NL
                + "TEST: tests/test_locations.py" + NL)
QTY_FOUND = 'docs/items.md:3 "' + QTY_LINE + '"'


def nested(tmp_path, monkeypatch, worker, tests=NESTED_TESTS):
    """an override run on two legs that moves `qty` into a nested shape: the
    planner stops on the qty line, the override goes in, and the second
    leg's worker rewrites the doc and the code, and the start test file to
    `tests`. -> (steps asked on the second leg, its exit code)."""
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", GLOBS)
    place = tmp_path / "project"
    a_place(place, {"docs/items.md": ITEMS_DOC, "items.py": ITEM,
                    "conftest.py": "", "tests/test_items.py": ITEM_TESTS})

    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_locations.py").write_text(
                SHAPE_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "items.py").write_text(NESTED_ITEM, encoding="utf-8")
            (place / "docs" / "items.md").write_text(NESTED_DOC,
                                                     encoding="utf-8")
            (place / "tests" / "test_items.py").write_text(
                tests, encoding="utf-8")

    stop = ('CONFLICT: ' + QTY_FOUND + NL + "request: " + SHAPE + NL)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [stop]}), lambda s, n: None,
                        "--task", SHAPE)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    plan = NL.join(["- behaviour: item() lists its locations",
                    "  file: items.py", ""])
    built_it = (worker + NL + "- items.py: locations" + NL
                + "- docs/items.md: locations" + NL)
    return go(tmp_path, monkeypatch, "build-feature",
              plain({"planner.md": [plan], "tester.md": [SHAPE_TESTER],
                     "worker.md": [built_it], "reviewer.md": [REVIEWED],
                     "reviewer-runs.md": [REVIEWED]}),
              edits, "--resume", leg.name, "--answer", SHAPE_OVERRIDE)[::2]


def test_a_field_moved_into_a_nested_shape_lets_its_start_test_follow(
        tmp_path, monkeypatch):
    _, code = nested(tmp_path, monkeypatch, wrong(QTY_TEST, QTY_FOUND))
    gates = record(tmp_path, "gates.md")
    assert "FAIL test-edits" not in gates
    assert code == stops.EXIT_OK, gates
    assert QTY_TEST + " <- ruling " + stamp_of(tmp_path) \
        + " (claimed on docs/items.md:3)" in record(tmp_path, "handoff.md")


def test_a_start_test_loosened_on_a_word_the_moved_line_shares_is_refused(
        tmp_path, monkeypatch):
    _, code = nested(tmp_path, monkeypatch, wrong(QTY_TEST, QTY_FOUND)
                     + wrong(UNIT_TEST, QTY_FOUND), tests=LOOSE_UNIT)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert "FAIL test-edits" in gates
    assert UNIT_TEST + " (changed)" in gates
    assert QTY_TEST + " (changed)" not in gates


@pytest.mark.parametrize("left", [
    'assert item()["locations"] and item()["unit"]',
    'assert item()["unit"] == "g"  # per entry, in locations' + NL
    + '    assert item()["unit"]'])
def test_a_start_test_loosened_with_a_word_the_move_wrote_is_refused(
        tmp_path, monkeypatch, left):
    loose = NESTED_TESTS.replace('assert item()["unit"] == "g"', left)
    _, code = nested(tmp_path, monkeypatch, wrong(QTY_TEST, QTY_FOUND)
                     + wrong(UNIT_TEST, QTY_FOUND), tests=loose)
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert "FAIL test-edits" in gates
    assert UNIT_TEST + " (changed)" in gates
    assert QTY_TEST + " (changed)" not in gates


def nested_place(tmp_path, monkeypatch):
    """-> (the place with the nested shape written, its start)."""
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", GLOBS)
    place = tmp_path / "project"
    a_place(place, {"docs/items.md": ITEMS_DOC, "items.py": ITEM,
                    "conftest.py": "", "tests/test_items.py": ITEM_TESTS})
    start = snapshot.take(place)
    (place / "docs" / "items.md").write_text(NESTED_DOC, encoding="utf-8")
    return place, start


def any_line(rel, line):
    return "a ruling" if rel == "docs/items.md" else None


def test_a_claim_on_a_moved_field_hands_the_tie_the_line_as_found(
        tmp_path, monkeypatch):
    place, start = nested_place(tmp_path, monkeypatch)
    seen = []
    d, cite = wrongtest.ruled_claim([wrong(QTY_TEST, QTY_FOUND)], QTY_TEST,
                                    place, start, any_line, tied_by(seen))
    assert d == "a ruling" and cite == "docs/items.md:3"
    assert seen == [(QTY_TEST, [QTY_LINE])]
    assert wrongtest.ruled_claim([wrong(QTY_TEST, QTY_FOUND)], QTY_TEST,
                                 place, None, any_line, tied_by([])) is None


def test_a_found_test_reads_the_moved_field_by_its_string_key(
        tmp_path, monkeypatch):
    place, start = nested_place(tmp_path, monkeypatch)
    from agentweft.runner.run import Run
    run = Run.__new__(Run)
    run.workdir, run.start = place, start
    line = ruling.words(QTY_LINE)
    assert run.found_words(QTY_TEST) & line == {"qty", "item"}
    assert run.found_words(UNIT_TEST) & line == {"unit", "item"}, \
        "words alone tie the unit test too: the effects are what refuse it"
    run.order = None
    assert not run.tied(QTY_TEST, [QTY_LINE]), "no replay, no tie"
    assert not run.tied("tests/items.test.js::qty", [QTY_LINE])


def test_a_claim_names_a_test_by_its_id_or_a_file_read_whole():
    assert wrongtest.same_test(ENVELOPE_TEST, ENVELOPE_TEST)
    assert wrongtest.same_test("./" + ENVELOPE_TEST.replace("/", "\\"),
                               ENVELOPE_TEST)
    assert wrongtest.same_test(ENVELOPE_TEST + "[1]", ENVELOPE_TEST)
    assert not wrongtest.same_test(FIRST_PAGE_TEST, ENVELOPE_TEST)
    assert not wrongtest.same_test("tests/test_envelope.py", ENVELOPE_TEST)
    assert wrongtest.same_test("frontend/tests/pager.test.js::first page",
                               "frontend/tests/pager.test.js")
    assert not wrongtest.same_test("frontend/tests/other.test.js::x",
                                   "frontend/tests/pager.test.js")
