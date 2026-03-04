"""a check that is a program, not a prompt.

a gate takes the text a step produced and says pass or fail and why. the flow
lists the ones it wants. nothing here knows what a model is.
"""


class Result(object):
    __slots__ = ("gate", "ok", "detail")

    def __init__(self, gate, ok, detail=""):
        self.gate = gate
        self.ok = ok
        self.detail = detail

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return ("PASS " if self.ok else "FAIL ") + self.gate + \
            ((" - " + self.detail) if self.detail else "")


class Gate(object):
    name = "gate"

    def __init__(self, **opts):
        self.opts = opts

    def run(self, text):
        raise NotImplementedError

    def ok(self, detail=""):
        return Result(self.name, True, detail)

    def fail(self, detail=""):
        return Result(self.name, False, detail)


registry = {}


def register(cls):
    registry[cls.name] = cls
    return cls


def build(spec):
    """{"gate": "regex", ...} -> a Gate. unknown names are an error, not a skip."""
    name = spec.get("gate")
    if name not in registry:
        raise ValueError("unknown gate: " + str(name))
    opts = dict(spec)
    opts.pop("gate")
    return registry[name](**opts)
