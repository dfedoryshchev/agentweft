"""the runner's own seconds, by phase.

a run's wall is its steps' model time, its gates' time and the runner's own
time between and around them. the loop names the phase it goes into, and
each phase holds the seconds from going into it to going into the next; the
seconds a step's model or a gate took inside it are taken out, so the steps,
the gates and the phases add up to the wall.

the phases, in the order a step meets them:

- setup: from the run's start to its first step: the place, the plan, the
  trail
- sizing: whether the reviewers run on a change this size
- before: the checks before a step is asked: refusals, the budget, the
  sign-off, the preflight
- snapshot: the place read and fingerprinted before the step
- step: the step's call less its model's time: the brief, the prompt, the
  answer and its block read back
- trail: the answer written down and its line opened, the transcript reads
  with it
- police: what police saw of the step
- asks: whether the answer stops the run, asks a question, or goes to the
  lead, less the lead's model time
- checks: the step's gates' own upkeep, less the gates: the fact checks,
  the spec and test rulings
- after: what follows the gates up to the next step: the red proof, the
  preflight after, the record
- finish, stop: the run ending, done or short, up to its handoff
- handoff: the handoff written, up to the wall's own reading
"""
import time

PHASES = ("setup", "sizing", "before", "snapshot", "step", "trail", "police",
          "asks", "checks", "after", "finish", "stop", "handoff")


class Laps(object):
    """the phases one leg of a run went through, from `began`, the clock
    time its wall is read from."""

    def __init__(self, began, phase="setup"):
        self.began = began
        self.now = phase
        self.at = began
        self.laps = []

    def to(self, phase):
        """the phase the runner goes into now."""
        here = time.time()
        self.laps.append((self.now, self.at, here))
        self.now, self.at = phase, here

    def end(self):
        """-> the wall up to now, the last phase closed with it."""
        self.to(self.now)
        return self.at - self.began

    def seconds(self, busy):
        """-> {phase: seconds}, every one of PHASES, the time each lap held
        less what of `busy`, (start, end) of the model's and the gates'
        time, fell inside it."""
        spans = merged(busy)
        out = dict((p, 0.0) for p in PHASES)
        for phase, start, end in self.laps:
            out[phase] = out.get(phase, 0.0) + (end - start) \
                - overlap(spans, start, end)
        return dict((p, round(max(s, 0.0), 1) + 0.0) for p, s in out.items())


def merged(spans):
    """-> `spans` as (start, end) that do not overlap, in order."""
    out = []
    for start, end in sorted(s for s in spans if s[1] > s[0]):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def overlap(spans, start, end):
    return sum(max(0.0, min(e, end) - max(s, start)) for s, e in spans)


def said(phases):
    """-> the handoff's line of the runner's seconds by phase."""
    return "- runner by phase: " + ", ".join(
        p + " " + str(phases[p]) + "s" for p in PHASES if p in phases)
