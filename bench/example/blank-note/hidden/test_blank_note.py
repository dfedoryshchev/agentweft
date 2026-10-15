import os
import sys

sys.path.insert(0, os.environ["TASK_REPO"])
import ledger  # noqa: E402


def test_a_line_with_no_note_reads_as_its_amount():
    assert ledger.parse("12.50") == {"amount": 12.5, "note": ""}


def test_a_line_with_only_a_trailing_space_has_an_empty_note():
    assert ledger.parse("3 ") == {"amount": 3.0, "note": ""}


def test_a_line_with_a_note_still_reads_it():
    assert ledger.parse("-4.20 coffee beans") == {"amount": -4.2,
                                                  "note": "coffee beans"}
