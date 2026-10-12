import concurrent.futures
import datetime
import os
import re
import sys
import time
import traceback
from pathlib import Path

from agentweft.roles import resolver

from .config import (VERDICTS, asks_for_verdict, config, due, fanout_step,
                     steps, verdict, where)
from agentweft import providers
from agentweft.flow.spec import step_id, step_name, steps_named
from agentweft.guardrails import (boundary, briefing, defaults, fence, gates,
                                  promises)
from agentweft.mcp import context, preflight
from agentweft.orchestrate import park, synthesise

NEWLINE = chr(10)
from agentweft.guardrails.budget import Budget

from .handoff import EMPTY, Handoff
from . import errors
from .errors import Fatal, Outage, kind_of
from . import prompts
from .prompts import flow_path, load_prompt, read
from . import models, resume, router
from .settings import get as setting  # noqa: F401
from . import settings
from . import state
from . import stops
from . import task
from . import trace
from .state import load_state, save_state

from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env():
    # not worth a dependency for six lines
    if not os.path.exists(".env"):
        return
    for line in open(".env", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        os.environ[k] = v


def retry(fn, cap=3, sleep=time.sleep):
    tries = 0
    wait = 2
    while tries < cap:
        ok, out = fn()
        if ok:
            return out
        tries = tries + 1
        if tries < cap:
            print("cli failed, waiting " + str(wait) + "s")
            sleep(wait)
            wait = wait * 2
    print("giving up")
    return ""


class Answer(tuple):
    """(text, cached), the pair call has always handed back, plus every reply
    it took to get there and how many goes failed, by cause."""

    def __new__(cls, text, cached, replies=(), retries=None):
        self = tuple.__new__(cls, (text, cached))
        self.replies = list(replies)
        self.retries = retries or {}
        return self


def call(prompt, timeout=None, cap=3, step="?", provider=None):
    p = provider or providers.build({})
    heard = []
    failed = {}

    def once():
        reply = p.ask(prompt, timeout=timeout)
        heard.append(reply)
        if reply:
            return True, reply.text
        kind = kind_of(reply)
        print("step " + step + " failed (" + kind.__name__.lower() + "): "
              + reply.detail)
        if kind is Fatal:
            # going again will not help and it still costs
            raise Fatal(reply.detail)
        cause = kind.__name__.lower()
        failed[cause] = failed.get(cause, 0) + 1
        if kind is Outage:
            raise Outage(reply.detail,
                         reply.outage or errors.resets(reply.detail),
                         replies=heard, retries=failed)
        return False, reply.text

    answer = retry(once, cap)
    return Answer(answer, False, heard, failed)


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
            why=None, saved=None):
    """the only place a journal line gets written. there were three, and the
    failure one had drifted into a different column order. the shapes are in
    `stops`, which is also what reads them back."""
    secs = int((datetime.datetime.now() - started).total_seconds())
    text = stops.line(started, flow_name, status, secs, run, cause, spend,
                      why, saved)
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


def resume_command(flow, run_id):
    """the line a person types to carry on after a park.

    it goes in the handoff, so it has to work as printed: the switches this run
    was started with come along, or the command in front of them is one they
    have to debug before they can use it.
    """
    out = ["python run.py", flow, "--resume", run_id]
    if "--force" in sys.argv:
        out.append("--force")
    if "--flows" in sys.argv:
        out = out + ["--flows", sys.argv[sys.argv.index("--flows") + 1]]
    return " ".join(out)


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


class Run(object):
    """everything a step needs, built once. fm and by_role were being threaded
    through five functions just so two of them could read a timeout."""

    def __init__(self, flow, fm, by_role, provider=None, workdir=None,
                 task=None, chosen=None):
        self.flow = flow
        self.chosen = dict(chosen or {})
        self.fm = fm
        self.task_text = task
        self.by_role = by_role
        self.workdir = where(fm, workdir)
        self.timeout = int(settings.get("timeout", flow=fm))
        self.retries = int(settings.get("retries", flow=fm))
        self.workers = int(settings.get("workers", flow=fm))
        self.fan = fanout_step(flow)
        self.produced = {}
        self.answers = {}
        self.attempts = []
        self.ranking = ""
        self.budget = Budget(*defaults.for_flow(fm))
        # an override replaces the per-step ones too. half a run on the pinned
        # provider and half on the flow's own is not a comparison of anything.
        pinned = providers.build(provider, where=self.workdir) \
            if provider else None
        self.provider = pinned or providers.build(fm.get("provider") or {},
                                                  where=self.workdir)
        self.by_step = {}
        for s in fm.steps:
            # a step gets its own provider when it names one, and now also
            # when it only names a tier. the tier has to reach something that
            # can act on it, and the flow's provider is shared - handing it a
            # tier would give it to every step that has not asked for one.
            asked, source = models.choose(s, fm, self.chosen)
            if not s.get("provider") and not asked:
                continue
            if pinned:
                self.by_step[step_id(s)] = pinned
                continue
            conf = dict(s.get("provider") or fm.get("provider") or {})
            tier = ""
            if asked and models.is_tier(asked):
                tier = asked
                if source == "run":
                    conf.pop("model", None)
            elif asked:
                conf["model"] = asked
            p = providers.build(conf, tier=tier, where=self.workdir)
            if asked:
                p.choice = {"role": s["role"], "asked": asked, "from": source,
                            "applies": p.chooses_model()}
            self.by_step[step_id(s)] = p
        self.briefed = briefing.digest(self.workdir)
        self.fence = fence.at(self.workdir, own=state.RUNS)

    def fenced(self, step):
        """what is gone or changed that git cannot give back, or "" for none.

        the fence was taken when the run started, so a file an earlier step
        created is this run's own and free to touch.
        """
        hit = self.fence.crossed() if self.fence is not None else []
        if not hit:
            return ""
        return (", ".join(p + " (" + what + ")" for p, what in hit)
                + " in " + str(self.workdir) + " by the time " + step
                + " finished. they were there before the run and git has no"
                " copy of them")

    def refused(self, step):
        """why this step may not start, or "" when it may.

        a step whose model is started in the place reads the instruction
        files lying there, so one written after the run started is the
        previous step steering this one. a step that only sends text reads
        nothing there and is never refused for it.
        """
        if not self.by_step.get(step, self.provider).reads_place:
            return ""
        moved = briefing.changed(self.briefed, briefing.digest(self.workdir))
        if not moved:
            return ""
        return (", ".join(moved) + " changed in " + str(self.workdir)
                + " since the run started, and " + step
                + " would start its model there and read it")

    def role_for(self, step):
        """the role this step declared, which the file name only usually says."""
        for s in self.fm.steps:
            if step_id(s) == step:
                return s["role"]
        raise KeyError("no step called " + step + " in " + str(self.fm.name))

    def preflight_for(self, step):
        for s in self.fm.steps:
            if step_id(s) == step:
                return s.get("preflight")
        return None

    def pause_for(self, step):
        """who the run waits for once this step is done, if anyone."""
        for s in self.fm.steps:
            if step_id(s) == step:
                return s.get("pause")
        return None

    def grant_for(self, step):
        """what this step may touch, or None when it did not say.

        None and [] are different answers and both of them are returned as
        they are: `boundary` treats the first as no boundary declared and the
        second as a boundary that allows nothing.
        """
        for s in self.fm.steps:
            if step_id(s) == step:
                return s.get("tools")
        return None

    def reports_for(self, step):
        """the reports a step said it judges, in the order it named them.

        a name is a role or a step, and a role is every step that declared it:
        a role run twice from two fixed positions arrives as two reports under
        a name each, which is the only form a judge can do anything with.

        a name that has produced nothing in this process is left out rather
        than sent empty: a resumed run starts in the middle, and a real name
        over an empty report is worse than one report fewer. a step named
        twice, once by its role and once by itself, is sent once - the same
        text under two headings is the judge being told to weigh it heavier.
        """
        for s in self.fm.steps:
            if step_id(s) != step:
                continue
            out = []
            seen = []
            for name in (s.get("reports") or []):
                for other in steps_named(self.fm.steps, name):
                    wrote = self.produced.get(step_id(other))
                    if not wrote or step_id(other) in seen:
                        continue
                    seen.append(step_id(other))
                    out.append(synthesise.Report(step_name(other), wrote))
            return out
        return []

    def gates_for(self, step):
        for s in self.fm.steps:
            if step_id(s) == step:
                earlier = [t for k, t in self.produced.items() if k != step]
                return [gates.build(g, where=self.workdir, ranking=self.ranking,
                                    earlier=earlier)
                        for g in (s.get("gates") or [])]
        return []

    def width_for(self, step):
        for s in self.fm.steps:
            if step_id(s) == step:
                return int(settings.get("workers", step=s, flow=self.fm))
        return 1

    def charge(self, prompt, answer, provider):
        """every go the answer took, the failed ones too: each was paid for."""
        replies = getattr(answer, "replies", None)
        if replies is None:
            self.budget.charge(prompt, answer[0], provider=provider)
            return
        for reply in replies:
            error = None if reply else kind_of(reply).__name__.lower()
            self.budget.charge(prompt, reply, provider=provider, error=error)

    def ask(self, prompt, step, used):
        """a redo re-runs most of a flow unchanged, so inside one run the same
        prompt to the same provider is the same answer. the answers are the
        run's own: a second run or a second eval case handed the first one's
        answer was scored on work it never did. an answer given up on is not
        kept, so the next time it is asked again."""
        key = (used, prompt)
        if key in self.answers:
            print("step " + step + " came from the cache")
            return Answer(self.answers[key], True)
        answer = call(prompt, timeout=self.timeout, cap=self.retries,
                      step=step, provider=used)
        if answer[0]:
            self.answers[key] = answer[0]
        return answer

    def taken(self):
        """-> the goes made since this was last asked, for the trace line."""
        out, self.attempts = self.attempts, []
        return out

    def step(self, step, previous=EMPTY, extra="", task=None):
        import time as _t

        began = _t.time()
        role = self.role_for(step)
        prompt = load_prompt(self.flow, step, self.by_role[role], role)
        # read before anything is appended or the task is put in: what an
        # earlier step produced, or a task quoting a review, can carry its own
        # verdict line, and that does not ask this one for one
        asked = asks_for_verdict(prompt)
        prompt = prompts.put_task(prompt, self.task_text)
        # the grant goes out with the role's own rules, before whatever this
        # particular call is about. it is the only half of a boundary that can
        # happen before the answer exists, and a step that was never told its
        # grant is one this cannot fairly hold to it afterwards.
        prompt = prompt + boundary.as_prompt(self.grant_for(step))
        if extra:
            prompt = prompt + extra
        reports = self.reports_for(step)
        prompt = prompt + (synthesise.brief(reports) if reports
                           else previous.as_prompt())
        tried = trace.Attempt(task)
        self.attempts.append(tried)
        used = self.by_step.get(step, self.provider)
        try:
            answer = tried.answered(self.ask(prompt, step, used))
        except Outage as e:
            refused = tried.answered(Answer("", False, e.replies, e.retries))
            self.charge(prompt, refused, used.name)
            raise
        text, cached = answer
        self.produced[step] = text
        if not cached:
            # a cached answer costs nothing and was counting against the cap,
            # so a flow with a redo in it hit the ceiling on work it never did
            self.charge(prompt, answer, used.name)
        return Handoff(role, text, verdict(text, asked=asked),
                       meta={"seconds": round(_t.time() - began, 1),
                             "cached": cached, "provider": used.name,
                             "asked": asked})


def run_steps(run, names, note=EMPTY):
    """the redo path. same pipeline as the first pass, fanout included - a redo
    that skips the fanout is not the same flow."""
    out = note
    for step in names:
        if step == run.fan:
            out = run_fanout(run, out)
            continue
        out = run.step(step, previous=out)
    return out


def fanned_verdict(parts):
    """-> one verdict for every task of a fanned-out step: the first word the
    router cannot read, else redo if any task asked for one, else ok."""
    words = [p.verdict for p in parts]
    for word in words:
        if word not in VERDICTS:
            return word
    return "redo" if "redo" in words else "ok"


def run_fanout(run, plan):
    """-> the fanned step's tasks, one per line of the plan, run side by side.

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
    tasks = [l for l in plan.output.split("\n") if "|" in l]
    if not tasks:
        return Handoff(role, "", meta={
            "tasks": 0, "seconds": round(time.time() - began, 1),
            "why": run.fan + " is fanned out one task per line with a | in it,"
                   " and what " + plan.role + " handed it has none"})

    def one(i):
        return run.step(run.fan, previous=back,
                        extra="\n\nyour task, only this one:\n\n" + tasks[i],
                        task=i + 1)

    # three workers and two tasks means an idle thread and a pool i paid to
    # build. no point.
    # planner 1, workers N, reviewer 1. the fanned out step is the only one
    # that gets to be plural, and it says so itself.
    width = min(run.width_for(run.fan), len(tasks)) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        parts = list(pool.map(one, range(len(tasks))))
    out = Handoff(role, "\n\n".join(p.output for p in parts),
                  verdict=fanned_verdict(parts),
                  meta={"tasks": len(tasks),
                        "seconds": round(time.time() - began, 1),
                        "asked": any(p.meta.get("asked") for p in parts)})
    # every task went through Run.step, so what it recorded is whichever one
    # finished last. the joined output is what the step actually produced.
    run.produced[run.fan] = out.output
    return out


def check_step(run, route, step, out, run_dir=None):
    """what a step has to get past once it has produced something.

    -> (the gate that failed, why the router will not go on), either of them
    "" when it did not happen. the results are written down when there is a
    run to write them into; a scored run has nowhere to write and still has to
    be stopped by them.

    a step that declares no gates gets a `no gates` line of its own, so the
    record tells a step that had none from one that passed them.
    """
    results = [g.run(out.output) for g in run.gates_for(step)]
    out.meta["gates"] = results
    out.meta["ungated"] = not results
    for r in results:
        print("  " + repr(r))
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
    return "", route.gate(step, out) or ""


def run_once(flow, provider=None, task=None):
    """run a flow and hand back what it produced, what it cost, and why it
    stopped short ("" when it did not). the eval harness wants the output, not
    the printing, and it wants to say which provider the whole thing runs on."""
    fm = config(flow)
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    run = Run(flow, fm, by_role, provider=provider, task=task)
    route = router.Router(fm, cap=2)
    out = EMPTY
    step = steps(flow)[0]
    while step:
        refused = run.refused(step)
        if refused:
            return out.output, run.budget, "refused at " + step + ": " + refused
        try:
            if step == run.fan:
                out = run_fanout(run, out)
            else:
                out = run.step(step, previous=out)
        except Outage as e:
            return (out.output, run.budget, "provider outage at " + step
                    + ": " + outage_why(e))
        fenced = run.fenced(step)
        if fenced:
            return out.output, run.budget, "fenced at " + step + ": " + fenced
        if not out:
            return out.output, run.budget, \
                out.meta.get("why") or "nothing came out of " + step
        failed, blocked = check_step(run, route, step, out)
        if failed:
            return out.output, run.budget, "gate " + failed + " failed at " + step
        if blocked:
            return out.output, run.budget, blocked
        step = route.next(step, out)
    return out.output, run.budget, ""


def main():
    load_env()
    if "--flows" in sys.argv:
        prompts.FLOW_ROOT[0] = sys.argv[sys.argv.index("--flows") + 1]
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    pick_up = None
    if "--resume" in sys.argv:
        i = sys.argv.index("--resume")
        pick_up = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if pick_up is None:
            ids = resume.runs_for(flow)
            pick_up = ids[-1] if ids else None
    try:
        fm = config(flow)
    except FileNotFoundError:
        known = ", ".join(sorted(p.name for p in Path(prompts.FLOW_ROOT[0]).iterdir()
                                 if p.is_dir() and not p.name.startswith("_")))
        print("no flow called " + flow + ". there is: " + known)
        return 1
    except ValueError as e:
        print(flow + "/flow.yaml is wrong: " + str(e))
        return 1
    if pick_up and not fm.get("journal", True):
        print(flow + " has journal: false, so a run that finished is never "
              "written down and --resume cannot tell it from one that stopped")
        return 1
    try:
        asked = task.settle(flow, task.places(flow_path(flow), fm),
                            task.given(sys.argv),
                            task.saved(state.RUNS / pick_up) if pick_up else None,
                            pick_up)
        chosen = models.parse(models.pairs(sys.argv))
        kept = models.load(state.RUNS / pick_up) if pick_up else {}
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
    started_in = resume.workdir(pick_up) if pick_up else ""
    try:
        if started_in and named and where(fm, named) != Path(started_in):
            print(pick_up + " was working in " + started_in + ", not "
                  + named + ". a run carries on where it started")
            return 1
        run = Run(flow, fm, by_role, workdir=started_in or named, task=asked,
                  chosen=chosen)
    except ValueError as e:
        print(str(e))
        return 1
    route = router.Router(fm, cap=2)
    started = datetime.datetime.now()
    run_id = flow + "-" + started.strftime("%Y-%m-%d-%H%M%S")
    timings = []
    risk_text = ""
    out = EMPTY
    came_from = None
    todo = steps(flow)
    if pick_up:
        stopped = resume.last_stop(fm["name"])
        if stopped:
            # a step that died produced nothing, so it runs again. a step that
            # parked produced its output and passed its checks, so the thing
            # that was missing was the person, and the run carries on past it.
            todo = (resume.after(todo, stopped.step) if stopped.parked
                    else resume.remaining(todo, stopped.step))
            if not todo:
                print("nothing left after " + stopped.step + " in " + pick_up)
                return stops.EXIT_OK
            before = steps(flow)[:len(steps(flow)) - len(todo)]
            if before:
                out = Handoff(run.role_for(before[-1]),
                              resume.step_output(pick_up, before[-1]))
                came_from = before[-1]
            print("picking " + pick_up + " up at " + todo[0])
    seen = load_state(flow).get("last_run")
    (state.RUNS / run_id).mkdir(parents=True, exist_ok=True)
    (state.RUNS / run_id / "workdir").write_text(str(run.workdir),
                                                   encoding="utf-8")
    if asked is not None:
        task.save(state.RUNS / run_id, asked)
    models.save(state.RUNS / run_id, chosen)
    trail = trace.Trail(state.RUNS / run_id,
                        after=trace.last_seq(state.RUNS / pick_up)
                        if pick_up else 0)
    if fm.get("journal", True):
        journal(fm["name"], stops.RUNNING, started, run=run_id)
    step = todo[0]
    used = run.provider

    def stop(cause, why, outcome, entry=None, index=None, waiting=None,
             told=None):
        """every way a run ends short goes out through here: the step's line
        and why.md say why, a handoff is left when someone is waited for, and
        the journal line carries the cause and what the run spent.

        -> the exit code.
        """
        at = step or came_from or todo[-1]
        if entry is None and step:
            entry = trail.open(step, run.taken(), used, came_from,
                               fanned=step == run.fan)
        if entry is not None:
            trail.close(entry, outcome, why=why, cause=cause)
        folder = state.RUNS / run_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "why.md").write_text(
            "stopped at " + at + NEWLINE + "cause      " + cause + NEWLINE
            + NEWLINE + why + NEWLINE, encoding="utf-8")
        if waiting:
            again = cause == stops.OUTAGE
            left = (resume.remaining if again else resume.after)(steps(flow),
                                                                 at)
            note = park.write(run_id, fm["name"], at, waiting,
                              [(name, secs) for name, secs, _ in timings],
                              left, resume_command(flow, run_id),
                              runs=state.RUNS,
                              why=why + "," if told is None else told,
                              again=again)
            print("parked at " + at + ", waiting for " + waiting)
            print("it needs you: " + str(note))
        if index:
            write_index(index)
        journal(fm["name"], stops.status(cause, at), started, run=run_id,
                cause=cause, spend=run.budget.summary(), why=why)
        return stops.exit_code(cause)

    try:
        while step:
            used = run.by_step.get(step, run.provider)
            refused = run.refused(step)
            if refused:
                print("refused at " + step + ": " + refused)
                return stop(stops.REFUSED, refused, "refused",
                            entry=trail.open(step, [], used, came_from),
                            index="REFUSED  " + flow + "  " + step)
            print("started " + step)
            if step == run.fan:
                out = run_fanout(run, out)
            else:
                extra = ""
                if step == "planner.md" and fm.get("context"):
                    risk_text, why = context.risk_map(fm.get("context"),
                                                      where=run.workdir)
                    if why:
                        print("no risk map: " + why)
                    run.ranking = risk_text
                    extra = extra + context.as_prompt(risk_text)
                if seen and step == "planner.md":
                    extra = "\n\nthe last run was " + seen + \
                        ". only tell me what is different since then."
                out = run.step(step, previous=out, extra=extra)
            step_dir = state.RUNS / run_id
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / step).write_text(out.output, encoding="utf-8")
            timings.append((step, out.meta.get("seconds", 0),
                            out.meta.get("cached")))
            entry = trail.open(step, run.taken(), used, came_from,
                               output=out.output, fanned=step == run.fan)

            fenced = run.fenced(step)
            if fenced:
                print("fenced at " + step + ": " + fenced)
                return stop(stops.PARKED, fenced, "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user")

            spent = run.budget.over()
            if spent:
                print("stopping: " + spent)
                return stop(stops.BUDGET, spent, "over budget", entry,
                            index="OVER  " + flow + "  " + spent)

            if not out:
                # an empty answer is checked before any gate: a gate handed
                # nothing reports on nothing, and that report reads as the
                # reason the run stopped
                why = out.meta.get("why")
                print("run stopped at " + step + (": " + why if why else ""))
                return stop(stops.NO_ANSWER, why or nothing_why(step, entry),
                            "failed", entry,
                            index="FAILED  " + flow + "  at " + step)

            failed, blocked = check_step(run, route, step, out,
                                         run_dir=step_dir)
            entry.gates = out.meta.get("gates", [])
            entry.ungated = out.meta.get("ungated")
            if failed:
                # a gate is not advice. it was failing the STEP, which meant the
                # run carried on and wrote the output anyway.
                print("gate failed at " + step + ", stopping")
                return stop(stops.GATE, gate_why(out.meta["gates"]),
                            "gate failed", entry,
                            index="GATE  " + flow + "  " + failed + " at "
                            + step)

            hot = []
            if fm.get("context") and run.preflight_for(step):
                hot = preflight.check(out.output, risk_text,
                                      threshold=float(run.preflight_for(step).get(
                                          "threshold", preflight.DEFAULT_THRESHOLD)))
                if hot:
                    mode = run.preflight_for(step).get("mode", "flag")
                    print("preflight: " + str(len(hot)) + " hot file(s) in that step")
                    for path, score in hot:
                        print("  " + path + "  " + str(score))
                    if mode == "refuse":
                        return stop(stops.REFUSED, "hot blast radius: "
                                    + ", ".join(p for p, _ in hot), "refused",
                                    entry, index="REFUSED  " + flow + "  "
                                    + hot[0][0])
                    if mode == "park":
                        why = (step + " touches " + ", ".join(
                            p + " (" + str(s) + ")" for p, s in hot)
                            + ", at or above the " + str(run.preflight_for(step).get(
                                "threshold", preflight.DEFAULT_THRESHOLD))
                            + " the risk map counts as hot")
                        return stop(stops.PARKED, why, "parked", entry,
                                    index="PARKED  " + flow + "  at " + step,
                                    waiting="user")

            # the boundary check reads what came back against what the step was
            # granted. it does not stop the run and it is not meant to: nothing
            # here was in the path of the thing it is reporting, so a stop would
            # be theatre. it is written down beside the gate results instead.
            crossed = boundary.check(out.output, run.grant_for(step))
            if crossed:
                print("boundary: " + step + " came back with " + str(len(crossed))
                      + " thing(s) it was not granted")
                for mark, line in crossed:
                    print("  " + mark.what + "  " + line[:60])
                step_dir = state.RUNS / run_id
                step_dir.mkdir(parents=True, exist_ok=True)
                with open(step_dir / "boundary.md", "a", encoding="utf-8") as bf:
                    bf.write("## " + step + "\n")
                    bf.write(boundary.as_note(crossed))

            if blocked:
                print(blocked + " - not going on")
                return stop(stops.GATE, blocked, "gate failed", entry,
                            index="FAILED  " + flow + "  at " + step)

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
                           " back " + str(route.cap) + " times already,")
                return stop(stops.PARKED,
                            why.rstrip(",") or "waiting for " + waiting,
                            "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting=waiting, told=why)
            trail.close(entry, "redo" if out.verdict == "redo" and nxt else "ok",
                        to=nxt)
            came_from = step
            step = nxt
        return finish(flow, fm, run, out, started, run_id, pick_up)
    except BaseException as e:
        cause = stops.of(e)
        if cause == stops.EXCEPTION:
            traceback.print_exc()
        at = step or came_from or todo[-1]
        if cause == stops.OUTAGE:
            print("provider outage at " + at + ": " + outage_why(e))
            return stop(cause, outage_why(e), "parked", trail.still_open(),
                        index="PARKED  " + flow + "  at " + at,
                        waiting="the limit to reset")
        if cause == stops.INTERRUPT:
            why = "interrupted while " + at + " was running"
        else:
            why = type(e).__name__ + ": " + str(e)
        print("stopped at " + at + ": " + why)
        return stop(cause, why, "crashed", trail.still_open(),
                    index=("INTERRUPTED  " if cause == stops.INTERRUPT
                           else "CRASHED  ") + flow + "  at " + at)


def outage_why(e):
    return ("limit reached, resets " + e.resets + "; the provider said: "
            + e.detail)


def gate_why(results):
    """-> the first failed gate, and what it said."""
    for r in results:
        if not r.ok:
            return r.gate + (": " + r.detail if r.detail else " failed")
    return "a gate failed"


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


def finish(flow, fm, run, out, started, run_id, pick_up):
    """the end of a run that got through every step. -> the exit code."""
    broken = promises.failures(out.output, fm.promises.invariants)
    for inv, detail in broken:
        print("promise broken: " + inv + " (" + detail + ")")
        write_index("BROKE  " + flow + "  " + inv)
    skipped = promises.unchecked(out.output, fm.promises.invariants)
    for inv in skipped:
        print("promise not checked: " + inv)

    path = next_run_path(flow)
    f = open(path, "w", encoding="utf-8")
    f.write(out.output)
    f.close()
    print("saved " + str(path))

    save_state(flow, {"last_run": path.name,
                      "at": datetime.datetime.now().isoformat(),
                      "workdir": str(run.workdir)})

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
                spend=run.budget.summary())

    write_index(path.name + "  " + flow + "  " + str(len(steps(flow))) + " steps")

    if flow == "weekly-digest":
        for section in out.output.split("## "):
            if not section.strip():
                continue
            name = section.split("\n")[0]
            print("## " + name)
            for it in items(section):
                print("  - " + it)
            print("")
    elif flow == "ops-check":
        for line in by_severity(items(out.output)):
            print("- " + line)
    else:
        print(out.output)
    return stops.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
