"""what the runs spent, grouped per flow and per provider.

the journal has one money figure per run. the steps of a run, in its
`steps.jsonl`, say which provider each one went to, so the grouping is read
from there: a run that went to two providers is split between them.

a step its provider did not count has no tokens and no money on its line, and
is called that rather than added in as nothing.
"""
import json
from decimal import Decimal

from agentweft.guardrails import prices
from agentweft.guardrails.budget import plural

from . import stops, trace

LAST = 20


class Group(object):
    __slots__ = ("runs", "steps", "counted", "input", "output", "cache_read",
                 "cache_creation", "usd", "unpriced", "reported", "unreported")

    def __init__(self):
        self.runs = set()
        self.steps = self.counted = 0
        self.input = self.output = self.cache_read = self.cache_creation = 0
        self.usd = Decimal(0)
        self.reported = Decimal(0)
        self.unpriced = self.unreported = 0

    def add(self, run, step):
        self.runs.add(run)
        if step.get("cached"):
            return
        self.steps += 1
        tokens = step.get("tokens") or {}
        if tokens.get("counted"):
            self.counted += 1
            self.input += tokens.get("input", 0)
            self.output += tokens.get("output", 0)
            self.cache_read += tokens.get("cache_read", 0)
            self.cache_creation += tokens.get("cache_creation", 0)
            if step.get("priced") is None:
                self.unpriced += 1
            else:
                self.usd += Decimal(str(step["priced"]))
        if step.get("cost") is None:
            self.unreported += 1
        else:
            self.reported += Decimal(str(step["cost"]))

    def line(self, name):
        head = ("  " + name + "  " + plural(len(self.runs), "run") + ", "
                + plural(self.steps, "step"))
        if not self.counted:
            return head + ", estimated only: no counts, no money"
        out = (head + ", input " + str(self.input) + ", output "
               + str(self.output) + ", cache read " + str(self.cache_read)
               + ", cache write " + str(self.cache_creation) + ", "
               + prices.money(self.usd) + " priced")
        if self.unpriced:
            out = out + " + " + plural(self.unpriced, "unpriced step")
        if self.steps > self.counted:
            out = out + ", " + plural(self.steps - self.counted,
                                            "step") + " estimated, not counted"
        if self.steps > self.unreported:
            out = out + ", reported " + prices.money(self.reported)
            if self.unreported:
                out = out + " on " + str(self.steps - self.unreported) + " of " \
                    + plural(self.steps, "step")
        return out


def read_steps(folder):
    path = folder / trace.FILE
    if not path.exists():
        return []
    out = []
    for text in path.read_text(encoding="utf-8").split("\n"):
        try:
            out.append(json.loads(text))
        except ValueError:
            continue
    return out


def report(runs):
    """-> the lines `python run.py spend` prints: the last runs that say what
    they spent, then the same runs per flow and per provider."""
    journal = runs / "journal.md"
    if not journal.exists():
        return ["no runs yet"]
    spent = [(text, stops.read(text)) for text in
             journal.read_text(encoding="utf-8").split("\n")]
    spent = [(text, line) for text, line in spent
             if line is not None and line.spend][-LAST:]
    out = [text for text, _ in spent]
    flows, providers, seen = {}, {}, set()
    for _, line in spent:
        if not line.run or line.run in seen:
            continue
        # a resumed run writes a journal line per leg into one folder
        seen.add(line.run)
        for step in read_steps(runs / line.run):
            flows.setdefault(line.flow, Group()).add(line.run, step)
            providers.setdefault(step.get("provider") or "?",
                                 Group()).add(line.run, step)
    if not flows:
        return out
    out = out + ["", "per flow"] + [flows[k].line(k) for k in sorted(flows)]
    out = out + ["", "per provider"] + [providers[k].line(k)
                                       for k in sorted(providers)]
    return out
