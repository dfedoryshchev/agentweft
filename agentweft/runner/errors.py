"""what kind of wrong it was. the runner only retries one of these."""
import datetime
import re


class Transient(Exception):
    """the cli fell over and it is worth going again. timeout, rate limit."""


class Fatal(Exception):
    """going again will not help. no credentials, flow does not exist."""


class BadPrompt(Exception):
    """it ran fine and gave me something i cannot use. a redo is the fix, not
    a retry - the same prompt gets the same answer."""


class Outage(Exception):
    """the account's own limit refused the call: a session, weekly or usage
    limit. going again before it resets is refused the same way, and the
    empty answer it leaves is not something any gate should be judging.

    `resets` is when the provider said it resets, "unknown" when it did not.
    `replies` is every go that was made, this one included: each was paid
    for, even the refused ones.
    """

    def __init__(self, detail, resets="unknown", replies=(), retries=None):
        Exception.__init__(self, detail)
        self.detail = detail
        self.resets = resets or "unknown"
        self.replies = list(replies)
        self.retries = dict(retries or {})


TRANSIENT_MARKERS = ("timeout", "timed out", "rate limit", "429", "connection reset",
                     "temporarily unavailable")
FATAL_MARKERS = ("not found", "no such", "unauthorized", "invalid api key",
                 "permission denied")
# what a plain-text command says when the account's limit refused it. a reply
# that says so in its own fields is read from those first; these are for
# whatever cannot.
OUTAGE_MARKERS = ("usage limit", "session limit", "weekly limit",
                  "hit your limit", "limit reached|")


def classify(stderr):
    low = (stderr or "").lower()
    for m in FATAL_MARKERS:
        if m in low:
            return Fatal
    for m in OUTAGE_MARKERS:
        if m in low:
            return Outage
    for m in TRANSIENT_MARKERS:
        if m in low:
            return Transient
    # unknown means transient. going again is cheap, giving up is not.
    return Transient


def kind_of(reply):
    """-> the kind of a failed reply: its own word for an outage first, then
    what its text reads as."""
    if getattr(reply, "outage", None):
        return Outage
    return classify(getattr(reply, "detail", ""))


def when(epoch):
    """-> an epoch in seconds as local time, or None for anything else."""
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)):
        return None
    try:
        return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return None


RESETS = re.compile(r"\bresets?\s+(?:at\s+)?(.+)$", re.IGNORECASE)
# an older claude cli put the reset after a bar, as an epoch
EPOCH = re.compile(r"limit reached\|(\d{9,})", re.IGNORECASE)


def resets(text):
    """-> when the limit in text says it resets, "unknown" when it does not."""
    text = (text or "").strip()
    said = EPOCH.search(text)
    if said and when(int(said.group(1))):
        return when(int(said.group(1)))
    said = RESETS.search(text)
    if said:
        out = said.group(1).strip().rstrip(".")
        # the cli appends "(exit 1)" to a failed call's words
        out = re.sub(r"\s*\(exit -?\d+\)$", "", out).strip()
        if out:
            return out
    return "unknown"
