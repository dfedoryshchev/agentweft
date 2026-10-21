"""the ledger as text, one entry a line."""
from . import money


def lines(entries, decimal_mark="."):
    out = []
    for entry in entries:
        out.append(entry.day + " " + money.fmt(entry.amount, decimal_mark))
    return out
