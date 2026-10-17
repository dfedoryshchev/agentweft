"""a step that says what it writes is held to it.

`writes:` on a step names what it may change, of the three things the start
snapshot hashes (`snapshot.py`): the tests, the spec files and the product
code (every other file, the test runner's own left out of all three).

- `tests`: test files only.
- `product`: product code and tests. the spec files too when the flow's
  `spec_files: additions` lets a step add to them, which that check holds,
  or when a ruling in decisions.md quotes every spec line that moved.
- `spec`: the spec files only, created or changed.
- `none`: nothing.

the three are hashed before the step's first go and again after each go, so
it is read by content and never by time, and a step that commits its edit is
read the same as one that leaves it in the work tree. a step that changed
what it may not fails like a gate, with the files named.
"""
from agentweft.guardrails.snapshot import changed

NAME = "writes"
# in the order `Snapshot.hashes()` hands them back
KINDS = ("tests", "spec files", "product code")
MAY = {"tests": ("tests",),
       "product": ("tests", "product code"),
       "spec": ("spec files",),
       "none": ()}
SAYS = {"tests": "tests only", "product": "product code",
        "spec": "the spec only", "none": "nothing"}


def declared(fm):
    """whether any step of the flow says what it writes."""
    return any(s.get("writes") in MAY for s in fm.steps)


def may(writes, spec_ok=False):
    """-> what a `writes:` value may change, of KINDS. `spec_ok` is a
    product step let into the spec files by the flow or a ruling."""
    out = MAY[writes]
    if writes == "product" and spec_ok:
        out = out + ("spec files",)
    return out


def held(step, writes, before, now, place, spec_ok=False):
    """-> why `step` fails for what changed between `before` and `now`,
    each `Snapshot.hashes()`, or "" when it kept to what it said. `place`
    turns a path from the top of the repo into one from the place."""
    allowed = may(writes, spec_ok)
    out = []
    for kind, was, has in zip(KINDS, before, now):
        moved = changed(was, has) if kind not in allowed else []
        if moved:
            out.append(kind + ": " + ", ".join(place(rel) for rel in moved))
    if not out:
        return ""
    return (step + " writes " + SAYS[writes] + " and changed "
            + "; ".join(out) + ". put each back as the run found it")


def unseen(step, writes):
    """-> why a step fails when there is no start snapshot to read it by."""
    return (step + " writes " + SAYS[writes] + ", and with no start snapshot"
            " nothing shows it kept to that")


def as_prompt(globs):
    """-> what a `writes: spec` step is told: the spec files, one glob a
    line. the cli can take a tool away but not hold an edit to a path, so
    the path is asked here and checked after the step."""
    return ("\n\nyou write the spec and nothing else. the spec files, from"
            " the top of the place:\n"
            + "".join("- " + g + "\n" for g in globs)
            + "you may create or change these only. changing any other file"
            " fails this step.\n")
