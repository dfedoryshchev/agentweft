"""the labelled lines a step's answer can carry, read one way everywhere.

a step talks to the runner in lines that start with a word in capitals and a
colon: `NEEDS:`, `ASSUMED:`, `REFUSED:`, the HANDOFF block's own headings.
each reader used to find them its own way, and the ways disagreed on the
cases that matter: a key in lower case, a key behind a bullet or in bold, a
key inside a fenced code block (a test that asserts on the string "NEEDS:"),
a key inside a `>` quote of the task. this is the one reader.

a line counts when it is outside a fence and not quoted; its key is read
whatever its case, and a bullet or bold around it is ignored. the first
`NEEDS:` or `REFUSED:` wins; the list verbs gather every line.
"""
import re

FENCE = re.compile(r"^\s*(```|~~~)")
QUOTE = re.compile(r"^\s*>")
BULLET = re.compile(r"^\s*[-*+]\s+(.*?)\s*$")
KEY = re.compile(r"^[\s#*`_\-+]*([A-Za-z][A-Za-z \-_]*?)[\s*`_]*:\s*(.*?)\s*$")

SINGLE = ("NEEDS", "REFUSED", "INTENT", "INTENT QUOTE")
LISTED = ("CITES", "OPTIONS", "ASSUMED", "INTENT SCOPE", "CHANGED UNDER")


def visible(text):
    """-> [(index, line)] for every line outside a fence and not quoted."""
    out = []
    fenced = None
    for i, line in enumerate((text or "").split("\n")):
        m = FENCE.match(line)
        if m:
            if fenced is None:
                fenced = m.group(1)
            elif m.group(1) == fenced:
                fenced = None
            continue
        if fenced is not None or QUOTE.match(line):
            continue
        out.append((i, line))
    return out


def key_of(line):
    """-> (NAME, rest, bulleted, in capitals) for a `NAME: rest` line, or
    None. NAME is upper case with `-` and `_` read as spaces, so `must-not-miss`
    and `MUST NOT MISS` are one key; `rest` has its bold and quotes taken off."""
    m = KEY.match(line)
    if not m:
        return None
    raw = m.group(1)
    name = " ".join(raw.upper().replace("-", " ").replace("_", " ").split())
    rest = m.group(2).strip().strip("*`_").strip()
    return name, rest, BULLET.match(line) is not None, raw == raw.upper()


def unquoted(text):
    return text.strip().strip('"').strip("'").strip()


class Verbs(object):
    """what the answer asked for or declared, None or [] when it did not."""

    __slots__ = ("needs", "cites", "options", "refused", "assumed", "intent",
                 "intent_quote", "intent_scope", "changed_under")

    def __init__(self):
        self.needs = None
        self.refused = None
        self.intent = None
        self.intent_quote = None
        self.cites = []
        self.options = []
        self.assumed = []
        self.intent_scope = []
        self.changed_under = []

    def __bool__(self):
        return any(getattr(self, k) for k in self.__slots__)


FIELD = {"NEEDS": "needs", "REFUSED": "refused", "INTENT": "intent",
         "INTENT QUOTE": "intent_quote", "CITES": "cites", "OPTIONS": "options",
         "ASSUMED": "assumed", "INTENT SCOPE": "intent_scope",
         "CHANGED UNDER": "changed_under"}


def parse(text):
    """-> Verbs read off `text`.

    a list verb takes what is on its own line and the `- ` lines under it,
    up to the next key line or a line that is neither; a single verb takes
    its line, and only the first one found.
    """
    out = Verbs()
    gathering = None
    for _, line in visible(text):
        head = key_of(line)
        if head is not None and head[0] in FIELD:
            name, rest, _, _ = head
            if name in SINGLE:
                gathering = None
                if getattr(out, FIELD[name]) is None:
                    setattr(out, FIELD[name],
                            unquoted(rest) if name == "INTENT QUOTE" else rest)
                continue
            gathering = getattr(out, FIELD[name])
            if rest:
                gathering.append(rest)
            continue
        if gathering is None:
            continue
        m = BULLET.match(line)
        if m:
            if m.group(1):
                gathering.append(m.group(1))
        elif line.strip():
            gathering = None
    return out
