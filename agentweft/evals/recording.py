"""a case's provider answers, kept beside it, so the case runs again without
calling anything.

a call is found by the step that made it, the task of a fanned-out step and
which go at that step it was, and the prompt it was sent is kept as a sha256.
matching on the order of the calls alone would hand an edited prompt the old
answer and score the old work as the new; here it stops the case as stale.
a call the recording does not have is an error, and so is a recorded answer
the run never asked for: either way the recording is of some other run.
"""
import datetime
import hashlib
import json
import threading
from pathlib import Path

from agentweft.providers.base import Provider, Reply, Usage

FILE = "recording.json"
PREFIX = "recording "


def digest(prompt):
    """-> the sha256 of a prompt, the same for a checkout with CRLF endings."""
    text = (prompt or "").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
                 outage=call.get("outage"),
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

    def asks_for(self):
        return self.inner.asks_for()

    def chooses_model(self):
        return self.inner.chooses_model()

    def check(self):
        return self.inner.check()

    def ask(self, prompt, timeout=None):
        step, task, go = self.goes.next()
        reply = self.inner.ask(prompt, timeout=timeout)
        call = {"step": step, "task": task, "go": go, "prompt": digest(prompt)}
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
        if call["prompt"] != digest(prompt):
            raise Mismatch(PREFIX + "is stale: " + named(key[0], key[1])
                           + " prompt changed")
        with self.lock:
            self.used.add(key)
        return reply_of(call)

    def unused(self):
        """-> the recorded calls this run never made, by name."""
        return [named(*k) for k in sorted(self.calls, key=lambda k: (
            k[0], k[1] or 0, k[2])) if k not in self.used]

    def check(self):
        return True, "replays " + str(len(self.calls)) + " recorded calls"
