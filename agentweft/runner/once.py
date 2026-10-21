"""a flow run for the evals: its answer, its spend and why it stopped."""
from pathlib import Path

from agentweft.roles import resolver

from .config import config, steps
from .handoff import EMPTY
from .errors import Outage
from .prompts import flow_path
from . import investigate, router, ruling, stops, trace, wrongtest
from .asking import lead_pass, rides, to_lead, worked_then_asked
from .fanout import run_fanout
from .gating import (and_forged, check_step, forged_by, forged_first,
                     gate_told, gate_why, off_task, outage_why, police_line)
from .run import Run


def run_once(flow, provider=None, task=None, trail=None, workdir=None):
    """run a flow and hand back what it produced, what it cost, and why it
    stopped short ("" when it did not). the eval harness wants the output, not
    the printing, and it wants to say which provider the whole thing runs on.

    `trail` is a folder to write the run's steps.jsonl into, the same lines a
    run of `main` writes, for a case that asserts the steps it took.
    `workdir` is the place it works in, over the flow's own."""
    fm = config(flow)
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    run = Run(flow, fm, by_role, provider=provider, task=task, workdir=workdir)
    route = router.Router(fm)
    run.ups = route.ups
    kept = trace.Trail(trail) if trail is not None else None
    if trail is not None:
        run.keep_in(Path(trail))
    out = EMPTY
    step = steps(flow)[0]
    came_from = None
    given = {}

    def note(outcome, why=None, cause=None, to=None, output=None):
        taken = run.taken()
        if kept is None:
            return
        entry = kept.open(step, taken, run.by_step.get(step, run.provider),
                          came_from, output=output, fanned=step == run.fan)
        entry.police = police_line(run, step)
        entry.gates = out.meta.get("gates", []) if output is not None else []
        entry.ungated = out.meta.get("ungated") if output is not None else None
        entry.handoff = out.block if output is not None else None
        entry.proved = output is not None and bool(out.meta.get("proved"))
        kept.close(entry, outcome, why=why, to=to, cause=cause)

    while step:
        refused = run.refused(step)
        if refused:
            note("refused", refused, stops.REFUSED)
            return out.output, run.budget, "refused at " + step + ": " + refused
        handed = out
        given[step] = handed
        writes = run.writes_for(step)
        refused = run.order.before(step, writes)
        if refused:
            note("refused", refused, stops.REFUSED)
            return out.output, run.budget, "refused at " + step + ": " + refused
        waits = run.budget.ahead(run.calls_for(step, out))
        if waits:
            note("parked", waits[1], stops.BUDGET)
            return (out.output, run.budget, "over budget at " + step + ": "
                    + waits[1])
        run.order.watch(step, writes)
        run.look()
        try:
            if step == run.fan:
                out = run_fanout(run, out)
            else:
                out = run.step(step, previous=out)
            run.gate_said.pop(step, None)
        except Outage as e:
            why = and_forged(outage_why(e), run.forged.pop(step, ""))
            note("parked", why, stops.OUTAGE)
            return (out.output, run.budget, "provider outage at " + step
                    + ": " + why)
        run.wrote_tests(step)
        forged = forged_first(run, step, out)
        fenced = run.fenced(step)
        if fenced:
            fenced = and_forged(fenced, forged)
            note("parked", fenced, stops.PARKED, output=out.output)
            return out.output, run.budget, "fenced at " + step + ": " + fenced
        off = off_task(run, step, Path(trail) if trail is not None else None)
        if off:
            off = and_forged(off, forged)
            note("parked", off, stops.OFF_TASK, output=out.output)
            return out.output, run.budget, "off task at " + step + ": " + off
        overlap = out.meta.get("overlap")
        if overlap:
            note("failed", overlap, stops.OVERLAP, output=out.output)
            return (out.output, run.budget, "tasks overlap at " + step + ": "
                    + overlap)
        if not out:
            why = and_forged(out.meta.get("why") or "nothing came out of "
                             + step, forged)
            note("failed", why, stops.NO_ANSWER, output=out.output)
            return out.output, run.budget, why
        honest = not forged_by(run, step)
        said = ruling.conflict_of(out.output, run.workdir, run.start) \
            if honest else None
        if said and not said[1]:
            note("conflict", said[0], stops.CONFLICT, output=out.output)
            return (out.output, run.budget, "spec conflict at " + step + ": "
                    + said[0].split("\n")[0][len("NEEDS: "):])
        wrong = wrongtest.judge(out.output, step, run, route) \
            if honest else None
        if wrong and wrong[0] == "back":
            _, writer, tests, told = wrong
            note("redo", ", ".join(tests) + (" is" if len(tests) == 1
                                             else " are")
                 + " wrong, back to " + writer, to=writer, output=out.output)
            run.wrong_back(step, writer, tests, told)
            out = given.get(writer, EMPTY)
            came_from = step
            step = writer
            continue
        if wrong:
            note("parked", wrong[1], stops.PARKED, output=out.output)
            return (out.output, run.budget, "parked at " + step
                    + " for a ruling: " + wrong[1].split("\n")[0])
        if honest:
            rides(step, out)
        said = ruling.asked_of(out.output, run.workdir, out.verdict,
                               out.meta.get("allowed"), run.start) \
            if honest else None
        if said and said[0] == ruling.DECLINED:
            note("refused", said[1], stops.DECLINED, output=out.output)
            return out.output, run.budget, ""
        if said:
            mine = run.taken()
            head, decided, question = to_lead(run, step, said[1], given,
                                              "a run of " + flow)
            theirs = run.taken()
            run.attempts = mine
            if decided:
                note("asked", said[1].split("\n")[0], to=run.lead,
                     output=out.output)
            else:
                worked_then_asked(run, route, step, out)
                note("parked", question, stops.PARKED, output=out.output)
            if head is not None and kept is not None:
                run.attempts = theirs
                lead_pass(kept, run, head, step, decided)
            if decided:
                run.ruled[step] = decided
                out = handed
                continue
            return (out.output, run.budget, "parked at " + step
                    + " for a ruling: " + question.split("\n")[0])
        failed, blocked = check_step(run, route, step, out)
        spec_asks = out.meta.pop("spec_ruling", None) or \
            out.meta.pop("test_ruling", None)
        if spec_asks:
            note("parked", spec_asks[1], stops.PARKED, output=out.output)
            return (out.output, run.budget, "parked at " + step
                    + " for a ruling: " + spec_asks[1].split("\n")[0])
        held = out.meta.pop("conflict", None)
        if held:
            note("conflict", held[1], stops.CONFLICT, output=out.output)
            return out.output, run.budget, "spec conflict at " + step + ": " \
                + held[0][len("spec conflict: "):]
        again = route.gate_back(step) if failed else None
        if again:
            note("gate failed", gate_why(out.meta["gates"]), to=again,
                 output=out.output)
            run.gate_said[again] = gate_told(out.meta["gates"])
            out = handed
            step = again
            continue
        if not failed:
            run.order.passed(step)
            out.meta["proved"] = run.order.proven(step, out.meta["gates"],
                                                  out.output)
        if failed or blocked:
            why = gate_why(out.meta["gates"]) if failed else blocked
            note("gate failed", why, stops.GATE, output=out.output)
            if failed:
                return (out.output, run.budget,
                        "gate " + failed + " failed at " + step)
            return out.output, run.budget, blocked
        unproven = investigate.unrooted(step, out.output)
        if unproven:
            note("parked", unproven, stops.PARKED, output=out.output)
            return out.output, run.budget, "parked at " + step + ": " + unproven
        nxt = route.next(step, out)
        note("redo" if out.verdict == "redo" and nxt else "ok", to=nxt,
             output=out.output)
        came_from = step
        step = nxt
    return out.output, run.budget, ""
