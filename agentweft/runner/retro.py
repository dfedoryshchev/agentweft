"""`retro: true` on a flow: one last step, once the handoff is written, that
reads why each failed attempt of the run failed and writes
runs/<run id>/retro.md, what failed, why, and which gate or prompt to change.

the role (`roles/library/retro.md`) is handed this run's facts; the skill
(`skills/retro/`) is the procedure. what it writes is advice: no gate reads
it, and a retro that fails is its own line in steps.jsonl, never a different
outcome for the run.
"""
import json

from agentweft.guardrails.budget import REACHED
from agentweft.roles import resolver

from . import investigate, manifest, stops, summary, trace
from .errors import Fatal, Outage

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


def on(fm):
    return fm.get("retro") is True


def failed(lines):
    """-> the lines of attempts that failed. a redo that only switched the
    cause step on and a stop that waits for someone are not failures."""
    return [l for l in lines if l.get("outcome") not in FINE
            and l.get("cause") not in HELD
            and not (l.get("outcome") == "redo"
                     and l.get("to") == investigate.STEP)]


def recorded(trail, earlier=None):
    """-> (line, its run folder) for every line of every leg up to this one,
    first leg first, from the last retro's line on: an attempt one retro has
    looked at is not handed to the next."""
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
    return out[seen[-1] + 1:] if seen else out


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


def prompt(run_id, flow, outcome, folder, lines):
    """-> the role, the skill, then this run's record."""
    text = (resolver.role_prompt(STEP).rstrip("\n") + "\n\n"
            + resolver.skill(ROLE).strip("\n") + "\n\n"
            + "this run:\n- run: " + run_id + "\n- flow: " + flow
            + "\n- outcome: " + outcome + "\n\n"
            + "why each failed attempt failed, from steps.jsonl:\n"
            + "\n".join(lines) + "\n")
    for name in ("why.md", summary.FILE):
        if (folder / name).is_file():
            text = (text + "\n" + name + ":\n\n"
                    + (folder / name).read_text(encoding="utf-8").rstrip("\n")
                    + "\n")
    return text + "\nevery pass in full: " + str(folder / trace.FILE) + "\n"


def held(run, stopped):
    """-> why the retro does not run after this stop, or ""."""
    cause = (stopped or {}).get("cause")
    if cause in HELD:
        return "the run stopped on " + cause
    waits = run.budget.ahead()
    if waits and waits[0] == REACHED:
        return waits[1]
    return ""


def ask(run, text, used):
    return run.ask(text, STEP, used)


def after(run, trail, run_id, flow, outcome, folder, stopped=None,
          earlier=None):
    """run the retro over the failed attempts no retro has looked at yet,
    this leg's and the legs' before it (`earlier`, the run this one picked
    up), when there are any. nothing it does or raises reaches the run's
    outcome."""
    try:
        look_back(run, trail, run_id, flow, outcome, folder, stopped, earlier)
    except (Exception, KeyboardInterrupt) as e:
        print("retro failed, the run's outcome stands: " + type(e).__name__
              + ": " + str(e))


def look_back(run, trail, run_id, flow, outcome, folder, stopped, earlier):
    from .engine import Answer

    lines = whys(trail, earlier)
    if not lines:
        return
    skip = held(run, stopped)
    if skip:
        print("retro not run: " + skip)
        return
    text = prompt(run_id, flow, outcome, folder, lines)
    used = run.by_step.get(STEP, run.provider)
    tried = trace.Attempt()
    used.at(STEP, None)
    tried.effort = run.effort_for(STEP, used)
    used.going = tried.effort["base"] and tried.effort["asked"]
    print("started " + STEP)
    said, why = "", None
    try:
        answer = tried.answered(ask(run, text, used))
        said = answer[0]
        if not answer[1]:
            run.charge(text, answer, used.name, used.asks_for())
    except (Outage, Fatal) as e:
        run.charge(text, tried.answered(Answer("", False, e.replies,
                                               e.retries)),
                   used.name, used.asks_for())
        why = type(e).__name__ + ": " + str(e)
    except (Exception, KeyboardInterrupt) as e:
        why = type(e).__name__ + ": " + str(e)
    if not said and not why:
        why = "nothing came out of " + STEP
    entry = trail.open(STEP, [tried], used, None, output=said or None)
    trail.close(entry, "failed" if why else "ok", why=why, planned=False)
    if why:
        print("retro failed, the run's outcome stands: " + why)
        return
    (folder / FILE).write_text(said, encoding="utf-8")
    print("retro: " + str(folder / FILE))
