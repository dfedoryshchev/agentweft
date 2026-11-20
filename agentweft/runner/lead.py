"""a step's question, and the flow's lead step that decides it before the
operator is asked.

a flow names its lead in flow.yaml, `lead: <step>`, or `lead: none`, or a
library role no step of its route plays (`lead: architect`): such a lead has
no page of its own, raises no question, and runs only when a step asks it
something, handed the request and where the spec is (`off_route`). a
`NEEDS:` from any other step goes to the lead first, with the question, its
CITES and its OPTIONS at the very end of the lead's prompt. the lead answers
on lines of its own:

    DECIDED: <the option it picks>
    why: <why, on the next line>

the decision goes into decisions.md as the lead's, and the step that asked
runs again with it at the end of its prompt. the lead can also answer
`ESCALATE: <why>`, and the question parks for the operator, the way a NEEDS
always has. so does a decision with no `why:`, and a question the lead has
already decided once in the run: one round each. the question and the
decision are read first by the reader the lead's own question goes through
(`asking.risk_of`): a question that names a test the run started with, or
carries a SPLIT line, goes to the operator with no lead call, and a decision
that names a start test goes up as the test question before any step acts
on it. a lead decides inside the spec and the tests it was given, never
over them, so its entry is never the ruling that lets a spec line or a
start test change, and the step acting on it is held by the spec files
check, the test-edits check and the start-tests replay like any other. a
CONFLICT stop never comes here; which of the request and the spec holds is
the operator's.

the lines are read by `verbs`, so the decision is never split on a `|`, and
one inside a code fence or a `>` quote is not a decision.
"""
import re

from . import verbs

DECIDED = "DECIDED"
# a reason after a picked option that takes the pick back
NO = re.compile(r"[\s.:;,-]*(?:no|not|never|nope|neither|none|wrong"
                r"|\w+n't)\b", re.I)
ESCALATE = "ESCALATE"
WHY = "WHY"


NUMBERED = re.compile(r"^NEEDS: (\d+)\. ")
EACH = re.compile(r"^[\s*_`-]*(DECIDED|ESCALATE)\s+(\d+)[\s*_`]*:\s*(.*?)\s*$",
                  re.I)


def numbers(question):
    """-> the numbers of the questions one ask holds, as `ruling.asked_of`
    writes them for an answer with more than one NEEDS; [] for a single
    question."""
    found = [int(m.group(1)) for m in (
        NUMBERED.match(line) for line in (question or "").split("\n")) if m]
    return found if len(found) > 1 else []


def parts(question):
    """-> {number: the lines of that question} of a numbered ask."""
    out, at = {}, None
    for line in (question or "").split("\n"):
        m = NUMBERED.match(line)
        if m:
            at = int(m.group(1))
            out[at] = []
        if at is not None:
            out[at].append(line)
    return dict((n, "\n".join(lines).strip()) for n, lines in out.items())


def key(question):
    """-> what makes two questions the same one: the NEEDS line, read
    without case or spacing; every NEEDS line of a numbered ask."""
    lines = (question or "").split("\n")
    if numbers(question):
        lines = [" ".join(line for line in lines if NUMBERED.match(line))]
    return " ".join(lines[0].lower().split())


def each(output, wanted):
    """-> ({number: (the option decided, its why)}, {number: why it was
    escalated}, why the whole ask was escalated or None) of a lead's answer
    to a numbered ask: a `DECIDED <n>:` line with a `why:` line under it,
    or `ESCALATE <n>: <why>`; a bare `ESCALATE:` escalates every one. a
    number not in `wanted`, a second answer to one number and a decision
    with no why are left out."""
    decided, escalated = {}, {}
    seen = verbs.visible(output)
    for i, (_, line) in enumerate(seen):
        head = verbs.key_of(line)
        if head is not None and head[0] == ESCALATE:
            return {}, {}, head[1]
        m = EACH.match(line)
        if not m:
            continue
        n = int(m.group(2))
        if n not in wanted or n in decided or n in escalated:
            continue
        if m.group(1).upper() == ESCALATE:
            escalated[n] = m.group(3)
            continue
        after = next((l for _, l in seen[i + 1:] if l.strip()), "")
        why = verbs.key_of(after)
        if m.group(3) and why is not None and why[0] == WHY and why[1]:
            decided[n] = (m.group(3), why[1])
    return decided, escalated, None


def all_decided(output):
    """-> the `DECIDED <n>:` options of a lead's answer to a numbered ask,
    joined, "" when there is none."""
    return "; ".join(str(n) + ": " + d for n, (d, _) in sorted(
        each(output, range(1, 100))[0].items()))


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


def off_route(task, globs):
    """-> the head of the prompt of a lead that is no step of the route: it
    has read nothing of the run, so it is handed the request and where the
    spec is."""
    return ("you are this flow's lead. you run no step of it: a step comes"
            " to you only when it cannot go on without a decision. read"
            " the spec and the code the question needs, and nothing else;"
            " change no file.\n\nthe request:\n\n" + ((task or "").strip()
                                                       or "(none given)")
            + "\n\nthe spec is " + ", ".join(globs) + " in the place, as far"
            " as it holds them.\n")


def brief(asker, question):
    """-> the end of the lead's prompt: the question last, so its options
    are the final thing the lead reads."""
    return ("\n\nQUESTION FOR THE LEAD. " + asker + " cannot go on without a"
            " decision, and this flow's lead decides it before the operator"
            " is asked. decide it from the spec and the request; do not do"
            " " + asker + "'s work.\n\nanswer with a line `DECIDED: <the"
            " option you pick>` and under it a line `why: <why, with the spec"
            " line it rests on>`. when the answer would change the spec or a"
            " test that was there before the run started, or only the"
            " operator can decide it, answer `ESCALATE: <why>` instead, and"
            " the operator"
            " decides.\n\nwhat " + asker + " asked:\n\n" + question + "\n"
            + each_asked(numbers(question)))


def finding_brief(asker, question):
    """-> the end of the lead's prompt for what a step found beside the
    change: each finding by its number, its three answers last."""
    return ("\n\nFINDINGS FOR THE LEAD. " + asker + " found beside the change"
            " what may be a line of the spec the code already broke when the"
            " run started, on a path the request does not touch, or it"
            " answers a question you decided otherwise. this flow's lead"
            " decides each before the operator is asked; do not do " + asker
            + "'s work.\n\nanswer each by its number with one of:\n- a line"
            " `FIX <n>: <spec file>:<line> for <the path it is broken on>`"
            " and under it a line `spec: breaks <spec file>:<line>, already"
            " at <file>:<line> \"<the code line, word for word>\"`, when the"
            " code breaks that spec line there: the run shows it broken with"
            " a test and fixes it, so the line holds for the old path and the"
            " new\n- a line `DECIDED <n>: <what stands>` with a line `why:"
            " <why, with the spec line it rests on>` under it, when it is no"
            " breach, or your decision stands\n- `ESCALATE <n>: <why>` when"
            " only the operator can decide it; a bare `ESCALATE: <why>`"
            " sends them all.\n\nwhat " + asker + " found:\n\n" + question
            + "\n")


def sibling_wanted(lead, marks):
    """-> what the test writer is told when the lead marked a later step's
    finding as a spec line the code already broke."""
    return ("\n\nMARKED BY THE LEAD. the flow's lead, " + lead + ", marks"
            " what a later step found as a line of the spec the code already"
            " broke when the run started:\n\n" + "\n".join(
                "- " + m for m in marks) + "\n\nwrite a test that fails on"
            " that code line as the run found it, for its outcome, and keep"
            " the tests you wrote. name it on its own line, `SIBLING TEST:"
            " <file>::<name>`; one that passes now shows the line is not"
            " broken there, and the run asks.\n")


def each_asked(found):
    """-> how a numbered ask is answered, "" for a single question."""
    if not found:
        return ""
    return ("\n" + asker_count(found) + " answer each by its number: a line"
            " `DECIDED <n>: <the option you pick>` with a line `why: <why,"
            " with the spec line it rests on>` under it, one pair for every"
            " number. `ESCALATE <n>: <why>` sends that one to the operator;"
            " a bare `ESCALATE: <why>` sends them all.\n")


def asker_count(found):
    return "these are " + str(len(found)) + " questions, numbered " + \
        ", ".join(str(n) for n in found) + ";"


def missing(found):
    """-> what a lead that left numbers undecided is told on its one more
    go."""
    return ("\nyour last answer left questions not decided: "
            + ", ".join(str(n) for n in found) + ". answer each of them by"
            " its number, as above.\n")


def not_decided(lead, found, escalated):
    """-> why a numbered ask goes to the operator: the numbers the lead
    did not decide, each escalated one with its reason."""
    said = []
    for n in found:
        said.append(str(n) + (" (escalated: " + (escalated[n] or "no reason")
                              + ")" if n in escalated else ""))
    return lead + " left questions undecided, not decided: " + ", ".join(said)


def told(lead, question, decided, why):
    """-> the end of the asking step's prompt on its next go."""
    return ("\n\nDECIDED. when this step last ran it asked:\n\n" + question
            + "\n\nthe flow's lead, " + lead + ", decided it, and that"
            " decides it for this step:\n\nDECIDED: " + decided + "\nwhy: "
            + why + "\n")


def told_each(lead, question, decided):
    """-> the end of the asking step's prompt on its next go, after a
    numbered ask: every decision under its number."""
    lines = []
    for n in sorted(decided):
        lines += ["DECIDED " + str(n) + ": " + decided[n][0],
                  "why: " + decided[n][1]]
    return ("\n\nDECIDED. when this step last ran it asked:\n\n" + question
            + "\n\nthe flow's lead, " + lead + ", decided each, and that"
            " decides them for this step:\n\n" + "\n".join(lines) + "\n")


LEAD_DECIDED = "\n\ndecided:\n\n"
LEAD_BY = "\n\ndecided by "
LEAD_BY_END = ", the flow's lead, before the operator was asked"


def recorded(lead, asker, where, question, decided, why):
    """-> (the decisions.md heading, its body)."""
    return (lead + " decided for " + asker + ": " + " ".join(decided.split()),
            "asked by " + asker + " in " + where + ":\n\n" + question
            + LEAD_DECIDED + "DECIDED: " + decided + "\nwhy: " + why
            + LEAD_BY + lead + LEAD_BY_END)


ASSUMED_BY = "\n\nanswered by "
ASSUMED_BY_END = (", whose ASSUMED item cites the line the question cites,"
                  " before the lead or the operator was asked")


def recorded_assumed(owner, n, asker, where, question, item):
    """-> (the decisions.md heading, its body) of a question the runner
    answered with ASSUMED item `n` of step `owner`, `item` its lines. it is
    written in the lead's form, so it decides inside the spec and the tests
    as a lead's decision does, never over them."""
    lines = [l.strip() for l in item.split("\n") if l.strip()]
    choice = lines[0] if lines else ""
    why = " ".join(l for l in lines[1:])
    return (asker + "'s question answered by " + owner + "'s ASSUMED "
            + str(n) + ": " + " ".join(choice.split()),
            "asked by " + asker + " in " + where + ":\n\n" + question
            + LEAD_DECIDED + "DECIDED: " + choice + "\nwhy: " + why
            + ASSUMED_BY + owner + ASSUMED_BY_END)


def told_assumed(question, owner, n, item):
    """-> the end of the asking step's prompt on its next go, for a
    question an ASSUMED item answered."""
    return ("\n\nANSWERED. when this step last ran it asked:\n\n" + question
            + "\n\n" + owner + " already took this as ASSUMED item " + str(n)
            + ", on the line the question cites, and that answers it for this"
            " step:\n\n" + item.strip() + "\n")


def decided_of(why):
    """-> the DECIDED and why lines of a decisions.md body the lead's
    decision wrote, or an ASSUMED item's answer in the same form, without
    the question it was asked; None for a body written any other way."""
    if not why.startswith("asked by "):
        return None
    if why.endswith(LEAD_BY_END):
        by = LEAD_BY
    elif why.endswith(ASSUMED_BY_END):
        by = ASSUMED_BY
    else:
        return None
    # the question is a step's words and may hold the markers itself; the
    # decision and its why are read off one line each, so the runner's own
    # markers are the last ones
    _, sep, rest = why.rpartition(LEAD_DECIDED)
    if not sep:
        return None
    return rest.rpartition(by)[0].strip()


OWN = re.compile(r"^asked by (\S+) in (\S+):\n\nNEEDS: ")
SETTLES, SETTLES_END = " settles, and ", " is the flow's lead"
SETTLED_BY = re.compile(r", which (.+)" + SETTLES + r"\S+" + SETTLES_END + "$")


def own(d):
    """-> (the run it was asked in, the question, the decision, the cite and
    quote that settled it or "", whether it departs from the recommendation
    of the page the run stopped on) of a decisions.md entry the lead wrote on a QUESTION of
    its own handoff; None for any other entry."""
    decided = decided_of(d.why)
    m = OWN.match(d.why)
    if decided is None or not m or not d.why.endswith(
            LEAD_BY + m.group(1) + LEAD_BY_END):
        return None
    departs = d.decided.startswith(m.group(1) + DEPARTS_FOR + m.group(1)
                                   + ": ")
    if not departs and not d.decided.startswith(
            m.group(1) + " decided for " + m.group(1) + ": "):
        return None
    asked = d.why[m.end():].rpartition(LEAD_DECIDED)[0]
    option, why, _ = read(decided)
    by = SETTLED_BY.search(why or "")
    return (m.group(2), asked.split("\n")[0], option or "",
            by.group(1) if by else "", departs)


DEPARTS_FOR = " departs for "
HANDED = ", decided under the operator's hand-back"
# a lead page on the leg after a hand-back says where it now answers
# otherwise a question of the page the run stopped on
DEPARTS = re.compile(r"^\s*DEPARTS:\s*(.*?)\s*$")


def departed(lead, where, question, was, now, why, settled):
    """-> (the decisions.md heading, its body) of a lead page that answers
    otherwise a question the page the run stopped on recommended, after the
    operator handed the call back; `settled` is the hand-back's `<cite>
    "<quote>"`."""
    return (lead + DEPARTS_FOR + lead + ": " + " ".join(now.split()),
            "asked by " + lead + " in " + where + ":\n\n" + question
            + LEAD_DECIDED + "DECIDED: " + now + "\nwhy: departs from the"
            " recommendation it stopped on \"" + " ".join(was.split()) + "\": "
            + " ".join(why.split()) + HANDED + ", which " + settled + SETTLES
            + lead + SETTLES_END + LEAD_BY + lead + LEAD_BY_END)


def departs_of(output):
    """-> [(the question's first words, the new answer, why) or (None, the
    line)] of each DEPARTS line of a lead page, outside fences and quotes;
    a line not in the three parts the form has is (None, the line)."""
    out = []
    for _, line in verbs.visible(output or ""):
        m = DEPARTS.match(line)
        if not m:
            continue
        parts = [p.strip() for p in m.group(1).split(" - ", 2)]
        if len(parts) != 3 or not all(parts):
            out.append((None, line.strip()))
        else:
            out.append(tuple(parts))
    return out


NOW, LATER = "re-iterate now", "accept as later"


def ticket_question(fact):
    """-> the question a critical nice-to-do puts to the lead once the run
    has ended, its two options last."""
    return ("NEEDS: the retro marks a nice-to-do critical, " + fact.id
            + " on " + ", ".join(fact.scopes) + ": " + fact.claim
            + "\nwhy: " + " ".join(fact.get("why").split())
            + "\nsource: " + " ".join(fact.get("source").split())
            + "\nOPTIONS:\n- " + NOW + ": the change is needed before this"
            " work is taken as done; the ticket goes first to the planner of"
            " the next run on its file\n- " + LATER + ": the work stands as it"
            " is; the ticket stays a nice-to-do for a later run\n"
            "start DECIDED: with the exact words of one option, `" + NOW
            + "` or `" + LATER + "`; a decision that opens any other way"
            " decides nothing, and the ticket stays the operator's\n")


def ticket_pick(head):
    """-> how the lead `head`'s DECIDED is read for a critical ticket:
    `fixed_pick` of its two options."""
    return fixed_pick(head, NOW, LATER)


def fixed_pick(head, first, second):
    """-> how the lead `head`'s DECIDED is read when it picks one of two
    fixed options: the option its line opens on, word for word, or why it
    is neither. the option ends the line or is followed by a `:`, `-`, `,`,
    `;` or `.` whose reason does not open on a no ("re-iterate now is not
    needed" and "re-iterate now: no" are neither); a line that opens any
    other way, or names the other option after, is neither."""
    def pick(decided):
        said = " ".join(decided.lower().split()).lstrip("`'\"*- ")
        for option, other in ((first, second), (second, first)):
            rest = said[len(option):]
            if not said.startswith(option) or rest[:1].isalnum() \
                    or rest[:1] == "-" or other in rest:
                continue
            rest = rest.lstrip("`'\"* ")
            if not rest or rest[0] in ":-,;." and not NO.match(rest[1:]):
                return option, ""
        return None, (head + " decided " + decided + ", neither " + first
                      + " nor " + second)
    return pick


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
