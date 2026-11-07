"""under a held override, a start test changed with no claim is asked about,
never listed under the ruling by the run alone.

the override lets spec lines change, and the run's edit rewrites them. a
start test the step changes with them, with no WRONG TEST line of its own,
fails the test-edits check and parks on its question, however much its
change looks like the edit's: changed, removed, or deleted with its file,
red as found or green, sharing a word with the edit or a builtin with the
ruled line. the question names every such test with what the run found
(red or green as found, a word of a ruled line its code reads, a rewrite red
on the start product) and counts them by group; that decides nothing, and
the person's `override:` to it lists each test it named under his ruling.
"""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import testedits
from agentweft.runner import stops

from test_named_spec_files import REVIEWED
from test_ruled_start_tests import (CURSOR_ENVELOPE, ENVELOPE_TEST,
                                    FIRST_PAGE_TEST, NAMES_START, NAMES_TEST,
                                    TYPED_PLAN, built, edits_of, overridden,
                                    record)
from test_spec_conflict import folders, go, plain

NL = chr(10)
ONLY_ENVELOPE = CURSOR_ENVELOPE.split(NL + NL + NL + "def test_a_list_starts")[0] \
    + NL
LOOSE_NAMES = NAMES_START.replace(" == ['b', 'a']", "")


def gates(tmp_path):
    return record(tmp_path, "gates.md")


def asked_about(tmp_path, code, *tests):
    said = gates(tmp_path)
    assert code != stops.EXIT_OK, said
    question = record(tmp_path, "question.md")
    handoff = record(tmp_path, "handoff.md")
    for test in tests:
        assert test in question, question
        assert test + " <- ruling" not in handoff


def test_tests_the_ruled_edit_moved_with_no_claim_are_asked_about(
        tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built())
    asked_about(tmp_path, code, ENVELOPE_TEST, FIRST_PAGE_TEST)


def test_a_removed_test_with_no_claim_is_asked_about(tmp_path, monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             rewrite=ONLY_ENVELOPE)
    asked_about(tmp_path, code, FIRST_PAGE_TEST)
    assert FIRST_PAGE_TEST + " - removed" in record(tmp_path, "question.md")


def test_a_deleted_test_file_is_asked_about_by_name(tmp_path, monkeypatch):
    def gone(place):
        (place / "tests" / "test_envelope.py").unlink(missing_ok=True)
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             rewrite=None, forge=gone)
    asked_about(tmp_path, code, ENVELOPE_TEST, FIRST_PAGE_TEST)


def cited(question, test):
    [line] = [l for l in question.split(NL) if l.startswith("- " + test + " ")]
    return line


def test_the_question_says_what_the_run_found_for_each_test(tmp_path,
                                                            monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             rewrite=ONLY_ENVELOPE)
    asked_about(tmp_path, code, ENVELOPE_TEST, FIRST_PAGE_TEST)
    question = record(tmp_path, "question.md")
    assert cited(question, ENVELOPE_TEST).endswith(
        " - changed; red as found; reads page of docs/api.md:3 (ruled);"
        " rewrite red on the start product"), question
    assert cited(question, FIRST_PAGE_TEST).endswith(
        " - removed; red as found; reads page of docs/api.md:3 (ruled)")
    assert question.split(NL)[0].endswith(
        " what the run found, which decides nothing: 2 red as found and"
        " reading a ruled line, 1 " + testedits.WHOLE + "."), question
    assert cited(question, "tests/test_envelope.py").endswith(
        " - " + testedits.SHARED)


ENTRIES_API = ("# api" + NL + NL + "- Every call takes `?after=&limit=`." + NL
               + "- Every call returns `{entries, next}`." + NL)


def test_a_test_the_move_also_broke_is_asked_about_with_what_it_reads(
        tmp_path, monkeypatch):
    # the rewording drops `items` from the file: no route lists the order
    # test under the ruling, the question shows what the run found
    def sort(place):
        listing = (place / "pages.py").read_text(encoding="utf-8")
        (place / "pages.py").write_text(listing.replace(
            '"items": items', '"items": sorted(items)'), encoding="utf-8")
        (place / "docs" / "api.md").write_text(ENTRIES_API, encoding="utf-8")
        (place / "tests" / "test_names.py").write_text(ORDER_LEFT,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             forge=sort, names_start=ORDER_START)
    asked_about(tmp_path, code, NAMES_TEST)
    question = record(tmp_path, "question.md")
    assert cited(question, NAMES_TEST).endswith(
        " - changed; red as found; reads items of docs/api.md:4 (ruled);"
        " rewrite red on the start product"), question


def test_a_test_still_green_as_found_is_asked_about_as_green(tmp_path,
                                                             monkeypatch):
    def loosen(place):
        (place / "tests" / "test_names.py").write_text(LOOSE_NAMES,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             forge=loosen)
    question = record(tmp_path, "question.md")
    assert cited(question, NAMES_TEST).endswith(" - changed; green as found")
    assert "1 green as found" in question.split(NL)[0]


ANSWER = ("override: the tests the question names change under the ruling"
          " of the paging; nothing else.")


def test_his_override_to_the_question_lists_each_test_it_named(tmp_path,
                                                                monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built())
    assert code == stops.EXIT_STOP
    leg = folders(tmp_path)[-1]
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"worker.md": [built()],
                               "reviewer.md": [REVIEWED],
                               "reviewer-runs.md": [REVIEWED]}),
                        edits_of(place), "--resume", leg.name,
                        "--answer", ANSWER)
    gates = record(tmp_path, "gates.md")
    assert code == stops.EXIT_OK, gates
    handoff = record(tmp_path, "handoff.md")
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        [line] = [l for l in handoff.split(NL) if test + " <- ruling " in l]
        assert line.endswith(" (" + testedits.NAMED_IN + ")"), line


def test_a_test_the_move_also_broke_is_asked_about_beside_them(tmp_path,
                                                               monkeypatch):
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             names=True)
    assert code != stops.EXIT_OK
    said = gates(tmp_path)
    assert "FAIL test-edits" in said
    left = said.split("FAIL test-edits")[-1].split(NL)[0]
    for test in (NAMES_TEST, ENVELOPE_TEST, FIRST_PAGE_TEST):
        assert test + " (changed)" in left, test


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
