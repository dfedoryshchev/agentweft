"""a check that is a program, not a prompt.

a gate takes the text a step produced and says pass or fail and why. the flow
lists the ones it wants. nothing here knows what a model is.
"""


class Result(object):
    """what a gate decided. `gate` is the gate's name, not the gate.

    `unproven` is the lines of a check the step was asked and said it could
    not decide: neither a pass nor a fail, and carried to the record so a
    passing gate never hides them.
    """

    __slots__ = ("gate", "ok", "detail", "unproven")

    def __init__(self, gate, ok, detail="", unproven=()):
        self.gate = gate
        self.ok = ok
        self.detail = detail
        self.unproven = list(unproven)

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return ("PASS " if self.ok else "FAIL ") + self.gate + \
            ((" - " + self.detail) if self.detail else "")


class Gate(object):
    name = "gate"
    options = ()
    where = None
    ranking = ""
    earlier = ()

    def __init__(self, **opts):
        self.opts = opts

    def run(self, text):
        raise NotImplementedError

    def ok(self, detail="", unproven=()):
        return Result(self.name, True, detail, unproven)

    def fail(self, detail="", unproven=()):
        return Result(self.name, False, detail, unproven)


registry = {}


def register(cls):
    registry[cls.name] = cls
    return cls


def build(config, where=None, ranking="", earlier=()):
    """{"gate": "regex", ...} -> a Gate. unknown names are an error, not a skip.

    the argument was called `spec`, which in this repo means a FlowSpec. it is
    a dict of gate options and nothing to do with a spec. `where` is the
    directory the run works in, for the gates that run something there.
    `ranking` is the risk map the run's `context:` block brought back, "" when
    there is none, for the gates that pick what to run by it. `earlier` is
    what the run's other steps answered in this process, oldest first, for a
    gate that can take something a step before this one already said.
    """
    name = config.get("gate")
    if name not in registry:
        raise ValueError("unknown gate: " + str(name) + ". there is: "
                         + ", ".join(sorted(registry)))
    opts = dict(config)
    opts.pop("gate")
    g = registry[name](**opts)
    g.where = where
    g.ranking = ranking or ""
    g.earlier = list(earlier or ())
    return g
