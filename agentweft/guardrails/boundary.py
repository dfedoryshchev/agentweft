"""what a step came back with, against what it was allowed to touch.

every agent file has granted a list since the day they arrived. the architect
gets `[read, grep]` and then argues it in prose a few lines further down - "you
are deliberately given no shell and no write access" - so the boundary was
written twice in one file and read neither time.

this is NOT a sandbox and the distinction is the whole point. the model's tool
calls are not something this runner is in the path of: a provider is handed a
prompt and hands text back (`providers/base.py`), so there is no call here to
intercept and nothing in this module can stop one. what it can do is say the
grant on the way out and read the answer on the way back. the first half is a
prompt, which is asking. the second half is this, which is checking. a check
described as a boundary and behaving like a fence is the more expensive of the
two mistakes, so: a finding here is a note, not a stop. the thing it would be
stopping already happened.

it works the way `mcp/preflight.py` does - judge the output after the fact -
and it is narrow the way `guardrails/promises.py` is. a tool leaves a mark in
text or it does not. the ones that do not are named in UNSEEN with the reason,
because a grant this quietly skipped would read as a grant it had cleared.
"""
import re

from agentweft.flow import spec


class Mark(object):
    """one thing an output can show, and the grants that would cover it.

    `needs` is a list because the evidence is coarser than the vocabulary. a
    diff says a file changed; it does not say whether the file was there
    first, so `write` answers for it as well as `edit`. narrowing that would
    flag the roles granted one and not the other for a formatting choice.
    """

    __slots__ = ("what", "needs", "shapes", "why")

    def __init__(self, what, needs, shapes, why):
        self.what = what
        self.needs = needs
        self.shapes = tuple(re.compile(s) for s in shapes)
        self.why = why

    def first(self, text):
        """-> the first line that shows it, stripped, or "" for none."""
        for line in (text or "").split(chr(10)):
            for shape in self.shapes:
                if shape.search(line):
                    return line.strip()
        return ""


MARKS = (
    Mark("ran a command", ("shell",),
         (r"^\s*`{3,}\s*(bash|sh|shell|zsh|console|shell-session)\s*$",
          r"^\s*\$ \S"),
         "a fenced block tagged as a shell, or a line opening with a prompt. "
         "a step that only says it would need a shell says so in prose."),
    Mark("changed a file", ("edit", "write"),
         (r"^@@ .*@@", r"^--- a/", r"^\+\+\+ b/",
          r"^\s*`{3,}\s*(diff|patch)\s*$"),
         "a unified diff, by its hunk header, its file headers or its fence. "
         "a step that was HANDED a diff and quotes it back is the false "
         "positive to know about, which is why the note carries the line."),
)


# the grants an output can show, derived rather than typed out so it cannot
# drift from the marks above.
MARKED = tuple(dict.fromkeys(t for m in MARKS for t in m.needs))

# the rest of the vocabulary, and why an output cannot show it. saying nothing
# about these would read as having checked them.
UNSEEN = {
    "read": "opening a file and quoting one look identical from here, and "
            "every step quotes something.",
    "grep": "the same, and a search that found nothing leaves no mark at all.",
    "browser": "a url in an output is a citation. nothing in the text says "
               "anyone went there.",
}


def check(text, granted):
    """-> [(mark, line)] the output shows and the grant does not cover.

    `granted` is None when the step said nothing, and that is not the same as
    granting nothing: a step with no `tools` declared no boundary, so there is
    nothing here to be outside of and this finds nothing. an empty list is a
    step saying it may touch nothing, and that IS a boundary.
    """
    if granted is None:
        return []
    have = set(granted)
    out = []
    for mark in MARKS:
        if have.intersection(mark.needs):
            continue
        line = mark.first(text)
        if line:
            out.append((mark, line))
    return out


def as_note(found):
    """the finding, as it is written down. -> "" when there is nothing.

    the matched line and the reason it counts both go in. a note saying only
    that a boundary was crossed is one nobody can argue with, and every mark
    in here is a heuristic somebody should be able to argue with.
    """
    if not found:
        return ""
    lines = ["this step came back with something it was not granted:"]
    for mark, line in found:
        lines.append("- " + mark.what + ", which needs "
                     + " or ".join(mark.needs) + ": " + line)
        lines.append("  (" + mark.why + ")")
    return chr(10).join(lines) + chr(10)


def as_prompt(granted):
    """the grant on its way out, so the check on the way back is fair.

    a step judged against a boundary nobody told it about is a trap rather
    than a check. this is the asking half, it is a prompt, and a prompt is the
    weakest thing in the repo - which matters more here than anywhere else,
    because there is no half after it that can stop anything.
    """
    if granted is None:
        return ""
    withheld = [g for g in spec.GRANTS if g not in granted]
    lines = ["", "what you may use: " + (", ".join(granted) or "nothing") + "."]
    if withheld:
        lines.append("you do not have " + ", ".join(withheld) + ". if the job "
                     "needs one of those, name it and stop, rather than "
                     "writing out what you would have run.")
    return chr(10).join(lines) + chr(10)
