"""keeping a waiting step's session warm.

a step that carries its own session on (`continue: resume`) reads most of it
from the cache, and only while the cache still holds it. a step can wait a
long while for its next go: a send-back after a slow step, the lead asked
late in the run. with `--keep-warm`, a session left waiting close to the end
of its cache's lifetime gets one cheap call that reads it whole and keeps
nothing, so the session saved stays as it was.

it is off unless asked for: whether a warm call costs less than the cache
it saves has not been shown. a run that stopped to wait for a person has
no process left to warm anything, so this only covers waits inside one run.
"""
import threading
import time

from .errors import kind_of

FLAG = "--keep-warm"
# the long cache lifetime and the short one, in seconds
LIFETIME = 3600
SHORT = 300
# how long before the end of its lifetime a waiting session is warmed, at
# most; a short lifetime gets a fifth of itself (`margin`)
MARGIN = 300
# warm calls per session, so a step that is never asked again stops costing
MOST = 3
# how often the waiting sessions are looked at
EVERY = 60
# how long one warm call may take; the run waits this long at most for one
# in flight when it ends
TIMEOUT = 120

STARTED = []


def wanted(argv):
    return FLAG in argv


def margin(span):
    """-> how long before the end of a `span`-second lifetime a waiting
    session is warmed."""
    return min(MARGIN, span // 5)


def lifetime(usage, before=None):
    """-> how long the cache of a session that used `usage` lives, from
    where its cache writes went; `before` when it wrote none, None when that
    is not known either."""
    said = usage.get("cache_creation") if isinstance(usage, dict) else None
    if isinstance(said, dict):
        if said.get("ephemeral_1h_input_tokens"):
            return LIFETIME
        if said.get("ephemeral_5m_input_tokens"):
            return SHORT
    return before


class Warmer(object):
    """looks over `run.sessions` and warms the ones that are due. the run
    hands it `sessions`, `busy` (the steps in a call now), `lock`, `budget`,
    `record` and `provider_for(step)`."""

    def __init__(self, run, most=MOST):
        self.run = run
        self.most = most
        self.stopped = threading.Event()
        self.thread = None

    def due(self, kept, now):
        """a session is due once it has waited its cache's lifetime less the
        margin, and not once that lifetime is over: a lapsed cache is built
        again by the step's own next call, which costs no more. the margin
        is a fifth of a short lifetime, so a five-minute cache is warmed
        after four minutes. a session whose lifetime is not known is never
        due."""
        span = kept.get("lifetime")
        if not span:
            return False
        idle = now - kept.get("at", now)
        return kept.get("warmed", 0) < self.most \
            and span - margin(span) <= idle < span

    def tick(self, now=None):
        from agentweft.providers.base import carry_of

        now = time.time() if now is None else now
        run = self.run
        with run.lock:
            waiting = [(step, dict(kept)) for step, kept in run.sessions.items()
                       if step not in run.busy and self.due(kept, now)]
        for step, kept in waiting:
            if self.stopped.is_set() or run.budget.ahead(1):
                return
            used = run.provider_for(step)
            reply = used.warm(carry_of(kept), timeout=TIMEOUT,
                              stop=self.stopped)
            if reply is not None:
                error = None if reply else kind_of(reply).__name__.lower()
                run.budget.charge("", reply, provider=used.name, error=error,
                                  model=used.asks_for())
            with run.lock:
                held = run.sessions.get(step)
                if held is None or held["id"] != kept["id"]:
                    continue
                held["warmed"] = self.most if reply is None \
                    else held.get("warmed", 0) + 1
                if reply:
                    held["at"] = now

    def start(self):
        def loop():
            while not self.stopped.wait(EVERY):
                self.tick()

        STARTED.append(self)
        self.thread = threading.Thread(target=loop, name="keep-warm")
        self.thread.daemon = True
        self.thread.start()
        return self

    def stop(self):
        """end the warm call in flight, if any, and wait for its charge."""
        self.stopped.set()
        if self in STARTED:
            STARTED.remove(self)
        if self.thread is not None:
            self.thread.join(TIMEOUT)


def stop_all():
    while STARTED:
        STARTED.pop().stop()
