"""what a run writes down as it ends: the journal, the index, the answer."""
import datetime
import re
import sys

from agentweft.guardrails import promises

from .config import steps
from .gating import NEWLINE
from .handoff import without
from . import investigate
from . import state
from . import stops
from . import summary
from . import trace
from .state import load_state, save_state

SEV = ("high", "med", "low")


def is_graded(line):
    return any(line.startswith("[" + s + "]") for s in SEV)


def by_severity(lines):
    out = []
    for s in SEV:
        for line in lines:
            if line.startswith("[" + s + "]"):
                out.append(line)
    for line in lines:
        if not is_graded(line):
            out.append(line)
    return out


def items(text):
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:])
    return out


def journal(flow_name, status, started, run=None, cause=None, spend=None,
            why=None, saved=None, origin=None, handoff=None):
    """the only place a journal line gets written. there were three, and the
    failure one had drifted into a different column order. the shapes are in
    `stops`, which is also what reads them back."""
    secs = int((datetime.datetime.now() - started).total_seconds())
    text = stops.line(started, flow_name, status, secs, run, cause, spend,
                      why, saved, handoff, origin)
    runs = state.RUNS
    runs.mkdir(parents=True, exist_ok=True)
    with open(runs / "journal.md", "a", encoding="utf-8") as f:
        f.write(text + NEWLINE)


def write_index(line):
    index = state.RUNS / "index.md"
    index.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if index.exists():
        lines = [l for l in index.read_text(encoding="utf-8").split("\n")
                 if l.strip()]
    lines.append(line)
    lines.sort()
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resume_command(flow, run_id, caps=None, raise_cap=None):
    """the line a person types to carry on after a park.

    it goes in the handoff, so it has to work as printed: the switches this run
    was started with come along, or the command in front of them is one they
    have to debug before they can use it. `caps` are the caps the run was
    given on the command line, repeated as they are; `raise_cap` is the one
    a budget park needs raised, written as `<n>`.
    """
    out = ["python run.py", flow, "--resume", run_id]
    if "--force" in sys.argv:
        out.append("--force")
    if "--flows" in sys.argv:
        out = out + ["--flows", sys.argv[sys.argv.index("--flows") + 1]]
    for flag, key in CAPS:
        if key == raise_cap:
            out = out + [flag, "<n>"]
        elif key in (caps or {}):
            out = out + [flag, str(caps[key])]
    return " ".join(out)


def cap_of(why):
    """-> the cap a budget park's why names, max_calls or max_tokens."""
    return "max_tokens" if "token cap" in why else "max_calls"


CAPS = (("--max-calls", "max_calls"), ("--max-tokens", "max_tokens"))
FLAG_OF = dict((key, flag) for flag, key in CAPS)


def next_run_path(flow):
    """-> runs/<flow>-<day>-<n>.md, n one past the day's highest saved run.

    the run's own folder, <flow>-<day>-<time>, starts with the same stem, so
    counting everything that did made the first run of a day number two.
    """
    runs = state.RUNS
    runs.mkdir(parents=True, exist_ok=True)
    day = datetime.date.today().isoformat()
    stem = flow + "-" + day
    saved = re.compile(re.escape(stem) + r"-(\d+)\.md$")
    taken = [int(m.group(1)) for m in (saved.match(f.name)
                                       for f in runs.iterdir()
                                       if f.is_file()) if m]
    return runs / (stem + "-" + str(max(taken + [0]) + 1) + ".md")


def passes(trail, run, fm):
    """-> every pass the trail closed, in the shape the handoff is built
    from: its gates with their commands, its block, its outcome."""
    out = []
    for entry, outcome in trail.closed:
        if outcome == trace.WARM:
            continue
        said = ""
        if entry.file and (trail.folder / entry.file).is_file():
            said = (trail.folder / entry.file).read_text(encoding="utf-8")
        try:
            role = run.role_for(entry.step)
        except KeyError:
            role = entry.step
        commands = summary.gate_commands(fm, entry.step, said)
        out.append(summary.a_pass(entry.step, role,
                                  trace.seconds(entry.attempts), entry.handoff,
                                  summary._gates(entry.gates, commands,
                                                 summary.gate_names(
                                                     fm, entry.step)),
                                  entry.ungated, outcome, said,
                                  facts=summary.facts_of(entry.written or {},
                                                         run.workdir)))
    return out


def show(note):
    """the run's last words: the top of its handoff, then where the whole
    of it is. the path is the last line so a person or a script scrolling up
    from the end finds it first."""
    path, lines = note
    for line in summary.top(lines):
        print(line)
    print("handoff: " + str(path))


def remember(flow, run, run_id, ended, saved=None):
    """keep how this run ended for the next run of the flow on the same repo
    and task. `last_run` is the newest saved answer, so a run that stopped
    short keeps the one before it."""
    entry = {"run": run_id, "ended": ended,
             "at": datetime.datetime.now().isoformat(),
             "workdir": str(run.workdir)}
    last = saved or load_state(flow, run.workdir, run.task_text).get(
        "last_run")
    if last:
        entry["last_run"] = last
    save_state(flow, entry, run.workdir, run.task_text)


def finish(flow, fm, run, out, started, run_id, pick_up, leave, record=None,
           origin=None, signed=()):
    """the end of a run that got through every step. -> the exit code.

    what is saved and printed is the last step's answer without its HANDOFF
    block: the block is on the step's line and in handoff.md, which `leave`
    writes and which is the run's last word.
    """
    body = without(out.output)
    broken = promises.failures(body, fm.promises.invariants)
    for inv, detail in broken:
        print("promise broken: " + inv + " (" + detail + ")")
        write_index("BROKE  " + flow + "  " + inv)
    # a run that got here passed every gate its steps declare, so a promise
    # one of those gates shows has been checked, by a program, on the way
    gated = dict((inv, by) for inv, by in promises.shown_by(
        fm.steps, fm.promises.invariants) if by)
    skipped = [inv for inv in promises.unchecked(body, fm.promises.invariants)
               if inv not in gated]
    for inv in skipped:
        print("promise not checked: " + inv)

    shown = body
    aside = investigate.for_the_person(run.produced.get(investigate.STEP, ""))
    if aside:
        shown = shown.rstrip("\n") + "\n\n" + aside + "\n"
    path = next_run_path(flow)
    f = open(path, "w", encoding="utf-8")
    f.write(shown)
    f.close()
    print("saved " + str(path))

    remember(flow, run, run_id, "ok", saved=path.name)

    write_index(path.name + "  " + flow + "  " + str(len(steps(flow))) + " steps")

    if flow == "weekly-digest":
        for section in body.split("## "):
            if not section.strip():
                continue
            name = section.split("\n")[0]
            print("## " + name)
            for it in items(section):
                print("  - " + it)
            print("")
    elif flow == "ops-check":
        for line in by_severity(items(body)):
            print("- " + line)
    else:
        print(shown)

    if record is not None:
        record.finish(run.workdir, state.RUNS)
        record.save(run.budget)

    run.committer.finish(flow, run.task_text,
                         sorted((run.order.proof or {}).get("tests") or {}))
    for line in signed:
        print(line[2:])
    note = leave(signed=signed)
    # last, so that anything above that raises is this run's only end line
    # rather than a second one after an `ok`.
    # code-review runs per diff, several times an hour. it drowns the weekly
    # rollup and none of it is interesting a day later.
    if fm.get("journal", True):
        status = "ok"
        if pick_up:
            status = "ok (resumed)"
        if broken:
            status = "ok, " + str(len(broken)) + " promise(s) broken"
        if skipped:
            status = status + ", " + str(len(skipped)) + " promise(s) not checked"
        journal(fm["name"], status, started, run=run_id, saved=path.name,
                spend=run.budget.summary(), origin=origin,
                handoff=run_id + "/" + summary.FILE)
    show(note)
    return stops.EXIT_OK
