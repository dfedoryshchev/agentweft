"""what runs next.

the step list has been a straight line since july: do these, in this order,
every time. that was fine until a step could come back and say the work is
wrong, which the reviewer has been able to do since september - and then the
straight line had a special case bolted onto the side of it.

so: the flow says where a verdict sends you, and the runner asks instead of
walking a list.

a step is named here by the file its words are in, because that is the only
name that tells two steps of the same role apart. `on_redo` names a ROLE
though - it is a person writing down who has to go again - so it is looked up
rather than turned into a file name.

two steps can answer to that role, and then the lookup has to pick one. it
picks the last one BEFORE the step sending the work away, which is the answer
this file already gives when nothing is declared at all: `_back_to` walks
backwards for a worker. a redo is work going back the way it came, so the one
it goes back to is the nearest, not the earliest. a target with nothing behind
it is a role the run has not reached, which has no nearest, so that one stays
the flow's first step of the role.
"""
from agentweft.flow.spec import step_id


class Router(object):
    def __init__(self, spec, cap=2):
        self.order = [step_id(s) for s in spec.steps]
        self.roles = {step_id(s): s["role"] for s in spec.steps}
        first_for_role = {}
        for s in spec.steps:
            first_for_role.setdefault(s["role"], step_id(s))
        self.on_redo = {}
        for i, s in enumerate(spec.steps):
            target = s.get("on_redo")
            if target:
                self.on_redo[step_id(s)] = \
                    self._earlier(i, lambda role: role == target) \
                    or first_for_role.get(target, target + ".md")
        self.must = {}
        for s in spec.steps:
            if s.get("must_produce"):
                self.must[step_id(s)] = s["must_produce"]
        self.cap = cap
        self.sent_back = 0

    def first(self):
        return self.order[0] if self.order else None

    def gate(self, step, handoff):
        """a step can be required to have produced something. red before green
        is not a preference in fix-with-test, it is the flow."""
        want = self.must.get(step)
        if want and want not in handoff.output:
            return "step " + step + " did not produce " + want
        return None

    def next(self, step, handoff):
        """-> the next step, or None when there is nothing left."""
        if handoff.verdict == "redo" and self.sent_back < self.cap:
            target = self.on_redo.get(step) or self._back_to(step)
            if target:
                self.sent_back = self.sent_back + 1
                return target
        i = self.order.index(step)
        return self.order[i + 1] if i + 1 < len(self.order) else None

    def _back_to(self, step):
        # nothing declared, so back to whoever produced the thing being judged
        i = self.order.index(step)
        return self._earlier(i, lambda role: role.startswith("worker")) \
            or (self.order[0] if i else None)

    def _earlier(self, i, fits):
        """-> the last step before the one at i whose role fits, or None."""
        for step in reversed(self.order[:i]):
            if fits(self.roles.get(step, "")):
                return step
        return None
