"""the flow vocabulary and the phase vocabulary, put next to each other.

docs/orchestrate.md says a phase is a flow. i wrote that after reading two
files and noticing they looked alike, which is the kind of claim that is right
until someone asks how much alike. this counts it: every key each side accepts,
which of them are one idea under two names, which exist on one side only, and
which words are spelled the same on both sides while meaning different things.

it compares and it prints. it merges nothing. the runner still runs a flow and
still does not know what a phase is, and this module is not the thing that
changes that - it is the thing that says how big the job is.

what the count says so far, and it is an expectation and not a decision: the
flow side is nearly all machinery and the phase side is nearly all vocabulary.
the words the phase side has that the flow side does not - a group of jobs with
a name, a stop that waits for a person, the same prompt twice with a fixed
position - are afternoons of work. the machinery is not. so i expect the phase
file to be the one that gives. nothing here has decided that, and until
something does, both files stay exactly as they are.
"""
import textwrap

from agentweft.flow import spec

from . import workflow


class Pair(object):
    """one idea, and what each side calls it.

    an empty side is not a gap in the table, it is the finding: that side has
    no word for the thing at all.
    """

    __slots__ = ("flow", "phase", "note")

    def __init__(self, flow, phase, note=""):
        self.flow = flow
        self.phase = phase
        self.note = note

    def both(self):
        return bool(self.flow) and bool(self.phase)


# every term in flow_vocabulary() and phase_vocabulary() has to appear here
# exactly once. unmapped() is what enforces that, and a test fails on it, so a
# key added to either side stays visible until someone says what the other side
# calls it - which is the question this whole file exists to keep asking.
MAP = (
    Pair("flow.name", "workflow.name",
         "the whole thing's name, and the only word that means the same on "
         "both sides."),
    Pair("flow.steps", "workflow.phases",
         "the ordered list. one of them is walked by the runner, the other is "
         "walked by me reading it."),
    Pair("step.role", "agent.agent",
         "the named job. a step has exactly one; a phase holds a list of them."),
    Pair("promises.outputs", "phase.produces",
         "what comes out, in prose, on both sides, and neither is checked "
         "against the output. `outputs` at least gets printed by `show`; only "
         "the invariants reach a prompt."),
    Pair("promises.inputs", "phase.entry",
         "what it starts from. the flow describes the input; the phase states "
         "a condition that has to hold first, which is the stronger of the two "
         "and the one nothing reads."),
    Pair("promises.invariants", "phase.exit",
         "what has to be true about the result. three shapes of invariant have "
         "a checker; an exit line has none."),
    Pair("step.workers", "phase.sequential",
         "the same axis from opposite ends. a step that fans out says how many "
         "at once; a phase says only that it cannot."),
    Pair("step.on_redo", "phase.loop",
         "going round again. the flow names who to go back to and the router "
         "counts the trips; the phase names a number and nothing counts."),

    # only the flow has a word for it
    Pair("flow.schedule", "", "when it runs unasked. nothing runs a phase at all."),
    Pair("flow.timeout", "", "how long one call gets before it is a failure."),
    Pair("flow.retries", "", "how many tries one call gets before it is given up on."),
    Pair("flow.workers", "", "the default width, which a step may override."),
    Pair("flow.max_calls", "", "the ceiling on calls. a phase has no ceiling."),
    Pair("flow.max_tokens", "", "the ceiling on tokens, charged per step as it goes."),
    Pair("flow.journal", "", "whether the run is written down. no phase is."),
    Pair("flow.provider", "", "who answers. a phase names an agent and leaves it there."),
    Pair("flow.temperature", "",
         "the loader accepts it and nothing reads it, so it documents an "
         "intention rather than setting one."),
    Pair("flow.note", "",
         "a comment with a key on it. the workflow file keeps its notes in "
         "yaml comments, where nothing can reach them either."),
    Pair("flow.context", "", "the tool a planner asks before it plans."),
    Pair("step.prompt", "",
         "which file the step sends. an agent's prompt is its own name plus "
         ".md, so it cannot be pointed anywhere else."),
    Pair("step.fanout", "",
         "one role, many copies, one per task the step before listed. a phase "
         "is plural the other way - several different roles at once - and the "
         "flow side has no word for that."),
    Pair("step.must_produce", "",
         "a string the output has to contain, checked by the router. it is "
         "`produces` with teeth."),
    Pair("step.gates", "",
         "a check that is a program. the phase side has no program anywhere."),
    Pair("step.provider", "", "who answers this one step."),
    Pair("step.preflight", "", "what to do when a step touches a risky file."),

    # only the phase has a word for it
    Pair("", "workflow.lead",
         "the one that runs the whole thing and does not implement. the flow's "
         "lead is the runner, which is code and not a prompt."),
    Pair("", "phase.name",
         "a named group of jobs. a flow has nothing between the flow and the "
         "step, so the group IS the flow."),
    Pair("", "phase.agents", "the jobs in the group. on the flow side those are steps."),
    Pair("", "phase.gate",
         "where it parks and waits for a person. the flow side can stop, but "
         "only by failing; it has no word for stopping on purpose."),
    Pair("", "agent.personality",
         "the same prompt twice from a fixed position. a flow wanting that "
         "needs a second prompt file."),
)


def flow_vocabulary():
    """every key a flow file may use, taken from the loader's own lists.

    `promises` is left out as a container; its three keys are here instead,
    and they are the ones a phase has something to say about.
    """
    out = ["flow." + k for k in spec.KNOWN if k != "promises"]
    out = out + ["promises." + k for k in spec.Promises.__slots__]
    return out + ["step." + k for k in spec.STEP_KNOWN]


def phase_vocabulary(wf=None):
    """every key the workflow file actually uses.

    the asymmetry starts here and it is worth saying out loud. the flow loader
    publishes what it accepts and complains about anything else, so the flow
    vocabulary can be read off the code. the workflow loader takes whatever is
    in the file and says nothing, so the only way to ask what a phase may say
    is to go and read one.
    """
    wf = wf or workflow.load()
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


def unmapped(wf=None):
    """-> (flow terms, phase terms) that MAP does not place.

    both are meant to be empty. a new key on either side lands here rather
    than quietly joining a vocabulary nobody compared.
    """
    placed = set()
    for pair in MAP:
        placed.add(pair.flow)
        placed.add(pair.phase)
    return ([t for t in flow_vocabulary() if t not in placed],
            [t for t in phase_vocabulary(wf) if t not in placed])


def pairs():
    return [p for p in MAP if p.both()]


def flow_only():
    return [p for p in MAP if p.flow and not p.phase]


def phase_only():
    return [p for p in MAP if p.phase and not p.flow]


def _stem(term):
    """the bare word, plural dropped.

    crude on purpose. `gates` and `gate` are one word wearing two numbers and
    treating them as different terms would hide the sharpest thing in here.
    """
    word = term.split(".")[-1]
    if word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def collisions(source=None):
    """words spelled the same on both sides that are not the same idea.

    -> [(word, [flow terms], [phase terms])]. a word both sides use inside ONE
    pair is the two sides agreeing, which is the opposite of what this looks
    for.
    """
    seen = {}
    for pair in source or MAP:
        for side, term in (("flow", pair.flow), ("phase", pair.phase)):
            if term:
                seen.setdefault(_stem(term), []).append((side, term, pair))
    out = []
    for word in sorted(seen):
        left = [u for u in seen[word] if u[0] == "flow"]
        right = [u for u in seen[word] if u[0] == "phase"]
        if not left or not right:
            continue
        if all(l[2] is r[2] for l in left for r in right):
            continue
        out.append((word, [l[1] for l in left], [r[1] for r in right]))
    return out


class Row(object):
    """one question, asked of both sides, answered in whatever unit fits."""

    __slots__ = ("label", "flow", "phase")

    def __init__(self, label, flow, phase):
        self.label = label
        self.flow = flow
        self.phase = phase


def census(wf=None):
    """the same questions, asked of the files that are actually in the repo.

    the vocabulary above is what the two sides CAN say. this is what they do
    say, which is the half that turns "these look alike" into numbers.
    """
    from agentweft.guardrails import promises
    from agentweft.runner import cli
    from agentweft.runner.config import config

    wf = wf or workflow.load()
    specs = []
    for name in cli.flows():
        try:
            specs.append(config(name))
        except Exception:
            # a broken flow.yaml is `run.py list`'s problem, not this one's
            continue
    steps = [s for sp in specs for s in sp.steps]
    roles = sorted(set(s["role"] for s in steps))
    invariants = [i for sp in specs for i in sp.promises.invariants]
    # the invariant text picks the branch in promises.check, not the output
    # text, so an empty output still says which ones have a checker at all.
    # ok is None for the ones it can only shrug at.
    checkable = [i for i, ok, _ in promises.check("", invariants) if ok is not None]
    capped = [sp for sp in specs
              if sp.get("max_calls") is not None or sp.get("max_tokens") is not None]
    gated = [s for s in steps if s.get("gates")]
    gates = [g for s in gated for g in s["gates"]]

    seats = [a for p in wf.phases for a in p.agents]
    widths = sorted(len(p.agents) for p in wf.phases)
    conditions = [c for p in wf.phases for c in (p.entry, p.exit) if c]
    phase_caps = [p for p in wf.phases
                  if [k for k in p.raw if k in ("max_calls", "max_tokens", "timeout")]]

    return [
        Row("ordered units",
            str(len(steps)) + " steps in " + str(len(specs)) + " flows",
            str(len(wf.phases)) + " phases"),
        Row("named jobs",
            str(len(steps)) + " roles, " + str(len(roles)) + " distinct",
            str(len(seats)) + " seats, " + str(len(wf.agents())) + " distinct"),
        Row("jobs in one unit",
            "1, a step has one role",
            str(widths[0]) + " to " + str(widths[-1])),
        Row("conditions in prose",
            str(len(invariants)) + " invariants",
            str(len(conditions)) + " entry and exit lines"),
        # the phase side is not a count. entry and exit are read in two
        # places, both of which print them, so there is nothing to count.
        Row("of those, something checks",
            str(len(checkable)) + " of " + str(len(invariants)),
            "none of " + str(len(conditions))),
        Row("checks that are programs",
            str(len(gates)) + " gates on " + str(len(gated)) + " steps",
            "none"),
        Row("declares a spend ceiling",
            str(len(capped)) + " of " + str(len(specs)) + " flows, rest default",
            str(len(phase_caps)) + " of " + str(len(wf.phases))
            + " phases, no default either"),
        Row("something executes it",
            str(len(steps)) + " of " + str(len(steps)) + " steps",
            "0 of " + str(len(wf.phases)) + " phases"),
    ]


def _wrapped(text, indent=6):
    return textwrap.fill(text, width=78, initial_indent=" " * indent,
                         subsequent_indent=" " * indent)


def _beside(term, note):
    """the term, then its note in the column to the right of it."""
    return textwrap.fill(note, width=78, initial_indent="  " + term.ljust(22),
                         subsequent_indent=" " * 24)


def report(wf=None):
    """-> the lines the command prints, so a test can read them."""
    wf = wf or workflow.load()
    out = []
    both, one, other = pairs(), flow_only(), phase_only()

    out.append("one idea, two names  (" + str(len(both)) + ")")
    for pair in both:
        out.append("  " + pair.flow.ljust(22) + pair.phase)
        out.append(_wrapped(pair.note))

    out.append("")
    out.append("only the flow has a word for it  (" + str(len(one)) + ")")
    for pair in one:
        out.append(_beside(pair.flow, pair.note))

    out.append("")
    out.append("only a phase has a word for it  (" + str(len(other)) + ")")
    for pair in other:
        out.append(_beside(pair.phase, pair.note))

    out.append("")
    out.append("the same word for two things")
    for word, left, right in collisions():
        out.append("  " + word + ": " + ", ".join(left) + "  vs  "
                   + ", ".join(right))

    out.append("")
    out.append("what is in the repo")
    for row in census(wf):
        out.append("  " + row.label.ljust(28) + row.flow.ljust(34) + row.phase)

    out.append("")
    out.append("which side gives")
    out.append(_wrapped(
        str(len(both)) + " ideas have a name on both sides. " + str(len(one))
        + " exist only as a flow key and " + str(len(other))
        + " only as a phase key, and almost everything on the flow-only side "
        "is a mechanism while almost everything on the phase-only side is a "
        "word. a word can be moved in an afternoon and a runner cannot, so i "
        "expect the phase file to be the one that gives. that is an "
        "expectation. nothing here has decided it, and nothing here has done "
        "it.", indent=2))
    return out
