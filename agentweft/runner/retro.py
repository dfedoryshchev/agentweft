"""`retro: true` on a flow: one last step after every run that ends, once
the handoff is written. it reads the run's record - the reasons each step
gave and what each led to, first, then why each failed attempt failed, each
gate that could not do its job, each shell write a step went on
after being refused, what each step handed over, the rulings written, the
files changed, and the project's facts that are stale or hold for those
files - and writes runs/<run id>/retro.md: what failed, why, which gate or
prompt to change, and a FACTS block of what the project's facts should
become.

the role (`roles/library/retro.md`) is handed this run's facts; the skill
(`skills/retro/`) is the procedure. the FACTS block is the one part the
runner acts on (`runner/upkeep.py`): it writes each fact that holds against
the record and proposes the guards and doc changes, and the retro itself
writes nothing. a retro that fails is its own line in steps.jsonl, never a
different outcome for the run.
"""
import json
import re

from agentweft.flow.spec import CONDITIONAL, step_id
from agentweft.guardrails import factsguard, police
from agentweft.guardrails.budget import REACHED
from agentweft.orchestrate import decisions, facts
from agentweft.roles import resolver

from . import handoff, investigate, manifest, stops, summary, trace, upkeep
from .errors import Fatal, Outage
from .upkeep import Maintained, execute  # noqa: F401

ROLE = "retro"
STEP = ROLE + ".md"
FILE = "retro.md"
# it reads the record it is handed and nothing else, so it gets the narrowest
# grant a step can have, whatever the flow's own steps were granted
GRANT = ["read"]
# outcomes of a pass that did what it was asked
FINE = ("ok", "asked", "decided", "escalated", trace.WARM)
# the run waits on the provider, the cap, a person who pressed ctrl-c or a
# ruling, and a retro would spend on the very thing it stopped for. the
# failed attempts carry to the leg that ends the run.
HELD = (stops.OUTAGE, stops.BUDGET, stops.INTERRUPT, stops.PARKED,
        stops.CONFLICT)
# a provider that refused a step outright (no credentials, not allowed to run
# here) refuses the retro the same way; the crashed attempt is still a failed
# one for the leg that carries the run on
HOLDS = HELD + (stops.EXCEPTION,)


def on(fm):
    """whether the flow runs the retro at all: `retro: true`, or
    `retro: conditional` on a run that had something to look back at."""
    said = fm.get("retro")
    return said is True or said == CONDITIONAL


def conditional(fm):
    return fm.get("retro") == CONDITIONAL


def trouble(run, lines, issued, worked, changed, looked):
    """-> "" when a conditional retro has something to look back at, else
    why it does not run: the run changed no file, had no failed attempt, no
    gate issue or refused write, and no question. a place outside git cannot
    say what changed, so it counts as changed."""
    asked = any(l.get("outcome") in ("asked", "decided", "escalated")
                or l.get("cause") in (stops.PARKED, stops.CONFLICT)
                for l, _ in looked)
    if lines or issued or worked or changed is None or changed or asked \
            or unheld(looked) \
            or getattr(getattr(run, "kept", None), "written", None):
        return ""
    return ("conditional, and the run changed no file, had no failed attempt,"
            " no gate issue and no question")


def failed(lines):
    """-> the lines of attempts that failed. a redo that only switched the
    cause step on and a stop that waits for someone are not failures."""
    return [l for l in lines if l.get("outcome") not in FINE
            and l.get("cause") not in HELD
            and not (l.get("outcome") == "redo"
                     and l.get("to") == investigate.STEP)]


def recorded(trail, earlier=None, since=True):
    """-> (line, its run folder) for every line of every leg up to this one,
    first leg first, from the last retro's line on: an attempt one retro has
    looked at is not handed to the next. `since` False keeps every line."""
    out = []
    if earlier is not None:
        for leg in manifest.legs(earlier)[0]:
            path = leg / trace.FILE
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8").split("\n"):
                try:
                    out.append((json.loads(raw), leg))
                except ValueError:
                    continue
    out.extend((entry.written or {}, trail.folder)
               for entry, _ in trail.closed)
    seen = [i for i, (l, _) in enumerate(out) if l.get("step") == STEP]
    return out[seen[-1] + 1:] if seen and since else out


def whys(trail, earlier=None):
    """-> one line per failed attempt not yet looked at, in the order they
    ran: its seq, step, outcome and the why on its line."""
    out = []
    lines = recorded(trail, earlier)
    for line, folder in lines:
        if line not in failed([line]):
            continue
        why = line.get("why")
        kept = line.get("file")
        if not why and kept and (folder / kept).is_file():
            why = summary.redo_why((folder / kept).read_text(encoding="utf-8"))
        out.append("- seq " + str(line.get("seq")) + " " + str(line.get("step"))
                   + ", " + str(line.get("outcome")) + ": "
                   + stops.flat(why or "no why was written"))
    return out


def issues(lines):
    """-> one line per gate that could not do its job, on the passes not yet
    looked at: its seq, step and what it could not do."""
    out = []
    for line, _ in lines:
        for g in line.get("gates") or []:
            if isinstance(g, dict) and g.get("issue"):
                out.append("- seq " + str(line.get("seq")) + " "
                           + str(line.get("step")) + ": "
                           + stops.flat(g["issue"]))
    return out


def workarounds(lines):
    """-> one line per shell write the hook refused a pass not yet looked
    at, which the step then went on past, from its run folder's denials."""
    from agentweft.guardrails import shellwrite

    out = []
    read = {}
    for line, folder in lines:
        sessions = set([line.get("session")] + [
            t.get("session") for t in line.get("tasks") or []
            if isinstance(t, dict)]) - {None}
        if not sessions:
            continue
        if folder not in read:
            read[folder] = refusals(folder / shellwrite.FILE)
        for said in read[folder]:
            if said.get("session") in sessions:
                out.append("- seq " + str(line.get("seq")) + " "
                           + str(line.get("step")) + " went on after the"
                           " shell write `" + stops.flat(str(
                               said.get("refused") or said.get("command")))
                           + "` was refused")
    return out


def refusals(path):
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


HANDED = (("did", "did"), ("assumed", "assumed"), ("tried", "tried"),
          ("doubts", "doubts"), ("adjacent", "found beside the change"))
# one item of the record, as long as it needs to be to be read and no longer
ITEM = 240


def handed(lines):
    """-> a line per DID, ASSUMED, TRIED, DOUBTS and ADJACENT item each pass
    not yet looked at handed over, with its seq and step; a defect found
    beside the change says whether it was fixed and by which test."""
    out = []
    for line, _ in lines:
        block = line.get("handoff") or {}
        if not isinstance(block, dict) or line.get("step") == STEP:
            continue
        for key, word in HANDED:
            for item in block.get(key) or []:
                text = item if isinstance(item, str) else str(item)
                if key == "adjacent":
                    found = summary.beside(text)
                    text = found["defect"] + " - " + summary.beside_said(found)
                out.append("- seq " + str(line.get("seq")) + " "
                           + str(line.get("step")) + " " + word + ": "
                           + stops.flat(text)[:ITEM])
    return out


def reasons(lines):
    """-> a line per BECAUSE item each pass not yet looked at handed over,
    with its seq and step, where the reason came from and what it led to."""
    out = []
    for line, _ in lines:
        block = line.get("handoff") or {}
        if not isinstance(block, dict) or line.get("step") == STEP:
            continue
        for item in block.get("because") or []:
            r = handoff.reason(item if isinstance(item, str) else str(item))
            out.append("- seq " + str(line.get("seq")) + " "
                       + str(line.get("step")) + " because "
                       + stops.flat(r["reason"] + " (from " + (
                           r["from"] or "own read") + ") -> led to "
                           + (r["led_to"] or "none named"))[:ITEM])
    return out


def ruled(run):
    """-> a line per ruling the runner wrote in this run, any leg."""
    kept = getattr(run, "kept", None)
    out = ["- decisions.md " + str(w.get("at")) + "  " + str(w.get("decided"))
           + " (" + str(w.get("by")) + ")"
           for w in (getattr(kept, "written", None) or [])]
    return out or ["- none"]


BEFORE = "already modified before the run"


def changed_files(run):
    """-> the paths git says the run changed, None outside git. a file that
    was already modified before the run started is the place's, not the
    run's: git cannot tell the run's part of it apart."""
    tree = getattr(run, "tree", None)
    try:
        found = tree.changes() if tree is not None else {}
    except (OSError, ValueError):
        return None
    if not found.get("git"):
        return None
    return [f[0] for f in found.get("files") or []
            if not str(f[3]).endswith(BEFORE)]


def store_of(run):
    store = getattr(run, "facts", None)
    if store is None:
        store = run.facts = factsguard.Store(
            run.workdir, off=factsguard.lane_off(getattr(run, "fm", None)))
    return store


def fact_line(f):
    return ("- " + f.id + " " + ", ".join(f.scopes) + ": " + f.claim
            + (" (stale: " + f.get("stale") + ")" if f.status == facts.STALE
               else ""))


def kept_facts(store, changed):
    """-> (a line per stale fact, a line per live fact that holds for a file
    the run changed)."""
    found = store.read()
    stale = [fact_line(f) for f in found if f.status == facts.STALE]
    live, seen = [], set()
    for path in changed or []:
        for f in facts.lookup(store.root, path, found=found):
            if f.status == facts.LIVE and f.id not in seen:
                seen.add(f.id)
                live.append(fact_line(f))
    return stale, live


EXIT = re.compile(r"\bexit (-?\d+)")


def gate_runs(lines, fm):
    """-> (command, exit code) for each command and red-test gate the passes
    ran, read off their lines and the flow's own gates."""
    out = []
    for line, folder in lines:
        step = line.get("step")
        declared = [g for s in getattr(fm, "steps", []) or []
                    if step_id(s) == step for g in (s.get("gates") or [])]
        if not declared:
            continue
        kept = line.get("file")
        said = (folder / kept).read_text(encoding="utf-8") \
            if kept and (folder / kept).is_file() else ""
        commands = summary.gate_commands(fm, step, said)
        results = [g for g in line.get("gates") or [] if isinstance(g, dict)]
        for i, g in enumerate(declared):
            name = g.get("gate")
            if name not in ("command", "red-test") or i >= len(commands) \
                    or not commands[i]:
                continue
            nth = sum(1 for d in declared[:i] if d.get("gate") == name)
            mine = [r for r in results if r.get("gate") == name]
            if nth < len(mine):
                m = EXIT.search(mine[nth].get("detail") or "")
                if m:
                    out.append((commands[i], int(m.group(1))))
    return out


def record_of(run, trail, earlier):
    """-> the factsguard.Record a FACTS block is held to."""
    try:
        stamps = [d.at.strftime(decisions.STAMP) for d in run.decided()]
    except (OSError, ValueError, AttributeError):
        stamps = []
    return factsguard.Record(run.workdir, start=getattr(run, "start", None),
                             ran=gate_runs(recorded(trail, earlier, False),
                                           getattr(run, "fm", None)),
                             stamps=stamps)


def parts(looked, rulings, changed, stale, live, cap):
    """-> (heading, lines) for each part of the record after the failed
    attempts, gate issues and refused writes. `changed` is None outside
    git."""
    return [("what each step handed over, from steps.jsonl:", handed(looked)),
            ("rulings written in this run, from decisions.md:", rulings),
            ("files this run changed, from git:",
             ["- " + p for p in changed] if changed else
             ["- nothing changed in the tree" if changed is not None
              else "- not a git checkout, so what changed is not recorded"]),
            ("facts marked stale, to re-anchor, retire or supersede:", stale),
            ("facts on record for the files this run changed:", live),
            ("fact checks a step's change broke or that could not run,"
             " from steps.jsonl:", unheld(looked)),
            ("new facts this run may write:", ["- " + str(cap)])]


def unheld(lines):
    """-> one line per fact check a pass not yet looked at broke or could
    not run, with its seq and step."""
    return ["- seq " + str(line.get("seq")) + " " + str(line.get("step"))
            + ": " + str(c.get("fact")) + " " + str(c.get("result")) + ": "
            + stops.flat(str(c.get("check"))) + (" - " + stops.flat(
                str(c["said"])) if c.get("said") else "")
            for line, _ in lines for c in line.get("conformance") or []
            if c.get("result") != "held"]


def prompt(run_id, flow, outcome, folder, lines, issued=(), worked=(),
           more=(), reasons=()):
    """-> the role, the skill, then this run's record, the reasons the steps
    gave first. `more` is (heading, lines) for each further part of it."""
    text = (resolver.role_prompt(STEP).rstrip("\n") + "\n\n"
            + resolver.skill(ROLE).strip("\n") + "\n\n"
            + "this run:\n- run: " + run_id + "\n- flow: " + flow
            + "\n- outcome: " + outcome + "\n\n")
    if reasons:
        text = (text + "the reasons each step gave for its work and what each"
                " led to, from steps.jsonl:\n" + "\n".join(reasons) + "\n\n")
    text = (text + "why each failed attempt failed, from steps.jsonl:\n"
            + "\n".join(lines or ["- none failed"]) + "\n")
    if issued:
        text = (text + "\ngates that could not do their job, from steps.jsonl:"
                "\n" + "\n".join(issued) + "\n")
    if worked:
        text = (text + "\nrefused tool calls a step went on past, from "
                + "tool-denials.jsonl:\n" + "\n".join(worked) + "\n")
    for heading, said in more:
        if said:
            text = text + "\n" + heading + "\n" + "\n".join(said) + "\n"
    for name in ("why.md", summary.FILE):
        if (folder / name).is_file():
            text = (text + "\n" + name + ":\n\n"
                    + (folder / name).read_text(encoding="utf-8").rstrip("\n")
                    + "\n")
    return text + "\nevery pass in full: " + str(folder / trace.FILE) + "\n"


def held(run, stopped):
    """-> why the retro does not run after this stop, or ""."""
    cause = (stopped or {}).get("cause")
    if cause in HOLDS:
        return "the run stopped on " + cause
    waits = run.budget.ahead()
    if waits and waits[0] == REACHED:
        return waits[1]
    return ""


def refused(run):
    """-> why the retro may not start, the way a step may not: its model
    would start in a place a step left an instruction file in."""
    check = getattr(run, "refused", None)
    return check(STEP) if callable(check) else ""


def ask(run, text, used):
    return run.ask(text, STEP, used)


def after(run, trail, run_id, flow, outcome, folder, stopped=None,
          earlier=None):
    """run the retro over the failed attempts, gate issues and refused tool
    calls no retro has looked at yet, this leg's and the legs' before it
    (`earlier`, the run this one picked up), when there are any. nothing it
    does or raises reaches the run's outcome."""
    try:
        look_back(run, trail, run_id, flow, outcome, folder, stopped, earlier)
    except (Exception, KeyboardInterrupt) as e:
        print("retro failed, the run's outcome stands: " + type(e).__name__
              + ": " + str(e))


def look_back(run, trail, run_id, flow, outcome, folder, stopped, earlier):
    from .engine import Answer

    skip = held(run, stopped) or refused(run)
    if skip:
        print("retro not run: " + skip)
        return
    lines = whys(trail, earlier)
    looked = recorded(trail, earlier)
    issued, worked = issues(looked), workarounds(looked)
    changed = changed_files(run)
    if conditional(getattr(run, "fm", None) or {}):
        skip = trouble(run, lines, issued, worked, changed, looked)
        if skip:
            print("retro not run: " + skip)
            return
    store = store_of(run)
    stale, live = kept_facts(store, changed)
    text = prompt(run_id, flow, outcome, folder, lines, issued, worked,
                  parts(looked, ruled(run), changed, stale, live,
                        0 if store.off else store.cap),
                  reasons=reasons(looked))
    used = run.by_step.get(STEP, run.provider)
    tried = trace.Attempt()
    used.at(STEP, None)
    tried.effort = run.effort_for(STEP, used)
    used.going = tried.effort["base"] and tried.effort["asked"]
    print("started " + STEP)
    said, why, seen = "", None, None
    try:
        answer = tried.answered(ask(run, text, used))
        said = answer[0]
        if not answer[1]:
            run.charge(text, answer, used.name, used.asks_for())
            seen, why = policed(run, used, tried, text, folder)
    except (Outage, Fatal) as e:
        run.charge(text, tried.answered(Answer("", False, e.replies,
                                               e.retries)),
                   used.name, used.asks_for())
        why = type(e).__name__ + ": " + str(e)
    except (Exception, KeyboardInterrupt) as e:
        why = type(e).__name__ + ": " + str(e)
    if not said and not why:
        why = "nothing came out of " + STEP
    done = Maintained()
    if not why:
        done = kept_up(run, trail, earlier, store, said, run_id)
    entry = trail.open(STEP, [tried], used, None, output=said or None)
    entry.police = seen
    if done.present:
        entry.facts = done.record()
    trail.close(entry, "failed" if why else "ok", why=why, planned=False)
    if why:
        print("retro failed, the run's outcome stands: " + why)
        return
    told = done.said()
    (folder / FILE).write_text(said if not told else said.rstrip("\n") + "\n"
                               + "\n" + upkeep.DONE_HEAD + "\n\n"
                               + "\n".join(told) + "\n", encoding="utf-8")
    for line in told:
        print("facts: " + line[2:])
    if told and (folder / summary.FILE).is_file():
        with open(folder / summary.FILE, "a", encoding="utf-8") as f:
            f.write("\n" + upkeep.SECTION + "\n\n" + "\n".join(told) + "\n")
    print("retro: " + str(folder / FILE))


def policed(run, used, tried, text, folder):
    """-> (the police line for the retro's go, why it failed or None): it
    reads the place like a step, so the check reads its transcript like a
    step's. with police on a hit fails the retro and nothing it proposed is
    acted on; in shadow the hit is written down and changes nothing. police
    off reads nothing."""
    mode = getattr(run, "policing", police.OFF)
    if mode == police.OFF:
        return None, None
    seen = police.report(STEP, used, GRANT, trace.sessions([tried]),
                         getattr(run, "network", None), text)
    police.add(folder, seen, mode == police.SHADOW)
    run.retro_seen = seen
    line = seen.line()
    if mode == police.SHADOW:
        line["mode"] = police.SHADOW
    if not seen.seen:
        print("police: " + STEP + " left no transcript to read, so what it"
              " did with its tools was not checked")
    if not seen.hits:
        return line, None
    with open(folder / police.FILE, "a", encoding="utf-8") as f:
        f.write("## " + STEP + "\n" + police.as_note([seen]))
    if mode == police.SHADOW:
        for hit in police.hit_lines([seen]):
            print("police (shadow): " + hit)
        return line, None
    return line, "off task: " + police.why(seen.hits)


def kept_up(run, trail, earlier, store, said, run_id):
    """-> what the runner did with the answer's FACTS block. a fault of its
    own is said in the block's note, never raised: the retro's outcome is
    the answer it gave. a flow whose lane is off acts on none of it."""
    if store.off:
        done = Maintained()
        if upkeep.parse(said) != (None, ""):
            done.present = True
            done.lines.append("- the flow's lane is off, so the FACTS block"
                              " was not acted on")
        return done
    try:
        return upkeep.maintain(store, record_of(run, trail, earlier), said,
                               run_id)
    except (OSError, ValueError, KeyError, TypeError) as e:
        done = Maintained()
        done.present = True
        done.fault = type(e).__name__ + ": " + str(e)
        return done
