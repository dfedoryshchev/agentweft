"""a step's question, and the flow's lead step that decides it before the
operator is asked.

a flow names its lead in flow.yaml, `lead: <step>`, or `lead: none`. a
`NEEDS:` from any other step goes to the lead first, with the question, its
CITES and its OPTIONS at the very end of the lead's prompt. the lead answers
on lines of its own:

    DECIDED: <the option it picks>
    why: <why, on the next line>

the decision goes into decisions.md as the lead's, and the step that asked
runs again with it at the end of its prompt. the lead can also answer
`ESCALATE: <why>`, and the question parks for the operator, the way a NEEDS
always has. so does a decision with no `why:`, one that names a spec file or
a test that was there when the run started (a lead decides inside the spec
and the tests it was given, never over them), and a question the lead has
already decided once in the run: one round each. a CONFLICT stop never comes
here; which of the request and the spec holds is the operator's.

the lines are read by `verbs`, so the decision is never split on a `|`, and
one inside a code fence or a `>` quote is not a decision.
"""
import re
from pathlib import Path

from agentweft.guardrails import snapshot

from . import verbs

DECIDED = "DECIDED"
ESCALATE = "ESCALATE"
WHY = "WHY"

PATH = re.compile(r"[A-Za-z0-9_.\\/-]*[A-Za-z0-9_]\.[A-Za-z][A-Za-z0-9]*")


def key(question):
    """-> what makes two questions the same one: the NEEDS line, read
    without case or spacing."""
    first = (question or "").split("\n")[0]
    return " ".join(first.lower().split())


def read(output):
    """-> (the option decided, its why, None), or (None, "", the reason) for
    an ESCALATE, or (None, "", None) for an answer that did neither. the
    first DECIDED or ESCALATE line wins; the why is the first `why:` line
    after a DECIDED and the plain lines straight under it."""
    decided = None
    why = []
    seen = verbs.visible(output)
    for i, (_, line) in enumerate(seen):
        head = verbs.key_of(line)
        if decided is None:
            if head is not None and head[0] == ESCALATE:
                return None, "", head[1]
            if head is not None and head[0] == DECIDED and head[1]:
                decided = head[1]
            continue
        if head is None or head[0] != WHY:
            continue
        why.append(head[1])
        for _, more in seen[i + 1:]:
            if not more.strip() or verbs.key_of(more) is not None:
                break
            why.append(more.strip())
        break
    if decided is None:
        return None, "", None
    return decided, " ".join(w for w in why if w), None


def changes(decided, workdir, start):
    """-> the first file `decided` names that is a spec, or a test that was
    there when the run started, or "" for none. with no start to read, a
    test file that is in the place now counts as one that was."""
    root = Path(workdir).resolve()
    for found in PATH.findall(decided or ""):
        rel = found.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if snapshot.is_spec(rel):
            return rel
        if not snapshot.is_test(rel):
            continue
        if start is not None and getattr(start, "hashed", False) \
                and start.root is not None:
            try:
                at = (root / rel).resolve().relative_to(
                    Path(start.root).resolve()).as_posix()
            except ValueError:
                continue
            if at in start.tests:
                return rel
        elif (root / rel).is_file():
            return rel
    return ""


def judged(output, lead, workdir, start):
    """-> (the option, its why, "") when the lead decided, or (None, "", why
    the operator decides it instead)."""
    decided, why, escalated = read(output)
    if escalated is not None:
        return None, "", lead + " escalated it: " + (
            escalated or "it gave no reason")
    if decided is None:
        return None, "", (lead + " answered with neither DECIDED: nor"
                          " ESCALATE:")
    if not why:
        return None, "", (lead + " decided " + decided + " with no why: line"
                          " under it")
    hit = changes(decided, workdir, start)
    if hit:
        return None, "", (lead + " decided " + decided + ", which changes "
                          + hit + ", and a change to the spec or to a test"
                          " the run started with is not the lead's")
    return decided, why, ""


def brief(asker, question):
    """-> the end of the lead's prompt: the question last, so its options
    are the final thing the lead reads."""
    return ("\n\nQUESTION FOR THE LEAD. " + asker + " cannot go on without a"
            " decision, and this flow's lead decides it before the operator"
            " is asked. decide it from the spec and the request; do not do"
            " " + asker + "'s work.\n\nanswer with a line `DECIDED: <the"
            " option you pick>` and under it a line `why: <why, with the spec"
            " line it rests on>`. when the answer would change the spec or a"
            " test that was there before the run started, or it is not yours"
            " to decide, answer `ESCALATE: <why>` instead, and the operator"
            " decides.\n\nwhat " + asker + " asked:\n\n" + question + "\n")


def told(lead, question, decided, why):
    """-> the end of the asking step's prompt on its next go."""
    return ("\n\nDECIDED. when this step last ran it asked:\n\n" + question
            + "\n\nthe flow's lead, " + lead + ", decided it, and that"
            " decides it for this step:\n\nDECIDED: " + decided + "\nwhy: "
            + why + "\n")


def recorded(lead, asker, where, question, decided, why):
    """-> (the decisions.md heading, its body)."""
    return (lead + " decided for " + asker + ": " + " ".join(decided.split()),
            "asked by " + asker + " in " + where + ":\n\n" + question
            + "\n\ndecided:\n\nDECIDED: " + decided + "\nwhy: " + why
            + "\n\ndecided by " + lead + ", the flow's lead, before the"
            " operator was asked")


def passed(question, why):
    """-> the question as the operator gets it once the lead did not decide
    it."""
    return (question + "\n\nthe flow's lead did not decide it: " + why
            + ". so it is the operator's.")


def again(question, lead, decided):
    """-> the question as the operator gets it when it comes back after the
    lead decided it once."""
    return (question + "\n\nthe flow's lead, " + lead + ", already decided"
            " this question once in this run (" + decided + "), and it was"
            " asked again. a question gets one round with the lead, so it is"
            " the operator's.")
