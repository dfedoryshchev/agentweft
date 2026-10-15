import pytest

import ledger


def test_parse_reads_the_amount_and_the_note():
    assert ledger.parse("-4.20 coffee") == {"amount": -4.2, "note": "coffee"}


def test_balance_sums_every_amount():
    entries = ledger.add([], 10, "pay")
    ledger.add(entries, -4, "lunch")
    assert ledger.balance(entries) == 6


def test_an_amount_of_zero_is_refused():
    with pytest.raises(ValueError):
        ledger.add([], 0)
