"""a step that asks instead of going on: an ASSUMED item of the run answers
it, the lead decides, or the run parks."""
import re

from agentweft.guardrails import rulings

from . import lead, ruling
from .gating import (and_forged, check_step, cited_past_end, gate_why,
                     off_task, police_line)
from .handoff import EMPTY, PARTIAL, PRESENT
from .handoff import parse as parse_handoff


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
    out, held = lead_go(run, head, given, lead.brief(step, question), folder)
    if held:
        return out, "", lead.passed(question, held)
    if lead.numbers(question):
        return each_to_lead(run, step, question, given, where, folder, out)
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


IF_WRONG = re.compile(r"^\s*if\s+wrong\s*:", re.I)
ASKED_LINE = re.compile(r"^NEEDS: (?:\d+\. )?")


def cited_lines(text):
    """-> the (file, line) of every `<file>:<line>` or `<file>:<a>-<b>` in
    `text`."""
    out = set()
    for m in ruling.MARKED.finditer(text or ""):
        first = int(m.group(2))
        out |= set((ruling.path_of(m.group(1)), n)
                   for n in range(first, int(m.group(3) or first) + 1))
    return out


def assumed_items(run, step):
    """-> [(the step, its number, the item's lines, the lines it cites)] of
    each ASSUMED item the run's other steps handed over, in the order they
    ran. what an item cites is read off its choice and its `why:`; its `if
    wrong:` is what would follow if it were wrong, never what it rests on."""
    out = []
    for owner, text in list((getattr(run, "produced", None) or {}).items()):
        if owner == step or not text:
            continue
        block = parse_handoff(text)
        if block.get("state") not in (PRESENT, PARTIAL):
            continue
        for n, item in enumerate(block.get("assumed") or [], 1):
            rests = "\n".join(l for l in item.split("\n")
                              if not IF_WRONG.match(l))
            found = cited_lines(rests)
            if found:
                out.append((owner, n, item, found))
    return out


def asked_key(question):
    """-> one question of an ask as its words, without its number."""
    first = (question or "").split("\n")[0]
    return " ".join(ASKED_LINE.sub("", first).lower().split())


def assumed_answer(run, step, question, where):
    """-> None when no question of `question` is answered by an ASSUMED
    item, else (what `step` is told on its next go, the rest of the ask or
    "" when nothing is left for the lead). a question is answered by the
    first ASSUMED item of another step of the run that cites a line the
    question cites: the match is the cited line, never the words. that
    answer is put on record in the lead's form and nobody is called. a
    question already answered this way and asked again is left for the
    lead."""
    told_once = getattr(run, "assumed_led", None)
    if told_once is None:
        told_once = run.assumed_led = set()
    items = assumed_items(run, step)
    numbered = lead.parts(question) if lead.numbers(question) else None
    asks = sorted(numbered.items()) if numbered else [(None, question)]
    told, left = [], []
    for n, text in asks:
        key = asked_key(text)
        hit = None
        if key not in told_once:
            cites = cited_lines(text)
            hit = next((i for i in items if i[3] & cites), None)
        if hit is None:
            left.append(text)
            continue
        owner, at, item, _ = hit
        told_once.add(key)
        run.rule(*lead.recorded_assumed(owner, at, step, where, text, item),
                 by=rulings.ASSUMED, step=owner, item=at)
        told.append(lead.told_assumed(text, owner, at, item))
        print(step + "'s question is answered by " + owner + "'s ASSUMED "
              + str(at) + ", on the line it cites: " + key)
    if not told:
        return None
    if len(left) == 1:
        left = [ASKED_LINE.sub("NEEDS: ", left[0], count=1)]
    elif len(left) > 1:
        left = [ASKED_LINE.sub("NEEDS: " + str(k) + ". ", t, count=1)
                for k, t in enumerate(left, 1)]
    return "".join(told), "\n".join(left)


def lead_go(run, head, given, last, folder):
    """-> (the lead's answer, why it is not held or ""): one go of the lead
    with `last` at the end of its prompt, read by the off task check and
    the rulings check as soon as it answers."""
    was = run.produced.get(head)
    try:
        out = run.step(head, previous=given.get(head, EMPTY), last=last)
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
        return out, off
    if forged:
        out.meta["passed"] = forged
        return out, forged
    return out, ""


def each_to_lead(run, step, question, given, where, folder, out):
    """`to_lead` for an ask of several numbered questions, after the lead's
    first answer `out`: every number decided goes on record, one entry
    each, and `step` is told them all. a lead that leaves a number neither
    decided nor escalated is asked once more for those; any still not
    decided sends the whole ask to the operator, with nothing recorded."""
    head = run.lead
    wanted = lead.numbers(question)
    decided, escalated, whole = lead.each(out.output, wanted)
    left = [n for n in wanted if n not in decided and n not in escalated]
    if whole is None and left and not run.budget.ahead(1):
        out, held = lead_go(run, head, given, lead.brief(step, question)
                            + lead.missing(left), folder)
        if held:
            return out, "", lead.passed(question, held)
        more, also, whole = lead.each(out.output, left)
        decided.update(more)
        escalated.update(also)
    if whole is not None:
        wrong = head + " escalated it: " + (whole or "it gave no reason")
    else:
        short = [n for n in wanted if n not in decided]
        wrong = lead.not_decided(head, short, escalated) if short else ""
    if wrong:
        out.meta["passed"] = wrong
        return out, "", lead.passed(question, wrong)
    asked = lead.parts(question)
    for n in wanted:
        run.rule(*lead.recorded(head, step, where, asked[n], *decided[n]),
                 by=rulings.LEAD, question=n)
    run.led[lead.key(question)] = "; ".join(
        str(n) + ": " + decided[n][0] for n in wanted)
    return out, lead.told_each(head, question, decided), ""


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


def given_answers(run):
    """-> the digests of the decisions.md entries --answer wrote in this run
    or a leg it carries on from."""
    kept = getattr(run, "kept", None)
    if kept is None:
        return set()
    return set(w.get("sha256") for w in kept.written
               if w.get("by") == "answer")


def answered_here(run):
    """-> the questions this run, or a leg it carries on from, put to the
    person and had answered with --answer, each as its lines."""
    kept = getattr(run, "kept", None)
    if kept is None:
        return []
    given = given_answers(run)
    out = []
    for d in kept.read():
        found = ruling.settled(d) if rulings.digest(d) in given else None
        if found:
            out.append(found[1].split("\n"))
    return out


def answered_marks(answered):
    """-> the (kind, file, line) of every spec line a mark listed in a
    question of `answered` (`answered_here`) cites."""
    out = set()
    for lines in answered:
        for line in lines:
            mark = line.strip().lstrip("-").strip()
            if ruling.BREAKS.match(mark) or ruling.CONTRADICTS.match(mark):
                out |= ruling.mark_lines(mark)
    return out


def marked(run, step, out, answered=()):
    """-> the `spec: breaks` and `spec: contradicts` marks of the lead's own
    answer, as written, but those on lines a ruling the run holds already
    lets change (`ruling.mark_ruled`) and those whose every cited line a
    mark of the same kind in a question of `answered` (`answered_here`)
    already put to the person, however the mark is worded around its cite;
    [] for any other step. each sends the lead's questions to the person."""
    if step != getattr(run, "lead", None):
        return []
    covered = getattr(run, "spec_line_covered", None)
    put = answered_marks(answered)
    found = []
    for m in ruling.broken(out.output):
        cited = ruling.mark_lines(m)
        if cited and cited <= put:
            continue
        if adjacent_fix(run, out, m):
            continue
        if covered is not None and ruling.mark_ruled(
                m, run.workdir, getattr(run, "start", None), covered):
            continue
        found.append(m)
    return found


SIBLING = "SIBLING TEST"


def adjacent_fix(run, out, mark):
    """whether `mark` is a spec line the code already breaks for a sibling
    path, to be fixed test-first rather than asked about: its quote is on
    the code line it names (`ruling.already_at`), the plan carries a `fix:`
    behaviour for that spec line, and no sibling test has shown it is not
    broken there. each such mark is kept on `run.adjacent` until a test
    writer proves it."""
    held = ruling.already_at(mark, run.workdir, getattr(run, "start", None))
    if held is None or not ruling.fix_planned(out.output, held[0]):
        return False
    if mark in (getattr(run, "not_broken", None) or ()):
        return False
    adjacent = getattr(run, "adjacent", None)
    if adjacent is None:
        adjacent = run.adjacent = {}
    adjacent.setdefault(mark, {"spec": held[0], "at": held[1],
                               "test": None})
    return True


def sibling_named(output):
    """-> the test id on the answer's `SIBLING TEST:` line, or ""."""
    from . import verbs

    for _, line in verbs.visible(output):
        head = verbs.key_of(line)
        if head is not None and head[0] == SIBLING and head[1]:
            return head[1].strip("`'\" ")
    return ""


def sibling_proved(run, step, out):
    """-> None when nothing waits on a sibling test, else (the gate result
    that shows each held mark's line already broken, "") or (None, the
    question the run parks on). it is read once a test writer's red-test
    gate passed and a mark waits on its proof: the test on the step's
    `SIBLING TEST:` line runs alone on the code as the run found it, and
    red proves the line is already broken there. green, a test that could
    not run, or no such line makes each mark a plain `spec: breaks` that
    goes to the person."""
    from agentweft.guardrails.gates.base import Result

    from . import wouldpass

    waiting = [(m, h) for m, h in (getattr(run, "adjacent", None)
                                   or {}).items() if not h["test"]]
    if not waiting or not any(
            getattr(g, "gate", None) == "red-test" and g.ok
            for g in out.meta.get("gates") or ()):
        return None
    named = sibling_named(out.output)
    red = wouldpass.alone(run, [named]) if named else None
    if red:
        for _, h in waiting:
            h["test"] = named
        return Result("already-broken", True, "; ".join(
            named + " red on the start commit: " + h["spec"]
            + " already broken at " + h["at"] for _, h in waiting)), ""
    why = (step + " names no " + SIBLING + " line" if not named else named
           + " passes on the code as the run found it" if red is False
           else named + " could not be run alone")
    not_broken = getattr(run, "not_broken", None)
    if not_broken is None:
        not_broken = run.not_broken = set()
    for m, _ in waiting:
        not_broken.add(m)
        run.adjacent.pop(m, None)
    return None, "\n".join(
        ["NEEDS: the plan marks a spec line already broken by the code, and"
         " " + why + ", so it is not shown broken there: the mark is a"
         " line the request breaks", "CITES:"]
        + ["- " + m for m, _ in waiting])


def answer_settles(run, said):
    """-> the `decisions.md:<line>` that `said`, the words of a `SETTLED BY:`
    line, cites when it quotes lines of the answer itself
    (`ruling.answer_part`) of one decisions.md entry that --answer wrote in
    this run or a leg it carries on from (`given_answers`): the person's
    answer is the context that settles a question asked again in other
    words. the lines whole, or QUOTE_WORDS words of them or more. "" for
    anything else: the entry's heading, the question it echoes and its
    closing line too. it checks the lines are the answer, never that the
    answer answers the question."""
    from pathlib import Path

    from agentweft.orchestrate import decisions

    m = ruling.FIRST_QUOTE.match((said or "").strip())
    if not m:
        return ""
    rel, first, last, quote, cite = ruling.cite_of(m)
    if ruling.path_of(rel) != decisions.FILE or not quote:
        return ""
    try:
        text = (Path(run.workdir) / decisions.FILE).read_text(
            encoding="utf-8")
    except OSError:
        return ""
    lines = text.split("\n")
    if not 1 <= first <= last <= len(lines):
        return ""
    heads = [i for i, line in enumerate(lines, 1)
             if decisions.ENTRY.match(line)]
    begins = [h for h in heads if h <= first]
    if not begins:
        return ""
    ends = [h - 1 for h in heads if h > begins[-1]] + [len(lines)]
    part = ruling.answer_part(lines[begins[-1] - 1:ends[0]])
    if part is None or not begins[-1] + part[0] - 1 <= first \
            or last > begins[-1] + part[1] - 1:
        return ""
    found = ruling.flat(" ".join(lines[first - 1:last]))
    if quote not in found or (quote != found and ruling.quote_words(quote)
                              < ruling.QUOTE_WORDS):
        return ""
    entry = decisions.parse("\n".join(lines[begins[-1] - 1:ends[0]]))
    if len(entry) != 1 or rulings.digest(entry[0]) not in given_answers(run):
        return ""
    return decisions.FILE + cite[cite.rindex(":"):]


def handed_back(run):
    """-> (`decisions.md:<line>`, its words) of the first line of the first
    answer --answer wrote in this run, or a leg it carries on from, that
    hands the call back (`ruling.handed_back`); None when there is none."""
    from pathlib import Path

    from agentweft.orchestrate import decisions

    given = given_answers(run)
    if not given:
        return None
    try:
        text = (Path(run.workdir) / decisions.FILE).read_text(
            encoding="utf-8")
    except OSError:
        return None
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines, 1)
             if decisions.ENTRY.match(line)]
    for begin, end in zip(heads, [h - 1 for h in heads[1:]] + [len(lines)]):
        entry = decisions.parse("\n".join(lines[begin - 1:end]))
        if len(entry) != 1 or rulings.digest(entry[0]) not in given \
                or not ruling.handed_back(ruling.answered(entry[0])):
            continue
        part = ruling.answer_part(lines[begin - 1:end])
        if part is None:
            continue
        n = begin + part[0] - 1
        return decisions.FILE + ":" + str(n), ruling.flat(lines[n - 1])
    return None


def lead_settled(run, rec, settled, marks):
    """-> (the line that settles a QUESTION of the lead's own, so the lead
    decides it by its RECOMMEND `rec`, the words it is settled by), or ("",
    ""): there is a RECOMMEND, the plan marks no spec line (`marks`), and
    the question's `SETTLED BY:` words `settled` quote a line of the place
    as the run found it (`ruling.settles`), the person's answer in this run
    (`answer_settles`) or the request the run was handed
    (`ruling.request_settles`); else the person handed the call back in
    this run (`handed_back`), and that answer settles it."""
    if not rec or marks:
        return "", ""
    line = ruling.settles(settled, run.workdir, getattr(run, "start", None)) \
        or answer_settles(run, settled) \
        or ruling.request_settles(settled, getattr(run, "task_text", None))
    if line:
        return line, ruling.settling_quote(settled)
    return handed_back(run) or ("", "")


def lead_s_own(run, rec, settled, marks):
    """-> the line that settles a QUESTION of the lead's own
    (`lead_settled`), or ""."""
    return lead_settled(run, rec, settled, marks)[0]


def lead_questions(run, step, out, answered=()):
    """-> [(the question as a NEEDS line, the RECOMMEND or "", the place
    lines it cites, its SIZE or "", its SETTLED BY words or "")] for each
    QUESTION the lead's own handoff asks, but one a question in `answered`
    (`answered_here`) already put to the person; [] for any other step."""
    if step != getattr(run, "lead", None) or \
            out.block.get("state") not in (PRESENT, PARTIAL):
        return []
    asked = set(lead.key(lines[0]) for lines in answered)
    found = []
    for q in out.block.get("questions") or []:
        text = ruling.flat(q.get("question") or "")
        if not text or ruling.says_none(text) \
                or lead.key("NEEDS: " + text) in asked:
            continue
        found.append(("NEEDS: " + text, ruling.flat(q.get("recommend") or ""),
                      ruling.place_cites(text, run.workdir),
                      ruling.flat(q.get("size") or ""),
                      ruling.flat(q.get("settled") or "")))
    return found


UNASKED = "NEEDS: the plan marks a line of the spec broken and asks nothing" \
    " about it"


def lead_escalates(run, step, out):
    """-> what of the lead's own answer goes to the person, as a NEEDS
    question, or "": its first QUESTION that no line of the place settles
    (`lead_s_own`), with the marks of a plan that marks a spec line listed
    first under its CITES; with no such question, a `spec: breaks` mark
    alone. a question or mark already put to the person in this run and
    answered is not asked again. the lead's own question has no one above
    it to decide it."""
    answered = answered_here(run)
    marks = marked(run, step, out, answered)
    for asked, rec, cites, size, settled in lead_questions(run, step, out,
                                                           answered):
        if lead_s_own(run, rec, settled, marks):
            continue
        said = [asked]
        if marks or cites:
            said += ["CITES:"] + ["- " + c for c in marks + cites]
        if rec:
            said.append("RECOMMEND: " + rec)
        if size:
            said.append("SIZE: " + size)
        return "\n".join(said)
    breaks = [m for m in marks if ruling.BREAKS.match(m)]
    if breaks:
        return "\n".join([UNASKED, "CITES:"] + ["- " + m for m in breaks])
    return ""


def lead_decides(run, step, out, where):
    """each QUESTION of the lead's own handoff that a line of the place
    settles (`lead_s_own`) is the lead's to decide, and its RECOMMEND is the
    decision: put on record as the lead's, so every later step gets it and
    the handoff lists it first, for the person to overrule. -> how many it
    put on record."""
    answered = answered_here(run)
    marks = marked(run, step, out, answered)
    count = 0
    for asked, rec, _, _, settled in lead_questions(run, step, out,
                                                    answered):
        line, quote = lead_settled(run, rec, settled, marks)
        if not line or lead.key(asked) in run.led:
            continue
        count += 1
        run.led[lead.key(asked)] = rec
        run.rule(*lead.recorded(step, step, where, asked, rec,
                                "the recommendation of " + step
                                + "'s own handoff, which " + line + ' "'
                                + quote + '"' + lead.SETTLES + step
                                + lead.SETTLES_END),
                 by=rulings.LEAD)
        # the handoff was made before the ruling was on record, and the
        # next step reads the rulings off it
        out.meta["rulings"] = run.rulings()
        print(step + ", the flow's lead, decided its own question: " + rec)
    return count


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
