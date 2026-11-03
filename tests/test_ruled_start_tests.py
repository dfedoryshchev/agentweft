"""a start test that pins a spec line an override rules may change with it.

once an `override:` answer lets spec lines change, a test the run started
with that pins exactly those lines is wrong with them. a step may change it
when its answer names it on a WRONG TEST line whose `spec:` line quotes a
line the ruling covers, as the run found it or as the run's own ruled edit
left it, and the handoff lists each such test under that ruling. a plan that
marks a ruled line `spec: contradicts` needs no new CONFLICT line for it.
everything else still holds: a test on a line no ruling covers, a test
changed with no WRONG TEST line, code a file's tests share with a test that
reads it unnamed, a quote of neither the found line nor the ruled edit, a
`request:` answer and an entry a step wrote in decisions.md itself let
nothing change, and a claim on a start test the step left as it was still
asks.
"""
import datetime
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import testedits
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
NAMES_START = ("from pages import names" + NL + NL + NL
               + "def test_names_keep_their_order():" + NL
               + "    assert names(['b', 'a']) == ['b', 'a']" + NL)
NAMES_SORTED = NAMES_START.replace("== ['b', 'a']", "== ['a', 'b']")

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


def place_of(tmp_path, monkeypatch, envelope=ENVELOPE):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", GLOBS)
    a_place(tmp_path / "project", {
        "docs/api.md": API, "docs/names.md": NAMES,
        "rules/api-shape.md": RULE, "pages.py": LISTING, "conftest.py": "",
        "tests/test_envelope.py": envelope,
        "tests/test_names.py": NAMES_START})
    return tmp_path / "project"


def edits_of(place, names=False, forge=None, rewrite=CURSOR_ENVELOPE):
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
            if forge is not None:
                forge(place)
    return edits


def overridden(tmp_path, monkeypatch, plan, worker, names=False,
               rewrite=CURSOR_ENVELOPE, envelope=ENVELOPE):
    """an override run on two legs: the planner stops on the rule's line, the
    override goes in, and the second leg's worker changes the start tests
    that pin the old envelope. -> (steps asked on the second leg, its exit
    code)."""
    place = place_of(tmp_path, monkeypatch, envelope)
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
                        edits_of(place, names, rewrite=rewrite), "--resume",
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
        wrong(ENVELOPE_TEST, FOUND[0])))
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL test-edits" in gates
    assert FIRST_PAGE_TEST + " (changed)" in gates
    assert "and so does a WRONG TEST line for the test" in gates


def test_a_claim_on_a_ruled_start_test_the_step_left_as_it_was_still_asks(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1])),
        rewrite=None)
    assert code == stops.EXIT_STOP
    assert "worker.md says " + ENVELOPE_TEST + " is wrong" in record(
        tmp_path, "question.md")


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
                             rewrite=CURSOR_SHARED, envelope=SHARED)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "tests/test_envelope.py (the code its tests share changed)" in gates


def test_a_start_test_on_a_line_no_ruling_covers_still_refuses(
        tmp_path, monkeypatch):
    names = wrong(NAMES_TEST, 'docs/names.md:3 "' + NAMES_LINE + '"')
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]),
        names), names=True)
    assert code != stops.EXIT_OK
    assert "worker.md says " + NAMES_TEST + " is wrong" in record(
        tmp_path, "question.md")


def test_a_quote_of_neither_the_found_line_nor_the_ruled_edit_still_fails(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        wrong(ENVELOPE_TEST, 'rules/api-shape.md:1 "Every list pages by'
              ' magic and returns what it likes."'),
        wrong(FIRST_PAGE_TEST, FOUND[1])))
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL quote" in gates
    assert "FAIL test-edits" in gates


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


def test_a_request_answer_covers_no_claim(tmp_path):
    specs_at(tmp_path)
    said = [wrong(ENVELOPE_TEST, FOUND[0]) + wrong(
        FIRST_PAGE_TEST, 'rules/api-shape.md:1 "' + RULE_LINE + '"')]
    over = by(OVERRIDE, ruling.OVERRIDE)
    kept = by("request: keep the envelope, and update docs/api.md",
              ruling.REQUEST)
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        assert wrongtest.ruled_claim(said, test, tmp_path, ruled=over)
        assert wrongtest.ruled_claim(said, test, tmp_path, ruled=kept) is None
        assert wrongtest.ruled_claim([built()], test, tmp_path,
                                     ruled=over) is None
    assert wrongtest.ruled_claim(said, NAMES_TEST, tmp_path,
                                 ruled=over) is None


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
