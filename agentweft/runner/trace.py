"""what a run did, one json line per step it ran.

`runs/<run id>/steps.jsonl` gets a line every time a step is run - a redo's
second pass is a second line - and it is written whatever happened next: the
run went on, sent the work back, parked, stopped or crashed. what the pass
produced is kept beside it as `steps/<seq>-<step>.md` and the line names that
file, so a redo no longer writes over the review that asked for it.

a line is the same shape every time and in the same key order, so two runs
of the same flow differ only in the time, the ids and the seconds. a gate's
entry carries `tests` only when that gate ran tests one by one. `handoff`
is the step's HANDOFF block as `runner/handoff.py` parsed it, with each
VERIFIED claim marked against the step's transcript; null only on a line
closed before the step answered.
"""
import datetime
import json
import time
from decimal import Decimal

from .task import FILE as TASK

FILE = "steps.jsonl"
FOLDER = "steps"


class Attempt(object):
    """one go at a step, from the moment it was asked until it answered.

    `replies` is every reply it took, failed goes included, because each of
    them was paid for. `retries` stays None until there is an answer: a step
    that crashed went some number of times, and nothing here knows how many.
    """

    __slots__ = ("task", "began", "started", "seconds", "cached", "replies",
                 "retries")

    def __init__(self, task=None):
        self.task = task
        self.began = datetime.datetime.now()
        self.started = time.time()
        self.seconds = None
        self.cached = False
        self.replies = []
        self.retries = None

    def answered(self, answer):
        """-> the answer, untouched, once what came with it is noted."""
        self.seconds = round(time.time() - self.started, 1)
        self.cached = bool(answer[1])
        self.replies = list(getattr(answer, "replies", ()))
        self.retries = dict(getattr(answer, "retries", None) or {})
        return answer

    def took(self):
        if self.seconds is not None:
            return self.seconds
        return round(time.time() - self.started, 1)


def tokens(attempts):
    """counted only when every reply was counted by whoever answered it. a sum
    with one estimate in it would read as a count."""
    replies = [r for a in attempts for r in a.replies]
    if not replies or any(r.usage is None for r in replies):
        return {"counted": False}
    return {"counted": True,
            "input": sum(r.usage.input_tokens for r in replies),
            "output": sum(r.usage.output_tokens for r in replies),
            "cache_read": sum(r.usage.cache_read_input_tokens for r in replies),
            "cache_creation": sum(r.usage.cache_creation_input_tokens
                                  for r in replies)}


def cost(attempts):
    """USD as the providers stated it, None when any of them did not say."""
    if attempts and all(a.cached for a in attempts):
        return 0
    asked = [a for a in attempts if not a.cached]
    costs = [r.cost for a in asked for r in a.replies]
    if not costs or any(c is None for c in costs):
        return None
    return round(sum(costs), 6)


def priced(attempts, model=None):
    """USD by the price table, None when any reply was not counted or could
    not be priced. `model` is the id asked for, for a reply that names none."""
    from agentweft.guardrails import prices

    if attempts and all(a.cached for a in attempts):
        return 0
    replies = [r for a in attempts if not a.cached for r in a.replies]
    if not replies or any(r.usage is None for r in replies):
        return None
    table = prices.load()
    total = prices.Priced(Decimal(0))
    for r in replies:
        total = total + prices.of_reply(table, r, asked=model)
    return prices.stored(total.usd)


def retries(attempts):
    out = {}
    for a in attempts:
        if a.retries is None:
            return None
        for cause, n in a.retries.items():
            out[cause] = out.get(cause, 0) + n
    return out


def killed(attempts):
    """the processes a step left running that were ended with it. None when no
    reply said, which a step that started no process never does."""
    said = [getattr(r, "killed", None) for a in attempts for r in a.replies]
    said = [n for n in said if n is not None]
    return sum(said) if said else None


def last(attempt, what):
    said = [getattr(r, what) for r in attempt.replies if getattr(r, what)]
    return said[-1] if said else None


def seconds(attempts):
    if not attempts:
        return 0.0
    start = min(a.started for a in attempts)
    return round(max(a.started + a.took() for a in attempts) - start, 1)


def facts(attempts, model=None):
    return {"tokens": tokens(attempts), "cost": cost(attempts),
            "priced": priced(attempts, model),
            "seconds": seconds(attempts),
            "cached": bool(attempts) and all(a.cached for a in attempts),
            "retries": retries(attempts),
            "background_killed": killed(attempts)}


def last_seq(folder):
    """-> the highest seq written into folder's steps.jsonl, 0 when none."""
    path = folder / FILE
    if not path.exists():
        return 0
    seen = [0]
    for text in path.read_text(encoding="utf-8").split("\n"):
        try:
            seen.append(int(json.loads(text)["seq"]))
        except (ValueError, KeyError, TypeError):
            # a line cut short by the process dying under it
            continue
    return max(seen)


class Entry(object):
    """a line that has a number and a file but not yet an outcome."""

    __slots__ = ("seq", "step", "attempts", "provider", "came_from", "file",
                 "fanned", "gates", "ungated", "handoff")

    def __init__(self, seq, step, attempts, provider, came_from, file, fanned):
        self.seq = seq
        self.step = step
        self.attempts = sorted(attempts, key=lambda a: a.task or 0)
        self.provider = provider
        self.came_from = came_from
        self.file = file
        self.fanned = fanned
        self.gates = []
        self.ungated = None
        self.handoff = None


class Trail(object):
    """the steps.jsonl of one run folder, and the per-pass step files.

    `after` is where the numbering carries on from: a resumed run counts on
    from the run it picked up, so the two files read as one sequence.
    """

    def __init__(self, folder, after=0):
        self.folder = folder
        self.seq = max(after, last_seq(folder))
        self.unclosed = []
        self.closed = []
        self.task_file = TASK if (folder / TASK).is_file() else None

    def open(self, step, attempts, provider, came_from, output=None,
             fanned=False):
        self.seq = self.seq + 1
        kept = None
        if output is not None:
            name = step if step.endswith(".md") else step + ".md"
            kept = FOLDER + "/" + "%03d" % self.seq + "-" + name
            path = self.folder / kept
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output, encoding="utf-8")
        entry = Entry(self.seq, step, attempts, provider, came_from, kept,
                      fanned)
        self.unclosed.append(entry)
        return entry

    def close(self, entry, outcome, why=None, to=None, cause=None):
        self.folder.mkdir(parents=True, exist_ok=True)
        if entry in self.unclosed:
            self.unclosed.remove(entry)
        self.closed.append((entry, outcome))
        with open(self.folder / FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(line(entry, outcome, why, to, cause,
                                    self.task_file),
                               ensure_ascii=False) + "\n")

    def still_open(self):
        """-> the entry opened and not yet given an outcome, or None."""
        return self.unclosed[-1] if self.unclosed else None


def gate_line(g):
    out = {"gate": g.gate, "ok": bool(g.ok), "detail": g.detail}
    if g.unproven:
        out["unproven"] = list(g.unproven)
    if getattr(g, "tests", None) is not None:
        out["tests"] = g.tests
    return out


def line(entry, outcome, why=None, to=None, cause=None, task_file=None):
    attempts = entry.attempts
    first = attempts[0] if attempts else None
    p = entry.provider
    said = facts(attempts, p.asks_for())
    one = attempts[0] if len(attempts) == 1 and not entry.fanned else None
    tasks = None
    if entry.fanned:
        tasks = []
        for a in attempts:
            task = {"task": a.task}
            task.update(facts([a], p.asks_for()))
            task["session"] = last(a, "session")
            task["model_reported"] = last(a, "model")
            tasks.append(task)
    return {"seq": entry.seq,
            "time": (first.began if first else datetime.datetime.now())
            .isoformat(timespec="seconds"),
            "step": entry.step,
            "from": entry.came_from,
            "to": to,
            "provider": p.name,
            "command": p.command,
            "model": p.asks_for(),
            "model_reported": last(one, "model") if one else None,
            "model_choice": getattr(p, "choice", None),
            "grant": p.granted(),
            "tokens": said["tokens"],
            "cost": said["cost"],
            "priced": said["priced"],
            "session": last(one, "session") if one else None,
            "seconds": said["seconds"],
            "cached": said["cached"],
            "retries": said["retries"],
            "background_killed": said["background_killed"],
            "gates": [gate_line(g) for g in entry.gates],
            "ungated": entry.ungated,
            "outcome": outcome,
            "cause": cause,
            "why": why,
            "file": entry.file,
            "task_file": task_file,
            "tasks": tasks,
            "handoff": entry.handoff}
