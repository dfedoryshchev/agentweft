"""why a run stopped, from a list that does not grow by accident, and the
journal line that says so.

every stop names one of CAUSES: in its journal line, in its step's line in
steps.jsonl and in runs/<run id>/why.md. the rollup counts by them, so a cause
made up where the run stopped would be a bucket nobody reads.

the journal has three shapes of line, the same first four columns in each:

    <when>  <flow>  running  0s  <run id>  [resumes <origin>]
    <when>  <flow>  failed at <step>  <secs>s  <run id>  <cause>  <spend>  <why>  <run id>/handoff.md  [resumes <origin>]
    <when>  <flow>  ok  <secs>s  <run id>  <saved as>  <spend>  <run id>/handoff.md  [resumes <origin>]

a stop is `parked at` when the run is waiting for someone, `failed at` for
everything else. `<when>` is when the run started, on every line it writes.

two columns can follow, each read off the end of the line by what it looks
like, so a line written before either existed still reads: the run's handoff,
`<run id>/handoff.md`, the file to read about it; and, on a resumed run,
which gets an id of its own, `resumes <run id>`: the run the task started as,
however many times it has been picked up since. that is what ties one task's
lines together.
"""
import datetime

GATE = "gate failed"
REFUSED = "refused"
PARKED = "parked"
OUTAGE = "provider outage"
BUDGET = "budget"
EXCEPTION = "exception"
INTERRUPT = "interrupt"
NO_ANSWER = "no answer"

CAUSES = (GATE, REFUSED, PARKED, OUTAGE, BUDGET, EXCEPTION, INTERRUPT,
          NO_ANSWER)

# the run waits for someone on these: a person for a park, the provider's
# limit for an outage
WAITING = (PARKED, OUTAGE)

EXIT_OK = 0
EXIT_STOP = 2
EXIT_INTERRUPT = 130

RUNNING = "running"
STAMP = "%Y-%m-%d %H:%M"

# what the journal said before the cause had a column of its own
OLD = (("refused at ", REFUSED), ("over budget at ", BUDGET),
       ("parked at ", PARKED), ("failed at ", NO_ANSWER))


def checked(cause):
    if cause not in CAUSES:
        raise ValueError("not a cause a run stops for: " + repr(cause)
                         + ". there is: " + ", ".join(CAUSES))
    return cause


def status(cause, step):
    """-> the journal's third column for a stop."""
    return ("parked at " if checked(cause) in WAITING else "failed at ") + step


def exit_code(cause):
    return EXIT_INTERRUPT if checked(cause) == INTERRUPT else EXIT_STOP


def of(error):
    """-> the cause for something raised while a step ran."""
    from .errors import Outage

    if isinstance(error, KeyboardInterrupt):
        return INTERRUPT
    if isinstance(error, Outage):
        return OUTAGE
    return EXCEPTION


def flat(text):
    """one line with no double space in it: the journal splits on those."""
    return " ".join(str(text or "").split())


RESUMES = "resumes "
HANDOFF = "/handoff.md"


def line(started, flow, state, secs, run=None, cause=None, spend=None,
         why=None, saved=None, handoff=None, origin=None):
    """-> one journal line, without its newline."""
    parts = [started.strftime(STAMP), flow, state, str(int(secs)) + "s"]
    if run:
        parts.append(run)
    if cause is not None:
        parts = parts + [checked(cause), spend or "0 calls, 0 tokens",
                         flat(why) or cause]
    elif saved is not None:
        parts = parts + [saved, spend or "0 calls, 0 tokens"]
    if handoff:
        parts.append(handoff)
    if origin:
        parts.append(RESUMES + origin)
    return "  ".join(parts)


class Line(object):
    """one journal line, read back. what a column did not say is None."""

    __slots__ = ("when", "flow", "status", "secs", "run", "cause", "spend",
                 "why", "saved", "step", "handoff", "origin")

    def __init__(self, when, flow, status, secs):
        self.when = when
        self.flow = flow
        self.status = status
        self.secs = secs
        self.run = self.cause = self.spend = self.why = None
        self.saved = self.step = self.handoff = self.origin = None

    @property
    def kind(self):
        """-> "running", "ok" or "stop"."""
        if self.status == RUNNING:
            return "running"
        return "stop" if self.cause else "ok"

    @property
    def parked(self):
        return self.status.startswith("parked at ")


def read(text):
    """-> Line, or None for a line too short to be one."""
    parts = [p.strip() for p in text.split("  ") if p.strip()]
    origin = pointed = None
    if len(parts) > 4 and parts[-1].startswith(RESUMES):
        origin = parts.pop()[len(RESUMES):]
    if len(parts) > 4 and parts[-1].endswith(HANDOFF):
        pointed = parts.pop()
    if len(parts) < 4:
        if len(parts) < 3:
            return None
        parts.append("0s")
    out = Line(parts[0], parts[1], parts[2], parts[3])
    out.handoff = pointed
    out.origin = origin
    rest = parts[4:]
    if out.status == RUNNING:
        out.run = rest[0] if rest else None
        return out
    if out.status.startswith("ok"):
        if rest and not rest[0].endswith(".md"):
            out.run, rest = rest[0], rest[1:]
        out.saved = rest[0] if rest else None
        out.spend = rest[1] if len(rest) > 1 else None
        return out
    if len(rest) >= 3:
        # the old stop lines had two columns after the seconds at most. the
        # cause is read as written, so one off the list fails whoever counts
        out.run, out.cause, out.spend = rest[0], rest[1], rest[2]
        out.why = "  ".join(rest[3:]) or None
    else:
        out.cause = old_cause(out.status)
        if rest and rest[-1].startswith(out.flow.replace(" ", "-") + "-"):
            out.run = rest[-1]
    out.step = stopped_at(out.status) if out.cause else None
    return out


def old_cause(state):
    if state.startswith("gate ") and " failed at " in state:
        return GATE
    for prefix, cause in OLD:
        if state.startswith(prefix):
            return cause
    return None


def stopped_at(state):
    step = state.rsplit(" at ", 1)[-1]
    # the old refusal line went on after the step: "refused at x.md, the
    # place changed"
    return step.split(",")[0].strip()


def parse_when(text):
    return datetime.datetime.strptime(text, STAMP)
