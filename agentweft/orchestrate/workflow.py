"""read the workflow layer i brought over from my own product.

over there this is prose. the phases are a diagram in a markdown file, the
agents are markdown files telling an agent to read other markdown files, and the
whole thing is held together by the agents doing what they were asked. ten months
of running it says that works about as well as you would expect.

so the first thing it gets here is a file that can be parsed. that is all this
module does: it reads workflow.yaml and tells you what it says. nothing checks
that a phase finished, nothing stops at a gate, nothing charges a budget. the
runner does all of that for a flow already, and a phase is not a flow yet.
"""
from pathlib import Path

import yaml

# same shape as FLOW_ROOT: a list so a test can point it somewhere else.
ROOT = ["orchestrate"]


def root():
    return Path(ROOT[0])


class Agent(object):
    """one launch of one named agent. two of them can be the same agent."""

    __slots__ = ("name", "personality", "raw")

    def __init__(self, raw):
        if isinstance(raw, str):
            raw = {"agent": raw}
        self.raw = raw
        self.name = raw["agent"]
        self.personality = raw.get("personality", "")

    def prompt(self):
        return root() / "agents" / (self.name + ".md")

    def __str__(self):
        if self.personality:
            return self.name + " (" + self.personality + ")"
        return self.name


class Phase(object):
    __slots__ = ("name", "agents", "produces", "entry", "exit", "gate", "loop",
                 "sequential", "raw")

    def __init__(self, raw):
        self.raw = raw
        self.name = raw["name"]
        self.agents = [Agent(a) for a in raw.get("agents") or []]
        self.produces = raw.get("produces", "")
        # what has to be true to start, and what has to be true to be done.
        # `produces` is the artifact; these two are the conditions around it,
        # which is a different question - a phase can produce its doc and still
        # not be finished with it.
        #
        # NOTHING CHECKS EITHER OF THESE. they are prose, and prose is the weak
        # kind of criterion: it only binds an agent that reads it and agrees.
        # writing them down is still worth it, because over there they were not
        # written down at all - the entry condition was me looking at the thing
        # and deciding it was ready.
        self.entry = raw.get("entry", "")
        self.exit = raw.get("exit", "")
        # who it stops for. "user" is the only answer so far and it is the whole
        # reason the thing is usable: full autonomy between two known points.
        self.gate = raw.get("gate", "")
        self.loop = int(raw.get("loop") or 1)
        self.sequential = bool(raw.get("sequential"))


class Workflow(object):
    __slots__ = ("name", "lead", "phases", "raw")

    def __init__(self, raw):
        self.raw = raw
        self.name = raw.get("name", "")
        self.lead = raw.get("lead", "")
        self.phases = [Phase(p) for p in raw.get("phases") or []]

    def gates(self):
        """the phases it stops at, in order. there are meant to be two."""
        return [p for p in self.phases if p.gate]

    def agents(self):
        """every distinct agent named anywhere, in the order first seen."""
        out = []
        for phase in self.phases:
            for agent in phase.agents:
                if agent.name not in out:
                    out.append(agent.name)
        return out

    def phase(self, name):
        for p in self.phases:
            if p.name == name:
                return p
        raise KeyError(name)

    def uncriteried(self):
        """phases missing an entry or an exit condition.

        not an error and not raised anywhere. it is here so the gap is
        countable instead of being something you notice by reading.
        """
        return [p for p in self.phases if not p.entry or not p.exit]


def load(path=None):
    # TODO: the flow loader refuses a duplicate key and this one does not. two
    # loaders for two file formats that are both a list of steps with roles.
    text = (path or (root() / "workflow.yaml")).read_text(encoding="utf-8")
    return Workflow(yaml.safe_load(text))
