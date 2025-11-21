"""what one step passes to the next.

it used to be the raw text, pasted at the bottom of the next prompt. that was
fine while a step only ever produced prose, but the reviewer now produces a
verdict as well and the fanout produces several pieces, and both of those were
being smuggled through the same string.
"""


class Handoff(object):
    __slots__ = ("role", "output", "verdict", "meta")

    def __init__(self, role, output, verdict="ok", meta=None):
        self.role = role
        self.output = output
        self.verdict = verdict
        self.meta = meta or {}

    def __bool__(self):
        return bool(self.output)

    def as_prompt(self):
        if not self.output:
            return ""
        return "\n\nhere is what " + self.role + " produced:\n\n" + self.output


EMPTY = Handoff("nobody", "")
