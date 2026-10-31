"""`retro: true` on a flow: one last step after every run that ends, once
the handoff is written. it reads the run's record - why each failed attempt
failed, each gate that could not do its job, each shell write a step went on
after being refused, what each step handed over, where the record holds what
each step's reasons led to (never the reasons' own words), the rulings
written, the files changed, the project's facts that are stale or hold for
those files, and the docs that name a changed file or a name the diff took
out or put in - and writes runs/<run id>/retro.md: what failed, why, which gate or
prompt to change, whether each named doc is current, and a FACTS block of
what the project's facts should become, a doc or test that should change
among them as a nice-to-do ticket on its one file.

the role (`roles/library/retro.md`) is handed this run's facts; the skill
(`skills/retro/`) is the procedure. the FACTS block is the one part the
runner acts on (`runner/upkeep.py`): it writes each fact and ticket that
holds against the record into facts/ and proposes the rest; neither the
retro nor the runner changes any other file of the tree for it. none of it
is staged: under `commits: wip` or `squash`, on a run
whose steps all passed, it is one commit of its own, `retro: ...`, after
the task's. a retro that fails is its own line in steps.jsonl, never a
different outcome for the run.
"""
import json
import re
import types
from pathlib import Path

from agentweft.flow.spec import CONDITIONAL, parks_on_fallback, step_id
from agentweft.guardrails import factsguard, police, retroedits
from agentweft.guardrails.budget import REACHED
from agentweft.orchestrate import decisions, facts
from agentweft.roles import resolver

from . import (asking, handoff, investigate, lead, manifest, stops, summary,
               trace, upkeep)
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
# what the handoff says of a retro another model answered under
# `on_fallback: park`
HELD_BACK = ("on_fallback: park holds its facts and tickets: none was kept;"
             " what it proposed is in " + FILE)
CRITICAL_HEAD = "## critical tickets, for the lead"
LATER_WORDS = "accept it as later"


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


def gave_reasons(lines):
    """-> the lines among `lines` of the passes that gave a reason."""
    return [(line, folder) for line, folder in lines
            if line.get("step") != STEP and line.get("outcome") != trace.WARM
            and isinstance(line.get("handoff"), dict)
            and line["handoff"].get("because")]


# the flow steps a run without a flow spec is read against
NO_FLOW = types.SimpleNamespace(steps=[])


def evidence(run, trail, earlier, lines):
    """-> a line per reason a pass not yet looked at gave that led to
    something the record holds, with its seq and step: where the runner
    found it (`summary.held_at`), never the reason's own words."""
    giving = gave_reasons(lines)
    if not giving:
        return []
    fm = getattr(run, "fm", None) or NO_FLOW
    every = [summary.line_pass(line, folder, {}, fm) for line, folder
             in recorded(trail, earlier, False)
             if line.get("step") != STEP and line.get("outcome") != trace.WARM]
    tree = getattr(run, "tree", None)
    try:
        changes = tree.changes() if tree is not None else {}
    except (OSError, ValueError):
        changes = {}
    try:
        decided = list(run.decided())
    except (OSError, ValueError, AttributeError):
        decided = []
    record = summary.record_of(every, changes, decided, getattr(
        getattr(run, "order", None), "proof", None))
    out = []
    for line, folder in giving:
        for cite in summary.evidence(summary.line_pass(line, folder, {}, fm),
                                     record):
            out.append(("- seq " + str(line.get("seq")) + " "
                        + str(line.get("step")) + " -> "
                        + stops.flat(cite))[:ITEM])
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


def pins_of(lines):
    """-> (the tests the last red-first gate that passed in `lines` ran green
    without the change, in its order, the seq and step of its pass); no
    tests when no such gate passed or it ran none green."""
    out = ([], None, None)
    for line, _ in lines:
        for g in line.get("gates") or []:
            if isinstance(g, dict) and g.get("gate") == "red-first" \
                    and g.get("ok") and isinstance(g.get("tests"), list):
                out = ([t["test"] for t in g["tests"] if isinstance(t, dict)
                        and t.get("before") == "green"
                        and isinstance(t.get("test"), str)],
                       line.get("seq"), line.get("step"))
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


def parts(looked, rulings, changed, stale, live, cap, docs=(),
          tickets=factsguard.TICKETS, led=()):
    """-> (heading, lines) for each part of the record after the failed
    attempts, gate issues and refused writes. `changed` is None outside
    git; `docs` is the docs that name what changed (`retroedits.named`);
    `led` is where the record holds what each step's reasons led to
    (`evidence`)."""
    return [("what each step handed over, from steps.jsonl:", handed(looked)),
            ("what each step's reasons led to, as the runner found it in the"
             " record:", list(led)),
            ("rulings written in this run, from decisions.md:", rulings),
            ("files this run changed, from git:",
             ["- " + p for p in changed] if changed else
             ["- nothing changed in the tree" if changed is not None
              else "- not a git checkout, so what changed is not recorded"]),
            ("docs that name a file or a name this run changed, each to"
             " confirm current or keep a ticket on:", list(docs)),
            ("test coverage a step named as missing, from steps.jsonl: each"
             " the run's tests left uncovered is a nice-to-do on its test"
             " file, or on the code it tests when there is none yet; one"
             " they cover needs nothing:", coverage_named(looked)),
            ("facts marked stale, to re-anchor, retire or supersede:", stale),
            ("facts on record for the files this run changed:", live),
            ("fact checks a step's change broke or that could not run,"
             " from steps.jsonl:", unheld(looked)),
            ("new facts this run may write:", ["- " + str(cap)]),
            ("nice-to-do tickets this run may write:",
             ["- " + str(tickets)])]


def diff_of(run, changed):
    """-> the change to the files in `changed` as `git diff` prints it, from
    the start commit to the tree as left, a file git does not track as all
    added; "" when there is no start to diff from."""
    tree = getattr(run, "tree", None)
    start = getattr(getattr(run, "start", None), "start", None) \
        or getattr(tree, "start", None)
    if tree is None or not getattr(tree, "git", False) or not start:
        return ""
    out = summary._git(tree.root, "diff", "--unified=0", "--no-color",
                       "--no-ext-diff", start, "--", *changed) or ""
    tracked = set(summary._lines(summary._git(
        tree.root, "ls-files", "--", *changed)))
    for path in changed:
        if path in tracked:
            continue
        try:
            text = (tree.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out = out + "\n" + "\n".join("+" + l for l in text.split("\n"))
    return out


def named_docs(run, changed, store):
    """-> the lines for the docs of the place that name a file the run
    changed or a name its diff took out or put in; [] when the lane is
    off or nothing changed."""
    if store.off or not changed:
        return []
    gone, put = retroedits.names_of(diff_of(run, changed))
    try:
        return retroedits.named(store.root, relative(run, changed),
                                gone + put, own=store.own)
    except OSError:
        return []


def relative(run, changed):
    """-> `changed`, paths from the top of the repo, as paths from the
    place, the ones outside it left out."""
    tree = getattr(run, "tree", None)
    root, place = getattr(tree, "root", None), getattr(tree, "place", None)
    if root is None or place is None:
        return list(changed)
    out = []
    for rel in changed:
        try:
            out.append((Path(root) / rel).resolve().relative_to(
                Path(place).resolve()).as_posix())
        except ValueError:
            continue
    return out


def coverage_named(lines):
    """-> one line per test coverage a pass not yet looked at named as
    missing, with its seq and step."""
    return ["- seq " + str(line.get("seq")) + " " + str(line.get("step"))
            + ": " + stops.flat(str(n.get("file"))) + " - "
            + stops.flat(str(n.get("what")))
            for line, _ in lines for n in line.get("coverage") or []
            if isinstance(n, dict)]


def unheld(lines):
    """-> one line per fact check a pass not yet looked at broke or could
    not run, with its seq and step."""
    return ["- seq " + str(line.get("seq")) + " " + str(line.get("step"))
            + ": " + str(c.get("fact")) + " " + str(c.get("result")) + ": "
            + stops.flat(str(c.get("check"))) + (" - " + stops.flat(
                str(c["said"])) if c.get("said") else "")
            for line, _ in lines for c in line.get("conformance") or []
            if c.get("result") != "held"]


VIEW = "retro-view"


def view(folder, into=None):
    """-> the path of a copy of the run folder's steps.jsonl with no step's
    own reasons in it, written under `into` (`<folder>/retro-view` when
    None) with each answer file a line names beside it, the BECAUSE section
    of every block in it taken out (`handoff.without_because`), and the gate
    record as it is.
    the run's own files keep the reasons."""
    out = Path(into) if into is not None else Path(folder) / VIEW
    out.mkdir(parents=True, exist_ok=True)
    kept = []
    path = Path(folder) / trace.FILE
    raw = path.read_text(encoding="utf-8") if path.is_file() else ""
    for text in raw.split("\n"):
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if isinstance(line.get("handoff"), dict) \
                and line["handoff"].get("because"):
            line["handoff"] = dict(line["handoff"], because=[])
        name = line.get("file")
        if isinstance(name, str) and (Path(folder) / name).is_file():
            copy = out / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_text(handoff.without_because(
                (Path(folder) / name).read_text(encoding="utf-8")),
                encoding="utf-8")
        kept.append(json.dumps(line, ensure_ascii=False))
    (out / trace.FILE).write_text("".join(k + "\n" for k in kept),
                                  encoding="utf-8")
    for name in (trace.GATES, "gates.md"):
        if (Path(folder) / name).is_file():
            (out / name).write_bytes((Path(folder) / name).read_bytes())
    return out / trace.FILE


def prompt(run_id, flow, outcome, folder, lines, issued=(), worked=(),
           more=(), record=None):
    """-> the role, the skill, then this run's record. `more` is
    (heading, lines) for each further part of it. the handoff is handed
    without the steps' own reasons (`summary.without_reasons`): what each
    led to is in the record as the runner found it (`evidence`). `record`
    is the copy of steps.jsonl the retro is pointed at for every pass in
    full (`view`), `<folder>/retro-view/steps.jsonl` when None; the
    handoff's pointers to the answers and the record name that copy."""
    text = (resolver.role_prompt(STEP).rstrip("\n") + "\n\n"
            + resolver.skill(ROLE).strip("\n") + "\n\n"
            + "this run:\n- run: " + run_id + "\n- flow: " + flow
            + "\n- outcome: " + outcome + "\n\n"
            + "why each failed attempt failed, from steps.jsonl:\n"
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
            said = (folder / name).read_text(encoding="utf-8")
            if name == summary.FILE:
                said = summary.without_reasons(said)
                if record is None or Path(record).parent == folder / VIEW:
                    run = "runs/" + run_id + "/"
                    said = said.replace(run + "steps/", run + VIEW
                                        + "/steps/").replace(
                        run + trace.FILE, run + VIEW + "/" + trace.FILE)
            text = text + "\n" + name + ":\n\n" + said.rstrip("\n") + "\n"
    return text + "\nevery pass in full: " + str(
        record if record is not None else folder / VIEW / trace.FILE) + "\n"


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
    touched = len(store.touched)
    pinned, pin_line = upkeep.pins(store, record_of(run, trail, earlier),
                                   pins_of(recorded(trail, earlier, False)),
                                   run_id)
    stale, live = kept_facts(store, changed)
    text = prompt(run_id, flow, outcome, folder, lines, issued, worked,
                  parts(looked, ruled(run), changed, stale, live,
                        0 if store.off else store.cap,
                        named_docs(run, changed, store),
                        0 if store.off else store.tickets,
                        evidence(run, trail, earlier, looked)),
                  record=view(folder))
    used = run.by_step.get(STEP, run.provider)
    tried = trace.Attempt()
    used.at(STEP, None)
    tried.effort = run.effort_for(STEP, used)
    used.going = tried.effort["base"] and tried.effort["asked"]
    print("started " + STEP)
    said, why, seen, answered = "", None, None, False
    try:
        answer = tried.answered(ask(run, text, used))
        answered = True
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
    if not answered:
        seen = unpoliced(run)
    if not said and not why:
        why = "nothing came out of " + STEP
    done = Maintained()
    held_back = HELD_BACK if not why and parks_on_fallback(
        getattr(run, "fm", None)) and trace.fallback([tried]) else None
    if not why and not held_back:
        done = kept_up(run, trail, earlier, store, said, run_id)
    if pin_line:
        done.present = True
        done.lines.insert(0, pin_line)
        done.pins = pinned.id if pinned is not None else ""
    led, passes = escalated(run, folder, store, done, run_id) \
        if not why and not held_back else ([], [])
    files = upkeep.files_changed(done, store.touched[touched:], store.root)
    kept = committed(run, [p for p, _ in files], done) if files else None
    entry = trail.open(STEP, [tried], used, None, output=said or None)
    entry.police = seen
    entry.held = held_back
    if done.present:
        entry.facts = done.record()
        if kept and kept[0]:
            entry.facts["commit"] = kept[0]
    trail.close(entry, "failed" if why else "ok", why=why, planned=False)
    for out, decided in passes:
        asking.lead_pass(trail, run, out, STEP, decided)
    if why:
        print("retro failed, the run's outcome stands: " + why)
        if not pin_line:
            return
    if held_back:
        print(STEP + ": " + held_back)
    told = done.said()
    if not why:
        (folder / FILE).write_text(
            said if not told else said.rstrip("\n") + "\n" + "\n"
            + upkeep.DONE_HEAD + "\n\n" + "\n".join(told) + "\n",
            encoding="utf-8")
    for line in told:
        print("facts: " + line[2:])
    changes = []
    if files:
        changes = ([upkeep.COMMITTED if kept[0] else upkeep.CHANGES, ""]
                   + ([kept[1]] if kept[1] else [])
                   + [line for _, line in files])
        for line in changes[2:]:
            print("retro changed: " + line[2:])
    for line in led:
        print("critical: " + line.strip().lstrip("- "))
    if (told or changes or led) and (folder / summary.FILE).is_file():
        with open(folder / summary.FILE, "a", encoding="utf-8") as f:
            if changes:
                f.write("\n" + "\n".join(changes) + "\n")
            if told:
                f.write("\n" + upkeep.SECTION + "\n\n" + "\n".join(told)
                        + "\n")
            if led:
                f.write("\n" + CRITICAL_HEAD + "\n\n" + "\n".join(led) + "\n")
    if not why:
        print("retro: " + str(folder / FILE))


def committed(run, paths, done):
    """-> (the sha of the retro's own commit or None, a line on it or "").
    under `commits: none` nothing is committed. otherwise the retro's files
    are one commit after the task's, made only once every step has passed:
    a run that stops short goes on in a leg whose step commits would come
    after it."""
    from . import commits

    who = getattr(run, "committer", None)
    if who is None or who.how == commits.NONE:
        return None, ""
    if who.order is None:
        return None, ("- not committed: the run stopped before every step"
                      " passed, and the leg that carries it on commits after"
                      " it; left unstaged")
    try:
        sha = who.retro([(Path(store_root(run)) / p) for p in paths],
                        message(done))
    except ValueError as e:
        return None, "- not committed: " + str(e) + "; left unstaged"
    if not sha:
        return None, ""
    return sha, ("- " + sha[:12] + " " + message(done) + ", on "
                 + str(who.branch))


def store_root(run):
    return getattr(getattr(run, "facts", None), "root", None) or run.workdir


def message(done):
    """-> the retro commit's subject: what it kept current."""
    n = len(done.written) + len(done.changed) + len(done.counted)
    said = str(n) + " fact" + ("" if n == 1 else "s") if n \
        else "the facts' proposals"
    return "retro: kept " + said + " current"


FAILED_CALL = "the call failed"


def unpoliced(run):
    """-> the police line of a retro whose call failed before it answered:
    there is no answer to read, and the line says so rather than leave a
    reader to count the call unpoliced. None with police off."""
    mode = getattr(run, "policing", police.OFF)
    if mode == police.OFF:
        return None
    line = {"seen": False, "why": FAILED_CALL}
    if mode == police.SHADOW:
        line["mode"] = police.SHADOW
    return line


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


def escalated(run, folder, store, done, run_id):
    """-> (the handoff's lines for each critical nice-to-do the retro wrote,
    the lead's (Handoff, decided) for each go it took). each goes to the
    flow's lead, who re-iterates now or accepts it as later; its decision
    is recorded in decisions.md as the lead's, and the ticket is then
    `important` (first for the next planner on its file) or unlabelled. a
    flow with no lead, or a lead that does not decide, leaves it critical
    and the person's. nothing in the tree changes for it either way."""
    lines, passes = [], []
    head = getattr(run, "lead", None)
    for id in done.tickets:
        fact = store.held(id)
        if fact is None or fact.label != facts.CRITICAL:
            continue
        lines.append("- " + id + " (" + ", ".join(fact.scopes) + "): "
                     + fact.claim)
        if head is None:
            lines.append("  the flow has no lead, so it is yours: "
                         + lead.NOW + " or " + LATER_WORDS)
            done.escalated.append({"id": id, "decided": None})
            continue
        out, _, passed = asking.to_lead(
            run, STEP, lead.ticket_question(fact), {}, "the retro of run "
            + run_id, folder, pick=lead.ticket_pick(head))
        decided = None if passed else run.led.get(lead.key(
            lead.ticket_question(fact)))
        if out is not None:
            passes.append((out, decided))
        done.escalated.append({"id": id, "decided": decided})
        if decided is None:
            why = (out.meta.get("passed") if out is not None else "") \
                or passed.split("\n\n")[-1]
            lines.append("  not decided by the lead (" + why + "), so it is"
                         " yours: " + lead.NOW + " or " + LATER_WORDS)
            continue
        store.change(id, (lambda f: f.put("label", "important"))
                     if decided == lead.NOW else (lambda f: f.drop("label")))
        lines.append("  the lead, " + head + ", decided: " + decided + " - "
                     + lead.read(out.output)[1] + " (on record in "
                     + decisions.FILE + ")")
    return lines, passes


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
