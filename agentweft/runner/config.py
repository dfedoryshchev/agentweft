import datetime

from agentweft.flow import reader, spec

from .prompts import flow_path


def config(flow):
    return spec.load(reader.read(flow_path(flow, "flow.yaml").read_text()))


def fanout_step(flow):
    for s in config(flow).steps:
        if s.get("fanout"):
            return s["role"]
    return None


def verdict(text):
    first = text.strip().split("\n")[0].strip()
    if first.startswith("VERDICT:"):
        return first.split(":", 1)[1].strip()
    return "ok"


def steps(flow):
    return [s.get("prompt", s["role"] + ".md") for s in config(flow).steps]


def due(fm):
    when = fm.get("schedule")
    if not when:
        return True
    if when == "daily":
        return True
    return datetime.date.today().strftime("%A").lower() == when
