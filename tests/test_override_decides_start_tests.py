"""under a held override, a start test the override's rewritten lines decide
is listed under that ruling without a claim per test.

the override lets spec lines change, and the run's edit rewrites them. a
start test whose change is that edit's needs no WRONG TEST line of its own:
the test as the run found it, green at the start, is red against the product
now, and the lines the change took out of it hold a word the edit took out of
a line the override covers and out of its file. such a test, changed,
removed or deleted with its file, is listed under the ruling in the handoff
with the line that decided it. a test the edit's lines do not decide still
needs its own claim or parks: one still green as found, one whose lines share
no word the edit took out, and one the move also broke whose rewrite writes
the new envelope's words, or shares a builtin with the ruled line.
"""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import testedits
from agentweft.runner import stops

from test_ruled_start_tests import (CURSOR_ENVELOPE, ENVELOPE_TEST,
                                    FIRST_PAGE_TEST, NAMES_START, NAMES_TEST,
                                    TYPED_PLAN, built, overridden, record,
                                    stamp_of)

NL = chr(10)
ONLY_ENVELOPE = CURSOR_ENVELOPE.split(NL + NL + NL + "def test_a_list_starts")[0] \
    + NL
LOOSE_NAMES = NAMES_START.replace(" == ['b', 'a']", "")


def gates(tmp_path):
    return record(tmp_path, "gates.md")


def test_tests_the_ruled_edit_decides_change_with_no_claim(tmp_path,
                                                           monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built())
    assert "FAIL test-edits" not in gates(tmp_path), gates(tmp_path)
    assert code == stops.EXIT_OK
    assert asked.count("worker.md") == 1
    handoff = record(tmp_path, "handoff.md")
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        line = test + " <- ruling " + stamp_of(tmp_path) + " ("
        assert line + testedits.DECIDED_BY + " docs/api.md:" in handoff, test


def test_a_removed_test_the_ruled_edit_decides_is_listed(tmp_path,
                                                         monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             rewrite=ONLY_ENVELOPE)
    assert code == stops.EXIT_OK, gates(tmp_path)
    handoff = record(tmp_path, "handoff.md")
    assert FIRST_PAGE_TEST + " <- ruling " + stamp_of(tmp_path) in handoff


def test_a_deleted_test_file_is_listed_by_name_under_the_ruling(
        tmp_path, monkeypatch):
    def gone(place):
        (place / "tests" / "test_envelope.py").unlink()
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             rewrite=None, forge=gone)
    assert code == stops.EXIT_OK, gates(tmp_path)
    handoff = record(tmp_path, "handoff.md")
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        assert test + " <- ruling " + stamp_of(tmp_path) in handoff, test


def test_a_test_the_edit_does_not_decide_still_needs_a_claim(tmp_path,
                                                             monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             names=True)
    assert code != stops.EXIT_OK
    said = gates(tmp_path)
    assert "FAIL test-edits" in said
    left = said.split("FAIL test-edits")[-1].split(NL)[0]
    assert NAMES_TEST + " (changed)" in left
    assert ENVELOPE_TEST not in left and FIRST_PAGE_TEST not in left


ORDER_START = ("from pages import listing" + NL + NL + NL
               + "def test_names_keep_their_order():" + NL
               + "    assert listing(['b', 'a'])['items'] == ['b', 'a']" + NL)
ORDER_LEFT = ORDER_START.replace(
    "== ['b', 'a']", "== ['a', 'b'] and listing(['b', 'a'])['next'] is None")
NAMES_LIST = NAMES_START.replace("assert names(['b', 'a'])",
                                 "assert list(names(['b', 'a']))")
NAMES_NEXT = NAMES_START.replace("assert names(['b', 'a']) == ['b', 'a']",
                                 "assert next(iter(names(['b', 'a']))) == 'a'")


def refused_on_names(tmp_path):
    said = gates(tmp_path)
    assert "FAIL test-edits" in said, said
    assert NAMES_TEST + " (changed)" in said.split("FAIL test-edits")[-1] \
        .split(NL)[0]


def test_a_test_the_move_also_broke_is_not_decided_by_a_word_the_step_wrote(
        tmp_path, monkeypatch):
    # the order test pins docs/names.md:3, which no ruling covers; the move
    # sorts the items and the rewrite adds the new envelope's key
    def sort(place):
        listing = (place / "pages.py").read_text(encoding="utf-8")
        (place / "pages.py").write_text(listing.replace(
            '"items": items', '"items": sorted(items)'), encoding="utf-8")
        (place / "tests" / "test_names.py").write_text(ORDER_LEFT,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             forge=sort, names_start=ORDER_START)
    assert code != stops.EXIT_OK
    refused_on_names(tmp_path)


def test_a_builtin_shared_with_the_ruled_line_does_not_decide_a_test(
        tmp_path, monkeypatch):
    def rewrite(place):
        (place / "tests" / "test_names.py").write_text(NAMES_NEXT,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             names=True, forge=rewrite,
                             names_start=NAMES_LIST)
    assert code != stops.EXIT_OK
    refused_on_names(tmp_path)


CALL_API = ("# api" + NL + NL + "- Every call takes `?after=&limit=`." + NL
            + "- Every call returns `{items, next}`." + NL)


def test_a_builtin_the_ruled_rewrite_drops_from_its_file_does_not_decide(
        tmp_path, monkeypatch):
    # the rewrite words the doc without `list`, so the edit took `list` out
    # of the line and out of its file; the names test reads `list(` as code
    def reword(place):
        (place / "docs" / "api.md").write_text(CALL_API, encoding="utf-8")
        (place / "tests" / "test_names.py").write_text(NAMES_NEXT,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             names=True, forge=reword,
                             names_start=NAMES_LIST)
    assert code != stops.EXIT_OK
    refused_on_names(tmp_path)


def test_a_test_still_green_as_found_is_not_decided(tmp_path, monkeypatch):
    def loosen(place):
        (place / "tests" / "test_names.py").write_text(LOOSE_NAMES,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             forge=loosen)
    assert code != stops.EXIT_OK
    left = gates(tmp_path).split("FAIL test-edits")[-1].split(NL)[0]
    assert NAMES_TEST + " (changed)" in left
