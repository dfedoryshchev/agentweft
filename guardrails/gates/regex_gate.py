import re

from .base import Gate, register


@register
class RegexGate(Gate):
    """must match, or must not match. the two cover most of what i want."""

    name = "regex"

    def run(self, text):
        pattern = self.opts.get("pattern", "")
        want = self.opts.get("present", True)
        found = re.search(pattern, text, re.M) is not None
        if found == bool(want):
            return self.ok()
        if want:
            return self.fail("no match for " + pattern)
        return self.fail("matched " + pattern + " and should not have")
