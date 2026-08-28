"""pick a flow back up, using the journal to find where it stopped.

there are two ways to stop short now. a run that died is picked up AT the step
that died, because that step produced nothing. a run that parked for a person
is picked up AFTER the step it parked on, because that step finished and the
only thing missing was the person.
"""
from pathlib import Path

JOURNAL = Path("runs") / "journal.md"

# the journal statuses that mean "this run did not finish", and what kind of
# not-finishing each one is. anything else on the line is a run that ended, and
# ending clears whatever was owed before it.
STOPS = (("failed at ", "failed"), ("parked at ", "parked"))


class Stop(object):
    """where a run stopped, and whether stopping was the point.

    a failure and a park are both "did not finish", and the journal only had a
    word for the first one until the flow could park. keeping them apart is the
    whole difference between rerunning a step and carrying on past it.
    """

    __slots__ = ("kind", "step", "when")

    def __init__(self, kind, step, when):
        self.kind = kind
        self.step = step
        self.when = when

    @property
    def parked(self):
        return self.kind == "parked"


def last_stop(flow_name):
    """-> Stop for the most recent unfinished run of this flow, or None."""
    if not JOURNAL.exists():
        return None
    found = None
    for line in JOURNAL.read_text().split("\n"):
        if not line.strip():
            continue
        parts = [p for p in line.split("  ") if p]
        if len(parts) < 3 or parts[1] != flow_name:
            continue
        for prefix, kind in STOPS:
            if parts[2].startswith(prefix):
                found = Stop(kind, parts[2][len(prefix):], parts[0])
                break
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
    p = Path("runs") / run_id / step
    return p.read_text(encoding="utf-8") if p.exists() else ""


def runs_for(flow):
    runs = Path("runs")
    if not runs.exists():
        return []
    return sorted(p.name for p in runs.iterdir() if p.is_dir() and p.name.startswith(flow + "-"))


def remaining(all_steps, failed_step):
    if failed_step not in all_steps:
        return all_steps
    return all_steps[all_steps.index(failed_step):]


def after(all_steps, done_step):
    """what is left once done_step is done, which is where a park picks up."""
    if done_step not in all_steps:
        return all_steps
    return all_steps[all_steps.index(done_step) + 1:]
