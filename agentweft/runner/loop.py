"""the step loop of a run a person started, and every way it stops."""
import sys
import time
import traceback

from agentweft.flow.spec import REVIEWER
from agentweft.guardrails import (baseline, police, redorder, signoff, skips,
                                  snapshot)
from agentweft.guardrails.budget import REACHING
from agentweft.guardrails import blocks, sacrifice
from agentweft.orchestrate import decisions, park

from .config import steps
from .handoff import EMPTY
from . import investigate
from . import (chain, leftred, manifest, resume, retro, ruling, warm)
from . import ending
from . import state
from . import stops
from . import summary
from . import trace
from . import worktrees
from . import wrongtest
from .asking import (asked_file, lead_pass, rides, to_lead,
                     worked_then_asked)
from .ending import (FLAG_OF, cap_of, finish, passes, remember,
                     resume_command, show, write_index)
from .fanout import run_fanout
from .gating import (NEWLINE, and_forged, boundary_note, check_step,
                     forged_by, forged_first, gate_told, gate_why,
                     held_after_stop, nothing_why, off_task, outage_why,
                     police_line, preflight_after, preflight_before, risk_map,
                     sent_back_times, since, times)


def roles_of(run, todo):
    out = {}
    for step in todo:
        try:
            out[step] = run.role_for(step)
        except KeyError:
            out[step] = step
    return out


def completion(record, order):
    passed = [s for s in record.data["steps"] if s["state"] == manifest.PASSED]
    return str(len(passed)) + "/" + str(len(order)) + " steps"


def go(leg):
    """run the steps from where the setup left off. -> the exit code."""
    flow, fm, run, route, record = leg.flow, leg.fm, leg.run, leg.route, \
        leg.record
    folder, run_id, started, clock = leg.folder, leg.run_id, leg.started, \
        leg.clock
    made, origin, earlier, asked = leg.made, leg.origin, leg.earlier, leg.asked
    pick_up, order, todo, start = leg.pick_up, leg.order, leg.todo, leg.start
    found, seen, out, came_from = leg.found, leg.seen, leg.out, leg.came_from
    uncut = leg.uncut
    timings = []
    risk_text = ""
    plan = blocks.Plan(run.budget, todo, roles_of(run, todo),
                       blocks.history(state.RUNS, flow, run.workdir,
                                      skip=run_id))
    run.cut = {}

    def cut_for(chosen):
        """leave the chosen steps out of the run, each as a named skip."""
        for name, cut, why in chosen:
            reason = sacrifice.BUDGET + why
            run.skipped[name] = reason
            for one in cut:
                run.cut[one] = name
                plan.drop(one, reason)
                print("cut " + one + ": " + reason)
            decisions.record(folder, name + " cut for the budget", reason
                             + NEWLINE + "sacrifice: in flow.yaml lists it, and"
                             " the steps ahead did not fit what the cap"
                             " leaves: " + ", ".join(cut) + " did not run.")
        if chosen:
            skips.save(folder, run.skipped)
            plan.write(folder)

    cut_for(sacrifice.choose(fm, plan.steps, plan.short, run.skipped)[0])
    for name in [n for n in uncut if n not in run.skipped]:
        decisions.record(folder, name + " runs: no longer cut for the budget",
                         pick_up + " cut it; planned again against the cap"
                         " this run has, the steps ahead fit without the cut.")
    plan.write(folder)
    if plan.warning():
        print(plan.warning())
    trail = trace.Trail(folder,
                        after=trace.last_seq(state.RUNS / pick_up)
                        if pick_up else 0, plan=plan)
    if fm.get("journal", True):
        ending.journal(fm["name"], stops.RUNNING, started, run=run_id,
                       origin=origin)
    step = todo[0]
    used = run.provider
    wrote = set()
    # the place as it was before the step running now, by content, to tell a
    # stop that left the step's work in the tree from one that left none
    before = {}
    # what each step was handed, for a step a wrong test sends the work back to
    given = {}
    # a run parked before a step is carried on by the person who read why, so
    # that step is not checked again on what it was handed the first time round
    cleared = None
    if found and (found.data.get("stopped") or {}).get("step") == start \
            and found.data["stopped"].get("cause") == stops.PARKED \
            and (found.step(start) or {}).get("state") == manifest.NOT_RUN:
        cleared = start

    def leave(stopped=None, needs=None, signed=()):
        """write the run's handoff.md from what the runner knows, and hand
        back (its path, its lines)."""
        # a warm call still in flight is ended, and charged, before anything
        # is written down
        warm.stop_all()
        ran = passes(trail, run, fm)
        warm.leftover(run, trail)
        record.ended(summary.outcome(stopped, summary.unproven(
            list(earlier) + ran)))
        record.data[chain.FIELD] = trail.head()
        record.save(run.budget)
        began = time.time()
        left = leftred.check(
            run.start, fm, leftred.chosen(fm, sys.argv),
            named=leftred.named_in(run.start, stopped.get("question"))) \
            if stopped else None
        if left and (left["red"] or left["named"]):
            run.suite_baseline()
        if left is not None:
            trail.timed("left-red", stopped["at"], since(began),
                        not left["red"] and not left["named"])
        known = run.baseline if run.baseline and "tests" in run.baseline \
            else None
        left = baseline.label(left, known)
        if left is not None:
            left = held_after_stop(run, left, folder)
        police.keep(folder, run.shadowed, run.told_read, run.shadow_read,
                    run.shadow_unread)
        hits, read, seen, unseen = police.kept_before(
            manifest.legs(state.RUNS / pick_up)[0] if pick_up else [])
        hits, seen = hits + run.shadowed, seen + run.shadow_read
        unseen += run.shadow_unread
        told = police.read_lines(read + run.told_read, str(run.workdir))
        lines = summary.build(run_id, fm["name"], asked, ran,
                              run.tree.changes(), run.decided(),
                              run.budget.summary(), stopped=stopped,
                              needs=needs, command=resume_command(flow, run_id, run.caps),
                              before=earlier, started=started,
                              found=run.produced.get(investigate.STEP, ""),
                              order=run.order.said(), left=left,
                              suite=baseline.lines(known),
                              chained=record.data[chain.FIELD],
                              skipped=skips.said(run.skipped),
                              kept=run.committer.said(),
                              worktree=worktrees.lines(
                                  made, run.committer.branch),
                              headline=worktrees.headline(made),
                              signed=signed,
                              spec_files=fm.get("spec_files"),
                              clock={"wall": since(clock),
                                     "gates": trail.gate_seconds},
                              held=not redorder.ordered(fm)
                              or bool(run.order.skip or run.order.proof),
                              proof=run.order.proof,
                              shadowed=hits,
                              told=told,
                              police=police.handoff_lines(
                                  run.policing, hits, seen, told, unseen))
        path = summary.write(state.RUNS / run_id, lines)
        if retro.on(fm):
            retro.after(run, trail, run_id, fm["name"],
                        record.data["outcome"], folder, stopped,
                        state.RUNS / pick_up if pick_up else None)
            record.data[chain.FIELD] = trail.head()
            record.save(run.budget)
        return path, lines

    def stop(cause, why, outcome, entry=None, index=None, waiting=None,
             told=None, at=None, handed=None, question=None, replayed=False,
             checked=(), worked=None, stopped_for=None, asked=None):
        """every way a run ends short goes out through here: the step's line
        and why.md say why, handoff.md says all of it with a "needs you"
        section when someone is waited for, and the journal line carries the
        cause, what the run spent and where the handoff is. `at` is the step
        the run stopped at, when that is not the one that ran. `handed` is
        the step whose output `at` was handed, for a park before `at` ran:
        the step stays not run, so carrying on starts at it. `question` is
        what the step asked instead of doing the work: the run waits for a
        ruling, and carrying on runs the step again with the answer.
        `checked` is (check, passed, what it found) for each check the
        runner made on the answer outside its gates. `worked` is what the
        gates of a step that changed the place before it asked said of it
        ("" passed), None when it changed nothing. `stopped_for` is what a
        step that did the work did that its gates stop the run on, for a
        question the runner asks rather than the step. `asked` is what the
        record keeps of a question the runner asks, so an answer to it is
        known by the record and not by the question's words.

        -> the exit code.
        """
        at = at or step or came_from or todo[-1]
        if entry is None and step:
            entry = trail.open(step, run.taken(), used, came_from,
                               fanned=step == run.fan)
        if entry is not None and entry.step in before:
            entry.changed = before[entry.step] != snapshot.fingerprint(
                run.workdir, own=state.RUNS)
        if entry is not None:
            trail.close(entry, outcome, why=why, cause=cause)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "why.md").write_text(
            "stopped at " + at + NEWLINE + "cause      " + cause + NEWLINE
            + ("kind       " + ruling.ASKED + NEWLINE if question else "")
            + NEWLINE + why + NEWLINE, encoding="utf-8")
        if question:
            (folder / "question.md").write_text(question + NEWLINE,
                                                encoding="utf-8")
        parked = cause in (stops.PARKED, stops.OFF_TASK)
        if handed:
            kept = manifest.NOT_RUN
        elif question:
            kept = manifest.RULING
        elif cause == stops.DECLINED:
            kept = manifest.PASSED
        else:
            kept = manifest.PARKED if parked else manifest.FAILED
        record.mark(at, kept,
                    run_id if at in wrote else None,
                    resume.step_output(run_id, at) if at in wrote else None)
        record.stop(at, cause, why, run.workdir, state.RUNS,
                    question=question, asked=asked)
        record.save(run.budget)
        remember(flow, run, run_id, stops.status(cause, at))
        done = [(name, secs) for name, secs, _ in timings]
        if question:
            conflict = cause == stops.CONFLICT
            did = run.start.product_changed() \
                if run.start is not None and worked is None \
                and not conflict and not stopped_for else []
            needs = park.lines(at, waiting, done,
                               resume.remaining(steps(flow), at),
                               resume_command(flow, run_id, run.caps),
                               question=question, conflict=conflict,
                               replayed=replayed, worked=worked,
                               stopped_for=stopped_for, run_did=did)
            print("stopped at " + at + " on a spec conflict" if conflict
                  else "parked at " + at + ", waiting for a ruling")
        elif cause == stops.DECLINED:
            needs = park.refused(at, why, done)
        elif waiting:
            again = cause == stops.OUTAGE
            left = (resume.remaining if again or handed else resume.after)(
                steps(flow), at)
            needs = park.lines(at, waiting, done, left,
                               resume_command(flow, run_id, run.caps),
                               why=why + "," if told is None else told,
                               again=again, handed=handed)
            print("parked at " + at + ", waiting for " + waiting)
        else:
            told = why
            carry = resume_command(flow, run_id, run.caps)
            if cause == stops.BUDGET:
                key = cap_of(why)
                carry = resume_command(flow, run_id, run.caps, raise_cap=key)
                told = (why + NEWLINE + "raise the cap to carry on: put the new"
                        " cap where the command below says <n>"
                        + ("; " + FLAG_OF[key] + " was given on the command"
                           " line, so it holds until a higher one is"
                           if key in run.caps else ", or raise " + key
                           + " in " + flow + "/flow.yaml and leave the flag"
                           " off") + ". a resume starts at what this run"
                        " spent.")
            needs = park.lines(at, None, done, resume.remaining(steps(flow), at),
                               carry, why=told, cause=cause, handed=handed)
        note = leave({"cause": cause, "why": why, "at": at,
                      "question": question, "checked": list(checked)}, needs)
        if index:
            write_index(index)
        ending.journal(fm["name"], stops.status(cause, at), started,
                       run=run_id, cause=cause, spend=run.budget.summary(),
                       why=why, origin=origin,
                       handoff=run_id + "/" + summary.FILE)
        show(note)
        return stops.exit_code(cause)

    def switch_on(at, entry, outcome, said, why):
        """`auto` turns the cause step on after `at`, once, and says why."""
        print("the cause step was switched on after " + at)
        trail.close(entry, outcome, why=said, to=investigate.STEP)
        record.mark(at, manifest.REDO, run_id, out.output)
        record.save(run.budget)
        decisions.record(folder, "the cause step was switched on after " + at,
                         why)
        return investigate.STEP

    def near(step, waits):
        """-> whether the run goes on past the token cap's warning: the
        flow's sacrifice list makes the steps ahead fit what is left. a
        plan that only shares the cap out has no estimate to cut on."""
        if not sacrifice.listed(fm) or waits[0] != REACHING \
                or plan.source == blocks.SHARES_SOURCE:
            return False
        ahead = [s for s in order[order.index(step):] if s in plan.steps]
        chosen, short = sacrifice.choose(
            fm, ahead, plan.short, run.skipped)
        if short:
            return False
        cut_for([(name, cut, waits[1] + "; " + why)
                 for name, cut, why in chosen])
        return True

    switched = False
    seen_head = (run.signoff or {}).get("head")
    try:
        while step:
            before.clear()
            if step in run.cut:
                step = route.next(step, EMPTY)
                continue
            used = run.by_step.get(step, run.provider)
            refused = run.refused(step)
            if refused:
                print("refused at " + step + ": " + refused)
                return stop(stops.REFUSED, refused, "refused",
                            entry=trail.open(step, [], used, came_from),
                            index="REFUSED  " + flow + "  " + step)
            writes = run.writes_for(step)
            refused = run.order.before(step, writes)
            if refused:
                print("refused at " + step + ": " + refused)
                return stop(stops.REFUSED, refused, "refused",
                            entry=trail.open(step, [], used, came_from),
                            index="REFUSED  " + flow + "  " + step)
            waits = run.budget.ahead(run.calls_for(step, out))
            if waits and near(step, waits):
                if step in run.cut:
                    continue
                waits = None
            if waits:
                why = (waits[0] + ", completion " + completion(record, order)
                       + ", " + waits[1])
                print("paused before " + step + ": " + why)
                return stop(stops.BUDGET, why, "parked",
                            index="PARKED  " + flow + "  at " + step,
                            handed=came_from or "the task")
            signed, seen_head = signoff.ahead(run.workdir, run.signoff,
                                              seen_head, step)
            if signed is not None and signed.state in (signoff.CONFLICT,
                                                       signoff.UNCHECKED):
                cause = stops.MOVED if signed.state == signoff.CONFLICT \
                    else stops.UNCHECKED
                print("not signed off before " + step + ": " + signed.why)
                return stop(cause, signed.why, "stopped",
                            index=("MOVED  " if cause == stops.MOVED
                                   else "UNCHECKED  ") + flow + "  "
                            + signed.target,
                            handed=came_from or "the task")
            if signed is not None and signed.state == signoff.MERGES:
                print("sign-off before " + step + ": " + signed.target
                      + " moved to " + signed.head + ", and the change still"
                      " merges onto it")
            held, unchecked, allowed = preflight_before(
                run, fm, step, out.output, risk_text, cleared)
            if held and held[0] == stops.REFUSED:
                return stop(held[0], held[1], "refused",
                            index="REFUSED  " + flow + "  " + held[2])
            if held:
                return stop(held[0], held[1], "parked",
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", handed=came_from or "the task")
            cleared = None
            run.order.watch(step, writes)
            print("started " + step)
            handed = out
            given[step] = handed
            run.look()
            before[step] = snapshot.fingerprint(run.workdir, own=state.RUNS)
            if step == run.fan:
                out = run_fanout(run, out)
            else:
                extra, ranked = risk_map(run, fm, step)
                if ranked is not None:
                    risk_text = ranked
                if seen and step == "planner.md":
                    extra = "\n\nthe last run was " + str(seen) + \
                        ". only tell me what is different since then."
                out = run.step(step, previous=out, extra=extra)
            run.gate_said.pop(step, None)
            step_dir = state.RUNS / run_id
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / step).write_text(out.output, encoding="utf-8")
            wrote.add(step)
            run.wrote_tests(step)
            timings.append((step, out.meta.get("seconds", 0),
                            out.meta.get("cached")))
            entry = trail.open(step, run.taken(), used, came_from,
                               output=out.output, fanned=step == run.fan)
            entry.handoff = out.block

            forged = forged_first(run, step, out)
            if forged:
                entry.gates = out.meta["gates"]
                entry.ungated = False
            fenced = run.fenced(step)
            if fenced:
                fenced = and_forged(fenced, forged)
                print("fenced at " + step + ": " + fenced)
                return stop(stops.PARKED, fenced, "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user")
            off = off_task(run, step, state.RUNS / run_id)
            entry.police = police_line(run, step)
            if off:
                off = and_forged(off, forged)
                print("off task at " + step + ": " + off)
                return stop(stops.OFF_TASK, off, "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user")
            overlap = out.meta.get("overlap")
            if overlap:
                print("tasks overlap at " + step + ": " + overlap)
                return stop(stops.OVERLAP, overlap, "failed", entry,
                            index="FAILED  " + flow + "  at " + step)

            if not out:
                # an empty answer is checked before any gate: a gate handed
                # nothing reports on nothing, and that report reads as the
                # reason the run stopped
                why = out.meta.get("why")
                blamed = None
                if (out.meta.get("tasks") == 0 and came_from
                        and handed.verdict != "redo"):
                    # the fanned step ran over nothing; what it was handed is
                    # where the run went wrong, and where a resume starts
                    blamed = came_from
                    why = "no tasks: " + why
                print("run stopped at " + (blamed or step)
                      + (": " + why if why else ""))
                return stop(stops.NO_ANSWER,
                            and_forged(why or nothing_why(step, entry),
                                       forged), "failed", entry,
                            index="FAILED  " + flow + "  at "
                            + (blamed or step), at=blamed)

            honest = not forged_by(run, step)
            said = ruling.conflict_of(out.output, run.workdir, run.start) \
                if honest else None
            if said and not said[1]:
                print(step + " found the request contradicts the spec")
                return stop(stops.CONFLICT, "spec conflict: "
                            + said[0].split(NEWLINE)[0][len("NEEDS: "):],
                            "conflict", entry,
                            index="CONFLICT  " + flow + "  at " + step,
                            question=said[0], checked=[(
                                "quote check", True, "the quote at "
                                + ", ".join(ruling.authorised(said[0]))
                                + " is there as the run found it")],
                            asked=ruling.conflict_asked(
                                out.output, run.workdir, run.start))
            wrong = wrongtest.judge(out.output, step, run, route) \
                if honest else None
            if wrong and wrong[0] == "back":
                _, writer, tests, told = wrong
                said = ", ".join(tests) + (" is" if len(tests) == 1
                                           else " are")
                print(step + " says " + said + " wrong, sent back to "
                      + writer)
                trail.close(entry, "redo", why=said + " wrong, back to "
                            + writer, to=writer)
                record.mark(step, manifest.REDO, run_id, out.output)
                record.save(run.budget)
                run.wrong_back(step, writer, tests, told)
                out = given.get(writer, EMPTY)
                came_from = step
                step = writer
                continue
            if wrong:
                print(step + " says a test the run will not rewrite is wrong")
                return stop(stops.PARKED, "needs a ruling: "
                            + wrong[1].split(NEWLINE)[0][len("NEEDS: "):],
                            "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=wrong[1])

            raw = out.output
            if honest and rides(step, out):
                entry.handoff = out.block
                (step_dir / step).write_text(out.output, encoding="utf-8")
                (step_dir / asked_file(step)).write_text(raw,
                                                         encoding="utf-8")
                if entry.file:
                    (trail.folder / entry.file).write_text(out.output,
                                                           encoding="utf-8")
            said = ruling.asked_of(out.output, run.workdir, out.verdict,
                                   out.meta.get("allowed"), run.start) \
                if honest else None
            if said and said[0] == ruling.DECLINED:
                print("refused at " + step + ": " + said[1])
                return stop(stops.DECLINED, said[1], "refused", entry)
            if said:
                head, decided, question = to_lead(run, step, said[1], given,
                                                  run_id)
                if head is not None:
                    lead_pass(trail, run, head, step, decided)
                if decided:
                    print(run.lead + " decided what " + step + " asked, and "
                          + step + " runs again with it")
                    trail.close(entry, "asked",
                                why=said[1].split(NEWLINE)[0], to=run.lead)
                    record.mark(step, manifest.REDO, run_id, out.output)
                    record.save(run.budget)
                    run.ruled[step] = decided
                    out = handed
                    continue
                worked = worked_then_asked(run, route, step, out,
                                           run_dir=step_dir)
                if worked is not None:
                    entry.gates = out.meta.get("gates", [])
                    entry.ungated = out.meta.get("ungated")
                print(step + (" asks for a ruling" if worked is None
                              else " did the work, then asked for a ruling"))
                return stop(stops.PARKED, "needs a ruling: "
                            + said[1].split(NEWLINE)[0][len("NEEDS: "):],
                            "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=question, worked=worked)

            failed, blocked = check_step(run, route, step, out,
                                         run_dir=step_dir)
            entry.gates = out.meta.get("gates", [])
            entry.ungated = out.meta.get("ungated")
            spec_asks = out.meta.pop("spec_ruling", None)
            if spec_asks:
                print(step + " removed or rewrote a line of the spec")
                return stop(stops.PARKED, spec_asks[0], "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=spec_asks[1],
                            stopped_for="removed or rewrote spec lines the"
                            " run started with", asked=spec_asks[2])
            test_asks = out.meta.pop("test_ruling", None)
            if test_asks:
                print(step + " changed a test the run started with")
                return stop(stops.PARKED, test_asks[0], "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=test_asks[1],
                            stopped_for="changed tests the run started with",
                            asked=test_asks[2])
            held = out.meta.pop("conflict", None)
            if held:
                print(step + " turned a test the run started with red")
                return stop(stops.CONFLICT, held[0], "conflict", entry,
                            index="CONFLICT  " + flow + "  at " + step,
                            question=held[1], replayed=True, checked=[(
                                "start tests", False, "run again against "
                                + step + ", not all green as they were")])
            if failed:
                # nothing goes past a failed gate: the step goes again with
                # what the gate said, and once the cap is spent the run stops
                again = route.gate_back(step)
                why = "" if again or switched else investigate.wanted(
                    fm, step, failed=failed)
                if why:
                    step = switch_on(step, entry, "gate failed",
                                     gate_why(out.meta["gates"]), why)
                    switched = True
                    out = handed
                    continue
                if again:
                    print("gate " + failed + " failed at " + step
                          + ", sent back to " + again)
                    trail.close(entry, "gate failed",
                                why=gate_why(out.meta["gates"]), to=again)
                    record.mark(step, manifest.REDO, run_id, out.output)
                    record.save(run.budget)
                    run.gate_said[again] = gate_told(out.meta["gates"])
                    out = handed
                    step = again
                    continue
                print("gate failed at " + step + ", stopping")
                return stop(stops.GATE, gate_why(out.meta["gates"])
                            + sent_back_times(route, step),
                            "gate failed", entry,
                            index="GATE  " + flow + "  " + failed + " at "
                            + step)
            run.order.passed(step)
            if run.order.proven(step, entry.gates, out.output):
                entry.proved = True
                run.order.save(folder)
                chain.wrote(folder)

            hot = preflight_after(run, step, out.output, risk_text, unchecked,
                                  allowed)
            if hot and hot[0] == stops.REFUSED:
                return stop(hot[0], hot[1], "refused", entry,
                            index="REFUSED  " + flow + "  " + hot[2])
            if hot:
                return stop(hot[0], hot[1], "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user")
            boundary_note(run, step, out.output, state.RUNS / run_id)

            if blocked:
                print(blocked + " - not going on")
                return stop(stops.GATE, blocked, "gate failed", entry,
                            index="FAILED  " + flow + "  at " + step)

            unproven = investigate.unrooted(step, out.output)
            if unproven:
                print(unproven)
                return stop(stops.PARKED, unproven, "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user")

            why = "" if switched else investigate.wanted(fm, step,
                                                         block=out.block)
            if why:
                step = switch_on(step, entry, "redo", why, why)
                switched = True
                out = handed
                continue

            stuck = route.out_of_redos(out)
            nxt = route.next(step, out)
            waiting = run.pause_for(step) or ("user" if stuck else None)
            if out.verdict == "redo" and nxt and not stuck:
                print("sent back to " + nxt)
            elif stuck or (waiting and nxt):
                # parking is a person letting the work through, so there has to be
                # work to let through: never on the last step, which has nothing
                # behind it to hold up. a redo takes the branch above instead - the
                # work is going round again, so there is nothing to let through
                # yet. a redo with none left is the exception: the reviewer did
                # not let it through, and the last step is where it most often
                # says so.
                why = ""
                if stuck:
                    why = (step + " still asks for a redo, and the work has gone"
                           " back " + times(route.cap) + " already (send_backs: "
                           + str(route.cap) + "),")
                return stop(stops.PARKED,
                            why.rstrip(",") or "waiting for " + waiting,
                            "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting=waiting, told=why)
            sent_back = out.verdict == "redo" and nxt
            if step in before:
                entry.changed = before[step] != snapshot.fingerprint(
                    run.workdir, own=state.RUNS)
            trail.close(entry, "redo" if sent_back else "ok", to=nxt)
            record.mark(step, manifest.REDO if sent_back else manifest.PASSED,
                        run_id, out.output)
            record.save(run.budget)
            run.committer.step(step, flow)
            if nxt and not sent_back and run.lens_for(nxt) \
                    and run.role_for(step) == REVIEWER:
                # handed the reviewer before it, the next one would read a
                # verdict on the work instead of the work, and with the
                # same verdict twice it would be sent the same prompt
                out = handed
            came_from = step
            step = nxt
        signed = signoff.check(run.workdir, run.signoff)
        if signed.state in (signoff.CONFLICT, signoff.UNCHECKED):
            cause = stops.MOVED if signed.state == signoff.CONFLICT \
                else stops.UNCHECKED
            print("not signed off: " + signed.why)
            return stop(cause, signed.why, "stopped",
                        entry=trail.open(came_from, [], used, came_from),
                        index=("MOVED  " if cause == stops.MOVED
                               else "UNCHECKED  ") + flow + "  "
                        + signed.target)
        return finish(flow, fm, run, out, started, run_id, pick_up, leave,
                      record, origin, signed=signed.lines())
    except BaseException as e:
        cause = stops.of(e)
        if cause == stops.EXCEPTION:
            traceback.print_exc()
        at = step or came_from or todo[-1]
        forged = run.forged.pop(at, "")
        if cause == stops.OUTAGE:
            why = and_forged(outage_why(e), forged)
            print("provider outage at " + at + ": " + why)
            return stop(cause, why, "parked", trail.still_open(),
                        index="PARKED  " + flow + "  at " + at,
                        waiting="the limit to reset")
        if cause == stops.INTERRUPT:
            why = "interrupted while " + at + " was running"
        else:
            why = type(e).__name__ + ": " + str(e)
        why = and_forged(why, forged)
        print("stopped at " + at + ": " + why)
        return stop(cause, why, "crashed", trail.still_open(),
                    index=("INTERRUPTED  " if cause == stops.INTERRUPT
                           else "CRASHED  ") + flow + "  at " + at)
