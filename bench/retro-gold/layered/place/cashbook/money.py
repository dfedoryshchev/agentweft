"""amounts as Decimal, read and written with the ledger's decimal mark."""
from decimal import Decimal, InvalidOperation


class AmountError(ValueError):
    pass


PLACES = Decimal("0.01")


def parse_amount(text, decimal_mark="."):
    try:
        return Decimal(text.strip().replace(decimal_mark, ".")).quantize(PLACES)
    except InvalidOperation:
        raise AmountError("not an amount: " + text)


def fmt(value, decimal_mark="."):
    return str(value.quantize(PLACES)).replace(".", decimal_mark)


def total(values):
    return sum(values, Decimal("0")).quantize(PLACES)
