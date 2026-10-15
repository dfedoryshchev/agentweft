import datetime
from pathlib import Path

from agentweft.flow import reader, spec

from .prompts import flow_path


def config(flow):
    return spec.load(reader.read(flow_path(flow, "flow.yaml").read_text(
        encoding="utf-8")))


def fanout_step(flow):
    """-> the fanned-out step, named the way every other step is named."""
    for s in config(flow).steps:
        if s.get("fanout"):
            return spec.step_id(s)
    return None


def where(fm, given=None):
    """-> the directory a run works in, absolute, and checked to be there.

    the place a person named beats the flow file's, and a run that names none
    works where it was started. a relative path is made absolute here, once, so
    nothing later has to know what directory the process happened to be in.
    """
    named = given or fm.get("workdir") or "."
    path = Path(named).resolve()
    if not path.exists():
        raise ValueError("workdir " + str(named) + ": no such directory")
    if not path.is_dir():
        raise ValueError("workdir " + str(named) + ": not a directory")
    return path


VERDICTS = ("ok", "redo")
SPEC_CHANGE = "spec change request"
SHAPES = VERDICTS + (SPEC_CHANGE,)


def declared(prompt):
    """-> the verdicts a step's own words allow it, each written as a line of
    its own: `VERDICT: ok`, `VERDICT: redo`, `VERDICT: spec change request`.
    a word the runner does nothing with is not one, so it is never in here."""
    said = set(line.strip() for line in prompt.split("\n"))
    return tuple(w for w in SHAPES if "VERDICT: " + w in said)


def asks_for_verdict(prompt):
    """-> whether a step's own words tell it to answer with a verdict line.

    the contract is the two lines the library gives a reviewer and a judge, so
    a prompt that only mentions a verdict in passing has not asked for one.
    """
    return any(w in VERDICTS for w in declared(prompt))


def verdict(text, asked=False):
    """-> the word on a `VERDICT:` first line, lower case and without the full
    stop. a step not asked for one and without the line is "ok"; a step asked
    for one and without it is "", which is no answer at all."""
    first = text.strip().split("\n")[0].strip()
    if first.upper().startswith("VERDICT:"):
        return first.split(":", 1)[1].strip().rstrip(".!").strip().lower()
    return "" if asked else "ok"


def steps(flow):
    return [spec.step_id(s) for s in config(flow).steps]


def due(fm):
    when = fm.get("schedule")
    if not when:
        return True
    if when == "daily":
        return True
    return datetime.date.today().strftime("%A").lower() == when
