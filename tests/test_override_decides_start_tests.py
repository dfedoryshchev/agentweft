"""under a held override, a start test the override's rewritten lines decide
is listed under that ruling without a claim per test.

the override lets spec lines change, and the run's edit rewrites them. a
start test whose change is that edit's needs no WRONG TEST line of its own:
the test as the run found it, green at the start, is red against the product
now, and the lines the change took out of it hold a word the edit took out of
a line the override covers (or hold a word of that line and the lines it put
in a new word the edit wrote). such a test, changed, removed or deleted with
its file, is listed under the ruling in the handoff with the line that
decided it. a test the edit's lines do not decide still needs its own claim
or parks: one still green as found, one whose lines share no word the edit
took out.
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


def test_a_test_still_green_as_found_is_not_decided(tmp_path, monkeypatch):
    def loosen(place):
        (place / "tests" / "test_names.py").write_text(LOOSE_NAMES,
                                                       encoding="utf-8")
    asked, code = overridden(tmp_path, monkeypatch, TYPED_PLAN, built(),
                             forge=loosen)
    assert code != stops.EXIT_OK
    left = gates(tmp_path).split("FAIL test-edits")[-1].split(NL)[0]
    assert NAMES_TEST + " (changed)" in left
