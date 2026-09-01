"""the workflow layer i brought over from my own product, read as flow specs.

over there this is prose. the phases are a diagram in a markdown file, the
agents are markdown files telling an agent to read other markdown files, and
the whole thing is held together by the agents doing what they were asked.

the first thing it got here was a file that could be parsed, and this module
was the parser: its own yaml reading, its own classes, its own idea of what a
valid file is. so the repo held two loaders, two validators and two object
models for one shape, while the docs said the shape was one thing.

a phase is a flow, so it is loaded as one now. TRANSLATION is the whole of the
merge: the file's words go into the flow vocabulary, the flow loader validates
what comes out, and a Phase is a view over the FlowSpec it hands back.

nothing about a run changes, and that is the point rather than a shortfall.
nothing executed a phase before and nothing executes one now; what moved is
which model the file is read into.

what did not come across is in RESIDUE, and it is the half worth having. to
take those the FLOW side would have to grow four or five keys that nothing
reads, on the loader the runner actually uses - which is the flow side giving,
not the phase side, and the opposite of what i expected when i first counted
the two vocabularies. doing the merge also cost two of the nine ideas i had
called shared: `loop` and `sequential` looked like pairs until a translation
had to pick a word for them, and there was no word to pick.

the file itself keeps its own words. its header is a running account of what
was and was not taken out of it on the way over, and rewriting it into flow
vocabulary would throw away the evidence that what came over came over whole.
"""
from pathlib import Path

from agentweft.flow import reader, spec

# same shape as FLOW_ROOT: a list so a test can point it somewhere else.
ROOT = ["orchestrate"]


def root():
    return Path(ROOT[0])


# the merge as a table: each word the phase file uses, and the flow word it
# becomes. as_flow() is this table, applied.
TRANSLATION = (
    ("phase.name", "flow.name"),
    ("phase.agents", "flow.steps"),
    ("phase.produces", "promises.outputs"),
    ("phase.entry", "promises.inputs"),
    ("phase.exit", "promises.invariants"),
    ("phase.gate", "step.pause"),
    ("agent.agent", "step.role"),
)


class Missing(object):
    """one thing the phase file can say that the flow vocabulary cannot.

    not a bug and not a plan. it is the price of the merge, itemised, and the
    price is paid by the side i did not expect: every one of these would be a
    new key on the live flow loader that nothing reads.
    """

    __slots__ = ("terms", "why")

    def __init__(self, terms, why):
        self.terms = terms
        self.why = why


RESIDUE = (
    Missing(("phase.sequential",),
            "a phase's agents are different roles working at the same time, "
            "and this is the only mark the file makes when they cannot. the "
            "flow side has no word for that plural - `fanout` is one role in "
            "many copies, which is the other kind of many."),
    Missing(("phase.loop",),
            "how many times round before it becomes a person's problem. a "
            "flow says who a verdict sends the work back to, and the engine "
            "hands the router the number of trips itself, so the count in the "
            "file has nowhere to land."),
    Missing(("agent.personality",),
            "the same prompt twice from a fixed position. a step carries a "
            "role, not a stance, and a flow that wanted two stances would "
            "need two prompt files."),
    Missing(("workflow.lead",),
            "the prompt that runs the whole thing and does not implement. a "
            "flow's lead is the runner, which is code, so there is nothing "
            "here for it to turn into."),
    Missing(("workflow.name", "workflow.phases"),
            "an ordered list of flows, and what that list is called. a flow "
            "spec says nothing about what runs after it, so the sequence the "
            "phases sit in has no flow word, and neither does its name."),
)


class Agent(object):
    """one seat: one launch of one named agent. two seats can be one agent."""

    __slots__ = ("name", "personality", "raw")

    def __init__(self, raw):
        if isinstance(raw, str):
            raw = {"agent": raw}
        self.raw = raw
        self.name = raw["agent"]
        self.personality = raw.get("personality", "")

    def step(self):
        """the seat as a flow step. the stance does not come with it."""
        return {"role": self.name}

    def prompt(self):
        return root() / "agents" / (self.name + ".md")

    def __str__(self):
        if self.personality:
            return self.name + " (" + self.personality + ")"
        return self.name


def as_flow(raw):
    """a phase in the flow vocabulary. -> the raw dict the flow loader takes.

    the only line here that changes shape rather than name is the gate. a
    phase stops after its last job, so the last step is the one that waits,
    and it is spelled `pause` because `gate` on a step is already a program.
    """
    steps = [Agent(a).step() for a in raw.get("agents") or []]
    if raw.get("gate") and steps:
        steps[-1] = dict(steps[-1], pause=raw["gate"])
    out = {"name": raw["name"], "steps": steps}
    promises = {}
    if raw.get("entry"):
        promises["inputs"] = raw["entry"]
    if raw.get("produces"):
        promises["outputs"] = raw["produces"]
    if raw.get("exit"):
        promises["invariants"] = [raw["exit"]]
    if promises:
        out["promises"] = promises
    return out


class Phase(object):
    """a phase, which is a flow, and the two words that would not translate.

    the spec IS the phase - name, seats and criteria all read off it. `loop`
    and `sequential` hang off the side because RESIDUE says they have nowhere
    to go, and they are read straight from the file rather than dressed up as
    flow keys they are not.
    """

    __slots__ = ("spec", "agents", "gate", "loop", "sequential", "raw")

    def __init__(self, raw):
        self.raw = raw
        self.agents = [Agent(a) for a in raw.get("agents") or []]
        self.gate = raw.get("gate", "")
        self.loop = int(raw.get("loop") or 1)
        self.sequential = bool(raw.get("sequential"))
        self.spec = spec.load(as_flow(raw))

    @property
    def name(self):
        return self.spec.name

    @property
    def steps(self):
        return self.spec.steps

    @property
    def produces(self):
        return self.spec.promises.outputs

    @property
    def entry(self):
        # what has to be true to start, and what has to be true to be done.
        # `produces` is the artifact; these two are the conditions around it,
        # and a phase can produce its doc and still not be finished with it.
        #
        # they are promises now, which is where the flow side keeps the same
        # three, and NOTHING CHECKS THEM STILL. the checker knows three shapes
        # and an exit line is none of them, so becoming an invariant made them
        # sayable in one vocabulary, not checkable.
        return self.spec.promises.inputs

    @property
    def exit(self):
        found = self.spec.promises.invariants
        return found[0] if found else ""


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


def terms(wf=None):
    """every term the workflow file actually uses.

    the asymmetry is worth saying out loud. the flow loader publishes the keys
    it accepts and complains about the rest, so its vocabulary is a fact about
    the code. this one takes whatever the file says, so its vocabulary is a
    fact about the file, and the only way to ask what a phase may say is to go
    and read one.
    """
    wf = wf or load()
    out = ["workflow." + k for k in wf.raw]
    for phase in wf.phases:
        for key in phase.raw:
            if "phase." + key not in out:
                out.append("phase." + key)
        for agent in phase.agents:
            for key in agent.raw:
                if "agent." + key not in out:
                    out.append("agent." + key)
    return out


def unplaced(wf=None):
    """-> terms the file uses that are neither translated nor named as missing.

    meant to be empty, and a test fails while it is not. a key added to the
    phase file has to be given a flow word or an entry in RESIDUE saying why
    it cannot have one. it does not get to arrive quietly.
    """
    placed = set(phase for phase, _ in TRANSLATION)
    for miss in RESIDUE:
        placed.update(miss.terms)
    return [t for t in terms(wf) if t not in placed]


def load(path=None):
    """read the file the way a flow file is read, and build the phases.

    the shared reader is half the point of doing this: `safe_load` keeps the
    last of two identical keys, so a phase with two `agents:` blocks in it
    used to lose one silently, which the flow side has refused for months.
    """
    text = (path or (root() / "workflow.yaml")).read_text(encoding="utf-8")
    return Workflow(reader.read(text))
