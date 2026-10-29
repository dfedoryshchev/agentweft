"""the fanned step's run: its tasks side by side, joined into one answer."""
import concurrent.futures
import time

from .config import VERDICTS
from .handoff import EMPTY, Handoff, merge
from . import fan, manifest, state


def fanned_verdict(parts):
    """-> one verdict for every task of a fanned-out step: the first word the
    router cannot read, else redo if any task asked for one, else ok."""
    words = [p.verdict for p in parts]
    for word in words:
        if word not in VERDICTS:
            return word
    return "redo" if "redo" in words else "ok"


def run_fanout(run, plan):
    """-> the fanned step's tasks, one per TASK: block of the plan, run side
    by side, but for tasks that name the same file, which go in turn.

    a redo arrives here carrying the reviewer's words, not a plan. the tasks
    are still the planner's, so the plan that fed the first pass is kept and
    each of its tasks goes again with the reviewer's finding beside it.
    """
    began = time.time()
    role = run.role_for(run.fan)
    kept = getattr(run, "plan", None)
    back = EMPTY
    if plan.verdict == "redo" and kept is not None:
        back, plan = plan, kept
    else:
        run.plan = plan
    tasks = fan.tasks(plan.output)
    if not tasks:
        return Handoff(role, "", meta={
            "tasks": 0, "seconds": round(time.time() - began, 1),
            "why": run.fan + " is fanned out one task per " + fan.TASK
                   + " block, and what " + plan.role + " handed it has none"})

    done = getattr(run, "reuse", {}) if back is EMPTY else {}
    run.reuse = {}
    getattr(run, "forged", {}).pop(run.fan, None)
    folder = getattr(run, "folder", None)
    own = state.RUNS
    got = {}
    windows = []
    # a fan carried on from a run that stopped in it is held to the place as
    # the first leg found it: a stray file that leg wrote is already in this
    # leg's own before and after
    carried = getattr(run, "fan_start", None)
    run.fan_start = None
    if folder is not None:
        fan.save(folder, carried or fan.hashes(run.workdir, own))

    def one(t, before):
        kept = done.get((t.n, t.text))
        if kept is not None:
            return Handoff(role, kept["output"], kept["verdict"],
                           meta={"asked": kept["asked"]}), before
        window = fan.Window(t, time.monotonic(),
                            before or fan.hashes(run.workdir, own))
        try:
            part = run.step(run.fan, previous=back,
                            extra="\n\nyour task, only this one:\n\n"
                            + t.text + "\n\nchange no file but the ones"
                            " under " + fan.FILES, task=t.n)
        finally:
            window.after = fan.hashes(run.workdir, own)
            window.ended = time.monotonic()
            windows.append(window)
        if folder is not None and part:
            manifest.task_done(folder, run.fan, t.n, t.text, part)
        return part, window.after

    def in_turn(turn):
        before = None
        for t in turn:
            got[t.n], before = one(t, before)

    # three workers and two tasks means an idle thread and a pool i paid to
    # build. no point.
    # planner 1, workers N, reviewer 1. the fanned out step is the only one
    # that gets to be plural, and it says so itself.
    turns = fan.turns(tasks)
    width = min(run.width_for(run.fan), len(turns)) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        list(pool.map(in_turn, turns))
    parts = [got[t.n] for t in tasks]
    overlap = "; ".join(said for said in (
        fan.check(windows),
        fan.since(carried, fan.hashes(run.workdir, own), tasks, run.fan)
        if carried is not None else "") if said)
    if folder is not None and not overlap:
        fan.done(folder)
    out = Handoff(role, "\n\n".join(p.output for p in parts),
                  verdict=fanned_verdict(parts),
                  meta={"tasks": len(tasks),
                        "seconds": round(time.time() - began, 1),
                        "asked": any(p.meta.get("asked") for p in parts),
                        "allowed": next((p.meta["allowed"] for p in parts
                                         if p.meta.get("allowed")), ()),
                        "rulings": run.rulings(),
                        "overlap": overlap},
                  block=merge(p.block for p in parts),
                  carried=list(run.constraints),
                  asked=list(run.questions))
    # every task went through Run.step, so what it recorded is whichever one
    # finished last. the joined output is what the step actually produced.
    run.produced[run.fan] = out.output
    return out
