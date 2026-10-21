"""a step that asks instead of going on: the lead decides, or the run parks."""
from agentweft.guardrails import rulings

from . import lead, ruling
from .gating import check_step, gate_why
from .handoff import EMPTY, PARTIAL, PRESENT


def to_lead(run, step, question, given, where):
    """-> (the lead's Handoff or None, the end of `step`'s next prompt when
    the lead decided or "", the question as the operator gets it when it
    did not). a flow with no lead, and the lead's own question, go to the
    operator as they were asked."""
    head = getattr(run, "lead", None)
    if head is None or head == step:
        return None, "", question
    asked = lead.key(question)
    if asked in run.led:
        return None, "", lead.again(question, head, run.led[asked])
    if head in (getattr(run, "cut", None) or {}):
        return None, "", lead.passed(question, head + " was cut for the"
                                     " budget, so it does not decide")
    waits = run.budget.ahead(1)
    if waits:
        return None, "", lead.passed(question, "the run cannot pay for "
                                     + head + " to decide it, " + waits[1])
    run.led[asked] = ""
    was = run.produced.get(head)
    try:
        out = run.step(head, previous=given.get(head, EMPTY),
                       last=lead.brief(step, question))
    finally:
        # the lead's decision is not its work: a step that reads what the
        # lead produced still reads its own pass
        if was is None:
            run.produced.pop(head, None)
        else:
            run.produced[head] = was
    forged = getattr(run, "forged", {}).pop(head, "")
    if forged:
        out.meta["passed"] = forged
        return out, "", lead.passed(question, forged)
    decided, why, wrong = lead.judged(out.output, head, run.workdir,
                                      run.start)
    if wrong:
        out.meta["passed"] = wrong
        return out, "", lead.passed(question, wrong)
    run.led[asked] = decided
    run.rule(*lead.recorded(head, step, where, question, decided, why),
             by=rulings.LEAD)
    return out, lead.told(head, question, decided, why), ""


def lead_pass(trail, run, out, asker, decided):
    """write the lead's go at a question into the trail, as its own line:
    decided when its decision is on record, overruled when it answered
    DECIDED and the runner did not hold it, else escalated."""
    entry = trail.open(run.lead, run.taken(),
                       run.by_step.get(run.lead, run.provider), asker,
                       output=out.output)
    entry.handoff = out.block
    entry.decided = bool(decided)
    if decided:
        trail.close(entry, "decided", to=asker)
        return
    said = lead.read(out.output)[0] is not None
    trail.close(entry, "overruled" if said else "escalated",
                why=out.meta.get("passed") or None)


def rides(step, out):
    """-> the doubt `step`'s question became, "" when it asked nothing that
    changes no code. the question comes out of `out` and the doubt goes into
    its block, so every reader after this sees a step that went on."""
    found = ruling.demoted(out.output)
    if found is None:
        return ""
    out.output, doubt = found
    if out.block.get("state") in (PRESENT, PARTIAL):
        out.block["doubts"].append(doubt)
    print(step + " asked what changes no code, and went on: " + doubt)
    return doubt


def asked_file(step):
    """-> the name, in the run folder, of the answer a step gave before its
    question was taken out as a doubt: `<step>.asked.md`."""
    stem = step[:-len(".md")] if step.endswith(".md") else step
    return stem + ".asked.md"


def worked_then_asked(run, route, step, out, run_dir=None):
    """-> None for a step that asked without changing the place, else what
    its gates said of what it changed: "" when they passed. the run parks
    either way; this is what the park can say the step left behind."""
    if not run.changed_tree():
        return None
    failed, _ = check_step(run, route, step, out, run_dir=run_dir)
    out.meta.pop("spec_ruling", None)
    out.meta.pop("conflict", None)
    return gate_why(out.meta["gates"]) if failed else ""
