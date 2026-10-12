import re

from .base import Gate, register

LEAD = r"^[\s>#*+\-`_]*(?:\d+[.)]\s*)?[\s*_`]*"
WORD = r"(?![\w-])"
FAIL = re.compile(LEAD + r"FAIL" + WORD, re.I)
PASS = re.compile(LEAD + r"PASS" + WORD, re.I)
UNSURE = re.compile(LEAD + r"(?:UNVERIFIED|UNKNOWN|UNCLEAR|CANNOT CHECK"
                    r"|CANNOT VERIFY|NOT CHECKED|SKIPPED)" + WORD, re.I)


@register
class VerdictGate(Gate):
    """an answer made of PASS and FAIL lines, read the way a person reads it.

    a line that starts with FAIL fails the step whatever list shape it comes
    in, and so does one that starts with a word that is not a verdict at all,
    UNVERIFIED or CANNOT CHECK: a check nobody could do has not passed. what
    is left needs `passes` PASS lines (default 1), so an answer that drops one
    of the checks it was asked for, or answers in prose, fails too.
    """

    name = "verdict"
    options = ("passes",)

    def run(self, text):
        want = self.opts.get("passes", 1)
        if isinstance(want, bool) or not isinstance(want, int) or want < 1:
            return self.fail("passes: " + repr(want)
                             + " is not a count of lines")
        lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
        if not lines:
            return self.fail("the step answered nothing")
        for line in lines:
            if FAIL.match(line):
                return self.fail("a FAIL line: " + line[:160])
        for line in lines:
            if UNSURE.match(line):
                return self.fail("not a verdict: " + line[:160])
        got = sum(1 for line in lines if PASS.match(line))
        if not got:
            return self.fail("no PASS or FAIL line, so nothing was checked")
        if got < want:
            return self.fail(str(got) + " PASS line" + ("" if got == 1 else "s")
                             + ", wanted " + str(want))
        return self.ok(str(got) + " PASS, no FAIL")
