"""pick a run back up where it stopped.

there are two ways to stop short. a run that died is picked up AT the step
that died, because that step produced nothing. a run that parked for a person
is picked up AFTER the step it parked on, because that step finished and the
only thing missing was the person - unless it parked before that step ran,
when the manifest keeps the step as not run and the resume starts at it.

where a run stopped is read from its own `manifest.json` (see `manifest`); the
journal is only asked about a run from before there was one.
"""
import re

from . import manifest, state, stops

JOURNAL = None


class Stop(object):
    """where a run stopped, why, and whether stopping was the point.

    a failure and a park are both "did not finish", and the journal only had a
    word for the first one until the flow could park. keeping them apart is the
    whole difference between rerunning a step and carrying on past it.

    an outage is written as a park, because the run is waiting, but what it
    waits on is the provider: the step it parked on got no answer and runs
    again.
    """

    __slots__ = ("kind", "step", "when", "cause")

    def __init__(self, kind, step, when, cause=None):
        self.kind = kind
        self.step = step
        self.when = when
        self.cause = cause

    @property
    def parked(self):
        return self.kind == "parked" and self.cause != stops.OUTAGE


def last_stop(flow_name):
    """-> Stop for the most recent unfinished run of this flow, or None."""
    journal = JOURNAL or state.RUNS / "journal.md"
    if not journal.exists():
        return None
    found = None
    for text in journal.read_text(encoding="utf-8").split("\n"):
        line = stops.read(text)
        if line is None or line.flow != flow_name:
            continue
        if line.kind == "running":
            # says a run began, not how it ended. one that died without a
            # word leaves the stop before it where it was
            continue
        if line.kind == "stop":
            found = Stop("parked" if line.parked else "failed", line.step,
                         line.when, line.cause)
        else:
            # a later good run means there is nothing to pick up
            found = None
    return found


def last_failure(flow_name):
    """-> (step, when) of the most recent failed run for this flow, or None.

    a park is not a failure and does not answer this. the caller that wants
    either kind asks last_stop.
    """
    stop = last_stop(flow_name)
    if stop and stop.kind == "failed":
        return (stop.step, stop.when)
    return None


def step_output(run_id, step):
    # the step files are written with encoding="utf-8" and were being read back
    # with the platform default, which on this machine is cp1252. a digest with
    # a single smart quote in it came back as a UnicodeDecodeError, and only
    # ever on resume, which is the least convenient place to find out.
    p = state.RUNS / run_id / step
    return p.read_text(encoding="utf-8") if p.exists() else ""


def workdir(run_id):
    """-> the place that run worked in, or "" for a run that never said."""
    p = state.RUNS / run_id / "workdir"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def runs_for(flow):
    """-> the run folders of this flow, oldest first.

    matched on the whole name: `fix-` is also the start of every run of a flow
    called fix-with-test.
    """
    runs = state.RUNS
    if not runs.exists():
        return []
    named = re.compile(re.escape(flow) + r"-\d{4}-\d{2}-\d{2}-\d+(-\d+)?$")
    found = [p.name for p in runs.iterdir() if p.is_dir() and named.match(p.name)]
    return sorted(found, key=order_of)


def order_of(run_id):
    """a second run started in the same second as another is `<id>-2`."""
    m = re.match(r"(.*?-\d{4}-\d{2}-\d{2}-\d+)(?:-(\d+))?$", run_id)
    if not m:
        return (run_id, 0)
    return (m.group(1), int(m.group(2) or 1))


def stop_of(run_id):
    """-> the last journal Line of that run, or None when it wrote none."""
    journal = JOURNAL or state.RUNS / "journal.md"
    if not journal.exists():
        return None
    found = None
    for text in journal.read_text(encoding="utf-8").split("\n"):
        line = stops.read(text)
        if line is not None and line.run == run_id:
            found = line
    return found


def finished(run_id, kept):
    if kept is not None:
        return kept.state == manifest.FINISHED
    line = stop_of(run_id)
    return line is not None and line.kind == "ok"


def start_at(run_id, order, kept=None):
    """-> the step a resume of run_id starts at, None when nothing is left.

    the manifest answers when there is one: the first step nothing passed
    for. a run from before manifests is read off its own journal lines, and
    one with no end line died without a word, so it starts at the first step
    with no output on disk.
    """
    if kept is not None:
        return kept.start_at(order)
    line = stop_of(run_id)
    if line is not None and line.kind == "stop":
        if line.parked and line.cause != stops.OUTAGE:
            left = after(order, line.step)
        else:
            left = remaining(order, line.step)
        return left[0] if left else None
    for step in order:
        if not (state.RUNS / run_id / step).exists():
            return step
    return None


def remaining(all_steps, failed_step):
    if failed_step not in all_steps:
        return all_steps
    return all_steps[all_steps.index(failed_step):]


def after(all_steps, done_step):
    """what is left once done_step is done, which is where a park picks up."""
    if done_step not in all_steps:
        return all_steps
    return all_steps[all_steps.index(done_step) + 1:]
