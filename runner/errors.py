"""what kind of wrong it was. the runner only retries one of these."""


class Transient(Exception):
    """the cli fell over and it is worth going again. timeout, rate limit."""


class Fatal(Exception):
    """going again will not help. no credentials, flow does not exist."""


class BadPrompt(Exception):
    """it ran fine and gave me something i cannot use. a redo is the fix, not
    a retry - the same prompt gets the same answer."""


TRANSIENT_MARKERS = ("timeout", "timed out", "rate limit", "429", "connection reset",
                     "temporarily unavailable")
FATAL_MARKERS = ("not found", "no such", "unauthorized", "invalid api key",
                 "permission denied")


def classify(stderr):
    low = (stderr or "").lower()
    for m in FATAL_MARKERS:
        if m in low:
            return Fatal
    for m in TRANSIENT_MARKERS:
        if m in low:
            return Transient
    # unknown means transient. going again is cheap, giving up is not.
    return Transient
