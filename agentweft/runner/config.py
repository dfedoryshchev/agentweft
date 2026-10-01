import datetime
from pathlib import Path

from agentweft.flow import reader, spec

from .prompts import flow_path


def config(flow):
    return spec.load(reader.read(flow_path(flow, "flow.yaml").read_text()))


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


def verdict(text):
    first = text.strip().split("\n")[0].strip()
    if first.startswith("VERDICT:"):
        return first.split(":", 1)[1].strip()
    return "ok"


def steps(flow):
    return [spec.step_id(s) for s in config(flow).steps]


def due(fm):
    when = fm.get("schedule")
    if not when:
        return True
    if when == "daily":
        return True
    return datetime.date.today().strftime("%A").lower() == when
