"""tokens into money, by a table a person keeps.

the table is `prices.yaml`: the one in the directory the run is started from,
or the one PRICES names, or the copy that ships beside this file. it says
where its numbers came from and on what day, because a price is only true on
the day somebody read it.

a model the table does not list, or a call it cannot price exactly, comes
back with no money and a reason. it is never priced at zero: zero reads as
free, and an unknown is a number somebody still owes.
"""
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import yaml

SHIPPED = Path(__file__).with_name("prices.yaml")
RATES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
MILLION = Decimal(1000000)
NO_MODEL = "no model named"
NOT_LISTED = None


def label(model, why=NOT_LISTED):
    """-> how an unpriced call is named on a line: the model, and the reason
    when the reason is not just that the table lacks it."""
    name = model or NO_MODEL
    return name if why is NOT_LISTED else name + " (" + why + ")"


def amount(value, where):
    if isinstance(value, bool):
        raise ValueError(where + ": " + repr(value) + " is not a price")
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(where + ": " + repr(value) + " is not a price")
    if not out.is_finite() or out < 0:
        raise ValueError(where + ": " + repr(value) + " is not a price")
    return out


class Rates(object):
    """USD per million tokens, one model, one prompt length band."""

    __slots__ = RATES + ("over", "above")

    def __init__(self, block, where):
        if not isinstance(block, dict):
            raise ValueError(where + ": not a table of rates")
        lacks = [k for k in RATES if k not in block]
        if lacks:
            raise ValueError(where + " has no " + ", ".join(lacks))
        for k in RATES:
            setattr(self, k, amount(block[k], where + "." + k))
        self.over = None
        self.above = None
        if block.get("over") is not None:
            self.over = int(amount(block["over"], where + ".over"))
            self.above = Rates(block.get("above"), where + ".above")

    def cost(self, plain, read, write_5m, write_1h, out):
        return (plain * self.input + read * self.cache_read
                + write_5m * self.cache_write_5m
                + write_1h * self.cache_write_1h
                + out * self.output) / MILLION


class Priced(object):
    """what a call or a set of calls cost. `usd` is None when any part of it
    could not be priced, and `missing` names those parts."""

    __slots__ = ("usd", "missing")

    def __init__(self, usd=None, missing=None):
        self.usd = usd
        self.missing = list(missing or [])

    def __add__(self, other):
        missing = self.missing + other.missing
        if missing:
            return Priced(None, missing)
        return Priced(self.usd + other.usd)


def split_writes(usage):
    """-> (5m, 1h) cache writes, or None when the provider did not say which
    lifetime they were written for."""
    total = usage.cache_creation_input_tokens
    if not total:
        return 0, 0
    said = (usage.raw or {}).get("cache_creation")
    if not isinstance(said, dict):
        return None
    five = said.get("ephemeral_5m_input_tokens")
    hour = said.get("ephemeral_1h_input_tokens")
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0
               for n in (five, hour)):
        return None
    return (five, hour) if five + hour == total else None


class Table(object):
    def __init__(self, data, where):
        if not isinstance(data, dict) or not isinstance(data.get("models"),
                                                        dict):
            raise ValueError(where + ": no models")
        self.source = str(data.get("source") or where)
        self.checked = str(data.get("checked") or "never")
        self.web_search = None
        if data.get("web_search_per_1000") is not None:
            self.web_search = amount(data["web_search_per_1000"],
                                     where + ".web_search_per_1000") / 1000
        self.models = {}
        for name, block in data["models"].items():
            rates = Rates(block, where + ": " + str(name))
            for alias in [name] + list((block or {}).get("ids") or []):
                self.models[str(alias)] = rates

    def rates(self, model):
        return self.models.get(model) if model else None

    def price(self, model, usage, one_request=False):
        """-> Priced for one usage block the provider counted."""
        rates = self.rates(model)
        if rates is None:
            return Priced(None, [label(model)])
        raw = usage.raw or {}
        if raw.get("speed") == "fast":
            return Priced(None, [label(model, "fast mode")])
        if raw.get("inference_geo") == "us":
            return Priced(None, [label(model, "US-only inference")])
        writes = split_writes(usage)
        if writes is None:
            return Priced(None, [label(model, "cache writes with no 5m / 1h"
                                              " split")])
        if rates.over is not None and usage.input_tokens > rates.over:
            if not one_request:
                return Priced(None, [label(model, "over " + str(rates.over)
                                           + " input tokens, summed over"
                                             " requests")])
            rates = rates.above
        read = usage.cache_read_input_tokens
        plain = usage.input_tokens - read - sum(writes)
        usd = rates.cost(plain, read, writes[0], writes[1],
                         usage.output_tokens)
        searches = (raw.get("server_tool_use") or {}).get("web_search_requests")
        if isinstance(searches, int) and searches > 0:
            if self.web_search is None:
                return Priced(None, [label(model, "web search")])
            usd = usd + searches * self.web_search
        return Priced(usd)

    def estimate(self, model, input_tokens, output_tokens):
        """-> Priced for a call nobody counted, from the chars/4 guess."""
        rates = self.rates(model)
        if rates is None:
            return Priced(None, [label(model)])
        if rates.over is not None and input_tokens > rates.over:
            rates = rates.above
        return Priced(rates.cost(input_tokens, 0, 0, 0, output_tokens))

    @property
    def named(self):
        return self.source + ", checked " + self.checked


def of_reply(table, reply, asked=None):
    """-> Priced for a reply that carries usage. the model that answered
    wins over the one that was asked for, which can be an alias."""
    usage = reply.usage
    models = getattr(reply, "models", None)
    if models:
        out = Priced(Decimal(0))
        for name in sorted(models):
            out = out + table.price(name, models[name])
        return out
    model = getattr(reply, "model", None) or asked
    if model and ", " in model:
        return Priced(None, [label(model, "several models, no split")])
    return table.price(model, usage, one_request=usage.requests == 1)


CACHE = {}


def where_from(path=None):
    if path:
        return Path(path)
    if os.environ.get("PRICES"):
        return Path(os.environ["PRICES"])
    own = Path("prices.yaml")
    return own if own.is_file() else SHIPPED


def load(path=None):
    """-> the Table in force. read again whenever the file changes."""
    path = where_from(path).resolve()
    key = (str(path), path.stat().st_mtime_ns)
    if key not in CACHE:
        CACHE[key] = Table(yaml.safe_load(path.read_text(encoding="utf-8")),
                           str(path.name))
    return CACHE[key]


CENT_HUNDREDTH = Decimal("0.0001")


def money(usd):
    """-> "$0.1234": four places, half up, and never a $0.0000 for
    something that cost more than nothing."""
    shown = Decimal(usd).quantize(CENT_HUNDREDTH, rounding=ROUND_HALF_UP)
    if usd > 0 and shown == 0:
        return "<$0.0001"
    return "$" + str(shown)


def stored(usd):
    """-> USD as a float to the millionth, for a json record."""
    if usd is None:
        return None
    return float(Decimal(usd).quantize(Decimal("0.000001"),
                                       rounding=ROUND_HALF_UP))
