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


def step_id(step):
    """what a step is called outside flow.yaml: the file its words live in.

    a role is what a step IS and the prompt file is only where its words
    happen to live, so one role can be two steps with a file each. the file
    name is what tells those two apart, which is why it is the name the
    runner, the router and the run directory all use.
    """
    return step.get("prompt", step["role"] + ".md")


def step_name(step):
    """what a step is called by another step: its file, without the `.md`.

    `reports:` is a list a person writes next to a role, and a role has never
    carried an extension there. so the step's name in that list does not carry
    one either, and a flow whose file is named after its role reads the same
    word both ways.
    """
    name = step_id(step)
    return name[:-3] if name.endswith(".md") else name


def steps_named(steps, name):
    """-> the steps `name` stands for, in flow order.

    a ROLE stands for every step that declared it, which is what makes a pair
    of personas addressable as the pair they are: the reviewer that was told
    to cut and the reviewer that was told to expand are both the reviewer, and
    a judge that was handed one of them is judging nothing. a STEP's own name
    stands for that one step, for a flow that wants a single stance judged.
    """
    return [s for s in steps if s["role"] == name or step_name(s) == name]


REQUIRED = ("name", "steps")
KNOWN = ("name", "steps", "promises", "schedule", "timeout", "retries", "workers",
         "temperature", "journal", "note", "max_calls", "max_tokens", "provider",
         "context")
STEP_KNOWN = ("role", "prompt", "fanout", "on_redo", "must_produce", "workers",
              "gates", "provider", "preflight", "pause", "model", "tools",
              "reports")

# `model` on a step is a tier, not an id. the workflow file's header says the
# model names came out of the imported prompts on the way over, because a tier
# means something to any provider and a version string means something to one
# of them for about a quarter. a flow file naming one would put them back.
TIERS = ("high", "mid", "low")

# `tools` on a step is what it is allowed to touch, and these are the six words
# the imported agent files have been granting each other since they arrived.
# the list is closed on purpose: a grant nothing has a name for is not a
# narrower grant, it is a word this repo cannot check anything against, and it
# would sit in a file looking like a boundary. `guardrails/boundary.py` is what
# reads a grant; this is only the vocabulary it and the flow files share.
GRANTS = ("read", "grep", "write", "edit", "shell", "browser")


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
    earlier = []
    for i, step in enumerate(raw.get("steps") or []):
        if not isinstance(step, dict) or "role" not in step:
            bad.append("step " + str(i) + " has no role")
            continue
        for key in step:
            if key not in STEP_KNOWN:
                bad.append("step " + str(i) + ": unknown key " + str(key))
        if step.get("model") and step["model"] not in TIERS:
            bad.append("step " + str(i) + ": model should be one of "
                       + ", ".join(TIERS))
        # `is not None` rather than truthiness: `tools: []` is a step saying it
        # may touch nothing, which is a boundary and not a missing one.
        if step.get("tools") is not None:
            if not isinstance(step["tools"], list):
                bad.append("step " + str(i) + ": tools should be a list")
            else:
                for tool in step["tools"]:
                    if tool not in GRANTS:
                        bad.append("step " + str(i) + ": no such tool "
                                   + str(tool) + ". there is: "
                                   + ", ".join(GRANTS))
        if step.get("reports") is not None:
            if not isinstance(step["reports"], list):
                bad.append("step " + str(i) + ": reports should be a list")
            else:
                for name in step["reports"]:
                    if name not in earlier:
                        bad.append("step " + str(i) + ": reports " + str(name)
                                   + ", which is not a role or a step before "
                                   "it. there is: "
                                   + (", ".join(earlier) or "nothing"))
        for name in (step["role"], step_name(step)):
            if name not in earlier:
                earlier.append(name)
    return bad


def load(raw):
    bad = check(raw)
    if bad:
        raise ValueError("flow.yaml: " + "; ".join(bad))
    return FlowSpec(raw)
