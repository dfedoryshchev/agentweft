import os
import sys

sys.path.insert(0, os.environ["TASK_REPO"])
import ledger  # noqa: E402


def test_spent_counts_what_went_out():
    entries = ledger.add([], -4, "lunch")
    ledger.add(entries, -6, "train")
    assert ledger.spent(entries) == 10


def test_spent_ignores_income():
    entries = ledger.add([], 100, "pay")
    ledger.add(entries, -1.5, "tea")
    assert ledger.spent(entries) == 1.5


def test_spent_of_nothing_is_zero():
    assert ledger.spent([]) == 0


def test_balance_still_sums_every_amount():
    entries = ledger.add([], 10, "pay")
    ledger.add(entries, -4, "lunch")
    assert ledger.balance(entries) == 6
