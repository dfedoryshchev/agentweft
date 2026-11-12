"""a WRONG TEST claim covers a start test only by what the run found and what
the tests do, never by what the step wrote into the spec.

under an override, a claim on a start test the step changed covers it when
the test as the run found it, green at the start, is red against the product
now; the test as the step left it is red against the product as the run
found it; and the test's code as the run found it (its names and strings,
and those of the code it reads at the top of its file) shares a word with
the quoted spec lines as the run found them. a comment, a docstring and an
assert message are no code; a builtin the code calls ties nothing; how the
step words its rewrite of the spec decides nothing.

a test still green as found, a rewrite that asserts nothing the found product
fails, a test whose found code shares no word with the line, and a claim
quoting a ruled line the run's edit left as it was are asked about. two
floors `docs/gates.md` states are pinned as the product holds them today: a
rewrite that reads a name or key the run added fails the found product
without pinning anything and is covered, and a module whose widened import
no longer loads on the found product asks about each changed test in it. a
quoted
line the run left as it was, moved down by a line the run
added above it, is read as the run found it.
"""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot, testedits
from agentweft.runner import ruling, stops

from test_ruled_start_tests import (CURSOR_ENVELOPE, CURSOR_LISTING,
                                    ENVELOPE_TEST,
                                    FIRST_PAGE_TEST, FOUND, NAMES_START,
                                    NAMES_TEST, TYPED_PLAN, built, overridden,
                                    record)

NL = chr(10)
ITEMS_TEST = "tests/test_names.py::test_items_is_a_list"
ITEMS_START = ("from pages import listing" + NL + NL + NL
               + "def test_items_is_a_list():" + NL
               + '    assert isinstance(listing([1])["items"], list)' + NL)
ITEMS_LOOSE = ITEMS_START.replace(
    'assert isinstance(listing([1])["items"], list)', "assert listing([1])")
ENTRIES_API = ("# api" + NL + NL + "- Every call takes `?after=&limit=`." + NL
               + "- Every call returns `{entries, next}`." + NL)


def wrong(test, spec):
    return NL.join(["WRONG TEST: " + test,
                    "why: it pins the envelope the ruling replaced",
                    "spec: " + spec, ""])


PAGED = (wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST, FOUND[1]))


def refused(tmp_path, code, test):
    gates = record(tmp_path, "gates.md")
    assert code != stops.EXIT_OK, gates
    assert "FAIL test-edits" in gates, gates
    assert test + " (changed)" in gates.split("FAIL test-edits")[-1] \
        .split(NL)[0]
    assert test + " <- ruling" not in record(tmp_path, "handoff.md")


def test_a_claim_on_a_test_still_green_as_found_covers_nothing(
        tmp_path, monkeypatch):
    # the rewrite of both ruled lines drops `items` from the file; the test
    # pins nothing the ruling moved, so the product leaves it green
    def loosen(place):
        (place / "docs" / "api.md").write_text(ENTRIES_API, encoding="utf-8")
        (place / "tests" / "test_names.py").write_text(ITEMS_LOOSE,
                                                       encoding="utf-8")
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        *PAGED, wrong(ITEMS_TEST, FOUND[0])), forge=loosen,
        names_start=ITEMS_START)
    refused(tmp_path, code, ITEMS_TEST)


def test_a_claim_on_a_test_still_green_as_found_with_the_shipped_wording(
        tmp_path, monkeypatch):
    def loosen(place):
        (place / "tests" / "test_names.py").write_text(ITEMS_LOOSE,
                                                       encoding="utf-8")
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        *PAGED, wrong(ITEMS_TEST, FOUND[0])), forge=loosen,
        names_start=ITEMS_START)
    refused(tmp_path, code, ITEMS_TEST)


COMMENTED = NAMES_START.replace(
    "    assert", "    # the page order is the insertion order" + NL
    + "    assert")
MESSAGED = NAMES_START.replace("== ['b', 'a']" + NL,
                               "== ['b', 'a'], \"page order kept\"" + NL)


def test_a_line_s_word_in_a_comment_of_the_test_does_not_tie_a_claim(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        *PAGED, wrong(NAMES_TEST, FOUND[0])), names=True,
        names_start=COMMENTED)
    refused(tmp_path, code, NAMES_TEST)


def test_a_line_s_word_in_an_assert_message_does_not_tie_a_claim(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        *PAGED, wrong(NAMES_TEST, FOUND[0])), names=True,
        names_start=MESSAGED)
    refused(tmp_path, code, NAMES_TEST)


NAMES_LIST = NAMES_START.replace("assert names(['b', 'a'])",
                                 "assert list(names(['b', 'a']))")
NAMES_NEXT = NAMES_START.replace("assert names(['b', 'a']) == ['b', 'a']",
                                 "assert next(iter(names(['b', 'a']))) == 'a'")
CALL_API = ("# api" + NL + NL + "- Every call takes `?after=&limit=`." + NL
            + "- Every call returns `{items, next}`." + NL)


def test_a_builtin_the_rewrite_drops_from_the_file_does_not_tie_a_claim(
        tmp_path, monkeypatch):
    def reword(place):
        (place / "docs" / "api.md").write_text(CALL_API, encoding="utf-8")
        (place / "tests" / "test_names.py").write_text(NAMES_NEXT,
                                                       encoding="utf-8")
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        *PAGED, wrong(NAMES_TEST, FOUND[1])), names=True, forge=reword,
        names_start=NAMES_LIST)
    refused(tmp_path, code, NAMES_TEST)


EMPTIED = CURSOR_ENVELOPE.replace(
    'assert set(listing([1])) == {"items", "next"}', "assert listing([1])")


def test_a_rewrite_the_found_product_passes_is_not_covered_by_a_claim(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(*PAGED),
                         rewrite=EMPTIED)
    refused(tmp_path, code, ENVELOPE_TEST)


def covered(tmp_path, code, test):
    gates = record(tmp_path, "gates.md")
    assert code == stops.EXIT_OK, gates
    assert "FAIL test-edits" not in gates, gates
    assert any(test + " <- ruling " in l
               for l in record(tmp_path, "handoff.md").split(NL))


LOOSE_NEW_NAME = CURSOR_ENVELOPE.replace(
    'assert set(listing([1])) == {"items", "next"}',
    "from pages import cursor" + NL + "    assert listing([1])")


def test_the_read_not_pin_floor_a_loose_rewrite_reading_a_new_name_is_covered(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(*PAGED),
                         rewrite=LOOSE_NEW_NAME)
    covered(tmp_path, code, ENVELOPE_TEST)


ORDER_TEST = "tests/test_names.py::test_items_keep_their_order"
ORDER_START = ("from pages import listing" + NL + NL + NL
               + "def test_items_keep_their_order():" + NL
               + "    assert listing(['b', 'a'])['items'] == ['b', 'a']" + NL)
SORTING = CURSOR_LISTING.replace("sorted(items)", "list(items)").replace(
    '{"items": items, "next": None}', '{"items": sorted(items), "next": None}')


def test_the_read_not_pin_floor_a_broken_test_rewritten_to_a_new_key_is_covered(
        tmp_path, monkeypatch):
    def forge(place):
        (place / "pages.py").write_text(SORTING, encoding="utf-8")
        (place / "tests" / "test_names.py").write_text(ORDER_START.replace(
            "['items'] == ['b', 'a']", "['next'] is None"), encoding="utf-8")
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(
        *PAGED, wrong(ORDER_TEST, FOUND[0])), forge=forge,
        names_start=ORDER_START)
    covered(tmp_path, code, ORDER_TEST)


def test_the_import_floor_an_honest_rewrite_widening_its_import_is_asked_about(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(*PAGED),
                         rewrite=CURSOR_ENVELOPE.replace(
                             "from pages import listing",
                             "from pages import cursor, listing"))
    refused(tmp_path, code, ENVELOPE_TEST)


def test_the_paging_claims_tie_by_both_effects_and_a_found_word(
        tmp_path, monkeypatch):
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(*PAGED))
    gates = record(tmp_path, "gates.md")
    assert "FAIL test-edits" not in gates, gates
    assert code == stops.EXIT_OK, gates
    handoff = record(tmp_path, "handoff.md")
    for test, cite in ((ENVELOPE_TEST, "docs/api.md:4"),
                       (FIRST_PAGE_TEST, "docs/api.md:3")):
        [line] = [l for l in handoff.split(NL) if test + " <- ruling " in l]
        assert line.endswith("(claimed on " + cite + ")"), line


def test_a_claim_on_a_ruled_line_the_run_left_as_it_was_covers_nothing(
        tmp_path, monkeypatch):
    # the override said the doc and the rule change; the worker moved the
    # product and the tests and left both as found
    from test_named_spec_files import API, RULE

    def keep(place):
        (place / "docs" / "api.md").write_text(API, encoding="utf-8")
        (place / "rules" / "api-shape.md").write_text(RULE, encoding="utf-8")
    _, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(*PAGED),
                         forge=keep)
    refused(tmp_path, code, ENVELOPE_TEST)
    refused(tmp_path, code, FIRST_PAGE_TEST)


KEYED = NL.join([
    "from pages import listing", "", "KEYS = ('page', 'total')", "", "",
    "def helper():", "    return KEYS", "", "",
    "def test_a_list_keys(page_size):",
    '    """every page has its total"""',
    "    # items in order",
    "    assert sorted(helper()) == list(listing([1])), \"items kept\"", "", "",
    "def test_other():", "    assert listing", ""])


def test_a_test_reads_its_own_code_and_the_code_it_reaches_at_the_top():
    read = testedits.read_by(KEYED, "tests/t.py", "tests/t.py::test_a_list_keys")
    words = ruling.code_words(read)
    assert {"page", "total", "keys", "helper", "listing",
            "page_size"} <= words
    assert not words & {"every", "items", "kept", "order", "sorted", "list",
                        "other"}
    assert testedits.read_by(KEYED, "tests/t.py", "tests/t.py::nope") == ""
    assert testedits.read_by("def broken(:", "t.py", "t.py::x") == ""


def test_a_builtin_name_in_code_is_no_word_but_a_string_holding_one_is():
    assert ruling.code_words(
        "assert list(names(['b']))['type'] == len(KEYS)") == {"names", "type",
                                                              "keys"}
    assert ruling.code_words("def broken(:") == set()


JS_SOURCE = NL.join([
    "// every page has its total",
    "import { listing } from '../pages';",
    "/* the items, in order */",
    "describe('the page envelope', () => {",
    "  it(\"keeps the count\", async () => {",
    "    const body = await listing([1]);",
    "    expect(body.next).toBeNull();",
    "    expect(Object.keys(body)).toEqual(['items', `cursor`, \"caf" + chr(233) + "\"]);",
    "  });",
    "});", ""])


def test_a_js_file_reads_its_names_and_strings_not_comments_or_titles():
    words = ruling.js_words(JS_SOURCE)
    assert {"listing", "pages", "body", "next", "items", "cursor",
            "object", "keys"} <= words
    assert not words & {"every", "page", "total", "order", "envelope",
                        "count", "expect", "const", "await", "tobenull",
                        "toequal", "describe", "import"}
    assert ruling.js_words("") == set()
    assert ruling.js_words("/* never closed items") == set()


LINE = "migrate runs every pending file in order."
SPEC = "# db" + NL + NL + "- " + LINE + NL + "- a name is kept." + NL
ADDED = ("# db" + NL + NL + "- 0007 holds the items that were deleted." + NL
         + "- " + LINE + NL + "- a name is kept." + NL)


def test_a_quoted_line_the_run_moved_down_is_read_as_the_run_found_it(
        tmp_path):
    from test_spec_conflict import a_place
    a_place(tmp_path / "p", {"TASK.md": SPEC, "conftest.py": ""})
    place = tmp_path / "p"
    start = snapshot.take(place)
    (place / "TASK.md").write_text(ADDED, encoding="utf-8")
    moved = 'TASK.md:4 "' + LINE + '"'
    assert ruling.claim_lines(moved, place, start) == ["TASK.md: - " + LINE]
    assert ruling.quoted_as_found(moved, place, start) == ["- " + LINE]
    assert ruling.claim_lines('TASK.md:3 "0007 holds the items that were'
                              ' deleted."', place, start) == []
