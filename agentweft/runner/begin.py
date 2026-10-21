"""a run's setup from its command line: a fresh run, or one carried on."""
import datetime
import sys
import time
from pathlib import Path

from agentweft.roles import resolver

from .config import config, due, steps, where
from agentweft.flow.spec import REVIEWER, step_id
from agentweft.guardrails import (baseline, redorder, sacrifice, signoff,
                                  skips, snapshot)
from agentweft.orchestrate import decisions, park, project

from .handoff import EMPTY, Handoff
from . import investigate
from .prompts import flow_path
from . import prompts
from . import commits
from . import (chain, fan, leftred, manifest, models, resume, router, ruling,
               warm)
from . import state
from . import stops
from . import summary
from . import task
from . import worktrees
from .ending import CAPS, FLAG_OF, cap_of, resume_command
from .gating import NEWLINE
from .run import Run


class Leg(object):
    """what the setup hands the step loop."""

    def __init__(self, **values):
        self.__dict__.update(values)


def first_reader(flow, fm, order, start):
    """-> the first step in `order` that is handed the request, never one
    after `start`. everything from there was done against the request as it
    was, so a request amended by a ruling runs it all again."""
    where = task.places(flow_path(flow), fm)
    for name in order:
        if name == start or "instructions.md" in where or name in where:
            return name
    return start


def valued(flag):
    """-> the value given after `flag`, "" when it has none, None when the
    flag was not given."""
    if flag not in sys.argv:
        return None
    i = sys.argv.index(flag)
    said = sys.argv[i + 1].strip() if len(sys.argv) > i + 1 else ""
    return "" if said.startswith("-") else said


def carried(name, run, fm):
    """-> (the red proof `--continue <name>` carries, "") or (None, why).
    a name that is a run of this place carries that run's proof, anything
    else is read as a commit the start commit's tests were added after."""
    folder = state.RUNS / name
    if folder.is_dir():
        was = (folder / "workdir").read_text(encoding="utf-8").strip() \
            if (folder / "workdir").is_file() else ""
        if not was or Path(was).resolve() != Path(run.workdir).resolve():
            return None, name + " did not work in " + str(run.workdir)
        broke = chain.verify(folder).broken
        if broke:
            return None, name + "'s record does not hold: " + broke
        return redorder.carry_run(folder, name, run.start)
    return redorder.carry_commit(run.start, name, redorder.test_command(fm))


def caps_given(argv):
    """-> {cap: value} for every cap argv sets, over the flow's own."""
    out = {}
    for flag, key in CAPS:
        if flag not in argv:
            continue
        i = argv.index(flag)
        value = argv[i + 1] if len(argv) > i + 1 else ""
        if not value.isdigit():
            raise ValueError(flag + " needs a whole number, 0 for no cap")
        out[key] = int(value)
    return out


def new_run_id(flow, started):
    """-> <flow>-<day>-<time>, with -2, -3 on it when a run of the same flow
    started in the same second: a resume is quick, and the two would have
    shared a folder."""
    base = flow + "-" + started.strftime("%Y-%m-%d-%H%M%S")
    run_id, n = base, 1
    while (state.RUNS / run_id).exists():
        n = n + 1
        run_id = base + "-" + str(n)
    return run_id


def begin(unrecorded):
    """-> the exit code when the run ends before its first step, else the
    Leg the step loop goes on from."""
    if "--flows" in sys.argv:
        prompts.FLOW_ROOT[0] = sys.argv[sys.argv.index("--flows") + 1]
    flow = sys.argv[1]
    pick_up = None
    resuming = "--resume" in sys.argv
    if resuming:
        i = sys.argv.index("--resume")
        named_run = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        if not named_run.startswith("-"):
            pick_up = named_run or None
    try:
        fm = config(flow)
    except FileNotFoundError:
        from .cli import missing

        print(missing(flow))
        return 1
    except ValueError as e:
        print(flow + "/flow.yaml is wrong: " + str(e))
        return 1
    if resuming and not fm.get("journal", True):
        print(flow + " has journal: false, so a run that finished is never "
              "written down and --resume cannot tell it from one that stopped")
        return 1
    skipped, wrong = skips.given(sys.argv)
    wrong = wrong or skips.unused(skipped, fm)
    if wrong:
        print(wrong)
        return 1
    carry = valued("--continue")
    if carry is not None and not carry:
        print("--continue needs the run or the commit whose tests it carries")
        return 1
    target = valued("--target")
    if target is not None and not target:
        print("--target needs the branch the run's change is for")
        return 1
    if leftred.given(sys.argv) is not None and \
            leftred.given(sys.argv) not in leftred.CHOICES:
        print(leftred.FLAG + " takes one of: " + ", ".join(leftred.CHOICES))
        return 1
    if carry and resuming:
        print("--continue starts a run on an earlier one's tests; --resume"
              " carries a run on. one or the other")
        return 1
    found = None
    if resuming:
        ids = resume.runs_for(flow)
        pick_up = pick_up or (ids[-1] if ids else None)
        if pick_up is None:
            print("no run of " + flow + " to pick up")
            return 1
        if not (state.RUNS / pick_up).is_dir():
            print("no run called " + pick_up + " in " + str(state.RUNS))
            return 1
        found = manifest.load(state.RUNS / pick_up)
        if resume.finished(pick_up, found):
            print(pick_up + " finished. there is nothing to pick up")
            return 1
    answer, wrong = ruling.answer_of(sys.argv)
    if wrong:
        print(wrong)
        return 1
    if answer is not None and not resuming:
        print("--answer goes with --resume <run id>: it answers the question"
              " a parked run asked")
        return 1
    question = found.question if found else None
    if found:
        ended = found.data.get("stopped") or {}
        if ended.get("cause") == stops.DECLINED:
            print(pick_up + " ended " + stops.status(stops.DECLINED,
                                                     ended.get("step"))
                  + ": " + str(ended.get("why"))
                  + ". that is its answer; there is nothing to pick up")
            return 1
        if question is not None and answer is None:
            print(pick_up + " is waiting for a ruling. "
                  + ended.get("step") + " asked:")
            print("")
            print(question)
            print("")
            print("answer it with")
            again = resume_command(flow, pick_up, found.data.get("caps"))
            if ended.get("cause") == stops.CONFLICT:
                print("  " + again + park.OVERRIDE)
                print("  " + again + park.REQUEST)
            else:
                print("  " + again + park.ANSWER)
            return stops.EXIT_STOP
    if answer is not None and question is None:
        print(pick_up + " is not waiting for a ruling, so --answer has nothing"
              " to answer")
        return 1
    # only a conflict's answer is read for its first word: a free answer to
    # any other question may well start with "request:" and mean nothing by it
    conflicted = answer is not None and \
        (found.data.get("stopped") or {}).get("cause") == stops.CONFLICT
    kind = ruling.kind_of(answer) if conflicted else None
    if conflicted and kind is None:
        print(pick_up + " stopped on a spec conflict, so the answer says which"
              " one holds: --answer \"override: <the new rule>\" lets the"
              " request win, --answer \"request: <what to do instead>\" keeps"
              " the spec")
        return 1
    try:
        asked = task.settle(flow, task.places(flow_path(flow), fm),
                            task.given(sys.argv),
                            (found.task if found else
                             task.saved(state.RUNS / pick_up))
                            if pick_up else None,
                            pick_up)
        if kind == ruling.REQUEST:
            asked = ruling.amended(asked, answer)
        chosen = models.parse(models.pairs(sys.argv))
        kept = {}
        if pick_up:
            kept = dict(found.data.get("models") or {}) if found \
                else models.load(state.RUNS / pick_up)
        if pick_up and chosen and chosen != kept:
            print(pick_up + " was started with " + (models.said(kept) or
                                                    "no models chosen")
                  + ", not " + models.said(chosen)
                  + ". a run carries on with the models it started with")
            return 1
        chosen = chosen or kept
        wrong = models.unknown(chosen, fm)
        if wrong:
            raise ValueError(wrong)
        efforts = models.efforts(sys.argv)
        had = models.load(state.RUNS / pick_up, models.EFFORT_FILE) \
            if pick_up else {}
        if pick_up and efforts and efforts != had:
            print(pick_up + " was started with " + (models.said(had) or
                                                    "no efforts chosen")
                  + ", not " + models.said(efforts)
                  + ". a run carries on with the efforts it started with")
            return 1
        efforts = efforts or had
        wrong = models.unknown(efforts, fm)
        if wrong:
            raise ValueError(wrong)
    except ValueError as e:
        print(str(e))
        return 1
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    if not due(fm) and "--force" not in sys.argv:
        print(flow + " is not due today, use --force")
        return stops.EXIT_OK
    named = None
    if "--workdir" in sys.argv:
        i = sys.argv.index("--workdir")
        if len(sys.argv) <= i + 1:
            print("--workdir needs a directory")
            return 1
        named = sys.argv[i + 1]
    tree_base = worktrees.asked(fm, sys.argv)
    made = (found.data.get("worktree") if found else None) or None
    started_in = ""
    if pick_up:
        if worktrees.FLAG in sys.argv and not made:
            print(pick_up + " did not start in a worktree of its own. a run"
                  " carries on where it started")
            return 1
        tree_base = None
        started_in = (found.data.get("workdir") if found else "") \
            or resume.workdir(pick_up)
    order = steps(flow)
    shape = manifest.flow_digest(flow_path(flow))
    notes = []
    start = investigate.held(fm, order)[0]
    if pick_up:
        start = resume.start_at(pick_up, investigate.held(fm, order, found),
                                found)
        if start is None:
            print("nothing left to run in " + pick_up)
            return stops.EXIT_OK
        if kind == ruling.REQUEST:
            start = first_reader(flow, fm, order, start)
        edited = manifest.changed(found.data.get("flow_files"), shape[1]) \
            if found else []
        if edited and "--force" not in sys.argv:
            print(flow + " has changed since " + pick_up + " stopped ("
                  + ", ".join(edited) + "). the rest of it would run on a "
                  "different flow than the part that ran; --force carries on "
                  "anyway")
            return 1
        if edited:
            notes.append(("carried " + pick_up + " on over an edited flow",
                          ", ".join(edited) + " changed since " + pick_up
                          + " stopped, and --force was given."))
        broke = chain.verify(state.RUNS / pick_up).broken
        if broke and "--force" not in sys.argv:
            print(pick_up + "'s record does not hold: " + broke + ". what it"
                  " says ran is not what ran; --force carries on anyway")
            return 1
        if broke:
            notes.append(("carried " + pick_up + " on over a broken record",
                          "runs/" + pick_up + "/steps.jsonl: " + broke
                          + ", and --force was given."))
    started = datetime.datetime.now()
    clock = time.time()
    run_id = new_run_id(flow, started)

    def undo(code):
        """-> code, once a checkout this run made and never used is gone."""
        if tree_base:
            worktrees.discard(made)
        return code

    try:
        if started_in and named and where(fm, named) != Path(started_in):
            print(pick_up + " was working in " + started_in + ", not "
                  + named + ". a run carries on where it started")
            return 1
        if tree_base:
            inside, made = worktrees.make(fm, named, run_id, tree_base)
            unrecorded.append(made)
            named = str(inside)
        run = Run(flow, fm, by_role, workdir=started_in or named, task=asked,
                  chosen=chosen, efforts=efforts,
                  held=project.kept(state.RUNS / pick_up, started_in)
                  if pick_up else None)
        if pick_up and run.start is not None:
            # a snapshot taken now would count the tests the first run wrote
            # as already there
            run.start = snapshot.load(state.RUNS / pick_up) or \
                snapshot.Snapshot(run.workdir, why="resumed, start state not"
                                  " kept")
            run.order.start = run.start
        run.committer = commits.Committer(
            run.commits, run.start,
            commits.load(state.RUNS / pick_up) if pick_up else None)
    except ValueError as e:
        print(str(e))
        return undo(1)
    if found and "signoff" in found.data:
        run.signoff = found.data["signoff"]
        meant = (run.signoff or {}).get("target")
        if target and target != meant:
            print(pick_up + " was started for " + (meant or "no branch")
                  + ", not " + target + ". a run carries on for the branch"
                  " it started for")
            return undo(1)
    else:
        run.signoff = signoff.mark(run.workdir, target,
                                   origin=made["repo"] if made else None)
        if target and run.signoff is None:
            print("--target " + target + ": " + str(run.workdir) + " is not"
                  " a git work tree with a commit, so there is no branch to"
                  " sign the change off against")
            return undo(1)
        if target and not run.signoff["head"]:
            print("--target " + target + ": git knows no branch or commit of"
                  " that name in " + str(run.workdir))
            return undo(1)
    run.skipped = {}
    run.worktree = made
    uncut = []
    if pick_up:
        run.order.skip, run.order.proof = redorder.load(state.RUNS / pick_up)
        run.skipped, uncut = sacrifice.uncut(
            fm, skips.load(state.RUNS / pick_up))
        lost = run.order.recheck()
        if lost:
            print("the red proof " + pick_up + " held is dropped: " + lost)
    run.skipped.update(skipped)
    if skipped.get(skips.TESTS):
        run.order.skip = skipped[skips.TESTS]
        notes.append(("tests skipped for this run", run.order.skip + NEWLINE
                      + "given with --skip tests: the red-test and red-first"
                      " gates and the test order checks did not run."))
    for names, reason in skips.grouped(skipped):
        notes.append((", ".join(names) + " skipped for this run", reason
                      + NEWLINE + "given with --skip " + ",".join(names)
                      + ": each step's " + " and ".join(names) + " gate"
                      + ("s" if len(names) > 1 else "")
                      + " did not run, and each says so in the record."))
    if carry:
        run.order.proof, why = carried(carry, run, fm)
        if why:
            print("nothing carried from " + carry + ": " + why)
            return undo(1)
        notes.append(("tests carried from " + run.order.proof["from"],
                      "given with --continue " + carry + ": "
                      + ", ".join(sorted(run.order.proof["tests"]))))
    try:
        given = caps_given(sys.argv)
    except ValueError as e:
        print(str(e))
        return undo(1)
    # a cap given on the command line is the run's, not one leg's: a resume
    # without it would carry on under the flow's, past the one it parked on
    held = dict((found.data.get("caps") or {}) if found else {})
    held.update(given)
    for key, value in held.items():
        setattr(run.budget, key, value)
    run.caps = held
    raised = None
    if found:
        run.budget.restore(found.spend)
        waits = run.budget.ahead()
        if waits:
            flag = FLAG_OF[cap_of(waits[1])]
            if cap_of(waits[1]) in held:
                print(pick_up + " is at its cap (" + waits[1] + "). " + flag
                      + " was given on the command line and holds until a"
                      " higher one is: carry on with " + resume_command(
                          flow, pick_up, held, raise_cap=cap_of(waits[1])))
            else:
                print(pick_up + " is at its cap (" + waits[1] + "). carry on"
                      " with --resume " + pick_up + " --max-calls <n> or"
                      " --max-tokens <n>, or raise max_calls or max_tokens in "
                      + flow + "/flow.yaml and add --force")
            return 1
        moved = run.budget.moved(found.spend)
        if moved:
            raised = ruling.capped(pick_up, moved, (found.data.get(
                "stopped") or {}).get("why"))
    route = router.Router(fm)
    run.ups = route.ups
    try:
        run.committer.begin(run_id)
    except ValueError as e:
        print(str(e))
        return undo(1)
    out = EMPTY
    came_from = None
    todo = order[order.index(start):]
    origin = None
    earlier = []
    if pick_up:
        origin = found.origin if found else pick_up
        before = order[:order.index(start)]
        earlier = summary.passes_of(
            state.RUNS / pick_up,
            dict((step_id(s), s["role"]) for s in fm.steps), fm)
        for p in earlier:
            run.keep(p["role"], p["block"])
            run.brief.add(p["step"], None, p["role"], p["block"])
        if before:
            came_from = before[-1]
            # a reviewer with a lens is handed the work, never the verdict
            # of the reviewer before it, a resume between them included
            given_by = came_from
            if run.lens_for(start):
                for s in reversed(before):
                    given_by = s
                    if run.role_for(s) != REVIEWER:
                        break
            entry = found.step(given_by) if found else None
            source = (entry or {}).get("in") or pick_up
            out = Handoff(run.role_for(given_by),
                          resume.step_output(source, given_by),
                          meta={"rulings": run.rulings()},
                          carried=list(run.constraints))
            if entry and entry.get("digest") and \
                    manifest.of_text(out.output) != entry["digest"]:
                print(given_by + " was edited after " + source
                      + " wrote it; the rest of the run works from the edit")
                notes.append((given_by + " was edited by hand before " + run_id
                              + " carried on",
                              "runs/" + source + "/" + given_by + " is not "
                              "what " + given_by + " produced, and what "
                              "comes after it works from the edited file."))
        if found and found.data.get("tree"):
            moved = manifest.moved(found.data["tree"],
                                   manifest.tree(run.workdir, state.RUNS))
            if moved:
                print("the place has changed since " + pick_up + " stopped: "
                      + ", ".join(moved))
        if found and start == run.fan and not (found.step(start) or {}).get(
                "digest"):
            run.reuse = manifest.tasks_done(state.RUNS / pick_up, start)
        if start == run.fan:
            run.fan_start = fan.load(state.RUNS / pick_up)
        if investigate.on(fm) and investigate.STEP not in todo:
            entry = found.step(investigate.STEP) if found else None
            run.produced[investigate.STEP] = resume.step_output(
                (entry or {}).get("in") or pick_up, investigate.STEP)
        print("picking " + pick_up + " up at " + start)
    seen = state.last_output(flow, run.workdir, asked)
    folder = state.RUNS / run_id
    folder.mkdir(parents=True, exist_ok=True)
    run.folder = folder
    run.keep_in(folder)
    if pick_up:
        run.kept.carry(state.RUNS / pick_up)
    run.kept.keep_in(folder)
    run.committer.keep_in(folder)
    (folder / "workdir").write_text(str(run.workdir), encoding="utf-8")
    if run.start is not None and run.start.hashed:
        run.start.save(folder)
    if run.suite == baseline.ON and run.suite_baseline() is None:
        print("no suite baseline: " + (run.baseline or {}).get(
            "why", "the run skips tests"))
    if redorder.ordered(fm) or run.order.skip or run.order.proof:
        run.order.save(folder)
    if run.skipped:
        skips.save(folder, run.skipped)
    project.keep(folder, run.project)
    if asked is not None:
        task.save(folder, asked)
    models.save(folder, chosen)
    models.save(folder, efforts, models.EFFORT_FILE)
    chain.wrote(folder)
    if found:
        record = found.carried(folder, run_id, order, shape,
                               workdir=str(run.workdir))
        if kind == ruling.REQUEST:
            record.data["task"] = asked
            for name in order[order.index(start):]:
                record.mark(name, manifest.NOT_RUN)
    else:
        record = manifest.Manifest.new(folder, run_id, flow, fm["name"], order,
                                       shape, task=asked, models=chosen,
                                       workdir=run.workdir, origin=origin,
                                       resumes=pick_up)
        for name in order[:order.index(start)]:
            record.mark(name, manifest.PASSED, pick_up)
    if found:
        route.ups.update(found.data.get("raised") or {})
    record.data["raised"] = route.ups
    if held:
        record.data["caps"] = held
    if made:
        record.data["worktree"] = made
    run.record = record
    run.sessions = dict(record.data.get("sessions") or {})
    if warm.wanted(sys.argv):
        warm.Warmer(run).start()
    record.data["signoff"] = run.signoff
    record.save(run.budget)
    del unrecorded[:]
    for decided, why in notes:
        decisions.record(folder, decided, why)
    if raised:
        # a raised cap is a person letting the run spend more, a ruling like
        # an --answer, so it is kept where the handoff reads the rulings
        run.rule(*raised, by="cap")
    if answer is not None:
        asker = (found.data.get("stopped") or {}).get("step") or start
        run.rule(ruling.decided(asker, answer),
                 ruling.why(asker, pick_up, question, answer, ruling.who(),
                            kind), by="answer")
        if kind == ruling.REQUEST:
            print("ruled: the request is amended, and the run starts again at "
                  + start)
        else:
            run.ruled[start] = ruling.told(question, answer, kind)
            print("ruled: " + start + " runs again with the answer")
    return Leg(flow=flow, fm=fm, run=run, route=route, record=record,
               folder=folder, run_id=run_id, started=started, clock=clock,
               made=made, origin=origin, earlier=earlier, asked=asked,
               pick_up=pick_up, order=order, todo=todo, start=start,
               found=found, seen=seen, out=out, came_from=came_from,
               uncut=uncut)
