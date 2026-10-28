"""a flow run for the evals: its answer, its spend and why it stopped."""
import shutil
import tempfile
from pathlib import Path

from agentweft.flow.spec import REVIEWER
from agentweft.roles import resolver

from .config import config, steps
from .handoff import EMPTY
from .errors import Outage
from .prompts import flow_path
from . import (investigate, retro, router, ruling, stops, summary, trace,
               upkeep, wouldpass, wrongtest)
from .asking import lead_pass, rides, to_lead, worked_then_asked
from .fanout import run_fanout
from .gating import (LEFT_OUT, SIZED, and_forged, boundary_note, check_step,
                     forged_by, forged_first, gate_told, gate_why, off_task,
                     outage_why, police_line, preflight_after,
                     preflight_before, reviewers_on, risk_map)
from .run import Run

# the run id a scored case's retro is told, in place of a live run's
RUN_ID = "eval"


def run_once(flow, provider=None, task=None, trail=None, workdir=None):
    """run a flow and hand back what it produced, what it cost, and why it
    stopped short ("" when it did not). the eval harness wants the output, not
    the printing, and it wants to say which provider the whole thing runs on.

    it takes the steps a run started by hand takes: the preflight before and
    after a step that has one, the boundary note, and the retro at the end of
    a flow with `retro: true`.

    `trail` is a folder to write the run's steps.jsonl into, the same lines a
    run of `main` writes, for a case that asserts the steps it took.
    `workdir` is the place it works in, over the flow's own."""
    fm = config(flow)
    made = None
    told = None
    if trail is None and retro.on(fm):
        # the retro reads the run's lines, so a run asked for none keeps them
        # where nothing else sees them
        made = trail = Path(tempfile.mkdtemp())
        if getattr(provider, "trail", False) is None:
            # a recording names the folder the retro is pointed at as
            # <trail>, and this one is new every run
            told = provider
            told.trail = made
    try:
        return scored(flow, fm, provider, task, trail, workdir)
    finally:
        if told is not None:
            told.trail = None
        if made is not None:
            shutil.rmtree(made, ignore_errors=True)


def scored(flow, fm, provider, task, trail, workdir):
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    run = Run(flow, fm, by_role, provider=provider, task=task, workdir=workdir)
    route = router.Router(fm)
    run.ups = route.ups
    kept = trace.Trail(Path(trail)) if trail is not None else None
    if trail is not None:
        run.keep_in(Path(trail))
    ended = {}
    state = {"out": EMPTY, "step": steps(flow)[0], "came_from": None}

    def note(outcome, why=None, cause=None, to=None, output=None, case=None):
        taken = run.taken()
        if cause:
            ended.update(cause=cause, why=why or "", at=state["step"])
        if kept is None:
            return None
        step, out = state["step"], state["out"]
        entry = kept.open(step, taken, run.by_step.get(step, run.provider),
                          state["came_from"], output=output,
                          fanned=step == run.fan)
        entry.police = police_line(run, step)
        entry.gates = out.meta.get("gates", []) if output is not None else []
        entry.ungated = out.meta.get("ungated") if output is not None else None
        entry.handoff = out.block if output is not None else None
        entry.proved = output is not None and bool(out.meta.get("proved"))
        entry.conformance = out.meta.pop("conformance", None) \
            if output is not None else None
        entry.case = case
        kept.close(entry, outcome, why=why, to=to, cause=cause)
        return entry

    said = steps_of(flow, fm, run, route, trail, kept, state, note)
    if kept is not None and retro.on(fm):
        stopped = dict(ended) if ended.get("cause") else None
        stopped_why(Path(trail), stopped)
        retro.after(run, kept, RUN_ID, fm["name"], summary.outcome(stopped),
                    Path(trail), stopped)
    upkeep.tally(run, kept)
    return said


def stopped_why(folder, stopped):
    """write why.md beside the lines for a run that stopped short, as a cli
    run does, so the retro of a scored run reads why it stopped. no
    handoff.md is written: it names the provider that answered, which a
    replay names as itself, and the commit the place started from, made new
    each run, so a replayed retro could not send the prompt it recorded; what
    the retro needs of it is already in its record. one that cannot be
    written is said, and the retro reads what there is."""
    if not stopped:
        return
    try:
        (folder / "why.md").write_text(
            "stopped at " + stopped["at"] + "\ncause      " + stopped["cause"]
            + "\n\n" + stopped["why"] + "\n", encoding="utf-8")
    except OSError as e:
        print("why.md not written for the retro: " + type(e).__name__ + ": "
              + str(e))


def steps_of(flow, fm, run, route, trail, kept, state, note):
    """the step loop. `state` holds the step running, what it was handed
    and where from, for `note`; `kept` is the trail, None for no lines."""
    given = {}
    risk_text = ""
    sizing = {}
    case_for = None
    while state["step"]:
        step, out = state["step"], state["out"]
        said = reviewers_on(run, fm, step, sizing)
        if said and said[0] == SIZED:
            print("sized the change: " + said[1])
        elif said and said[0] == LEFT_OUT:
            print(said[1])
            state["step"] = route.next(step, EMPTY)
            continue
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
        held, unchecked, allowed = preflight_before(run, fm, step, out.output,
                                                    risk_text)
        if held:
            return held_by(note, run, out, step, held)
        run.order.watch(step, writes)
        run.look()
        try:
            if step == run.fan:
                out = run_fanout(run, out)
            else:
                extra, ranked = risk_map(run, fm, step)
                if ranked is not None:
                    risk_text = ranked
                out = run.step(step, previous=out, extra=extra)
            run.gate_said.pop(step, None)
        except Outage as e:
            why = and_forged(outage_why(e), run.forged.pop(step, ""))
            note("parked", why, stops.OUTAGE)
            return (out.output, run.budget, "provider outage at " + step
                    + ": " + why)
        state["out"] = out
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
            state["out"] = given.get(writer, EMPTY)
            state["came_from"] = step
            state["step"] = writer
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
            head, decided, question = to_lead(
                run, step, said[1], given, "a run of " + flow,
                folder=Path(trail) if trail is not None else None)
            theirs = run.taken()
            run.attempts = mine
            off = head.meta.get("off") if head is not None else ""
            if decided:
                note("asked", said[1].split("\n")[0], to=run.lead,
                     output=out.output)
            elif off:
                note("parked", off, stops.OFF_TASK, output=out.output)
            else:
                worked_then_asked(run, route, step, out)
                note("parked", question, stops.PARKED, output=out.output)
            if head is not None and kept is not None:
                run.attempts = theirs
                lead_pass(kept, run, head, step, decided)
            if decided:
                run.ruled[step] = decided
                state["out"] = handed
                continue
            if off:
                return (out.output, run.budget, "off task at " + step + ": "
                        + off)
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
        if failed and all(getattr(r, "host", "") for r in out.meta["gates"]
                          if not r.ok):
            note("gate failed", gate_why(out.meta["gates"]) + "; " + step
                 + " was not sent back: the fault is the machine's, not the"
                 " step's", stops.GATE, output=out.output)
            return (out.output, run.budget, "gate " + failed + " could not run"
                    " at " + step + ": the machine could not start a process,"
                    " twice")
        again = route.gate_back(step) if failed else None
        if again:
            note("gate failed", gate_why(out.meta["gates"]), to=again,
                 output=out.output)
            run.gate_said[again] = gate_told(out.meta["gates"])
            state["out"] = handed
            state["step"] = again
            continue
        if failed:
            note("gate failed", gate_why(out.meta["gates"]), stops.GATE,
                 output=out.output)
            return (out.output, run.budget,
                    "gate " + failed + " failed at " + step)
        run.order.passed(step)
        out.meta["proved"] = run.order.proven(step, out.meta["gates"],
                                              out.output)
        hot = preflight_after(run, step, out.output, risk_text, unchecked,
                              allowed)
        if hot:
            return held_by(note, run, out, step, hot, output=out.output)
        boundary_note(run, step, out.output,
                      Path(trail) if trail is not None else None)
        if blocked:
            note("gate failed", blocked, stops.GATE, output=out.output)
            return out.output, run.budget, blocked
        unproven = investigate.unrooted(step, out.output)
        if unproven:
            note("parked", unproven, stops.PARKED, output=out.output)
            return out.output, run.budget, "parked at " + step + ": " + unproven
        missed = wouldpass.read(out.output) \
            if honest and out.verdict != "redo" else None
        writer = route.missed_to(step) if missed else None
        if writer:
            routed = note(trace.ROUTED, "the tests would pass " + missed[0]
                          + ", back to " + writer + " for the case", to=writer,
                          output=out.output)
            run.gate_said[writer] = wouldpass.told(step, *missed)
            coder = route.on_redo.get(step)
            if coder:
                run.gate_said[coder] = wouldpass.then(writer, step, missed[0])
                case_for = {"writer": writer, "named": step, "coder": coder,
                            "seq": routed.seq if routed else None,
                            "missed": missed,
                            "before": wouldpass.ids(run.start),
                            "again": False}
            state["out"] = given.get(writer, EMPTY)
            state["came_from"] = step
            state["step"] = writer
            continue
        nxt = route.next(step, out)
        sent_back = out.verdict == "redo" and nxt
        already = noted = case = None
        if case_for and step == case_for["writer"]:
            named, coder = case_for["named"], case_for["coder"]
            new = wouldpass.added(case_for["before"], run.start)
            if new == [] and not sent_back and not case_for["again"]:
                case_for["again"] = True
                note("redo", step + " added no case for what " + named
                     + " named, back to " + step + " once more", to=step,
                     output=out.output)
                run.gate_said[step] = wouldpass.none_added(
                    named, *case_for["missed"])
                state["out"] = handed
                state["came_from"] = step
                continue
            wrong = case_for["missed"][0]
            ran = run.suite_of(coder) \
                if nxt == coder and not sent_back and new else []
            case = wouldpass.held(
                case_for, ran, wouldpass.alone(run, new)
                if ran and not wouldpass.green(ran) else None)
            case_for = None
            if not new and not sent_back:
                noted = wouldpass.no_case(step, named, coder, new)
                run.gate_said[coder] = wouldpass.unheld(named, wrong)
            elif wouldpass.green(ran):
                already = noted = wouldpass.passes_already(coder, ran)
                run.gate_said.pop(coder, None)
                nxt = route.next(named, EMPTY)
        note("redo" if sent_back else "ok", noted, to=nxt,
             output=out.output, case=case)
        if nxt and not sent_back and run.lens_for(nxt) \
                and run.role_for(step) == REVIEWER:
            state["out"] = handed
        if already:
            state["out"] = given.get(named, out)
        state["came_from"] = step
        state["step"] = nxt
    return state["out"].output, run.budget, ""


def held_by(note, run, out, step, held, output=None):
    """-> what `run_once` hands back for a step the preflight held."""
    cause, why, _ = held
    if cause == stops.REFUSED:
        note("refused", why, cause, output=output)
        return out.output, run.budget, "refused at " + step + ": " + why
    note("parked", why, cause, output=output)
    return out.output, run.budget, "parked at " + step + ": " + why
