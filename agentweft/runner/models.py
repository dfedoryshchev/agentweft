"""which model each role runs on, chosen by the run, the step or the flow.

a step's `model:` asks for a tier, and changing it meant editing the flow.
comparing two models on the same reviewer should not need a different flow
file, so a run can say it: `--model-for reviewer=low,planner=opus`. the value
is a tier (high, mid, low) or a model id, handed over as typed.

order, highest first: the run, the step, the flow's `tiers:`, then whatever
the provider would have used anyway (its block, MODEL_<TIER>, MODEL).

the same map for how hard each role's model thinks is `--effort-for
reviewer=high`, a step's `effort:` and the flow's `efforts:`, in the same
order, before the provider's own (its block, EFFORT_<TIER>, EFFORT).
"""
from agentweft.flow.spec import LEVELS, TIERS

FLAG = "--model-for"
FILE = "models"
EFFORT_FLAG = "--effort-for"
EFFORT_FILE = "efforts"


def pairs(argv, flag=FLAG, what="model"):
    """-> every value given after `flag`, in the order typed."""
    out = []
    for i, word in enumerate(argv):
        if word != flag:
            continue
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            raise ValueError(flag + " needs role=" + what)
        out.append(argv[i + 1])
    return out


def parse(values, what="model"):
    """-> {role: model} out of `role=model[,role=model]` values."""
    out = {}
    for value in values:
        for pair in value.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                raise ValueError(pair + " is not role=" + what)
            role, model = (part.strip() for part in pair.split("=", 1))
            if not role:
                raise ValueError(pair + " has no role")
            if not model:
                raise ValueError(role + " has no " + what)
            if role in out:
                raise ValueError(role + " is given twice")
            out[role] = model
    return out


def efforts(argv):
    """-> {role: level} out of every `--effort-for` typed, each level one
    the providers take."""
    out = parse(pairs(argv, EFFORT_FLAG, "level"), "level")
    for role, level in out.items():
        if level not in LEVELS:
            raise ValueError(EFFORT_FLAG + ": " + role + " should be one of "
                             + ", ".join(LEVELS))
    return out


def effort_of(step, fm, chosen):
    """-> (the level asked for, where it was asked) for this step, or
    (None, None) when nothing chose and the provider decides."""
    role = step["role"]
    if chosen and chosen.get(role):
        return chosen[role], "run"
    if step.get("effort"):
        return step["effort"], "step"
    flow = fm.get("efforts") or {}
    if flow.get(role):
        return flow[role], "flow"
    return None, None


def roles(fm):
    out = []
    for s in fm.steps:
        if s["role"] not in out:
            out.append(s["role"])
    return out


def unknown(chosen, fm):
    """-> why the map names a role this flow does not have, or ""."""
    known = roles(fm)
    for role in chosen:
        if role not in known:
            return ("no role called " + role + " in " + str(fm.name)
                    + ". there is: " + ", ".join(known))
    return ""


def said(chosen):
    return ",".join(r + "=" + m for r, m in sorted(chosen.items()))


def choose(step, fm, chosen):
    """-> (what was asked for, where it was asked) for this step, or
    (None, None) when nothing chose and the provider decides."""
    role = step["role"]
    if chosen and chosen.get(role):
        return chosen[role], "run"
    if step.get("model"):
        return step["model"], "step"
    flow = fm.get("tiers") or {}
    if flow.get(role):
        return flow[role], "flow"
    return None, None


def is_tier(value):
    return value in TIERS


def save(folder, chosen, name=FILE):
    if chosen:
        (folder / name).write_text(said(chosen), encoding="utf-8")


def load(folder, name=FILE):
    """-> the map a run was started with, {} for one that had none."""
    p = folder / name
    if not p.exists():
        return {}
    return parse([p.read_text(encoding="utf-8").strip()])
