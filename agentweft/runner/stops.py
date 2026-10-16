"""why a run stopped, from a list that does not grow by accident, and the
journal line that says so.

every stop names one of CAUSES: in its journal line, in its step's line in
steps.jsonl and in runs/<run id>/why.md. the rollup counts by them, so a cause
made up where the run stopped would be a bucket nobody reads.

the journal has three shapes of line, the same first four columns in each:

    <when>  <flow>  running  0s  <run id>  [resumes <origin>]
    <when>  <flow>  failed at <step>  <secs>s  <run id>  <cause>  <spend>  <why>  <run id>/handoff.md  [resumes <origin>]
    <when>  <flow>  ok  <secs>s  <run id>  <saved as>  <spend>  <run id>/handoff.md  [resumes <origin>]

a stop is `parked at` when the run is waiting for someone, `refused at` when
a step declined the work and cited the spec line that says why, `stopped at`
when a step found the request contradicts a spec line it quoted or the run's
change could not be signed off against its branch, `failed at` for
everything else. `<when>` is when the run started, on every line it writes.

the run's outcome, the word a program reads, is `done` (with the count of
checks nobody could decide, when there were any) or the one OUTCOME maps the
cause to. it is the first thing after the run id in handoff.md and on the
console, and `outcome` in manifest.json.

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
# a step's own refusal, with a cited spec line. REFUSED is the runner
# refusing to start a step, which is a stop; this is an answer, and the run
# ends on it
DECLINED = "declined"
# a step found the request contradicts a line of the spec, quoted it, and the
# quote was there. nothing broke, so it is not a gate failure; it waits for
# someone to say which one holds, and carrying on runs that step again
CONFLICT = "conflict"
# the tasks of a fanned-out step wrote a file one of them did not name, or
# the same file twice
OVERLAP = "overlap"
# the branch the run's change is for moved while it ran, and the change no
# longer merges onto it
MOVED = "target moved"
# the change could not be checked against the branch with read-only git, so
# a person has to
UNCHECKED = "merge unchecked"

CAUSES = (GATE, REFUSED, PARKED, OUTAGE, BUDGET, EXCEPTION, INTERRUPT,
          NO_ANSWER, DECLINED, CONFLICT, OVERLAP, MOVED, UNCHECKED)

# the run waits for someone on these: a person for a park or a cap, the
# provider's limit for an outage
WAITING = (PARKED, OUTAGE, BUDGET)
# a wait on these comes before the step it names has done its work, so
# carrying on runs that step rather than the one after it
AGAIN = (OUTAGE, BUDGET)

DONE = "done"
# no default: a cause added without an outcome fails where it is read rather
# than ending runs under a word nobody chose
OUTCOME = {GATE: "stopped: gate failed",
           REFUSED: "stopped: guard refused",
           PARKED: "needs you: ruling",
           OUTAGE: "waiting: provider limit",
           BUDGET: "needs you: budget",
           EXCEPTION: "stopped: tool fault",
           INTERRUPT: "stopped: interrupted",
           NO_ANSWER: "stopped: tool fault",
           DECLINED: "refused (spec cited)",
           CONFLICT: "stopped: spec conflict",
           OVERLAP: "stopped: tasks overlap",
           MOVED: "stopped: target moved",
           UNCHECKED: "stopped: merge unchecked"}
OUTCOMES = (DONE,) + tuple(sorted(set(OUTCOME.values())))

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
    if checked(cause) == DECLINED:
        return "refused at " + step
    if cause in (CONFLICT, MOVED, UNCHECKED):
        return "stopped at " + step
    return ("parked at " if cause in WAITING else "failed at ") + step


def outcome(cause):
    """-> the outcome of a run that stopped for `cause`."""
    return OUTCOME[checked(cause)]


def done(unproven=0):
    """-> the outcome of a run that got through, with the checks nobody could
    decide counted so it never reads as a clean finish."""
    if not unproven:
        return DONE
    return (DONE + ", " + str(unproven) + " check"
            + ("" if unproven == 1 else "s") + " unproven")


def exit_code(cause):
    if checked(cause) == DECLINED:
        return EXIT_OK
    return EXIT_INTERRUPT if cause == INTERRUPT else EXIT_STOP


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
