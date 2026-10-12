"""what a run is allowed to cost.

the digest is eight calls on a full inbox and a redo makes it twelve. i have
been running this for nine months with no idea what that adds up to, which is
fine right up until a prompt bug puts it in a loop.

a provider that says what a call used is charged exactly that, split the way
it said it. one that says nothing is charged an estimate from the length of
the text. the two are kept apart: a total with an estimate in it says so.

money is the tokens through the price table (`prices.py`), and beside it what
the provider said the calls cost, when it said. the two are both kept and
both printed: a provider figure is not a price check, and a priced figure is
not what the provider billed.

the fan-out charges one budget from every worker thread, so a charge is taken
whole or not at all: a total read by one thread and written back by it after
another has charged is a call that never happened.
"""
import threading
from decimal import Decimal

from . import prices


class OverBudget(Exception):
    pass


# rough, and deliberately so. i want an order of magnitude, not an invoice.
CHARS_PER_TOKEN = 4

# named after the OpenTelemetry GenAI usage attributes. `input` is the whole
# input, cache_read and cache_creation INCLUDED, and `output` includes reasoning:
# those three are parts of the two totals and are never added to them again.
SPLIT = ("input", "output", "cache_read", "cache_creation", "reasoning")


def plural(n, what):
    return str(n) + " " + what + ("" if n == 1 else "s")


class Budget(object):
    def __init__(self, max_calls=0, max_tokens=0, prices=None):
        self.max_calls = int(max_calls or 0)
        self.max_tokens = int(max_tokens or 0)
        self.table = prices
        self.usd = Decimal(0)
        self.usd_estimated = Decimal(0)
        self.priced_calls = 0
        self.unpriced = {}
        self.reported = Decimal(0)
        self.reported_calls = 0
        self.calls = 0
        self.by_provider = {}
        self.counted = dict.fromkeys(SPLIT, 0)
        self.counted_calls = 0
        self.estimated = 0
        self.estimated_calls = 0
        # failed goes the provider gave no usage for, by error kind. they are
        # charged as calls and as 0 tokens, which is not the same as free
        self.unreported = {}
        self.lock = threading.Lock()

    def charge(self, prompt, answer, provider="cli", error=None, model=None):
        """one go at a model.

        `answer` is the reply, or only its text when that is all there is.
        `error` is the kind of failure when the go failed, None when it
        answered. `model` is the id that was asked for; the one the reply
        says answered wins over it.
        """
        with self.lock:
            return self._charge(prompt, answer, provider, error, model)

    def _charge(self, prompt, answer, provider, error, model):
        usage = getattr(answer, "usage", None)
        if usage is not None:
            self.counted["input"] += usage.input_tokens
            self.counted["output"] += usage.output_tokens
            self.counted["cache_read"] += usage.cache_read_input_tokens
            self.counted["cache_creation"] += usage.cache_creation_input_tokens
            self.counted["reasoning"] += usage.reasoning_output_tokens or 0
            self.counted_calls += 1
            self.price(prices.of_reply(self.prices, answer, asked=model))
        elif error:
            self.unreported[error] = self.unreported.get(error, 0) + 1
        else:
            text = getattr(answer, "text", answer) or ""
            self.estimated += (len(prompt) + len(text)) // CHARS_PER_TOKEN
            self.estimated_calls += 1
            self.price(self.prices.estimate(
                getattr(answer, "model", None) or model,
                len(prompt) // CHARS_PER_TOKEN,
                len(text) // CHARS_PER_TOKEN), estimated=True)
        cost = getattr(answer, "cost", None)
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            self.reported += Decimal(str(cost))
            self.reported_calls += 1
        self.calls += 1
        self.by_provider[provider] = self.by_provider.get(provider, 0) + 1
        return self

    @property
    def prices(self):
        if self.table is None:
            self.table = prices.load()
        return self.table

    def price(self, priced, estimated=False):
        if priced.missing:
            for name in priced.missing:
                self.unpriced[name] = self.unpriced.get(name, 0) + 1
            return
        self.usd += priced.usd
        if estimated:
            self.usd_estimated += priced.usd
        self.priced_calls += 1

    def money(self):
        """-> what the run cost, for a record. `usd` is None when any call
        could not be priced; `priced_usd` is then the part that could.
        `reported_usd` is None unless every call that answered reported one.
        """
        answered = self.counted_calls + self.estimated_calls
        whole = answered and self.reported_calls >= answered
        return {"usd": None if self.unpriced else prices.stored(self.usd),
                "estimated": bool(self.usd_estimated),
                "priced_usd": prices.stored(self.usd),
                "estimated_usd": prices.stored(self.usd_estimated),
                "unpriced": dict(self.unpriced),
                "reported_usd": prices.stored(self.reported) if whole
                else None,
                "reported_calls": self.reported_calls,
                "prices": self.prices.named}

    def spent(self):
        """-> the money part of the summary, "" when no call answered."""
        if not (self.priced_calls or self.unpriced or self.reported_calls):
            return ""
        rough = "~" if self.usd_estimated else ""
        out = []
        if self.priced_calls:
            part = rough + prices.money(self.usd) + " priced"
            if self.usd_estimated and self.usd_estimated != self.usd:
                part = (part + " (~" + prices.money(self.usd_estimated)
                        + " of it estimated)")
            out.append(part)
        if self.unpriced:
            names = ", ".join(k + " x" + str(v)
                              for k, v in sorted(self.unpriced.items()))
            if out:
                out[0] = out[0] + " + unpriced: " + names
            else:
                out.append("unpriced: " + names)
        if self.reported_calls:
            part = "reported " + prices.money(self.reported)
            answered = self.counted_calls + self.estimated_calls
            if self.reported_calls < answered:
                part = (part + " on " + str(self.reported_calls) + " of "
                        + plural(answered, "call"))
            elif (self.priced_calls and not self.unpriced
                  and not self.usd_estimated
                  and prices.money(self.usd) != prices.money(self.reported)):
                part = (part + ", they differ by "
                        + prices.money(abs(self.usd - self.reported)))
            out.append(part)
        return ", ".join(out)

    @property
    def tokens(self):
        """what the token cap reads: everything counted plus the estimate."""
        return self.counted["input"] + self.counted["output"] + self.estimated

    def metered(self):
        """-> "counted", "estimated" or "mixed: N estimated calls"."""
        if self.counted_calls and self.estimated_calls:
            return "mixed: " + plural(self.estimated_calls, "estimated call")
        return "counted" if self.counted_calls else "estimated"

    def split(self, parts=True):
        c = self.counted
        n = c["input"] + c["output"]
        if not parts:
            return (str(n) + " counted: input " + str(c["input"])
                    + ", output " + str(c["output"]))
        inside = [k + " " + str(c[k]) for k in ("cache_read", "cache_creation")
                  if c[k]]
        out = "input " + str(c["input"]) \
            + (" incl. " + " and ".join(inside) if inside else "")
        out = out + ", output " + str(c["output"]) \
            + (" incl. reasoning " + str(c["reasoning"]) if c["reasoning"]
               else "")
        return str(n) + " tokens counted (" + out + ")"

    def over(self):
        if self.max_calls and self.calls > self.max_calls:
            return "call cap: " + str(self.calls) + " > " + str(self.max_calls)
        if self.max_tokens and self.tokens > self.max_tokens:
            why = []
            if self.counted_calls:
                why.append(self.split(parts=False))
            if self.estimated_calls:
                why.append(("+ " if why else "") + "~" + str(self.estimated)
                           + " estimated")
            return ("token cap: " + str(self.tokens) + " > "
                    + str(self.max_tokens) + " (" + ", ".join(why) + ")")
        return None

    def summary(self):
        if not self.calls:
            return "0 calls, 0 tokens"
        out = plural(self.calls, "call") + ", "
        estimate = "~" + str(self.estimated) + " tokens estimated"
        if self.counted_calls and self.estimated_calls:
            out = (out + self.metered() + ", " + self.split()
                   + " + ~" + str(self.estimated) + " estimated")
        elif self.counted_calls:
            out = out + self.split()
        elif self.estimated_calls:
            out = out + estimate
        else:
            out = out + "0 tokens"
        failed = sum(self.unreported.values())
        if failed:
            out = (out + ", " + plural(failed, "failed call") + " charged 0 ("
                   + ", ".join(k + " x" + str(v)
                               for k, v in sorted(self.unreported.items()))
                   + ")")
        money = self.spent()
        if money:
            out = out + ", " + money
        where = ", ".join(k + " x" + str(v)
                          for k, v in sorted(self.by_provider.items()))
        return out + (" (" + where + ")" if where else "")
