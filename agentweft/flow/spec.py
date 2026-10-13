"""a flow spec: what it takes, what it gives back, and what is always true.

the steps have lived in flow.yaml since september. this adds the part that says
what the thing is FOR, so a run can be judged against something other than my
memory of what it used to look like.
"""
import difflib


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
         "journal", "max_calls", "max_tokens", "provider", "context", "workdir",
         "tiers", "investigate")
STEP_KNOWN = ("role", "prompt", "fanout", "on_redo", "must_produce", "workers",
              "gates", "provider", "preflight", "pause", "model", "tools",
              "reports")
PROMISES_KNOWN = ("inputs", "outputs", "invariants")
CONTEXT_KNOWN = ("command", "arguments", "tool", "timeout")
PREFLIGHT_KNOWN = ("mode", "threshold")

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

PREFLIGHT_MODES = ("flag", "refuse", "park")

# `investigate:` puts one step in front of the flow's own that finds the cause
# of the task and everything it reaches before anything is written. `cause` is
# the cause and its sites, `plan` adds the tests to write and what the person
# has to decide. the step's name is not `planner`, which already means a step
# whose lines are fanned out and that is handed the risk map.
INVESTIGATE = ("off", "cause", "plan")
INVESTIGATOR = "investigator"
# one site per line, `file:function`: a few anchors and not the code, which the
# step after reads for itself
SITES = r"^SITES:[ \t]*\n(?:[ \t]*-[ \t]+\S+:\S+.*\n?)+"
ROOTED = r"^ROOTED:[ \t]*(yes|no)\b"


def investigating(raw):
    """-> the mode a flow asked for, "off" when it asked for none.

    a bare `off` in yaml is read as false, so false is off as well.
    """
    value = raw.get("investigate")
    if value is None or value is False:
        return "off"
    return value


def investigator():
    return {"role": INVESTIGATOR, "prompt": INVESTIGATOR + ".md",
            "must_produce": "CAUSE:", "tools": ["read", "grep", "shell"],
            "gates": [{"gate": "regex", "pattern": SITES},
                      {"gate": "regex", "pattern": ROOTED}]}


def with_investigator(raw):
    """-> raw, with the investigator as its first step when it asked for one."""
    if investigating(raw) not in INVESTIGATE[1:]:
        return raw
    out = dict(raw)
    out["steps"] = [investigator()] + list(raw.get("steps") or [])
    return out


TYPES = {"timeout": int, "retries": int, "workers": int, "max_calls": int,
         "max_tokens": int, "journal": bool, "name": str, "workdir": str}


def meant(word, known):
    """-> ", did you mean <the closest known word>?", or "" when none is close."""
    near = difflib.get_close_matches(str(word), list(known), n=1)
    return ", did you mean " + near[0] + "?" if near else ""


def unknown(key, known):
    return "unknown key " + str(key) + meant(key, known)


def block(where, value, known):
    """-> complaints about a nested mapping such as `context:`."""
    if not isinstance(value, dict):
        return [where + " should be a mapping"]
    return [where + ": " + unknown(k, known) for k in value if k not in known]


def check_gates(at, gates):
    """-> complaints about a step's `gates:`, made before the step is paid for.

    `gates.build` refuses the same names, but only once the step has run.
    """
    # here and not at the top: the coverage and reject gates read project.yml
    # through orchestrate, which loads this module
    from agentweft.guardrails.gates import registry

    if not isinstance(gates, list):
        return [at + "gates should be a list"]
    bad = []
    for j, g in enumerate(gates):
        if not isinstance(g, dict):
            bad.append(at + "gate " + str(j) + " should be a mapping")
            continue
        name = g.get("gate")
        if name is None:
            bad.append(at + "gate " + str(j) + " has no gate name")
            continue
        if name not in registry:
            bad.append(at + "no such gate " + str(name) + meant(name, registry)
                       + ". there is: " + ", ".join(sorted(registry)))
            continue
        takes = registry[name].options
        for k in g:
            if k != "gate" and k not in takes:
                bad.append(at + "gate " + str(name) + " has no option " + str(k)
                           + meant(k, takes)
                           + ". it takes: " + (", ".join(takes) or "nothing"))
    return bad


def check(raw):
    """-> list of complaints. a typo in flow.yaml used to just do nothing."""
    bad = []
    for key in REQUIRED:
        if key not in raw:
            bad.append("missing " + key)
    for key in raw:
        if key not in KNOWN:
            bad.append(unknown(key, KNOWN))
            continue
        want = TYPES.get(key)
        if want and not isinstance(raw[key], want):
            bad.append(key + " should be " + want.__name__)
    if raw.get("promises") is not None:
        more = block("promises", raw["promises"], PROMISES_KNOWN)
        bad.extend(more)
        inv = raw["promises"].get("invariants") if not more else None
        if inv is not None and not isinstance(inv, list):
            bad.append("promises: invariants should be a list")
    if raw.get("context") is not None:
        bad.extend(block("context", raw["context"], CONTEXT_KNOWN))
    earlier = []
    for i, step in enumerate(raw.get("steps") or []):
        if not isinstance(step, dict) or "role" not in step:
            bad.append("step " + str(i) + " has no role")
            continue
        at = "step " + str(i) + ": "
        for key in step:
            if key not in STEP_KNOWN:
                bad.append(at + unknown(key, STEP_KNOWN))
        if step.get("gates") is not None:
            bad.extend(check_gates(at, step["gates"]))
        if step.get("preflight") is not None:
            pre = step["preflight"]
            bad.extend(at + c for c in block("preflight", pre, PREFLIGHT_KNOWN))
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
        pre = step.get("preflight")
        if isinstance(pre, dict) and \
                pre.get("mode", "flag") not in PREFLIGHT_MODES:
            bad.append("step " + str(i) + ": preflight mode should be one of "
                       + ", ".join(PREFLIGHT_MODES))
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
    if investigating(raw) not in INVESTIGATE:
        bad.append("investigate should be one of " + ", ".join(INVESTIGATE))
    bad.extend(check_tiers(with_investigator(raw)))
    return bad


def check_tiers(raw):
    """`tiers:` is a tier per role, held to the same rule as a step's own."""
    chosen = raw.get("tiers")
    if chosen is None:
        return []
    if not isinstance(chosen, dict):
        return ["tiers should be a mapping of role to tier"]
    known = []
    for step in raw.get("steps") or []:
        if isinstance(step, dict) and step.get("role") not in known:
            known.append(step.get("role"))
    bad = []
    for role, tier in chosen.items():
        if role not in known:
            bad.append("tiers: no role called " + str(role) + ". there is: "
                       + ", ".join(str(r) for r in known))
        elif tier not in TIERS:
            bad.append("tiers: " + str(role) + " should be one of "
                       + ", ".join(TIERS))
    return bad


def load(raw):
    bad = check(raw)
    if bad:
        raise ValueError("flow.yaml: " + "; ".join(bad))
    return FlowSpec(with_investigator(raw))
