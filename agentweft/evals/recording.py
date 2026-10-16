"""a case's provider answers, kept beside it, so the case runs again without
calling anything.

a call is found by the step that made it, the task of a fanned-out step and
which go at that step it was, and the prompt it was sent is kept as a sha256.
matching on the order of the calls alone would hand an edited prompt the old
answer and score the old work as the new; here it stops the case as stale.
a call the recording does not have is an error, and so is a recorded answer
the run never asked for: either way the recording is of some other run.

the files an answer left in the place are kept with it and written again
when it is replayed, so a step's gates find what they found when it ran.
"""
import datetime
import hashlib
import json
import re
import sys
import threading
from pathlib import Path

from agentweft.providers.base import Provider, Reply, Usage
from agentweft.providers.fake_provider import write_into

FILE = "recording.json"
PREFIX = "recording "
# the head of what the runner adds to a prompt when a gate sent the step back
GATE_SAID = "your last answer failed a gate, so this step runs again."
DURATION = re.compile(r"(?<= in )\d+(?:\.\d+)?s\b")


def spellings(path):
    """-> every way a path may be written into a prompt, longest first."""
    p = Path(str(path))
    out = {str(path), str(path).replace("\\", "/"), str(p), p.as_posix()}
    try:
        out.add(str(p.resolve()))
        out.add(p.resolve().as_posix())
    except OSError:
        pass
    return sorted(out, key=len, reverse=True)


def neutral(prompt, place=None):
    """-> the prompt as any machine would have sent it.

    the place a case runs in is a new temp folder every run, named the way
    its OS names it, and a gate that failed says it, says the python it ran
    and hands on the tail of what that printed, separators, timings and all.
    those become `<place>` and `<python>` wherever they are, and in what a
    gate said a backslash is a slash and a duration is `<secs>s`. the words
    the step was given are left as they are."""
    text = (prompt or "").replace("\r\n", "\n")
    for where, name in ((sys.executable, "<python>"), (place, "<place>")):
        if where:
            for spelt in spellings(where):
                text = text.replace(spelt, name)
    head, said, tail = text.partition(GATE_SAID)
    if said:
        tail = DURATION.sub("<secs>s", tail.replace("\\", "/"))
    return head + said + tail


def digest(prompt, place=None):
    """-> the sha256 of a prompt made `neutral`, so a recording made on one
    machine is not stale on another."""
    return hashlib.sha256(neutral(prompt, place).encode("utf-8")).hexdigest()


class Mismatch(Exception):
    """the run asked for something the recording cannot answer as asked."""


def named(step, task, go=None):
    out = step + ("" if task is None else " task " + str(task))
    return out if go is None else out + " go " + str(go)


class Goes(object):
    """which call this is. the tasks of a fanned-out step ask from threads of
    their own, so the step asking is kept per thread."""

    def __init__(self):
        self.now = threading.local()
        self.counted = {}
        self.lock = threading.Lock()

    def at(self, step, task):
        self.now.key = (step, task)

    def next(self):
        step, task = getattr(self.now, "key", ("?", None))
        with self.lock:
            go = self.counted.get((step, task), 0) + 1
            self.counted[(step, task)] = go
        return step, task, go


def kept(reply):
    usage = reply.usage
    out = {"say": reply.text or "", "detail": reply.detail or "",
           "retryable": reply.retryable, "outage": reply.outage,
           "model": reply.model, "session": reply.session, "cost": reply.cost,
           "usage": None if usage is None
           else {"raw": usage.raw, "requests": usage.requests},
           "models": None if not reply.models
           else {k: u.raw for k, u in reply.models.items()}}
    if reply.metered:
        out["metered"] = reply.metered
        out["guess"] = reply.guess
    if getattr(reply, "writes", None):
        out["writes"] = dict(reply.writes)
    return out


def reply_of(call):
    usage = call.get("usage")
    models = call.get("models")
    return Reply(call.get("say") or "", detail=call.get("detail") or "",
                 metered=call.get("metered"), guess=call.get("guess"),
                 usage=None if usage is None
                 else Usage(usage["raw"], usage.get("requests")),
                 cost=call.get("cost"), session=call.get("session"),
                 model=call.get("model"), retryable=call.get("retryable"),
                 outage=call.get("outage"), writes=call.get("writes"),
                 models=None if not models
                 else {k: Usage(raw) for k, raw in models.items()})


class Recorder(Provider):
    """the case's own provider, with every answer it gives written down."""

    def __init__(self, inner):
        Provider.__init__(self)
        self.inner = inner
        self.name = inner.name
        self.command = inner.command
        self.reads_place = inner.reads_place
        self.goes = Goes()
        self.calls = []
        self.lock = threading.Lock()
        self.began = datetime.datetime.now().replace(microsecond=0)

    @property
    def where(self):
        return self.inner.where

    @where.setter
    def where(self, value):
        self.inner.where = value

    def at(self, step, task):
        self.goes.at(step, task)
        self.inner.at(step, task)

    def asks_for(self):
        return self.inner.asks_for()

    def chooses_model(self):
        return self.inner.chooses_model()

    @property
    def going(self):
        return self.inner.going

    @going.setter
    def going(self, value):
        self.inner.going = value

    @property
    def terse(self):
        return self.inner.terse

    @terse.setter
    def terse(self, value):
        self.inner.terse = value

    def output_limit(self):
        return self.inner.output_limit()

    def own_effort(self):
        return self.inner.own_effort()

    def chooses_effort(self):
        return self.inner.chooses_effort()

    def check(self):
        return self.inner.check()

    def ask(self, prompt, timeout=None):
        step, task, go = self.goes.next()
        reply = self.inner.ask(prompt, timeout=timeout)
        call = {"step": step, "task": task, "go": go,
                "prompt": digest(prompt, self.where)}
        call.update(kept(reply))
        with self.lock:
            self.calls.append(call)
        return reply

    def blob(self):
        return {"recorded": self.began.isoformat(), "provider": self.inner.name,
                "asked": self.inner.asks_for(),
                "calls": sorted(self.calls, key=lambda c: (
                    c["step"], c["task"] or 0, c["go"]))}

    def save(self, path):
        Path(path).write_bytes((json.dumps(self.blob(), indent=2,
                                           ensure_ascii=True) + "\n")
                               .encode("utf-8"))


class Replay(Provider):
    """answers from a recording and from nothing else."""

    name = "replay"

    def __init__(self, blob):
        Provider.__init__(self)
        self.recorded = blob.get("asked")
        self.calls = {(c["step"], c["task"], c["go"]): c
                      for c in blob.get("calls") or []}
        self.used = set()
        self.goes = Goes()
        self.lock = threading.Lock()

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_bytes().decode("utf-8")))

    def at(self, step, task):
        self.goes.at(step, task)

    def asks_for(self):
        return self.recorded

    def ask(self, prompt, timeout=None):
        key = self.goes.next()
        call = self.calls.get(key)
        if call is None:
            raise Mismatch(PREFIX + "has no answer for " + named(*key))
        if call["prompt"] != digest(prompt, self.where):
            raise Mismatch(PREFIX + "is stale: " + named(key[0], key[1])
                           + " prompt changed")
        with self.lock:
            self.used.add(key)
        write_into(self.where, call.get("writes"))
        return reply_of(call)

    def unused(self):
        """-> the recorded calls this run never made, by name."""
        return [named(*k) for k in sorted(self.calls, key=lambda k: (
            k[0], k[1] or 0, k[2])) if k not in self.used]

    def check(self):
        return True, "replays " + str(len(self.calls)) + " recorded calls"
