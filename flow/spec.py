"""a flow spec: what it takes, what it gives back, and what is always true.

the steps have lived in flow.yaml since september. this adds the part that says
what the thing is FOR, so a run can be judged against something other than my
memory of what it used to look like.
"""


class Promises(object):
    __slots__ = ("inputs", "outputs", "invariants")

    def __init__(self, inputs="", outputs="", invariants=None):
        self.inputs = inputs
        self.outputs = outputs
        self.invariants = list(invariants or [])

    def as_prompt(self):
        if not self.invariants:
            return ""
        lines = ["", "this flow promises, every time:"]
        for i in self.invariants:
            lines.append("- " + i)
        return "\n".join(lines) + "\n"


class FlowSpec(object):
    __slots__ = ("name", "steps", "promises", "raw")

    def __init__(self, raw):
        self.raw = raw
        self.name = raw.get("name", "")
        self.steps = raw.get("steps", [])
        p = raw.get("promises") or {}
        self.promises = Promises(p.get("inputs", ""), p.get("outputs", ""),
                                 p.get("invariants"))

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def __getitem__(self, key):
        return self.raw[key]


REQUIRED = ("name", "steps")
KNOWN = ("name", "steps", "promises", "schedule", "timeout", "retries", "workers",
         "temperature", "journal", "note", "max_calls", "max_tokens")
STEP_KNOWN = ("role", "prompt", "fanout", "on_redo", "must_produce", "workers")


TYPES = {"timeout": int, "retries": int, "workers": int, "max_calls": int,
         "max_tokens": int, "journal": bool, "name": str}


def check(raw):
    """-> list of complaints. a typo in flow.yaml used to just do nothing."""
    bad = []
    for key in REQUIRED:
        if key not in raw:
            bad.append("missing " + key)
    for key in raw:
        if key not in KNOWN:
            bad.append("unknown key " + str(key))
            continue
        want = TYPES.get(key)
        if want and not isinstance(raw[key], want):
            bad.append(key + " should be " + want.__name__)
    for i, step in enumerate(raw.get("steps") or []):
        if not isinstance(step, dict) or "role" not in step:
            bad.append("step " + str(i) + " has no role")
            continue
        for key in step:
            if key not in STEP_KNOWN:
                bad.append("step " + str(i) + ": unknown key " + str(key))
    return bad


def load(raw):
    bad = check(raw)
    if bad:
        raise ValueError("flow.yaml: " + "; ".join(bad))
    return FlowSpec(raw)
