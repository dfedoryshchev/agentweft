import os
import sys

import pytest

sys.path.insert(0, os.environ["TASK_REPO"])
import ledger  # noqa: E402


def test_an_amount_of_zero_is_still_refused():
    with pytest.raises(ValueError):
        ledger.add([], 0, "placeholder")


def test_other_amounts_are_still_entries():
    assert ledger.add([], -2, "bus") == [{"amount": -2.0, "note": "bus"}]
