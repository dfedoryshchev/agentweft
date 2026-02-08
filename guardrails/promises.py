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


def failures(text, invariants):
    return [(inv, detail) for inv, ok, detail in check(text, invariants) if ok is False]
