"""what a run did, one json line per step it ran.

`runs/<run id>/steps.jsonl` gets a line every time a step is run - a redo's
second pass is a second line - and it is written whatever happened next: the
run went on, sent the work back, parked, stopped or crashed. what the pass
produced is kept beside it as `steps/<seq>-<step>.md` and the line names that
file, so a redo no longer writes over the review that asked for it.

a line is the same shape every time and in the same key order, so two runs
of the same flow differ only in the time, the ids and the seconds.
"""
import datetime
import json
import time

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


def retries(attempts):
    out = {}
    for a in attempts:
        if a.retries is None:
            return None
        for cause, n in a.retries.items():
            out[cause] = out.get(cause, 0) + n
    return out


def last(attempt, what):
    said = [getattr(r, what) for r in attempt.replies if getattr(r, what)]
    return said[-1] if said else None


def seconds(attempts):
    if not attempts:
        return 0.0
    start = min(a.started for a in attempts)
    return round(max(a.started + a.took() for a in attempts) - start, 1)


def facts(attempts):
    return {"tokens": tokens(attempts), "cost": cost(attempts),
            "seconds": seconds(attempts),
            "cached": bool(attempts) and all(a.cached for a in attempts),
            "retries": retries(attempts)}


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
                 "fanned", "gates", "ungated")

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


class Trail(object):
    """the steps.jsonl of one run folder, and the per-pass step files.

    `after` is where the numbering carries on from: a resumed run counts on
    from the run it picked up, so the two files read as one sequence.
    """

    def __init__(self, folder, after=0):
        self.folder = folder
        self.seq = max(after, last_seq(folder))

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
        return Entry(self.seq, step, attempts, provider, came_from, kept,
                     fanned)

    def close(self, entry, outcome, why=None, to=None):
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.folder / FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(line(entry, outcome, why, to),
                               ensure_ascii=False) + "\n")


def line(entry, outcome, why=None, to=None):
    attempts = entry.attempts
    first = attempts[0] if attempts else None
    p = entry.provider
    said = facts(attempts)
    one = attempts[0] if len(attempts) == 1 and not entry.fanned else None
    tasks = None
    if entry.fanned:
        tasks = []
        for a in attempts:
            task = {"task": a.task}
            task.update(facts([a]))
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
            "tokens": said["tokens"],
            "cost": said["cost"],
            "session": last(one, "session") if one else None,
            "seconds": said["seconds"],
            "cached": said["cached"],
            "retries": said["retries"],
            "gates": [{"gate": g.gate, "ok": bool(g.ok), "detail": g.detail}
                      for g in entry.gates],
            "ungated": entry.ungated,
            "outcome": outcome,
            "why": why,
            "file": entry.file,
            "tasks": tasks,
            "handoff": None}
