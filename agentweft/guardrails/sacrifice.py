"""what a flow gives up when its budget is short, in the order it said so.

`sacrifice:` in flow.yaml lists steps or roles, one per line, first to go
first. the list is read twice: before the first call, when the budget plan
(`blocks.py`) says RISKY, and when the token cap warns that the run is near
it. either way the cuts are made one at a time, in order, and only until the
blocks of the steps still ahead fit what the cap leaves. a role cuts every
one of its steps still ahead.

each cut is a named skip (`skips.py`) under the name the list gave, with a
reason that starts `budget: `, so it is kept in skips.json, written to
decisions.md and said in the handoff. a run picked up later does not take
the cuts over: it plans them again against the cap it has now, so one that
raised the cap runs the steps that now fit. a list that
cannot make the rest fit cuts nothing: before the first call the run says
RISKY, near the cap it waits at the cap as it always did.

what guards the tests is never on the list: the red test, the tests the run
started with and the suite gate, by name or by the step that carries them.
`flow.spec.check_sacrifice` refuses those at load.
"""
from agentweft.flow.spec import step_id, steps_named

from .skips import BUDGET


def listed(fm):
    return list(fm.get("sacrifice") or [])


def steps_of(fm, name):
    return [step_id(s) for s in steps_named(fm.steps, name)]


def uncut(fm, skipped):
    """-> (skipped without the cuts an earlier leg made, their names). a run
    picked up later plans its cuts again against the cap it has now."""
    gone = [n for n in listed(fm) if (skipped.get(n) or "").startswith(BUDGET)]
    return dict((k, v) for k, v in skipped.items() if k not in gone), gone


def choose(fm, ahead, short, skipped):
    """-> [(name, [steps], why)], the cuts that make `short(left)` say
    nothing, in the flow's order, and what is still short after them. a list
    that cannot make it fit cuts nothing: -> [] and what is short as it is.

    `short` is the plan's: why the blocks of the steps given do not fit, []
    when they do. a name already skipped, or with no step ahead, is passed.
    """
    left = list(ahead)
    why = short(left)
    chosen = []
    for name in listed(fm):
        if not why:
            break
        if name in skipped:
            continue
        cut = [s for s in steps_of(fm, name) if s in left]
        if not cut:
            continue
        chosen.append((name, cut, "; ".join(why)))
        left = [s for s in left if s not in cut]
        why = short(left)
    if why:
        return [], short(list(ahead))
    return chosen, why
