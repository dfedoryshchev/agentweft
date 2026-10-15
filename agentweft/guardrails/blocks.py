"""a run's budget, split into a block per step before the first call.

the cap says when a run has spent too much. it says nothing until then, so a
flow that never had a chance of fitting finds out at step four, with three
steps paid for. the blocks are worked out before step one and written to
`runs/<id>/budget-plan.md`: what each step should take, a buffer, and whether
the whole of it fits. when it does not, the run says RISKY before it calls
anything.

an estimate is what the step took in earlier runs of the same flow in the same
project. with none, the cap is split by the share of a run's spend each role
took, measured over earlier runs of the shipped flows. a block is accounting
inside the run's total, not a second cap: nothing stops at the end of a block.
a step that finishes under its block leaves the rest to the buffer, and one
that goes over draws the difference from it.
"""
import json
import math

FILE = "budget-plan.md"
RISKY = "RISKY"
TOKENS = "tokens"
CALLS = "calls"

SHARES = {"worker": 41, "patcher": 22, "tester": 14, "verify": 11,
          "planner": 8, "reviewer": 4}
BUFFER = 10
KEEP = 5


def share(role):
    return SHARES.get(role, float(sum(SHARES.values())) / len(SHARES))


def capped(line):
    """-> what the token cap would read for one line, None when uncounted."""
    if line.get("cached"):
        return 0
    t = line.get("tokens") or {}
    if not t.get("counted"):
        return None
    return t["input"] + t["output"] - t["cache_read"]


def calls_of(line):
    if line.get("cached"):
        return 0
    return len(line.get("tasks") or ()) or 1


def read(path):
    """-> {step: [tokens or None, calls]} summed over one run's lines."""
    out = {}
    if not path.is_file():
        return out
    for text in path.read_text(encoding="utf-8").split("\n"):
        try:
            line = json.loads(text)
            step = line["step"]
        except (ValueError, KeyError, TypeError):
            continue
        tokens, calls = out.get(step, [0, 0])
        took = capped(line)
        out[step] = [None if tokens is None or took is None
                     else tokens + took, calls + calls_of(line)]
    return out


def history(runs, flow, workdir, skip=None):
    """-> {step: (tokens or None, calls)}, the mean over the newest earlier
    runs of `flow` on the same project, rounded up."""
    from agentweft.runner import state

    if not runs.is_dir():
        return {}
    here = state.root_of(workdir)
    found = []
    for d in sorted(runs.iterdir(), reverse=True):
        rest = d.name[len(flow) + 1:]
        if d.name == skip or not d.name.startswith(flow + "-") \
                or not rest[:1].isdigit() or not (d / "workdir").is_file():
            continue
        if state.root_of((d / "workdir").read_text(
                encoding="utf-8").strip()) != here:
            continue
        per = read(d / "steps.jsonl")
        if per:
            found.append(per)
        if len(found) == KEEP:
            break
    out = {}
    for step in set(s for per in found for s in per):
        ran = [per[step] for per in found if step in per]
        tokens = [t for t, _ in ran if t is not None]
        out[step] = (int(math.ceil(float(sum(tokens)) / len(tokens)))
                     if tokens else None,
                     int(math.ceil(float(sum(c for _, c in ran)) / len(ran))))
    return out


class Plan(object):
    """the blocks, the buffer, and what has been drawn from them."""

    def __init__(self, budget, steps, roles, past=None):
        self.budget = budget
        self.steps = list(steps)
        self.roles = dict(roles)
        past = past or {}
        known = dict((s, past[s][0]) for s in self.steps
                     if s in past and past[s][0] is not None)
        self.calls = dict((s, past[s][1] if s in past else 1)
                          for s in self.steps)
        self.unit = TOKENS if budget.max_tokens or known else CALLS
        self.cap = self.left(self.unit)
        self.filled = []
        if self.unit == CALLS:
            self.source = ("earlier runs" if any(s in past for s in self.steps)
                           else "one call per step")
            self.blocks = dict(self.calls)
        elif known:
            self.source = "earlier runs"
            self.blocks = self.from_past(known)
        else:
            self.source = "shares"
            self.blocks = self.from_shares()
        total = sum(self.blocks.values())
        if self.cap is None:
            self.buffer = None
        else:
            self.buffer = self.cap - total
        self.allowed = dict(self.blocks)
        self.used = {}
        self.seen = self.now()
        self.risky = []
        need = sum(self.calls.values())
        room = self.left(CALLS)
        if room is not None and need > room:
            self.risky.append("the steps take ~" + str(need) + " calls, the "
                              "call cap leaves " + str(room))
        room = self.left(TOKENS)
        if self.unit == TOKENS and room is not None and total > room:
            self.risky.append("the blocks add up to ~" + str(total)
                              + " tokens, the token cap leaves " + str(room))

    def left(self, unit):
        """-> what the cap in `unit` leaves of the run, None when uncapped."""
        b = self.budget
        if unit == TOKENS:
            return b.max_tokens - b.capped if b.max_tokens else None
        return b.max_calls - b.calls if b.max_calls else None

    def now(self):
        return self.budget.capped if self.unit == TOKENS else self.budget.calls

    def from_shares(self):
        pool = self.cap * (100 - BUFFER) // 100
        weights = dict((s, share(self.roles.get(s))) for s in self.steps)
        whole = sum(weights.values()) or 1
        return dict((s, int(pool * w / whole)) for s, w in weights.items())

    def from_past(self, known):
        """a step with no history is scaled from the ones that have one."""
        out = dict(known)
        weight = sum(share(self.roles.get(s)) for s in known)
        per = float(sum(known.values())) / weight if weight else 0
        for s in self.steps:
            if s not in out:
                out[s] = int(math.ceil(share(self.roles.get(s)) * per))
                self.filled.append(s)
        return out

    def realism(self):
        if self.risky:
            biggest = max(self.steps, key=lambda s: self.blocks[s])
            return ("short: the estimate does not fit the cap. raise the cap,"
                    " or save on the biggest block first (" + biggest + ", ~"
                    + str(self.blocks[biggest]) + " " + self.unit + "); never"
                    " by dropping the red test")
        if self.source == "shares":
            return ("a split, not a forecast: no earlier run of this flow here"
                    " says what its steps take, so the cap is shared out by"
                    " the measured shares")
        if self.cap is None:
            return "no cap, so nothing to fit: the blocks are for reading"
        if self.buffer * BUFFER < self.cap:
            return ("lower bound: the buffer is under a tenth of the cap, and"
                    " one redo can spend it")
        return "comfortable: the buffer is a tenth of the cap or more"

    def text(self):
        caps = []
        b = self.budget
        if b.max_tokens:
            caps.append(str(b.max_tokens) + " tokens")
        if b.max_calls:
            caps.append(str(b.max_calls) + " calls")
        if self.source == "earlier runs":
            source = ("earlier runs of this flow in this project, in "
                      + self.unit)
            if self.filled:
                source = (source + "; " + ", ".join(self.filled)
                          + " scaled from the others by the measured shares")
        elif self.source == "shares":
            source = ("measured shares of a run's spend: "
                      + ", ".join(k + " " + str(v) + "%"
                                  for k, v in sorted(SHARES.items(),
                                                     key=lambda kv: -kv[1])))
        else:
            source = ("one call per step; a fanned-out step counts once until"
                      " its width is known")
        width = max([len(s) for s in self.steps] + [len("buffer")]) + 2
        rows = ["step".ljust(width) + "estimate"]
        for s in self.steps:
            rows.append(s.ljust(width) + str(self.blocks[s]))
        if self.buffer is not None:
            rows.append("buffer".ljust(width) + str(self.buffer))
        out = ["# budget plan", "",
               "cap       " + (", ".join(caps) if caps else "none"),
               "unit      " + self.unit,
               "estimate  " + source,
               "realism   " + self.realism(), ""]
        out = out + ["    " + r for r in rows]
        if self.risky:
            out = out + ["", RISKY + ": " + "; ".join(self.risky)]
        return "\n".join(out) + "\n"

    def write(self, folder):
        (folder / FILE).write_text(self.text(), encoding="utf-8")

    def warning(self):
        """-> the line printed before any call, "" when the plan fits."""
        if not self.risky:
            return ""
        return RISKY + ": " + "; ".join(self.risky) + " (" + FILE + ")"

    def closed(self, step, outcome):
        """-> the health line for a pass of `step` that has just ended."""
        now = self.now()
        took = now - self.seen
        self.seen = now
        self.used[step] = self.used.get(step, 0) + took
        allowed = self.allowed.get(step, 0)
        over = self.used[step] - allowed
        risk = "ok"
        if over > 0:
            self.allowed[step] = allowed + over
            if self.buffer is None:
                risk = "over by " + str(over)
            else:
                self.buffer -= over
                risk = "over by " + str(over) + ", drawn from the buffer"
        elif over < 0 and outcome == "ok":
            self.allowed[step] = self.used[step]
            if self.buffer is not None:
                self.buffer -= over
                risk = "ok, " + str(-over) + " left to the buffer"
        if self.buffer is not None and self.buffer < 0:
            risk = (risk + "; the buffer is spent, the run is "
                    + str(-self.buffer) + " " + self.unit + " over its plan")
        return {"spent": self.used[step], "planned": self.blocks.get(step, 0),
                "buffer": self.buffer, "risk": risk}
