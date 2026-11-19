"""a step that asks instead of going on: an ASSUMED item of the run answers
it, the lead decides, or the run parks."""
import ast
import hashlib
import json
import re
from pathlib import Path

from agentweft.guardrails import rulings

from . import lead, ruling, trace
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


IF_WRONG = re.compile(r"\bif\s+wrong\s*:", re.I)
ASKED_LINE = re.compile(r"^NEEDS: (?:\d+\. )?")
WORD = re.compile(r"[a-z0-9_]+")
CARRIED = 3


def cites_in(text, workdir, start=None):
    """-> [(file, first line, last line)] of each `<file>:<line>` or
    `<file>:<a>-<b>` in `text` whose lines were all in that file when the
    run started; a line past the end, a file that was not there and a file
    of the runner's own cite nothing."""
    from agentweft.guardrails.snapshot import is_runners

    out = []
    for m in ruling.MARKED.finditer(text or ""):
        rel = ruling.path_of(m.group(1))
        first = int(m.group(2))
        last = int(m.group(3) or first)
        if is_runners(rel) or (rel, first, last) in out:
            continue
        lines, _ = ruling.lines_of(workdir, rel, first, last, start)
        if lines is not None:
            out.append((rel, first, last))
    return out


def spec_cites(text, workdir, start):
    """-> the cites of `cites_in` that fall in a spec file of the run, as
    the start snapshot typed its files; none without a snapshot."""
    specs = getattr(start, "specs", None) or {}
    if not specs:
        return []
    out = []
    for rel, first, last in cites_in(text, workdir, start):
        try:
            key = (Path(start.place) / rel).resolve().relative_to(
                Path(start.root).resolve()).as_posix()
        except (TypeError, ValueError, OSError):
            continue
        if key in specs:
            out.append((rel, first, last))
    return out


def split_item(item):
    """-> (what an ASSUMED item rests on, its `if wrong:` words): what it
    cites is read off its choice and its why, never off what would follow
    if it were wrong."""
    m = IF_WRONG.search(item or "")
    if not m:
        return item or "", ""
    return item[:m.start()], item[m.end():]


def assumed_items(run, step):
    """-> [(the lead, its number, the item's lines, the single spec lines it
    rests on, its `if wrong:` words)] of each ASSUMED item the flow's lead
    handed over that rests on a single line of a spec file; [] in a flow
    with no lead and for the lead's own question. another step's item is a
    choice nobody with the lead's role took."""
    head = getattr(run, "lead", None)
    text = (getattr(run, "produced", None) or {}).get(head) \
        if head is not None and head != step else None
    if not text:
        return []
    block = parse_handoff(text)
    if block.get("state") not in (PRESENT, PARTIAL):
        return []
    out = []
    workdir = getattr(run, "workdir", ".")
    start = getattr(run, "start", None)
    for n, item in enumerate(block.get("assumed") or [], 1):
        rests, wrong = split_item(item)
        found = [c for c in spec_cites(rests, workdir, start) if c[1] == c[2]]
        if found:
            out.append((head, n, item, found, wrong))
    return out


def word_runs(text):
    """-> each run of CARRIED consecutive words of `text`, lower case."""
    said = WORD.findall((text or "").lower())
    return set(tuple(said[i:i + CARRIED])
               for i in range(len(said) - CARRIED + 1))


def disputes(question, wrong):
    """whether a question carries CARRIED consecutive words of an item's
    `if wrong:`: it asks about what follows if the item is wrong, so the
    item cannot be its answer. words only ever send a question on to the
    lead here, never answer one."""
    return bool(word_runs(question) & word_runs(wrong))


def assumed_answer(run, step, question, where):
    """-> None when no question of `question` is answered by an ASSUMED
    item, else (what `step` is told on its next go, the rest of the ask or
    "" when nothing is left for the lead). a question is answered by the
    first ASSUMED item of the lead's own (`assumed_items`) that cites every
    spec-file cite of the question, each a single line the file had when
    the run started: the match is the cite, never the words, and a range
    on either side matches nothing. that answer is put on record in the
    lead's form and nobody is called; it re-delivers the lead's own choice
    and never checks the choice answers the question. a question on a cite
    an item already answered for this step once in the run, and one that
    carries the item's `if wrong:` words, go to the lead."""
    told_once = getattr(run, "assumed_led", None)
    if told_once is None:
        told_once = run.assumed_led = set()
    items = assumed_items(run, step)
    workdir = getattr(run, "workdir", ".")
    start = getattr(run, "start", None)
    numbered = lead.parts(question) if lead.numbers(question) else None
    asks = sorted(numbered.items()) if numbered else [(None, question)]
    told, left = [], []
    for n, text in asks:
        cites = set(spec_cites(text, workdir, start))
        hits = [i for i in items if cites and cites <= set(i[3])]
        hit = hits[0] if hits else None
        if hit is not None and (
                any((step, i[0], i[1]) in told_once for i in hits)
                or disputes(text, hit[4])):
            hit = None
        if hit is None:
            left.append(text)
            continue
        owner, at, item = hit[0], hit[1], hit[2]
        key = " ".join(ASKED_LINE.sub("", text.split("\n")[0]).split())
        told_once.add((step, owner, at))
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
            if ruling.BREAKS.match(mark) or ruling.CONTRADICTS.match(mark) \
                    or unread_spec(mark):
                out |= ruling.mark_lines(mark)
    return out


SPEC_KEY = re.compile(r"^[\s>*_`+\-]*spec(?=[\s*_`:])[\s*_`]*(:?)[\s*_`]*(.*?)"
                      r"\s*$", re.I)
SPEC_VERB = re.compile(r"^(?:allows|adds\s+to|nothing|contradicts?|breaks?|"
                       r"broken|violates?|conflicts?)\b", re.I)
# the forms planner.md teaches that mark nothing; the two that mark are read
# by ruling.BREAKS and ruling.CONTRADICTS
QUIET = re.compile(r"^(?:allows\s+\S|adds\s+to\s+\S|nothing\s+in\s+the\s+spec"
                   r"\b)", re.I)


def unread_spec(line):
    """whether `line` opens as a behaviour's `spec` line and reads as none of
    the five forms the plan is taught: no colon, bold, a verb off the list
    or out of its form. such a line parks like a mark, never passes."""
    m = SPEC_KEY.match(line or "")
    if not m or ruling.BREAKS.match(line) or ruling.CONTRADICTS.match(line):
        return False
    if not m.group(1):
        said = m.group(2)
        return bool(SPEC_VERB.match(said) or ruling.MARKED.search(said))
    plain = re.match(r"^\s*(?:-\s*)?spec:\s*(.*)$", line.strip(), re.I)
    return not (plain and QUIET.match(plain.group(1)))


def unread_specs(output):
    """-> the lines of `output` that `unread_spec` finds, as written."""
    from . import verbs
    return [line.strip().lstrip("-").strip() for _, line in
            verbs.visible(output) if unread_spec(line)]


def marked(run, step, out, answered=()):
    """-> the `spec: breaks` and `spec: contradicts` marks of the lead's own
    answer, as written, but those on lines an answer of the run already
    ruled on: a ruling that lets them change (`ruling.mark_ruled`), a
    `request:` answer that holds them (`spec_line_held`), an `override:`
    whose rename each restates (`spec_line_restated`), or a mark of the
    same kind in a question of `answered` (`answered_here`) that already
    put every cited line to the person, however the mark is worded around
    its cite. a spec line the code already breaks for a sibling path
    (`adjacent_fix`) is fixed rather than asked, and a plain `breaks` of
    that same line on the same page is the same breach on the new path,
    fixed with it. [] for any other step. each sends the lead's questions
    to the person."""
    if step != getattr(run, "lead", None):
        return []
    start = getattr(run, "start", None)
    ruled = [r for r in (getattr(run, "spec_line_covered", None),
                         getattr(run, "spec_line_held", None),
                         getattr(run, "spec_line_restated", None))
             if r is not None]
    put = answered_marks(answered)
    every = ruling.broken(out.output)
    fixing = set()
    for m in every:
        if adjacent_fix(run, out, m):
            fixing.add(ruling.already_at(m, run.workdir, start)[0])
    found = []
    for m in every:
        cited = ruling.mark_lines(m)
        if cited and cited <= put:
            continue
        if adjacent_fix(run, out, m):
            continue
        if cited and ruling.BREAKS.match(m) and not ruling.ALREADY.match(m) \
                and set(f + ":" + str(n) for _, f, n in cited) <= fixing:
            continue
        if any(ruling.mark_ruled(m, run.workdir, start, r) for r in ruled):
            continue
        found.append(m)
    for m in unread_specs(out.output):
        cited = ruling.mark_lines(m)
        if not (cited and cited <= put):
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


def not_shown(run, marks, why):
    """take each of `marks` off `run.adjacent` as a mark not shown broken
    there, so it is a plain `spec: breaks` from now on. -> the question the
    run parks on, `why` under its NEEDS line and the marks under CITES."""
    not_broken = getattr(run, "not_broken", None)
    if not_broken is None:
        not_broken = run.not_broken = set()
    for m in marks:
        not_broken.add(m)
        run.adjacent.pop(m, None)
    return "\n".join(
        ["NEEDS: the plan marks a spec line already broken by the code, and "
         + why + ": the mark is a line the request breaks", "CITES:"]
        + ["- " + m for m in marks])


def sibling_proved(run, step, out):
    """-> None when nothing waits on a sibling test, else (the gate result
    `sibling-red`, "") or (None, the question the run parks on). it is read
    once a test writer's red-test gate passed and a mark waits on its proof:
    the test on the step's `SIBLING TEST:` line must be red on the start
    commit for its outcome (`sibling_red`). no such line, or a test that is
    not, makes each mark a plain `spec: breaks` that goes to the person."""
    from agentweft.guardrails.gates.base import Result

    waiting = [(m, h) for m, h in (getattr(run, "adjacent", None)
                                   or {}).items() if not h["test"]]
    if not waiting or not any(
            getattr(g, "gate", None) == "red-test" and g.ok
            for g in out.meta.get("gates") or ()):
        return None
    named = sibling_named(out.output)
    how, why = sibling_red(run, named, [h["at"] for _, h in waiting]) \
        if named else (None, step + " names no " + SIBLING + " line")
    if how:
        for _, h in waiting:
            h["test"] = named
            h["how"] = how
        return Result(SIBLING_RED, True, "; ".join(
            named + " red on the start commit (" + how + "): " + h["spec"]
            + " already broken at " + h["at"] for _, h in waiting)), ""
    return None, not_shown(run, [m for m, _ in waiting],
                           why + ", so it is not shown broken there")


SIBLING_RED = "sibling-red"
ALREADY = "already-broken"
RUNNER = trace.RUNNER


def sibling_red(run, test, ats):
    """-> (how `test` failed, "") when it is a test this run added and it
    fails in a checkout of the start commit holding the run's test changes,
    on an assertion or on an exception raised in a product file the run
    started with, and that run executed each code line of `ats` (`<file>:
    <line>` of the place): it fails there on its outcome, on the code the
    marks name, not on reaching code that is not there yet. else (None, why
    not): a missing name, an error raised in the test file, a collection
    error, a pass, no start commit, a marked line it never reached or that
    no probe could see (a file that is not python, a python that skipped
    the probe)."""
    from agentweft.guardrails import reached, redorder, worktree
    from agentweft.guardrails.gates import redfirst_gate as rf
    from agentweft.guardrails.snapshot import is_test, is_tooling

    start = getattr(run, "start", None)
    if start is None or not getattr(start, "start", None):
        return None, "the run has no start commit to run " + test + " on"
    if test.split("[")[0] not in (start.new_test_ids() or ()):
        return None, test + " is not a test this run added"
    if not ats:
        return None, "no code line is named for " + test + " to reach"
    fm = getattr(run, "fm", None)
    cmd = redorder.test_command(fm) if fm is not None else None
    if ".py::" not in test or not cmd:
        return None, test + " could not be run alone"
    try:
        with worktree.temporary(start.root, start.start) as tree:
            start.lay_out(tree, start.test_changes())
            where = start.place_in(tree)
            targets, blind = watched(where, ats)
            with reached.probe([t for _, t in targets]) as (first, seen):
                r, why = rf.RedFirstGate(command=cmd).ran(cmd, test, where,
                                                          first=first)
                hits = seen()
            output = r.stdout + "\n" + r.stderr if r is not None else ""
            at = rf.raised_at(output, where) if r is not None else None
    except ValueError:
        return None, test + " could not be run on the start commit"
    if r is None:
        return None, test + " could not be run on the start commit: " + why
    if r.returncode == 0:
        return None, test + " passes on the code as the run found it"
    if r.returncode != 1 or not redorder.failed_only(output):
        return None, (test + " does not run to an outcome on the start"
                      " commit (exit " + str(r.returncode) + ")")
    kind = rf.kind_of(output)
    product = at is not None and at[0] in start.product \
        and not is_test(at[0]) and not is_tooling(at[0])
    if kind in rf.MISSES and not product:
        return None, (test + " is red on the start commit on a missing name"
                      " (" + kind + "), so it is a test of the new path")
    if kind != "assertion" and (not kind or not product):
        return None, (test + " is red on the start commit by "
                      + (kind or "an error pytest does not name")
                      + (" raised in " + at[0] if at else "")
                      + ", not in the code as the run found it")
    if blind:
        return None, (test + " cannot be shown to reach " + blind[0][0]
                      + " on the start commit: " + blind[0][1])
    if hits is None:
        return None, (test + " ran where no line probe loaded, so nothing"
                      " shows it reaches " + ", ".join(a for a, _ in targets))
    missed = [a for i, (a, _) in enumerate(targets) if i not in hits]
    if missed:
        return None, (test + " never reaches " + ", ".join(missed)
                      + " on the start commit, so it is not a test of the"
                      " code the mark names")
    if kind == "assertion":
        return "assertion", ""
    return (kind + " raised at " + start.from_place(at[0]) + ":"
            + str(at[1])), ""


def watched(where, ats):
    """-> ([(the `<file>:<line>`, (its path under `where`, the lines of the
    statement holding it))] a probe can watch, [(the `<file>:<line>`, why
    not)] for the rest): a file that is not python, not there or not
    parsing."""
    from agentweft.guardrails import reached

    targets, blind = [], []
    for a in ats:
        rel, _, n = a.rpartition(":")
        path = Path(where) / rel
        if not rel.endswith(".py") or not n.isdigit():
            blind.append((a, "not python"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
            lines = reached.lines_of(text, int(n))
        except (OSError, SyntaxError, ValueError):
            blind.append((a, "the file does not read or parse there"))
            continue
        targets.append((a, (str(path), lines)))
    return targets, blind


FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFS = FUNCS + (ast.ClassDef,)


def function_at(text, n):
    """-> (the names from the module down to the innermost function of
    python `text` that holds line `n`, its first line with its decorators,
    its last line, its indent), None when no function holds it. raises
    SyntaxError or ValueError when `text` does not parse."""
    found = []

    def walk(node, names):
        for child in ast.iter_child_nodes(node):
            last = getattr(child, "end_lineno", None)
            if not hasattr(child, "lineno") or last is None:
                continue
            first = min([child.lineno] + [
                d.lineno for d in getattr(child, "decorator_list", ())])
            if not first <= n <= last:
                continue
            here = names + (child.name,) if isinstance(child, DEFS) else names
            if isinstance(child, FUNCS):
                found[:] = [(here, first, last, child.col_offset)]
            walk(child, here)

    walk(ast.parse(text), ())
    return found[0] if found else None


def function_named(text, names):
    """-> (first line with decorators, last line, indent) of the function
    `names` names in python `text`, None when it has none by that name.
    raises SyntaxError or ValueError when `text` does not parse."""
    def walk(node, left):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEFS):
                if child.name != left[0]:
                    continue
                if len(left) == 1:
                    if not isinstance(child, FUNCS):
                        continue
                    return (min([child.lineno] + [
                        d.lineno for d in child.decorator_list]),
                        child.end_lineno, child.col_offset)
                found = walk(child, left[1:])
            else:
                found = walk(child, left)
            if found:
                return found
        return None

    return walk(ast.parse(text), names)


def put_back(now, was, names, at):
    """-> `now` with the function `names` names written back as `was` holds
    it (`at` from `function_at`), everything else as it is, or None when
    `now` has no function by that name."""
    found = function_named(now, names)
    if found is None:
        return None
    lines, old = now.split("\n"), was.split("\n")[at[1] - 1:at[2]]
    shift = found[2] - at[3]
    moved = [(" " * shift + l if shift > 0 else l[min(-shift, len(l) - len(
        l.lstrip(" "))):]) if l.strip() else l for l in old]
    return "\n".join(lines[:found[0] - 1] + moved + lines[found[1]:])


def assert_lines(workdir, test):
    """-> the source of each `assert` statement of the test function `test`
    names, one flat line each, [] when it cannot be read."""
    rel, _, name = test.partition("::")
    try:
        text = (Path(workdir) / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return []
    found = function_named(text, tuple(name.split("[")[0].split("::")))
    if found is None:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) \
                and found[0] <= node.lineno <= found[1]:
            out.append(ruling.flat(ast.get_source_segment(text, node) or ""))
    return [a for a in out if a]


KEPT = Path("kept")
RECORD = "kept.json"
REPLACED = chr(0xFFFD)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def keep(folder, rel, data, wrote):
    """copy `data`, the place's `rel` before a sibling check writes `wrote`
    over it, under the run folder `folder`, outside the tmp folder the steps
    may write, with the runner's record of the file and of both hashes."""
    copy = Path(folder) / KEPT / rel
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(data)
    (Path(folder) / RECORD).write_text(json.dumps(
        {"rel": rel, "kept": digest(data), "wrote": digest(wrote)}),
        encoding="utf-8")


def unkept(folder, rel):
    for path in (Path(folder) / RECORD, Path(folder) / KEPT / rel):
        try:
            path.unlink()
        except OSError:
            pass


def restore_kept(folder, workdir):
    """put back the product file a sibling check rewrote and was stopped in
    before it put it back itself, from the copy it kept under `folder`: only
    the file the runner's record names, inside the place, from a copy that
    is the one kept, over bytes that are the ones the check wrote. anything
    else is left as it is and said. -> the paths from the place it put
    back."""
    try:
        said = json.loads((Path(folder) / RECORD).read_text(encoding="utf-8"))
        rel = said["rel"]
        root = Path(workdir).resolve()
        target = (root / rel).resolve()
        target.relative_to(root)
    except (OSError, ValueError, KeyError, TypeError):
        return []
    copy = Path(folder) / KEPT / rel
    try:
        data, now = copy.read_bytes(), target.read_bytes()
    except OSError:
        return left(rel, copy, "the copy or the file is not there")
    if digest(data) != said.get("kept"):
        return left(rel, copy, "the copy is not the one the check kept")
    if digest(now) == digest(data):
        unkept(folder, rel)
        return []
    if digest(now) != said.get("wrote"):
        return left(rel, copy, "it changed after the check rewrote it")
    target.write_bytes(data)
    unkept(folder, rel)
    return [rel]


def left(rel, copy, why):
    print(rel + " is left as it is: " + why + "; the bytes it had before a"
          " sibling check rewrote it are kept at " + str(copy))
    return []


def sibling_fixed(run, h):
    """-> (the `already-broken` line for the mark held in `h`, "") when the
    run's change shows it fixed, else (None, why not). red on the start
    commit for its outcome shows the test exercises code that was there;
    the test must also pass on the code as the run leaves it, and fail
    again with the function holding the marked code line put back as the
    run found it, everything else as the run left it."""
    from . import wouldpass

    rel, _, n = h["at"].rpartition(":")
    test = h["test"]
    was = ruling.as_found(run.workdir, rel, getattr(run, "start", None))
    now = ruling.now_of(run.workdir, rel)
    if was is None or now is None or REPLACED in was + now:
        return None, "cannot read the function at " + h["at"]
    try:
        at = function_at(was, int(n))
    except (SyntaxError, ValueError):
        return None, "cannot read the function at " + h["at"]
    if at is None:
        return None, h["at"] + " is in no function, so nothing ties it to" \
            " the change"
    name = ".".join(at[0])
    if wouldpass.alone(run, [test]) is not False:
        return None, test + " does not pass on the code as the run leaves it"
    try:
        mutated = put_back(now, was, at[0], at)
    except (SyntaxError, ValueError):
        return None, rel + " does not parse as the run leaves it"
    if mutated is None:
        return None, ("`" + name + "` is not a function in " + rel
                      + " as the run leaves it")
    try:
        ast.parse(mutated)
    except (SyntaxError, ValueError):
        return None, "`" + name + "` cannot be put back in " + rel
    target = Path(run.workdir) / rel
    data, wrote = target.read_bytes(), mutated.encode("utf-8")
    folder = getattr(run, "folder", None)
    if folder:
        keep(folder, rel, data, wrote)
    try:
        target.write_bytes(wrote)
        red = wouldpass.alone(run, [test])
    finally:
        target.write_bytes(data)
        if folder:
            unkept(folder, rel)
    if red is not True:
        return None, (test + (" still passes" if red is False
                              else " could not be run") + " with `" + name
                      + "` put back as found, so the change there is not"
                      " the fix")
    return (test + " red on the start commit (" + h.get("how", "")
            + "), green now, red again with `" + name + "` put back as"
            " found: " + h["spec"] + " already broken at " + h["at"]
            + "".join("\n    " + a for a in assert_lines(run.workdir,
                                                         test))), ""


def sibling_unfixed(run):
    """-> (the `already-broken` result of every mark a sibling test proved
    red and the change shows fixed (`sibling_fixed`) or None, the question
    the run parks on or ""): any mark not shown fixed is a plain `spec:
    breaks` for the person, and then nothing passes."""
    from agentweft.guardrails.gates.base import Result

    fixed, left = [], []
    for m, h in list((getattr(run, "adjacent", None) or {}).items()):
        if h.get("test"):
            said, why = sibling_fixed(run, h)
            if said:
                fixed.append(said)
            else:
                left.append((m, why))
    if left:
        return None, not_shown(run, [m for m, _ in left],
                               "the change does not show it fixed ("
                               + "; ".join(w for _, w in left) + ")")
    if not fixed:
        return None, ""
    return Result(ALREADY, True, "\n".join(fixed)), ""


def answer_settles(run, said):
    """-> the `decisions.md:<line>` that `said`, the words of a `SETTLED BY:`
    line, cites when it quotes lines of the answer itself
    (`ruling.answer_part`) of one decisions.md entry that --answer wrote in
    this run or a leg it carries on from (`given_answers`): the person's
    answer is the context that settles a question asked again in other
    words. the lines whole, or QUOTE_WORDS words of them or more. "" for
    anything else: the entry's heading, the question it echoes and its
    closing line too. the entry may be named by its line numbers or by its
    stamp (`by_stamp`). it checks the lines are the answer, never that the
    answer answers the question."""
    return answer_settled(run, said)[0]


def answer_settled(run, said):
    """-> (the cite `answer_settles` reads, the quote it read there), or
    ("", "")."""
    from pathlib import Path

    from agentweft.orchestrate import decisions

    try:
        text = (Path(run.workdir) / decisions.FILE).read_text(
            encoding="utf-8")
    except OSError:
        return "", ""
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines, 1)
             if decisions.ENTRY.match(line)]
    for first, last, quote in decisions_cites(said, lines, heads):
        if not quote or not 1 <= first <= last <= len(lines):
            continue
        begins = [h for h in heads if h <= first]
        if not begins:
            continue
        ends = [h - 1 for h in heads if h > begins[-1]] + [len(lines)]
        part = ruling.answer_part(lines[begins[-1] - 1:ends[0]])
        if part is None or not begins[-1] + part[0] - 1 <= first \
                or last > begins[-1] + part[1] - 1:
            continue
        found = ruling.flat(" ".join(lines[first - 1:last]))
        if quote not in found or (quote != found and ruling.quote_words(
                quote) < ruling.QUOTE_WORDS):
            continue
        entry = decisions.parse("\n".join(lines[begins[-1] - 1:ends[0]]))
        if len(entry) != 1 or rulings.digest(entry[0]) \
                not in given_answers(run):
            continue
        return decisions.FILE + ":" + str(first) + (
            "-" + str(last) if last != first else ""), quote
    return "", ""


STAMPED = re.compile(r"""^[`'"]?decisions\.md[`'"]?(?::\s*|\s+)"""
                     r"""(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})[`'"]?\s+(?=")""")


def decisions_cites(said, lines, heads):
    """-> (first line, last line, quote) for each way `said`, the words of
    a `SETTLED BY:` line, can name lines of decisions.md, `lines` the file
    and `heads` the line numbers of its entries' headings: by line numbers,
    or by an entry's stamp (`by_stamp`)."""
    from agentweft.orchestrate import decisions

    out = [(first, last, quote) for rel, first, last, quote, _
           in ruling.readings(said) if ruling.path_of(rel) == decisions.FILE]
    return out + by_stamp(said, lines, heads)


def by_stamp(said, lines, heads):
    """-> (first line, last line, quote) for a `decisions.md:<date> <time>
    "<quote>"` cite (the colon may be left out): the lines of the one entry
    under that stamp the quote is on, its answer's lines first. [] for a
    stamp no entry has, a stamp two entries share with the quote on both,
    and a quote on no line of the entry."""
    from agentweft.orchestrate import decisions

    said = (said or "").strip()
    m = STAMPED.match(said)
    if not m:
        return []
    stamp = m.group(1) + " " + m.group(2)
    body = said[m.end() + 1:].split("\n")[0]
    quotes = [ruling.flat(body[:i]) for i, ch in enumerate(body) if ch == '"']
    found = []
    for begin, end in zip(heads, [h - 1 for h in heads[1:]] + [len(lines)]):
        if decisions.ENTRY.match(lines[begin - 1]).group(1) != stamp:
            continue
        part = ruling.answer_part(lines[begin - 1:end])
        spans = ([(begin + part[0] - 1, begin + part[1] - 1)] if part
                 else []) + [(begin, end)]
        for quote in quotes:
            at = next((s for s in (span_of(lines, a, b, quote)
                                   for a, b in spans) if s), None)
            if at:
                found.append(at + (quote,))
                break
    return found if len(found) == 1 else []


def span_of(lines, first, last, quote):
    """-> the fewest lines from `first` to `last`, (a, b), that hold `quote`
    whole, or None."""
    for size in range(1, last - first + 2):
        for a in range(first, last - size + 2):
            if quote in ruling.flat(" ".join(lines[a - 1:a - 1 + size])):
                return a, a + size - 1
    return None


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


def settled_reason(run, settled):
    """-> (the line a QUESTION's `SETTLED BY:` words `settled` cite, the
    words it is settled by), or ("", ""): a line of the place as the run
    found it (`ruling.settled_by`), the person's answer in this run
    (`answer_settles`), the request the run was handed
    (`ruling.request_settles`), or else the person's answer that handed the
    call back in this run (`handed_back`). it is the reason recorded beside
    the lead's decision and decides nothing: a reason that cannot be read
    leaves the decision standing, said so on its record."""
    start = getattr(run, "start", None)
    line, quote = ruling.settled_by(settled, run.workdir, start)
    if line:
        return line, quote
    line, quote = answer_settled(run, settled)
    if line:
        return line, quote
    line = ruling.request_settles(settled, getattr(run, "task_text", None))
    if line:
        return line, ruling.settling_quote(settled)
    return handed_back(run) or ("", "")


def lead_questions(run, step, out, answered=()):
    """-> [(the question as a NEEDS line, the RECOMMEND or "", the place
    lines it cites, its SIZE or "", its SETTLED BY words or "", its SPLIT
    line or "")] for each QUESTION the lead's own handoff asks, but one a
    question in `answered` (`answered_here`) already put to the person; []
    for any other step."""
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
                      ruling.flat(q.get("settled") or ""),
                      ruling.flat(q.get("split") or "")))
    return found


UNASKED = "NEEDS: the plan marks a line of the spec broken and asks nothing" \
    " about it"
UNREAD = "NEEDS: the plan holds a line the runner cannot read in any form it" \
    " was taught"
UNREAD_SAID = " (not read: not in the form taught for it)"
ASK_KEY = re.compile(r"^\s*(?:[-*+]\s*)?[*_`]*\s*(QUESTION|SETTLED\s+BY|SPLIT|"
                     r"RECOMMEND|SIZE)\b[*_`]*\s*(?:[:=]|-\s|$)", re.I)
ASK_BARE = re.compile(r"^\s*(?:[-*+]\s*)?[*_`]*\s*(QUESTION|SETTLED BY|SPLIT|"
                      r"RECOMMEND|SIZE)[*_`]*\s+\S")


def unread_asking(output):
    """-> each line of the answer's HANDOFF block that opens with a key a
    QUESTION carries (QUESTION, SETTLED BY, SPLIT, RECOMMEND, SIZE), written
    with a capital, that the block's reader does not take as that key: a
    bulleted one, one with `-` or `=` or nothing for its colon. the reader
    drops such a line, so a risk it would have typed is lost; it parks
    instead."""
    from . import verbs
    from .handoff import ASKING, bounds

    shown = verbs.visible(output)
    span, _ = bounds(shown)
    if span is None:
        return []
    out = []
    for _, line in shown[span[0] + 1:span[1]]:
        m = ASK_KEY.match(line) or ASK_BARE.match(line)
        if not m or not m.group(1)[0].isupper():
            continue
        head = verbs.key_of(line)
        if head is not None and head[0] in ASKING and not head[2]:
            continue
        out.append(line.strip())
    return out
WHO = r"(?:the\s+)?(?:person|operator|user|owner|maintainer|you|they)"
PERSON_HOLDS = re.compile(
    r"^\W*" + WHO + r"\s+(?:(?:must|should|will|can|could|needs?\s+to|has\s+to"
    r"|have\s+to|to)\s+)?(?:names?|decides?|chooses?|picks?|gives?|says?|"
    r"sets?|confirms?|answers?|rules?|tells?)\b", re.I)
HANDED_ON = re.compile(r"\bask\s+" + WHO + r"\b|\b" + WHO + r"'s\s+(?:call|"
                       r"choice|decision)\b|\bup\s+to\s+" + WHO + r"\b", re.I)
NO_CHOICE = re.compile(r"^(?:none|n/a|na|tbd|tbc|unknown|unsure|unclear|"
                       r"undecided|no\s+recommendation|not\s+sure|nothing\s+to"
                       r"\s+recommend|-+|\?+)(?:$|[^a-z0-9/])")


def no_recommendation(rec):
    """whether a RECOMMEND holds no choice the program can record as the
    lead's decision. its words, markdown, brackets and quotes taken off,
    record no choice when they are empty, are `nothing`, open with a
    placeholder for one (`none`, `tbd`, `unknown`, `-`, ...), are a
    question, or hand the answer to someone else in any sentence ("the
    person names a date", "ask the user", "the owner's call"). these only
    ever send a question on to the person, never decide one."""
    said = re.sub(r"[*_`~\"()\[\]<>{}]|(?<!\w)'|'(?!\w)", " ", rec or "")
    said = " ".join(said.split()).strip(" .,;:!").lower()
    if not said or said == "nothing" or NO_CHOICE.match(said) \
            or said.endswith("?") or HANDED_ON.search(said):
        return True
    return any(PERSON_HOLDS.match(s) for s in re.split(r"[.;:!?\n]", said))


def start_tests(run, texts):
    """-> the test files the run started with that `texts` name, each as a
    path from the place, and the test ids of the lines they cite there:
    the start snapshot types a file as a test (`snapshot.is_test` on the
    place as it is when the run has none), never a word. a name matches a
    start test however it is spelt: a bare file name, `./`, either
    separator, an absolute path, any case. with no hashed snapshot to read,
    any name the snapshot's path rule would take for a test, in any case,
    is taken as one."""
    from agentweft.guardrails.snapshot import is_runners

    start = getattr(run, "start", None)
    known = start_paths(start) if getattr(start, "hashed", False) else None
    files, ids = [], []
    for text in texts:
        names = [(m.group(1), int(m.group(2)))
                 for m in ruling.MARKED.finditer(text or "")]
        names += [(n, None) for n in ruling.NAME.findall(text or "")]
        for name, line in names:
            rel = re.sub(r":\d+(?:-\d+)?$", "",
                         ruling.path_of(name.split("::")[0]))
            if not rel or is_runners(rel):
                continue
            found = test_named(rel, known)
            for path in found:
                if path not in files:
                    files.append(path)
                if line is None:
                    continue
                source = ruling.as_found(run.workdir, path, start)
                at = test_at(source, path, line) if source else None
                if at and at not in ids:
                    ids.append(at)
    return files, ids


def start_paths(start):
    """-> the start snapshot's test files as paths from the place."""
    out = []
    try:
        place = Path(start.place).resolve()
        root = Path(start.root).resolve()
    except (TypeError, OSError):
        return out
    for key in start.tests:
        try:
            out.append((root / key).relative_to(place).as_posix())
        except ValueError:
            out.append(key)
    return out


def test_named(rel, known):
    """-> the start tests of `known` the name `rel` spells, by its last
    parts and in any case; with `known` None, [rel] when the path rule takes
    it for a test file in any case, else []."""
    from agentweft.guardrails.snapshot import is_test

    said = re.sub(r"^[A-Za-z]:", "", rel.replace("\\", "/"))
    parts = [p for p in said.casefold().split("/") if p not in ("", ".")]
    if not parts:
        return []
    if known is None:
        whole = "/".join(parts)
        return [rel] if is_test(said) or is_test(whole) else []
    out = []
    for path in known:
        have = [p for p in path.casefold().split("/") if p]
        n = min(len(have), len(parts))
        if n and have[-n:] == parts[-n:]:
            out.append(path)
    return out


def test_at(source, rel, n):
    """-> the id of the pytest test whose code holds line `n` of `source`,
    or None."""
    import ast as parsed

    try:
        tree = parsed.parse(source)
    except (SyntaxError, ValueError):
        return None

    def walk(body, prefix):
        for node in body:
            if isinstance(node, FUNCS) and node.name.startswith("test") \
                    and node.lineno <= n <= (node.end_lineno or node.lineno):
                return prefix + "::" + node.name
            if isinstance(node, parsed.ClassDef):
                found = walk(node.body, prefix + "::" + node.name)
                if found:
                    return found
        return None

    return walk(tree.body, rel)


SPLIT_READS = re.compile(r"^\s*reads\s+as\s+(.+?),?\s+or\s+as\s+(\S.*)$",
                         re.I)


def split_checked(run, split):
    """-> where a SPLIT line's quote was found, `the request` or a spec
    line's cite, or "" when the line cannot be checked: its words must be
    QUOTE_WORDS or more of the request as handed or of one spec line as the
    run found it, followed by `reads as <one>, or as <another>`."""
    m = ruling.REQUEST_QUOTE.match(split)
    if m:
        rest = split[m.end():]
        if SPLIT_READS.match(rest) and ruling.request_settles(
                m.group(0), getattr(run, "task_text", None)):
            return ruling.THE_REQUEST
        return ""
    start = getattr(run, "start", None)
    m = ruling.QUOTE_OPENS.match(split)
    if not m or split[m.end():m.end() + 1] != '"':
        return ""
    cite = split[:m.end()].strip()
    body = split[m.end() + 1:]
    for i, ch in enumerate(body):
        if ch != '"' or not SPLIT_READS.match(body[i + 1:]):
            continue
        line, _ = ruling.settled_by(cite + ' "' + body[:i] + '"',
                                    run.workdir, start)
        if not line or "-" in line.rpartition(":")[2]:
            continue
        if getattr(start, "specs", None) and not spec_cites(
                line, run.workdir, start):
            continue
        return line
    return ""


def lead_parks(run, step, out):
    """-> (the NEEDS question the lead's own answer parks the run on, what
    the run's record keeps of it or None), or ("", None) when every
    QUESTION of it is the lead's to decide (`lead_decides`). it parks only
    on a risk the program finds on the page:
    - a `spec: breaks` or `spec: contradicts` mark no answer of the run
      already ruled on (`marked`): every such mark, in one stop, under the
      first question or alone;
    - a question whose words, cites or SETTLED BY name a test the run
      started with (`start_tests`): the test question, an `override:`
      naming the test letting it change;
    - a typed `SPLIT:` line: two readings of the request's words or of one
      spec line, the quote checked where it can be (`split_checked`), any
      SPLIT line parking;
    - no recommendation (`no_recommendation`).
    a question or mark already put to the person in this run and answered
    is not asked again. the lead's own question has no one above it."""
    answered = answered_here(run)
    marks = marked(run, step, out, answered)
    questions = lead_questions(run, step, out, answered)
    unread = [line + UNREAD_SAID for line in unread_asking(out.output)] \
        if step == getattr(run, "lead", None) else []
    if (marks or unread) and questions:
        asked, rec, cites, size, _, _ = questions[0]
        return asked_as(asked, marks + unread + cites, rec, size), None
    alone = [m for m in marks if not ruling.CONTRADICTS.match(m)] + unread
    if alone:
        head = UNASKED if all(ruling.BREAKS.match(m) for m in alone) \
            else UNREAD
        return "\n".join([head, "CITES:"] + ["- " + m for m in alone]), None
    for asked, rec, cites, size, settled, split in questions:
        files, ids = start_tests(run, [asked, settled, rec] + cites)
        if files:
            named = ids or files
            return "\n".join(
                [asked, "CITES:"]
                + ["- " + t + " - a test the run started with" for t in named]
                + ["- " + c for c in cites if c.split(":")[0] not in files]
                + (["RECOMMEND: " + rec] if rec else [])
                + (["SIZE: " + size] if size else [])
                + ["OPTIONS:",
                   "- override: <why the change holds>. name each test above,"
                   " and the change to it stands",
                   "- anything else is told to " + step + ", which plans"
                   " again with the tests as they are"]), \
                ruling.edits_asked(ids + files)
        if split and not ruling.says_none(split):
            where = split_checked(run, split)
            said = asked_as(asked, cites, rec, size).split("\n")
            said.insert(1, "SPLIT: " + split + (
                " (the quote is in the request)" if where == ruling.THE_REQUEST
                else " (the quote is on " + where + ")" if where
                else " (not checked: no quote of the request or of one spec"
                " line, then reads as <one>, or as <another>)"))
            return "\n".join(said), None
        if no_recommendation(rec):
            return asked_as(asked, cites, rec, size), None
    return "", None


def asked_as(asked, cites, rec, size):
    said = [asked]
    if cites:
        said += ["CITES:"] + ["- " + c for c in cites]
    if rec:
        said.append("RECOMMEND: " + rec)
    if size:
        said.append("SIZE: " + size)
    return "\n".join(said)


def lead_escalates(run, step, out):
    """-> what of the lead's own answer goes to the person, as a NEEDS
    question, or "" (`lead_parks`)."""
    return lead_parks(run, step, out)[0]


def lead_decides(run, step, out, where):
    """each QUESTION of the lead's own handoff that parks nothing
    (`lead_parks`) is the lead's to decide, and its RECOMMEND is the
    decision: put on record as the lead's, so every later step gets it and
    the handoff lists it first, for the person to overrule. its SETTLED BY
    is the reason recorded beside it (`settled_reason`). -> how many it put
    on record."""
    if lead_parks(run, step, out)[0]:
        return 0
    answered = answered_here(run)
    count = 0
    for asked, rec, _, _, settled, _ in lead_questions(run, step, out,
                                                       answered):
        if lead.key(asked) in run.led:
            continue
        line, quote = settled_reason(run, settled)
        count += 1
        run.led[lead.key(asked)] = rec
        run.rule(*lead.recorded(
            step, step, where, asked, rec,
            "the recommendation of " + step + "'s own handoff, which "
            + line + ' "' + quote + '"' + lead.SETTLES + step
            + lead.SETTLES_END if line else
            "the recommendation of " + step + "'s own handoff; no spec mark,"
            " start test or split on it goes to the person, so " + step
            + lead.SETTLES_END), by=rulings.LEAD)
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
