"""do not let a step walk into the blast radius without saying so.

the risk map has been advisory since june: it goes into the planner's prompt
and the planner mostly weights by it. mostly is the problem. a plan that says
"rewrite the thing everything imports" is exactly the plan a model produces
when it is being helpful, and nothing downstream stops it.

so: before a step that is going to touch files, check what it is about to touch
against the ranking. above the threshold it is flagged, and the flow can be set
to refuse rather than flag.

this is the half of the idea that is not a prompt. a prompt asking an agent to
be careful about a hot file is a prompt. this is a number and a comparison.
"""
import re

DEFAULT_THRESHOLD = 0.7


def parse_ranking(text):
    """`path score` per line, which is what every ranking i have seen emits.
    anything it cannot parse is skipped rather than guessed at."""
    out = {}
    for line in (text or "").split(chr(10)):
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            out[parts[0]] = float(parts[-1])
        except ValueError:
            continue
    return out


def files_mentioned(text):
    """paths a step says it is going to touch. crude on purpose - it is looking
    for something to check, not parsing a patch."""
    found = set()
    for m in re.finditer(r"[\w./\\-]+\.[A-Za-z]{1,5}\b", text or ""):
        token = m.group(0).strip(".")
        if "." in token and not token.startswith("."):
            found.add(token)
    return found


def check(text, ranking_text, threshold=DEFAULT_THRESHOLD):
    """-> list of (path, score) at or above the threshold."""
    ranking = parse_ranking(ranking_text)
    if not ranking:
        return []
    hot = []
    for path in files_mentioned(text):
        for known, score in ranking.items():
            if known.endswith(path) or path.endswith(known):
                if score >= threshold:
                    hot.append((known, score))
                break
    return sorted(set(hot), key=lambda p: -p[1])


def as_warning(hot):
    if not hot:
        return ""
    lines = ["", "this touches code the map says is risky:"]
    for path, score in hot:
        lines.append("- " + path + " (" + str(score) + ")")
    lines.append("say why it has to be this file, or propose a smaller change.")
    return chr(10).join(lines) + chr(10)
