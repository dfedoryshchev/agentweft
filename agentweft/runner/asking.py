"""a step that asks instead of going on: the lead decides, or the run parks."""
import re

from agentweft.guardrails import rulings

from . import lead, ruling
from .gating import (and_forged, check_step, cited_past_end, gate_why,
                     off_task, police_line)
from .handoff import EMPTY, PARTIAL, PRESENT


def to_lead(run, step, question, given, where, folder=None, pick=None):
    """-> (the lead's Handoff or None, the end of `step`'s next prompt when
    the lead decided or "", the question as the operator gets it when it
    did not). a flow with no lead, and the lead's own question, go to the
    operator as they were asked. `pick` reads the decision as one of fixed
    options, -> (the option, "") or (None, why it is none), before anything
    is recorded.

    the lead's go is read by the off task check as soon as it answers, like
    any step's: what it found goes on the lead's own line (`meta["police"]`),
    and a hit that stops the run is `meta["off"]`, the decision not held, so
    the step that asked never runs again on it. `folder` is where police.md
    is written."""
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
    off = off_task(run, head, folder)
    out.meta["police"] = police_line(run, head)
    forged = getattr(run, "forged", {}).pop(head, "")
    if off:
        off = and_forged(head + " " + off, forged)
        out.meta["passed"] = out.meta["off"] = off
        return out, "", lead.passed(question, off)
    if forged:
        out.meta["passed"] = forged
        return out, "", lead.passed(question, forged)
    decided, why, wrong = lead.judged(out.output, head, run.workdir,
                                      run.start)
    if not wrong and pick is not None:
        decided, wrong = pick(decided)
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
    DECIDED and the runner did not hold it, else escalated. its cites past
    a file's end are on the line too (`cited_past_end`)."""
    entry = trail.open(run.lead, run.taken(),
                       run.by_step.get(run.lead, run.provider), asker,
                       output=out.output)
    entry.handoff = out.block
    entry.police = out.meta.get("police")
    entry.decided = bool(decided)
    entry.past_end = cited_past_end(run, out, looked=False) or None
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


TESTISH = re.compile(r"::|\btest", re.I)


def names_a_test_or_quotes(text):
    """whether `text` quotes something or may name a test: a decision's own
    words that name a test or quote a spec line let that test or line
    change, so a step's own words never get there unasked."""
    return bool(ruling.QUOTED.search(text) or TESTISH.search(text))


def names_a_spec_or_test(text):
    """whether `text` names a spec file or a test file, with or without a
    line: a question about one is the person's, however it is worded."""
    from agentweft.guardrails.snapshot import is_spec, is_test

    for name in ruling.NAME.findall(text or ""):
        rel = ruling.path_of(re.sub(r":\d+(?:-\d+)?$", "", name))
        if is_spec(rel) or is_test(rel):
            return True
    return False


def lead_s_own(asked, rec, cites):
    """whether the lead's own QUESTION `asked` is the lead's to decide by
    its RECOMMEND `rec`: there is one, it cites no line of the place
    (`cites`), it neither quotes nor may name a test, and neither names a
    spec or test file."""
    return bool(rec) and not cites and not names_a_test_or_quotes(rec) \
        and not names_a_spec_or_test(asked + " " + rec)


def lead_questions(run, step, out):
    """-> [(the question as a NEEDS line, the RECOMMEND or "", the place
    lines it cites, its SIZE or "")] for each QUESTION the lead's own
    handoff asks; [] for any other step."""
    if step != getattr(run, "lead", None) or \
            out.block.get("state") not in (PRESENT, PARTIAL):
        return []
    found = []
    for q in out.block.get("questions") or []:
        text = ruling.flat(q.get("question") or "")
        if not text or ruling.says_none(text):
            continue
        found.append(("NEEDS: " + text, ruling.flat(q.get("recommend") or ""),
                      ruling.place_cites(text, run.workdir),
                      ruling.flat(q.get("size") or "")))
    return found


def lead_escalates(run, step, out):
    """-> the first QUESTION of the lead's own handoff that goes to the
    person, as a NEEDS question, or "": one that cites a line of the place,
    recommends nothing, recommends in words that quote something or may
    name a test (`names_a_test_or_quotes`), or names a spec or test file
    (`names_a_spec_or_test`). the lead's own question has no one above it to
    decide it."""
    for asked, rec, cites, size in lead_questions(run, step, out):
        if lead_s_own(asked, rec, cites):
            continue
        said = [asked]
        if cites:
            said += ["CITES:"] + ["- " + c for c in cites]
        if rec:
            said.append("RECOMMEND: " + rec)
        if size:
            said.append("SIZE: " + size)
        return "\n".join(said)
    return ""


def lead_decides(run, step, out, where):
    """each QUESTION of the lead's own handoff that does not go to the
    person (`lead_escalates`) is the lead's to decide, and its RECOMMEND is
    the decision: put on record as the lead's, so every later step gets it
    and the handoff holds it settled."""
    for asked, rec, cites, _ in lead_questions(run, step, out):
        if not lead_s_own(asked, rec, cites) or lead.key(asked) in run.led:
            continue
        run.led[lead.key(asked)] = rec
        run.rule(*lead.recorded(step, step, where, asked, rec,
                                "the recommendation of " + step
                                + "'s own handoff, and " + step
                                + " is the flow's lead"),
                 by=rulings.LEAD)
        # the handoff was made before the ruling was on record, and the
        # next step reads the rulings off it
        out.meta["rulings"] = run.rulings()
        print(step + ", the flow's lead, decided its own question: " + rec)


def asked_file(step):
    """-> the name, in the run folder, of the answer a step gave before its
    question was taken out as a doubt: `<step>.asked.md`."""
    stem = step[:-len(".md")] if step.endswith(".md") else step
    return stem + ".asked.md"


def worked_then_asked(run, route, step, out, run_dir=None, checked=None):
    """-> None for a step that asked without changing the place, else what
    its gates said of what it changed: "" when they passed. the run parks
    either way; this is what the park can say the step left behind.
    `checked` is what `check_step` already said of this answer."""
    if not run.changed_tree():
        return None
    failed, _ = checked or check_step(run, route, step, out, run_dir=run_dir)
    out.meta.pop("spec_ruling", None)
    out.meta.pop("conflict", None)
    return gate_why(out.meta["gates"]) if failed else ""


HELD = ("spec_ruling", "test_ruling", "conflict")


def goes_on(run, route, step, out, run_dir=None):
    """-> (what `check_step` said, whether the run goes on past `step`'s
    question): it goes on only when the step changed the place, the answer
    it recommends changes no product code (`ruling.asks_no_code`) and every
    gate passed on that change with nothing held for a ruling; the question
    stays in its answer for the person. (None, False) when the gates were
    not run."""
    if not ruling.asks_no_code(out.output) or not run.changed_tree():
        return None, False
    checked = check_step(run, route, step, out, run_dir=run_dir)
    clean = not checked[0] and not checked[1] \
        and not any(k in out.meta for k in HELD)
    return checked, clean
