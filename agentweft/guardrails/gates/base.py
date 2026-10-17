"""a check that is a program, not a prompt.

a gate takes the text a step produced and says pass or fail and why. the flow
lists the ones it wants. nothing here knows what a model is.
"""
import contextlib
import os
import tempfile


@contextlib.contextmanager
def fresh_python(env=None):
    """-> the environment a gate runs the project's tests in: `env` (or this
    process's) with python neither writing bytecode nor reading any left by
    an earlier run."""
    with tempfile.TemporaryDirectory(prefix="agentweft-pyc-") as empty:
        # a .pyc is trusted on source mtime in whole seconds plus size, so a
        # same-size edit within the second would run the old code
        yield dict(os.environ if env is None else env,
                   PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=empty)


class Result(object):
    """what a gate decided. `gate` is the gate's name, not the gate.

    `unproven` is the lines of a check the step was asked and said it could
    not decide: neither a pass nor a fail, and carried to the record so a
    passing gate never hides them. `tests` is what a gate that ran tests one
    by one saw of each, None for the rest. `skipped` is a pass the run gave a
    gate it did not run, which proves nothing. `broke` is a fail that is the
    gate's own: it could not run, or could not build what it runs on, so it
    says nothing of the step's work. `seconds` is how long it took, None
    until the runner times it.
    """

    __slots__ = ("gate", "ok", "detail", "unproven", "tests", "skipped",
                 "broke", "seconds")

    def __init__(self, gate, ok, detail="", unproven=(), tests=None,
                 skipped=False, broke=False):
        self.gate = gate
        self.ok = ok
        self.detail = detail
        self.unproven = list(unproven)
        self.tests = tests
        self.skipped = skipped
        self.broke = broke
        self.seconds = None

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
    said_by = ()
    start = None
    order = None
    project = None

    def __init__(self, **opts):
        self.opts = opts

    def run(self, text):
        raise NotImplementedError

    def ok(self, detail="", unproven=()):
        return Result(self.name, True, detail, unproven)

    def fail(self, detail="", unproven=()):
        return Result(self.name, False, detail, unproven)

    def broke(self, detail):
        """a fail the gate caused, not the step: see Result."""
        return Result(self.name, False, detail, broke=True)


registry = {}


def register(cls):
    registry[cls.name] = cls
    return cls


def build(config, where=None, ranking="", earlier=(), start=None, order=None,
          said_by=(), project=None):
    """{"gate": "regex", ...} -> a Gate. unknown names are an error, not a skip.

    the argument was called `spec`, which in this repo means a FlowSpec. it is
    a dict of gate options and nothing to do with a spec. `where` is the
    directory the run works in, for the gates that run something there.
    `ranking` is the risk map the run's `context:` block brought back, "" when
    there is none, for the gates that pick what to run by it. `earlier` is
    what the run's other steps answered in this process, oldest first, for a
    gate that can take something a step before this one already said.
    `start` is the run's snapshot of the place as it started
    (`guardrails/snapshot.py`), for a gate that compares against it, and
    `order` the red proof the run holds (`guardrails/redorder.py`).
    `said_by` is the same answers as (role, text), for a gate that takes a
    line only from a step of a given role. `project` is the project.yml the
    run held as it started (`orchestrate/project.py`), for a gate that reads
    one; None reads the file now.
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
    g.said_by = list(said_by or ())
    g.start = start
    g.order = order
    g.project = project
    return g
