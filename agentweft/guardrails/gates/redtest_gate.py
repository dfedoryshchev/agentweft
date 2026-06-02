from .base import Gate, register


@register
class RedTestGate(Gate):
    """red before green, checked rather than asked for.

    fix-with-test says the test must fail before the patch. the worker prompt
    says so and the must_produce marker checks the words are there. this checks
    the claim: the named error has to appear in the worker's output, and must
    NOT appear once the patcher has been.
    """

    name = "red-test"

    def run(self, text):
        marker = self.opts.get("marker", "FAILS:")
        want_red = bool(self.opts.get("red", True))
        has = marker in text
        if want_red and not has:
            return self.fail("no " + marker + " line, so the test never failed")
        if not want_red and has:
            return self.fail(marker + " still there after the patch")
        return self.ok("red" if want_red else "green")
