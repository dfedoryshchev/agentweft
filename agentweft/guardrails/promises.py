"""check the output against what the flow said it would always do.

the invariants have been going into every role prompt since december, which
means the model is TOLD them. this is the part that checks, which is a
different thing and the only one worth anything when it matters.

deliberately dumb: a handful of shapes i can actually assert. anything it
cannot check it says it cannot check, rather than passing quietly.
"""
import re


def _max_lines_under(text, heading, limit):
    lines = []
    seen = False
    for line in text.split("\n"):
        if line.strip().lower().startswith("## "):
            seen = heading.lower() in line.lower()
            continue
        if seen and line.strip().startswith("- "):
            lines.append(line)
    return len(lines) <= limit, str(len(lines)) + " lines under " + heading


def check(text, invariants):
    """-> list of (invariant, ok, detail). ok is None when it cannot be checked."""
    out = []
    for inv in invariants:
        low = inv.lower()
        m = re.search(r"at most (\d+) lines?", low)
        if m and " is " in low:
            heading = low.split(" is ")[0].strip()
            ok, detail = _max_lines_under(text, heading, int(m.group(1)))
            out.append((inv, ok, detail))
        elif "no file appears in two lists" in low:
            seen, dupes = {}, []
            section = ""
            for line in text.split("\n"):
                if line.strip().startswith("## "):
                    section = line.strip()
                    continue
                if line.strip().startswith("- "):
                    name = line.strip()[2:].split("|")[0].strip()
                    if name and name in seen and seen[name] != section:
                        dupes.append(name)
                    seen[name] = section
            out.append((inv, not dupes, ", ".join(dupes) or "none"))
        elif "every line names a file" in low:
            bad = [l for l in text.split("\n")
                   if l.strip().startswith("- ") and "." not in l]
            out.append((inv, not bad, str(len(bad)) + " lines with no filename"))
        else:
            out.append((inv, None, "not checkable here"))
    return out


def _red_test(g, red):
    return g.get("gate") == "red-test" and bool(g.get("red", True)) == red


# what a gate shows when it passes, in the words a promise says it with. a
# promise the output cannot show can still be one a program shows, and that is
# a different answer from "not checkable here".
# the first shape a promise's words fit is the one it is held to, so "the
# suite passes with the patch" is the suite's and not the one test's.
SHOWN = (
    (("suite passes",), lambda g: g.get("gate") == "command"),
    (("fails on the unpatched code", "fails without the fix"),
     lambda g: _red_test(g, True) or g.get("gate") == "red-first"),
    (("passes with the patch", "passes with the fix"),
     lambda g: _red_test(g, False)),
)


def shown_by(steps, invariants):
    """-> list of (invariant, ["<gate> on <step>", ...]): the gates the steps
    declare that show each promise when they pass. an empty list is a promise
    no program in the flow shows."""
    out = []
    for inv in invariants:
        low = inv.lower()
        shows = next((test for words, test in SHOWN
                      if any(w in low for w in words)), None)
        by = []
        for step in steps or []:
            name = step.get("prompt", step.get("role", "?") + ".md")
            for g in step.get("gates") or []:
                if shows and isinstance(g, dict) and shows(g):
                    by.append(g["gate"] + " on " + name)
        out.append((inv, by))
    return out


def failures(text, invariants):
    return [(inv, detail) for inv, ok, detail in check(text, invariants) if ok is False]


def unchecked(text, invariants):
    return [inv for inv, ok, _detail in check(text, invariants) if ok is None]
