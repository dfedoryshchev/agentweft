"""do not let a step walk into the blast radius without saying so.

the risk map has been advisory since june: it goes into the planner's prompt
and the planner mostly weights by it. mostly is the problem. a plan that says
"rewrite the thing everything imports" is exactly the plan a model produces
when it is being helpful, and nothing downstream stops it.

so: before a step that is going to touch files, check what it is about to touch
against the ranking. above the threshold it is flagged, and the flow can be set
to refuse rather than flag, or to park the run so a person makes the edit.

this is the half of the idea that is not a prompt. a prompt asking an agent to
be careful about a hot file is a prompt. this is a number and a comparison.

the runner asks twice. once on the text a step is handed, before the step is
called, because a step that can edit files has already edited them by the time
its answer comes back. and once on what the step said it did, after. the first
catches only the files the plan names: a file the model picks mid-step is not
in the text it was handed, so the second check, and the fence on what actually
changed, are still what report it.
"""
import re

DEFAULT_THRESHOLD = 0.7
NO_RANKING = "no ranking to check against"


def parse_ranking(text):
    """`path score` per line, which is what every ranking i have seen emits.
    anything it cannot parse is skipped rather than guessed at."""
    out = {}
    for line in (text or "").split(chr(10)):
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            out[parts[0].rstrip(":")] = float(parts[-1])
        except ValueError:
            continue
    return out


def files_mentioned(text):
    """paths a step says it is going to touch. crude on purpose - it is looking
    for something to check, not parsing a patch."""
    found = set()
    for m in re.finditer(r"[\w./\\-]+\.[A-Za-z]{1,5}\b", text or ""):
        token = re.sub(r"^(\.\.?/)+", "", _slashes(m.group(0)).rstrip("."))
        if "." in token and not token.startswith("."):
            found.add(token)
    return found


def _slashes(path):
    return path.replace(chr(92), "/")


def _same_file(a, b):
    """one path is the other, or ends with it at a `/`."""
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def check(text, ranking_text, threshold=DEFAULT_THRESHOLD):
    """-> list of (path, score) at or above the threshold, or None when there
    is no ranking to check against.

    None and [] are different answers on purpose. [] is "checked, nothing
    hot"; None is "not checked", which a step set to park or refuse must not
    read as permission to go on."""
    ranking = parse_ranking(ranking_text)
    if not ranking:
        return None
    hot = []
    for path in files_mentioned(text):
        for known, score in ranking.items():
            if _same_file(_slashes(known), path):
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
