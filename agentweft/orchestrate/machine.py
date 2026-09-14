"""the phase list as an explicit state machine, to see what the order really is.

`run.py workflow` reads the file as a list and prints it as one, which is what
it is on the page. three of the keys sitting on it say the page is not the whole
shape. `gate: user` stops the list dead and hands it to a person. `loop: 5`
sends one phase round again. every phase carries an entry and an exit line,
which are conditions on getting in and getting out rather than descriptions of
the work. none of that fits in a list, so this asks the file the other question:
where can a run be, and what moves it.

the answer is that the states are not the phases, and both of the reasons are
read straight off the file.

a phase that stops is TWO states. `planning` working through its three seats and
`planning` waiting for me are not the same situation - different events leave
them, and in the second one nothing is running at all - so a gate is a state of
its own rather than a mark on the phase.

a trip has to be IN the state or there is no finite machine here. `loop: 5`
means technical review can be entered five times and the fifth refusal becomes
mine rather than a sixth trip, so a state is a phase AND which time round it is,
and one phase in the file is five of the states in here.

eight phases come out as fourteen states, plus the two ways it ends.

what it does not do is guess. one phase in the file has a `loop`, so one phase
has somewhere to go when the work comes back refused; at the other seven step()
hands back None and `no_way_back()` is how you ask which those are. inventing a
target for them would make this a worse reader of the file than the list it is
trying to improve on.

`sequential` never reaches here. it says whether a phase's seats can work at the
same time, which is something inside a phase and not a move between them.

nothing executes a phase - not here and not anywhere else in the repo - so this
is a model of what the file says rather than of anything that has run.
"""
from . import workflow

OK = "ok"
REDO = "redo"
APPROVE = "approve"

# closed on purpose, the way `spec.GRANTS` is: an event this has no name for is
# a typo that would otherwise read as a situation with no move out of it.
EVENTS = (OK, REDO, APPROVE)

DONE = "done"
ATTENTION = "attention"
ENDS = (DONE, ATTENTION)


class State(object):
    """where a run is: which phase, which time round, and whether it is waiting.

    the two ends are states too, so step() has one kind of thing to hand back.
    """

    __slots__ = ("name", "trip", "waiting")

    def __init__(self, name, trip=1, waiting=False):
        self.name = name
        self.trip = trip
        self.waiting = waiting

    def key(self):
        return (self.name, self.trip, self.waiting)

    def final(self):
        return self.name in ENDS

    def __eq__(self, other):
        return isinstance(other, State) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def __str__(self):
        out = self.name
        if self.trip > 1:
            out = out + " #" + str(self.trip)
        if self.waiting:
            out = out + " (waiting)"
        return out

    def __repr__(self):
        return str(self)


class Machine(object):
    """a workflow read as states and one transition function.

    built from a Workflow rather than from the file, so a test can hand it a
    phase list that is not the one in the repo.
    """

    __slots__ = ("wf",)

    def __init__(self, wf=None):
        self.wf = wf or workflow.load()

    def start(self):
        return State(self.wf.phases[0].name) if self.wf.phases else State(DONE)

    def states(self):
        """every situation the file allows, in the order a run meets them."""
        out = []
        for phase in self.wf.phases:
            for trip in range(1, max(phase.loop, 1) + 1):
                out.append(State(phase.name, trip))
                if phase.gate:
                    out.append(State(phase.name, trip, waiting=True))
        return out + [State(DONE), State(ATTENTION)]

    def step(self, state, event):
        """-> the state that event moves to, or None when the file does not say.

        None is an answer rather than a hole. a phase with no `loop` has no
        target for a refusal written anywhere, and picking one here would be
        this module deciding something the workflow file has not.
        """
        if event not in EVENTS:
            raise ValueError("no such event " + str(event) + ". there is: "
                             + ", ".join(EVENTS))
        if state.final():
            return None
        phase = self.wf.phase(state.name)
        if state.waiting:
            return self._after(state.name) if event == APPROVE else None
        if event == OK:
            if phase.gate:
                return State(state.name, state.trip, waiting=True)
            return self._after(state.name)
        if event == REDO and phase.loop > 1:
            if state.trip < phase.loop:
                return State(state.name, state.trip + 1)
            return State(ATTENTION)
        return None

    def _after(self, name):
        order = [p.name for p in self.wf.phases]
        i = order.index(name)
        return State(order[i + 1]) if i + 1 < len(order) else State(DONE)

    def table(self):
        """-> [(state, event, next)] for every move the file allows."""
        out = []
        for state in self.states():
            for event in EVENTS:
                nxt = self.step(state, event)
                if nxt is not None:
                    out.append((state, event, nxt))
        return out

    def refusals(self):
        """-> [(state, event)] there is no move for, ends left out.

        an end refusing everything is what an end is, so counting those would
        bury the ones that say something about the file.
        """
        return [(s, e) for s in self.states() if not s.final()
                for e in EVENTS if self.step(s, e) is None]

    def no_way_back(self):
        """phases the file never says how to leave backwards. -> their names.

        `loop` is the file's only word for going round again, so a phase
        without one has nowhere to put a refusal. seven of the eight.
        """
        return [p.name for p in self.wf.phases if p.loop <= 1]

    def reachable(self):
        """the states a run can actually get to from the first phase.

        every state in here is one the file allows; this is the smaller
        question of which ones something could ever be sitting in.
        """
        seen = []
        queue = [self.start()]
        while queue:
            state = queue.pop(0)
            if state in seen:
                continue
            seen.append(state)
            if state.final():
                continue
            for event in EVENTS:
                nxt = self.step(state, event)
                if nxt is not None:
                    queue.append(nxt)
        return seen

    def unreachable(self):
        """states the table names that no run can be in. empty today.

        countable rather than raised, the same as `uncriteried()` next door:
        it would be a gap in the file, not a failure of this.
        """
        got = self.reachable()
        return [s for s in self.states() if s not in got]

    def walk(self, events):
        """drive it from the start. -> (the states passed through, the refused event).

        it stops at the first event it has no move for instead of skipping it,
        because that event is the thing worth having found.
        """
        state = self.start()
        seen = [state]
        for event in events:
            nxt = None if state.final() else self.step(state, event)
            if nxt is None:
                return seen, event
            state = nxt
            seen.append(state)
        return seen, None


def report(machine=None):
    """-> the lines the command prints, so a test can read them."""
    m = machine or Machine()
    moves = {}
    for state, event, nxt in m.table():
        moves.setdefault(state.key(), []).append(event + " -> " + str(nxt))
    out = [m.wf.name + "  " + str(len(m.wf.phases)) + " phases, "
           + str(len(m.states())) + " states, " + str(len(m.table())) + " moves",
           ""]
    for state in m.states():
        line = "  " + str(state).ljust(26) + "; ".join(moves.get(state.key()) or [])
        out.append(line.rstrip())
    out.append("")
    out.append("no move written for a refusal  (" + str(len(m.no_way_back()))
               + " of " + str(len(m.wf.phases)) + " phases)")
    for name in m.no_way_back():
        out.append("  " + name)
    out.append("")
    out.append("out of reach  (" + str(len(m.unreachable())) + ")")
    for state in m.unreachable():
        out.append("  " + str(state))
    return out
