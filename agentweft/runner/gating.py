"""what a step's answer has to get past before the run goes on."""
import time

from agentweft.flow.spec import step_id
from agentweft.guardrails import police, rulings
from agentweft.guardrails import writes as bounds
from agentweft.guardrails.gates.base import Result
from agentweft.guardrails.gates.redfirst_gate import said_of
from agentweft.guardrails.gates.redtest_gate import named_test

from . import leftred, ruling, wrongtest
from .handoff import without

NEWLINE = chr(10)
RED_MARKER = "FAILS:"


def shown(step, results, output):
    """-> the lines a later step is told about what this step's gates ran:
    a red test seen failing before the next step began, and each new test
    seen red without the fix and green with it. a gate that ran nothing, or
    failed, shows nothing."""
    out = []
    for r in results:
        if not r.ok:
            continue
        if r.gate == "red-test" and r.detail.startswith("red") \
                and "nothing was run" not in r.detail:
            named = named_test(output or "")
            out.append("- " + step + "'s red-test gate ran "
                       + (named or "the test") + " before any later step"
                       " started, and it failed (" + r.detail + ")")
        if r.gate == "red-first" and r.tests:
            out.append("- " + step + "'s red-first gate ran each new test on"
                       " the start commit with only the test files changed,"
                       " then on the place as it is now:")
            out.extend("  - " + said_of(t) for t in r.tests)
    return out


def forged_first(run, step, out):
    """-> what `step` did to decisions.md, "" for nothing, put on `out` as a
    failed rulings gate. read before a fence or an empty answer can stop the
    run, so the stop says it too; `check_step` reads it again after."""
    said = getattr(run, "forged", {}).get(step, "")
    if said:
        out.meta["gates"] = [Result(rulings.GATE, False, said)]
        out.meta["ungated"] = False
    return said


def off_task(run, step, folder=None):
    """-> why the run stops off task after `step`, "" when it does not.

    every go the check read since the last step is read here, a lead's that
    answered in between included, so no hit waits for a step that may never
    come. what it found for `step` itself goes on that step's line.
    """
    found = run.policed_now() if hasattr(run, "policed_now") else []
    mine = [r for r in found if r.step == step]
    if mine:
        line = {"hits": sum(len(r.hits) for r in mine),
                "seen": all(r.seen for r in mine),
                "seconds": round(sum(r.seconds for r in mine), 3)}
        run.police_lines[step] = line
        if not line["seen"]:
            print("police: " + step + " left no transcript to read, so what"
                  " it did with its tools was not checked")
    hit = [r for r in found if r.hits]
    if not hit:
        return ""
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / police.FILE, "a", encoding="utf-8") as f:
            f.write("## " + step + NEWLINE + police.as_note(hit))
    hits = [h for r in hit for h in r.hits]
    first = hit[0]
    return ("" if first.step == step else first.step + " ") \
        + police.why(hits)


def police_line(run, step):
    return getattr(run, "police_lines", {}).pop(step, None)


def and_forged(why, forged):
    return why + "; " + forged if forged else why


def forged_by(run, step):
    """whether `step` changed decisions.md, and so fails before anything it
    asked or claimed is read."""
    return bool(getattr(run, "forged", {}).get(step))


def held_after_stop(run, left, folder):
    """-> `left` with what the stop's own test run did to decisions.md, put
    on why.md too. those runs are code a step wrote, after its last check."""
    said = run.kept.check(leftred.RAN)
    if not said:
        return left
    with open(folder / "why.md", "a", encoding="utf-8") as f:
        f.write(said + NEWLINE)
    return dict(left, forged=said)


def handed_to(run, step):
    """-> what the steps before `step` in the flow produced in this run."""
    fm = getattr(run, "fm", None)
    produced = getattr(run, "produced", None) or {}
    order = [step_id(s) for s in fm.steps] if fm is not None else []
    if step not in order:
        return []
    return [produced[k] for k in order[:order.index(step)] if produced.get(k)]


def since(began):
    return round(time.time() - began, 3)


def clocked(gate, text):
    """-> what `gate` said of text, with the seconds it took."""
    began = time.time()
    r = gate(text)
    r.seconds = since(began)
    return r


def check_step(run, route, step, out, run_dir=None):
    """what a step has to get past once it has produced something.

    -> (the gate that failed, why the router will not go on), either of them
    "" when it did not happen. the results are written down when there is a
    run to write them into; a scored run has nowhere to write and still has to
    be stopped by them.

    a step that declares no gates gets a `no gates` line of its own, so the
    record tells a step that had none from one that passed them.

    the gates read the answer without its HANDOFF block: the block is the
    step's account of the work, and a length cap or a pattern is about the
    work.
    """
    held = getattr(run, "held", lambda g, s: g.run)
    results = [clocked(held(g, step), without(out.output))
               for g in run.gates_for(step)]
    order = getattr(run, "order", None)
    if order is not None:
        unruled = getattr(run, "spec_unruled", None)
        moved = order.after(step, run.writes_for(step),
                            ruled=(lambda: not unruled()) if unruled else None)
        if moved:
            results.insert(0, Result(bounds.NAME, False, moved))
    workdir, start = getattr(run, "workdir", "."), getattr(run, "start", None)
    wrong = [w for w in (ruling.misquoted(out.output, workdir, start),
                         wrongtest.misquoted(out.output, workdir, start)) if w]
    if wrong:
        results.insert(0, Result("quote", False, "; ".join(wrong)))
    said = ruling.conflict_of(out.output, workdir, start,
                              handed=handed_to(run, step))
    if said and said[1]:
        results.insert(0, Result("conflict", False, said[1]))
    forged = getattr(run, "forged", {}).pop(step, "")
    if forged:
        results.insert(0, Result(rulings.GATE, False, forged))
    guarded = getattr(run, "spec_held", None)
    if guarded is not None:
        began = time.time()
        line, spec_asks = guarded(step, all(r.ok for r in results))
        if line is not None:
            line.seconds = since(began)
            results.append(line)
        if spec_asks:
            out.meta["spec_ruling"] = spec_asks
    kept = getattr(run, "tests_held", None)
    if kept is not None:
        ok = all(r.ok for r in results)
        tries = getattr(route, "gate_tries", None)
        last = ok and tries is not None and \
            tries.get(step, 0) >= route.gate_cap(step)
        line, test_asks = kept(step, last)
        if line is not None:
            results.append(line)
        if test_asks and "spec_ruling" not in out.meta:
            out.meta["test_ruling"] = test_asks
    replayed = getattr(run, "replayed", None)
    if replayed is not None and all(r.ok for r in results):
        began = time.time()
        line, held = replayed(step)
        if line is not None:
            line.seconds = since(began)
            results.append(line)
        if held:
            out.meta["conflict"] = held
    kept = getattr(run, "kept", None)
    # a gate runs code the step wrote, so a write it makes is the step's,
    # not the next one's
    ran = kept.check(step, ", in the code its gates ran") \
        if kept is not None else ""
    if ran:
        results.insert(0, Result(rulings.GATE, False, ran))
    out.meta["gates"] = results
    out.meta["ungated"] = not results
    for r in results:
        print("  " + repr(r))
    if isinstance(getattr(run, "proven", None), dict):
        run.proven[step] = shown(step, results, out.output)
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "gates.md", "a", encoding="utf-8") as gf:
            gf.write("## " + step + NEWLINE)
            for r in results:
                gf.write(repr(r) + NEWLINE)
            if not results:
                gf.write("no gates" + NEWLINE)
    failed = [r for r in results if not r.ok]
    if failed:
        return failed[0].gate, ""
    if order is not None and order.skip and \
            getattr(route, "must", {}).get(step) == RED_MARKER:
        return "", route.unread(step, out) or ""
    return "", route.gate(step, out) or ""


def outage_why(e):
    return ("limit reached, resets " + e.resets + "; the provider said: "
            + e.detail)


def gate_why(results):
    """-> the first failed gate, and what it said."""
    for r in results:
        if not r.ok:
            return r.gate + (": " + r.detail if r.detail else " failed")
    return "a gate failed"


def gate_told(results):
    """-> the end of a step's next prompt, once a gate has sent it back."""
    return ("\n\nyour last answer failed a gate, so this step runs again. the"
            " gate said:\n\n" + gate_why(results) + NEWLINE)


def sent_back_times(route, step):
    """-> how often a failed gate already sent the step back, for the why."""
    n = route.gate_tries.get(step, 0)
    cap = " (send_backs: " + str(route.gate_cap(step)) + ")"
    if not n:
        return "; " + step + " was not sent back" + cap
    return "; " + step + " was sent back " + times(n) + " already" + cap


def times(n):
    return str(n) + " time" + ("" if n == 1 else "s")


def nothing_why(step, entry):
    """-> what the provider said about the goes that came back empty."""
    said = [r.detail for a in entry.attempts for r in a.replies
            if not r and r.detail]
    goes = sum(len(a.replies) for a in entry.attempts)
    out = "nothing came out of " + step
    if said:
        out = out + " in " + str(goes) + (" go" if goes == 1 else " goes") \
            + "; the provider said: " + said[-1]
    return out
