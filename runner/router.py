"""what runs next.

the step list has been a straight line since july: do these, in this order,
every time. that was fine until a step could come back and say the work is
wrong, which the reviewer has been able to do since september - and then the
straight line had a special case bolted onto the side of it.

so: the flow says where a verdict sends you, and the runner asks instead of
walking a list.
"""


class Router(object):
    def __init__(self, spec, cap=2):
        self.order = [s.get("prompt", s["role"] + ".md") for s in spec.steps]
        self.on_redo = {}
        for s in spec.steps:
            target = s.get("on_redo")
            if target:
                self.on_redo[s.get("prompt", s["role"] + ".md")] = target + ".md"
        self.cap = cap
        self.sent_back = 0

    def first(self):
        return self.order[0] if self.order else None

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
        for earlier in reversed(self.order[:i]):
            if earlier.startswith("worker"):
                return earlier
        return self.order[0] if i else None
