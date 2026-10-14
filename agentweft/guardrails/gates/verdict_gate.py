import re

from .base import Gate, register

LEAD = r"^[\s>#*+\-`_]*(?:\d+[.)]\s*)?[\s*_`]*"
WORD = r"(?![\w-])"
FAIL = re.compile(LEAD + r"FAIL" + WORD, re.I)
PASS = re.compile(LEAD + r"PASS" + WORD, re.I)
UNSURE = re.compile(LEAD + r"(?:UNSURE|NOT SURE|UNVERIFIED|UNKNOWN|UNCLEAR"
                    r"|CANNOT CHECK|CANNOT VERIFY|NOT CHECKED|SKIPPED)" + WORD,
                    re.I)


@register
class VerdictGate(Gate):
    """an answer made of PASS and FAIL lines, read the way a person reads it.

    a line that starts with FAIL fails the step whatever list shape it comes
    in. a line that starts with UNSURE, UNVERIFIED, CANNOT CHECK and the like
    is a check the step could not decide: it is neither a pass nor a fail, it
    counts as one of the checks answered and is handed back as `unproven`, so
    the record and the run's last line say it was never proven. the step needs
    `passes` checks answered (default 1), at least one of them a PASS, so an
    answer that drops a check, answers in prose, or is nothing but unsure
    lines fails.
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
        unsure = [line for line in lines if UNSURE.match(line)]
        for line in lines:
            if FAIL.match(line):
                return self.fail("a FAIL line: " + line[:160], unsure)
        got = sum(1 for line in lines if PASS.match(line))
        if not got:
            return self.fail("no PASS or FAIL line, so nothing was checked",
                             unsure)
        if got + len(unsure) < want:
            return self.fail(str(got) + " PASS line" + ("" if got == 1 else "s")
                             + (", " + str(len(unsure)) + " unproven"
                                if unsure else "")
                             + ", wanted " + str(want), unsure)
        return self.ok(str(got) + " PASS, "
                       + (str(len(unsure)) + " unproven, " if unsure else "")
                       + "no FAIL", unsure)
