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
always has. so does a decision with no `why:`, and a question the lead has
already decided once in the run: one round each. a decision is not judged by
the files it names: a lead decides inside the spec and the tests it was
given, never over them, so its entry is never the ruling that lets a spec
line or a start test change, and the step acting on it is held by the spec
files check and the start-tests replay like any other. a CONFLICT stop
never comes here; which of the request and the spec holds is the
operator's.

the lines are read by `verbs`, so the decision is never split on a `|`, and
one inside a code fence or a `>` quote is not a decision.
"""
from . import verbs

DECIDED = "DECIDED"
ESCALATE = "ESCALATE"
WHY = "WHY"


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


LEAD_DECIDED = "\n\ndecided:\n\n"
LEAD_BY = "\n\ndecided by "
LEAD_BY_END = ", the flow's lead, before the operator was asked"


def recorded(lead, asker, where, question, decided, why):
    """-> (the decisions.md heading, its body)."""
    return (lead + " decided for " + asker + ": " + " ".join(decided.split()),
            "asked by " + asker + " in " + where + ":\n\n" + question
            + LEAD_DECIDED + "DECIDED: " + decided + "\nwhy: " + why
            + LEAD_BY + lead + LEAD_BY_END)


def decided_of(why):
    """-> the DECIDED and why lines of a decisions.md body the lead's
    decision wrote, without the question it was asked; None for a body
    written any other way."""
    if not why.startswith("asked by ") or not why.endswith(LEAD_BY_END):
        return None
    # the question is a step's words and may hold the markers itself; the
    # decision and its why are read off one line each, so the runner's own
    # markers are the last ones
    _, sep, rest = why.rpartition(LEAD_DECIDED)
    if not sep:
        return None
    return rest.rpartition(LEAD_BY)[0].strip()


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
