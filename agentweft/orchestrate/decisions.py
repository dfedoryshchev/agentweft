"""what was decided, and why.

the journal says what happened: this run, this status, this long. nothing said
why. three of the agent prompts under `orchestrate/agents/` already assume
something does - the doc updater is told to keep the answered questions because
"they are the record of why", and both QA seats are told to read those answers
before they judge anything - and there was no such record for any of them to
read.

this is that record and only that. one entry is a decision and the reason for
it, stamped with when. it does not decide what is worth writing down and it
does not choose what to hand back; whoever writes an entry has already decided
it matters, and whoever reads the file reads all of it.

it lives in the codebase being worked on, as a plain markdown file a person can
read in a diff, so every function takes the folder it writes into. there is no
default, because the only folder this module could default to is one it owns.
"""
import datetime
import re

FILE = "decisions.md"
STAMP = "%Y-%m-%d %H:%M"

ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})  (.+)$")


class Decision(object):
    """one entry: when, what was decided, and why."""

    __slots__ = ("at", "decided", "why")

    def __init__(self, decided, why, at):
        self.at = at
        self.decided = decided
        self.why = why


def lines(decided, why, at):
    """the entry as the lines it is written from.

    the decision is the heading, so the file reads as a list of them; the why
    is the body under it, as many lines as it takes.
    """
    decided = decided.strip()
    why = why.strip()
    if not decided:
        raise ValueError("a decision needs to say what was decided")
    if "\n" in decided:
        raise ValueError("a decision is one line, the why is where the rest goes: "
                         + decided.split("\n")[0])
    if not why:
        raise ValueError("no why for: " + decided)
    return ["## " + at.strftime(STAMP) + "  " + decided, ""] + why.split("\n") + [""]


def record(root, decided, why, at=None):
    """append one decision to the log under root, and hand back the path.

    appended, never rewritten. a decision that turns out wrong gets a later
    entry saying so, and the earlier one stays, because why it looked right at
    the time is part of the record.
    """
    at = at or datetime.datetime.now()
    body = lines(decided, why, at)
    root.mkdir(parents=True, exist_ok=True)
    path = root / FILE
    head = [] if path.exists() else ["# decisions", ""]
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head + body) + "\n")
    return path


def read(root):
    """-> every Decision in the log under root, oldest first. no log, no list."""
    path = root / FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = ENTRY.match(line)
        if m:
            at = datetime.datetime.strptime(m.group(1), STAMP)
            out.append(Decision(m.group(2), [], at))
        elif out:
            out[-1].why.append(line)
    for d in out:
        d.why = "\n".join(d.why).strip()
    return out
