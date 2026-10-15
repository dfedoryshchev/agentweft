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
                                  promises, redorder, shellwrite, snapshot,
                                  worktree)
from agentweft.guardrails.gates.base import Result
from agentweft.guardrails.gates.redfirst_gate import said_of
from agentweft.guardrails.gates.redtest_gate import named_test
from agentweft.mcp import context, preflight
from agentweft.orchestrate import decisions, park, synthesise

NEWLINE = chr(10)
RED_MARKER = "FAILS:"
from agentweft.guardrails.budget import Budget

from .handoff import EMPTY, Handoff, back, merge, parse, transcript, without
from . import errors
from . import investigate
from .errors import Fatal, Outage, kind_of
from . import prompts
from .prompts import flow_path, load_prompt, read
from . import levels, manifest, models, resume, router, ruling
from .settings import get as setting  # noqa: F401
from . import settings
from . import state
from . import stops
from . import summary
from . import task
from . import trace
from . import wrongtest
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


def console():
    """a character the console has no byte for is printed as `?`.

    a model answers in any script and a Windows console is often cp1252, so
    printing an answer raised after the run's work was done and written down.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


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
        cause = kind.__name__.lower()
        failed[cause] = failed.get(cause, 0) + 1
        if kind is Fatal:
            # going again will not help and it still costs
            raise Fatal(reply.detail, replies=heard, retries=failed)
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
        self.fan = fanout_step(flow)
        self.produced = {}
        self.folder = None
        self.reuse = {}
        self.answers = {}
        self.attempts = []
        self.gate_said = {}
        self.ruled = {}
        self.ranking = ""
        self.budget = Budget(*defaults.for_flow(fm))
        # an override replaces the per-step ones too. half a run on the pinned
        # provider and half on the flow's own is not a comparison of anything.
        if isinstance(provider, providers.Provider):
            pinned = provider
            pinned.where = self.workdir
        else:
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
            grant = s.get("tools")
            if not s.get("provider") and not asked and grant is None:
                continue
            if pinned:
                rebuild = grant is not None and \
                    not isinstance(provider, providers.Provider)
                self.by_step[step_id(s)] = providers.build(
                    provider, where=self.workdir, grant=grant) if rebuild \
                    else pinned
                continue
            conf = dict(s.get("provider") or fm.get("provider") or {})
            tier = ""
            if asked and models.is_tier(asked):
                tier = asked
                if source == "run":
                    conf.pop("model", None)
            elif asked:
                conf["model"] = asked
            p = providers.build(conf, tier=tier, where=self.workdir,
                                grant=grant)
            if asked:
                p.choice = {"role": s["role"], "asked": asked, "from": source,
                            "applies": p.chooses_model()}
            self.by_step[step_id(s)] = p
        self.briefed = briefing.digest(self.workdir)
        self.fence = fence.at(self.workdir, own=state.RUNS)
        self.start = None
        if replays(fm):
            worktree.prune(self.workdir)
        if replays(fm) or redorder.ordered(fm):
            self.start = snapshot.take(self.workdir, own=state.RUNS)
        self.order = redorder.Order(self.start)
        # what a gate ran and saw, by step, handed to the steps after it
        self.proven = {}
        self.tree = summary.tree(self.workdir)
        # every MUST NOT MISS line any step handed over, as (role, line): a
        # constraint read from the spec by the first step binds the last
        self.constraints = []
        # the step that first wrote each test file, by path from the place
        self.authors = {}
        self.test_seen = {}

    def wrote_tests(self, step):
        """note `step` as the writer of each test file it made or changed."""
        start = getattr(self, "start", None)
        if start is None or not start.hashed:
            return
        for rel, now in start.test_changes():
            sha = snapshot._sha(now)
            if self.test_seen.get(rel) == sha:
                continue
            self.test_seen[rel] = sha
            self.authors.setdefault(start.from_place(rel), step)

    def wrong_back(self, step, writer, test, told):
        """send a test `step` called wrong back to `writer`: the claim at the
        end of its prompt, and the red proof that test gave dropped, so the
        corrected test has to be shown red again before product code."""
        self.gate_said[writer] = told
        if writer != step:
            self.gate_said[step] = wrongtest.back_to(writer, test)
        proof = self.order.proof
        path = redorder.norm(test.partition("::")[0])
        if proof and proof.get("how") == "gate" and path in set(
                redorder.norm(f) for f in proof.get("tests") or {}):
            self.order.proof = None

    def keep_in(self, folder):
        """every provider of this run notes a refused shell write in folder."""
        for p in list(self.by_step.values()) + [self.provider]:
            p.denials = folder / shellwrite.FILE

    def rulings(self):
        """-> the decisions on record in the place, as lines."""
        return [summary.stamp(d) for d in decisions.read(self.workdir)]

    def keep(self, role, block):
        for line in block.get("must_not_miss", []):
            if (role, line) not in self.constraints:
                self.constraints.append((role, line))

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

        a step whose provider cannot hold it to its grant is refused too.
        """
        used = self.by_step.get(step, self.provider)
        held = used.refuses()
        if held:
            return held
        if not used.reads_place:
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

    def writes_tests(self, step):
        """whether this step said it writes tests, and so gets the brief."""
        for s in self.fm.steps:
            if step_id(s) == step:
                return bool(s.get("writes_tests"))
        return False

    def writes_for(self, step):
        """tests, product or none: what this step said it writes, or "" when
        it did not say."""
        for s in self.fm.steps:
            if step_id(s) == step:
                return s.get("writes") or ""
        return ""

    def held(self, gate, step):
        """the gate built for `step`, or a pass saying it was not run when
        the run skips tests and it is a test check."""
        order = getattr(self, "order", None)
        if order is not None and order.skip and \
                gate.name in redorder.TEST_GATES:
            return lambda text: Result(gate.name, True, "not run - tests"
                                       " skipped: " + order.skip)
        return gate.run

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
                roles = dict((step_id(o), o["role"]) for o in self.fm.steps)
                said_by = [(roles.get(k, k), t)
                           for k, t in self.produced.items() if k != step]
                return [gates.build(g, where=self.workdir, ranking=self.ranking,
                                    earlier=earlier, said_by=said_by,
                                    start=getattr(self, "start", None),
                                    order=getattr(self, "order", None))
                        for g in (s.get("gates") or [])]
        return []

    def width_for(self, step):
        for s in self.fm.steps:
            if step_id(s) == step:
                return int(settings.get("workers", step=s, flow=self.fm))
        return 1

    def calls_for(self, step, handed):
        """-> the calls `step` is about to make on what it was handed: one,
        or one per task of the fanned step not already done."""
        if step != self.fan:
            return 1
        plan, done = handed, getattr(self, "reuse", {})
        if handed.verdict == "redo" and getattr(self, "plan", None) is not None:
            plan, done = self.plan, {}
        tasks = [l for l in plan.output.split("\n") if "|" in l]
        return max(1, len(tasks) - len(done))

    def charge(self, prompt, answer, provider, model=None):
        """every go the answer took, the failed ones too: each was paid for."""
        replies = getattr(answer, "replies", None)
        if replies is None:
            self.budget.charge(prompt, answer[0], provider=provider,
                               model=model)
            return
        for reply in replies:
            error = None if reply else kind_of(reply).__name__.lower()
            self.budget.charge(prompt, reply, provider=provider, error=error,
                               model=model)

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
        found = self.produced.get(investigate.STEP, "") \
            if step != investigate.STEP else ""
        prompt = investigate.scope(prompt, found)
        if step == investigate.STEP:
            prompt = prompt + investigate.plan_words(self.fm)
        prompt = prompts.put_task(prompt, self.task_text)
        if self.writes_tests(step):
            prompt = prompt + levels.as_prompt(self.fm, self.workdir)
        # the grant goes out with the role's own rules, before whatever this
        # particular call is about. it is the only half of a boundary that can
        # happen before the answer exists, and a step that was never told its
        # grant is one this cannot fairly hold to it afterwards.
        said = self.by_step.get(step, self.provider).granted()
        prompt = prompt + boundary.as_prompt(
            self.grant_for(step),
            shell_writes=said.get("shell_writes") if said else None)
        if extra:
            prompt = prompt + extra
        ran = [line for k, lines in getattr(self, "proven", {}).items()
               if k != step for line in lines]
        if ran:
            prompt = (prompt + "\n\nwhat the runner ran and saw itself, not"
                      " what a step said:\n" + "\n".join(ran))
        block = investigate.handed(found)
        prompt = prompt + block
        reports = self.reports_for(step)
        if reports:
            prompt = prompt + synthesise.brief(reports)
        elif block and previous.role == investigate.INVESTIGATOR:
            # the investigator's findings are handed as its labelled lines;
            # its account of how it got them still travels
            prompt = prompt + previous.as_brief()
        else:
            prompt = prompt + previous.as_prompt()
        # last, so every go at the step shares the whole prompt before it
        prompt = prompt + self.gate_said.get(step, "")
        prompt = prompt + getattr(self, "ruled", {}).get(step, "")
        tried = trace.Attempt(task)
        self.attempts.append(tried)
        used = self.by_step.get(step, self.provider)
        used.at(step, task)
        try:
            answer = tried.answered(self.ask(prompt, step, used))
        except (Outage, Fatal) as e:
            refused = tried.answered(Answer("", False, e.replies, e.retries))
            self.charge(prompt, refused, used.name, used.asks_for())
            raise
        text, cached = answer
        self.produced[step] = text
        if not cached:
            # a cached answer costs nothing and was counting against the cap,
            # so a flow with a redo in it hit the ceiling on work it never did
            self.charge(prompt, answer, used.name, used.asks_for())
        block = back(parse(text), transcript(trace.last(tried, "session")))
        self.keep(role, block)
        return Handoff(role, text, verdict(text, asked=asked),
                       meta={"seconds": round(_t.time() - began, 1),
                             "cached": cached, "provider": used.name,
                             "asked": asked, "rulings": self.rulings()},
                       block=block, carried=list(self.constraints))


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

    done = getattr(run, "reuse", {}) if back is EMPTY else {}
    run.reuse = {}
    folder = getattr(run, "folder", None)

    def one(i):
        kept = done.get((i + 1, tasks[i]))
        if kept is not None:
            part = Handoff(role, kept["output"], kept["verdict"],
                           meta={"asked": kept["asked"]})
        else:
            part = run.step(run.fan, previous=back,
                            extra="\n\nyour task, only this one:\n\n"
                            + tasks[i], task=i + 1)
        if folder is not None and part:
            manifest.task_done(folder, run.fan, i + 1, tasks[i], part)
        return part

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
                        "asked": any(p.meta.get("asked") for p in parts),
                        "rulings": run.rulings()},
                  block=merge(p.block for p in parts),
                  carried=list(run.constraints))
    # every task went through Run.step, so what it recorded is whichever one
    # finished last. the joined output is what the step actually produced.
    run.produced[run.fan] = out.output
    return out


def replays(fm):
    """whether any step of the flow has a red-first gate, which needs the
    place as the run found it."""
    return any(g.get("gate") == "red-first" for s in fm.steps
               for g in (s.get("gates") or []))


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
        return redorder.carry_run(folder, name, run.start)
    return redorder.carry_commit(run.start, name, redorder.test_command(fm))


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
    results = [held(g, step)(without(out.output)) for g in run.gates_for(step)]
    order = getattr(run, "order", None)
    if order is not None:
        moved = order.after(step, run.writes_for(step))
        if moved:
            results.insert(0, Result("tests-only", False, moved))
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


def run_once(flow, provider=None, task=None, trail=None):
    """run a flow and hand back what it produced, what it cost, and why it
    stopped short ("" when it did not). the eval harness wants the output, not
    the printing, and it wants to say which provider the whole thing runs on.

    `trail` is a folder to write the run's steps.jsonl into, the same lines a
    run of `main` writes, for a case that asserts the steps it took."""
    fm = config(flow)
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    run = Run(flow, fm, by_role, provider=provider, task=task)
    route = router.Router(fm)
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
        entry.gates = out.meta.get("gates", []) if output is not None else []
        entry.ungated = out.meta.get("ungated") if output is not None else None
        entry.handoff = out.block if output is not None else None
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
        run.order.watch(step, writes)
        try:
            if step == run.fan:
                out = run_fanout(run, out)
            else:
                out = run.step(step, previous=out)
            run.gate_said.pop(step, None)
        except Outage as e:
            note("parked", outage_why(e), stops.OUTAGE)
            return (out.output, run.budget, "provider outage at " + step
                    + ": " + outage_why(e))
        run.wrote_tests(step)
        fenced = run.fenced(step)
        if fenced:
            note("parked", fenced, stops.PARKED, output=out.output)
            return out.output, run.budget, "fenced at " + step + ": " + fenced
        if not out:
            why = out.meta.get("why") or "nothing came out of " + step
            note("failed", why, stops.NO_ANSWER, output=out.output)
            return out.output, run.budget, why
        wrong = wrongtest.judge(out.output, step, run, route)
        if wrong and wrong[0] == "back":
            _, writer, test, told = wrong
            note("redo", test + " is wrong, back to " + writer, to=writer,
                 output=out.output)
            run.wrong_back(step, writer, test, told)
            out = given.get(writer, EMPTY)
            came_from = step
            step = writer
            continue
        if wrong:
            note("parked", wrong[1], stops.PARKED, output=out.output)
            return (out.output, run.budget, "parked at " + step
                    + " for a ruling: " + wrong[1].split("\n")[0])
        said = ruling.asked_of(out.output, run.workdir)
        if said and said[0] == ruling.DECLINED:
            note("refused", said[1], stops.DECLINED, output=out.output)
            return out.output, run.budget, ""
        if said:
            note("parked", said[1], stops.PARKED, output=out.output)
            return (out.output, run.budget, "parked at " + step
                    + " for a ruling: " + said[1].split("\n")[0])
        failed, blocked = check_step(run, route, step, out)
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
            run.order.proven(step, out.meta["gates"], out.output)
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


def main():
    console()
    load_env()
    if "--flows" in sys.argv:
        prompts.FLOW_ROOT[0] = sys.argv[sys.argv.index("--flows") + 1]
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
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
        known = ", ".join(sorted(p.name for p in Path(prompts.FLOW_ROOT[0]).iterdir()
                                 if p.is_dir() and not p.name.startswith("_")))
        print("no flow called " + flow + ". there is: " + known)
        return 1
    except ValueError as e:
        print(flow + "/flow.yaml is wrong: " + str(e))
        return 1
    if resuming and not fm.get("journal", True):
        print(flow + " has journal: false, so a run that finished is never "
              "written down and --resume cannot tell it from one that stopped")
        return 1
    skip = valued("--skip-tests")
    if skip is not None and not skip:
        print("--skip-tests needs a reason: --skip-tests \"<why this run has"
              " no tests>\"")
        return 1
    carry = valued("--continue")
    if carry is not None and not carry:
        print("--continue needs the run or the commit whose tests it carries")
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
            print("  " + resume_command(flow, pick_up) + park.ANSWER)
            return stops.EXIT_STOP
    if answer is not None and question is None:
        print(pick_up + " is not waiting for a ruling, so --answer has nothing"
              " to answer")
        return 1
    try:
        asked = task.settle(flow, task.places(flow_path(flow), fm),
                            task.given(sys.argv),
                            (found.task if found else
                             task.saved(state.RUNS / pick_up))
                            if pick_up else None,
                            pick_up)
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
    started_in = ""
    if pick_up:
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
    try:
        if started_in and named and where(fm, named) != Path(started_in):
            print(pick_up + " was working in " + started_in + ", not "
                  + named + ". a run carries on where it started")
            return 1
        run = Run(flow, fm, by_role, workdir=started_in or named, task=asked,
                  chosen=chosen)
        if pick_up and run.start is not None:
            # a snapshot taken now would count the tests the first run wrote
            # as already there
            run.start = snapshot.load(state.RUNS / pick_up) or \
                snapshot.Snapshot(run.workdir, why="resumed, start state not"
                                  " kept")
            run.order.start = run.start
    except ValueError as e:
        print(str(e))
        return 1
    if pick_up:
        run.order.skip, run.order.proof = redorder.load(state.RUNS / pick_up)
        lost = run.order.recheck()
        if lost:
            print("the red proof " + pick_up + " held is dropped: " + lost)
    if skip:
        run.order.skip = skip
        notes.append(("tests skipped for this run", skip + NEWLINE
                      + "given with --skip-tests: the red-test and red-first"
                      " gates and the test order checks did not run."))
    if carry:
        run.order.proof, why = carried(carry, run, fm)
        if why:
            print("nothing carried from " + carry + ": " + why)
            return 1
        notes.append(("tests carried from " + run.order.proof["from"],
                      "given with --continue " + carry + ": "
                      + ", ".join(sorted(run.order.proof["tests"]))))
    try:
        for key, value in caps_given(sys.argv).items():
            setattr(run.budget, key, value)
    except ValueError as e:
        print(str(e))
        return 1
    if found:
        run.budget.restore(found.spend)
        waits = run.budget.ahead()
        if waits:
            print(pick_up + " is at its cap (" + waits[1] + "). carry on with"
                  " --resume " + pick_up + " --max-calls <n> or --max-tokens"
                  " <n>, or raise max_calls or max_tokens in " + flow
                  + "/flow.yaml and add --force")
            return 1
        moved = run.budget.moved(found.spend)
        if moved:
            notes.append(("carried " + pick_up + " on with the "
                          + ", the ".join(moved),
                          (found.data.get("stopped") or {}).get("why")
                          or "the caps were changed before carrying on."))
    route = router.Router(fm)
    started = datetime.datetime.now()
    run_id = new_run_id(flow, started)
    timings = []
    risk_text = ""
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
        if before:
            came_from = before[-1]
            held = found.step(came_from) if found else None
            source = (held or {}).get("in") or pick_up
            out = Handoff(run.role_for(came_from),
                          resume.step_output(source, came_from),
                          meta={"rulings": run.rulings()},
                          carried=list(run.constraints))
            if held and held.get("digest") and \
                    manifest.of_text(out.output) != held["digest"]:
                print(came_from + " was edited after " + source
                      + " wrote it; the rest of the run works from the edit")
                notes.append((came_from + " was edited by hand before " + run_id
                              + " carried on",
                              "runs/" + source + "/" + came_from + " is not "
                              "what " + came_from + " produced, and what "
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
        if investigate.on(fm) and investigate.STEP not in todo:
            held = found.step(investigate.STEP) if found else None
            run.produced[investigate.STEP] = resume.step_output(
                (held or {}).get("in") or pick_up, investigate.STEP)
        print("picking " + pick_up + " up at " + start)
    seen = state.last_output(flow, run.workdir, asked)
    folder = state.RUNS / run_id
    folder.mkdir(parents=True, exist_ok=True)
    run.folder = folder
    run.keep_in(folder)
    (folder / "workdir").write_text(str(run.workdir), encoding="utf-8")
    if run.start is not None and run.start.hashed:
        run.start.save(folder)
    if redorder.ordered(fm) or run.order.skip or run.order.proof:
        run.order.save(folder)
    if asked is not None:
        task.save(folder, asked)
    models.save(folder, chosen)
    if found:
        record = found.carried(folder, run_id, order, shape,
                               workdir=str(run.workdir))
    else:
        record = manifest.Manifest.new(folder, run_id, flow, fm["name"], order,
                                       shape, task=asked, models=chosen,
                                       workdir=run.workdir, origin=origin,
                                       resumes=pick_up)
        for name in order[:order.index(start)]:
            record.mark(name, manifest.PASSED, pick_up)
    record.save(run.budget)
    for decided, why in notes:
        decisions.record(folder, decided, why)
    if answer is not None:
        decisions.record(run.workdir, ruling.decided(start, answer),
                         ruling.why(start, pick_up, question, answer,
                                    ruling.who()))
        run.ruled[start] = ruling.told(question, answer)
        print("ruled: " + start + " runs again with the answer")
    trail = trace.Trail(folder,
                        after=trace.last_seq(state.RUNS / pick_up)
                        if pick_up else 0)
    if fm.get("journal", True):
        journal(fm["name"], stops.RUNNING, started, run=run_id, origin=origin)
    step = todo[0]
    used = run.provider
    wrote = set()
    # what each step was handed, for a step a wrong test sends the work back to
    given = {}
    # a run parked before a step is carried on by the person who read why, so
    # that step is not checked again on what it was handed the first time round
    cleared = None
    if found and (found.data.get("stopped") or {}).get("step") == start \
            and found.data["stopped"].get("cause") == stops.PARKED \
            and (found.step(start) or {}).get("state") == manifest.NOT_RUN:
        cleared = start

    def leave(stopped=None, needs=None):
        """write the run's handoff.md from what the runner knows, and hand
        back (its path, its lines)."""
        ran = passes(trail, run, fm)
        record.ended(summary.outcome(stopped, summary.unproven(
            list(earlier) + ran)))
        record.save(run.budget)
        lines = summary.build(run_id, fm["name"], asked, ran,
                              run.tree.changes(), decisions.read(run.workdir),
                              run.budget.summary(), stopped=stopped,
                              needs=needs, command=resume_command(flow, run_id),
                              before=earlier, started=started,
                              found=run.produced.get(investigate.STEP, ""),
                              order=run.order.said())
        return summary.write(state.RUNS / run_id, lines), lines

    def stop(cause, why, outcome, entry=None, index=None, waiting=None,
             told=None, at=None, handed=None, question=None):
        """every way a run ends short goes out through here: the step's line
        and why.md say why, handoff.md says all of it with a "needs you"
        section when someone is waited for, and the journal line carries the
        cause, what the run spent and where the handoff is. `at` is the step
        the run stopped at, when that is not the one that ran. `handed` is
        the step whose output `at` was handed, for a park before `at` ran:
        the step stays not run, so carrying on starts at it. `question` is
        what the step asked instead of doing the work: the run waits for a
        ruling, and carrying on runs the step again with the answer.

        -> the exit code.
        """
        at = at or step or came_from or todo[-1]
        if entry is None and step:
            entry = trail.open(step, run.taken(), used, came_from,
                               fanned=step == run.fan)
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
        parked = cause == stops.PARKED
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
                    question=question)
        record.save(run.budget)
        remember(flow, run, run_id, stops.status(cause, at))
        done = [(name, secs) for name, secs, _ in timings]
        if question:
            needs = park.lines(at, waiting, done,
                               resume.remaining(steps(flow), at),
                               resume_command(flow, run_id),
                               question=question)
            print("parked at " + at + ", waiting for a ruling")
        elif cause == stops.DECLINED:
            needs = park.refused(at, why, done)
        elif waiting:
            again = cause == stops.OUTAGE
            left = (resume.remaining if again or handed else resume.after)(
                steps(flow), at)
            needs = park.lines(at, waiting, done, left,
                               resume_command(flow, run_id),
                               why=why + "," if told is None else told,
                               again=again, handed=handed)
            print("parked at " + at + ", waiting for " + waiting)
        else:
            told = why
            if cause == stops.BUDGET:
                told = (why + NEWLINE + "raise the cap to carry on: add"
                        " --max-calls <n> or --max-tokens <n> to the command"
                        " below, or edit max_calls or max_tokens in " + flow
                        + "/flow.yaml. a resume starts at what this run"
                        " spent.")
            needs = park.lines(at, None, done, resume.remaining(steps(flow), at),
                               resume_command(flow, run_id), why=told,
                               cause=cause, handed=handed)
        note = leave({"cause": cause, "why": why, "at": at}, needs)
        if index:
            write_index(index)
        journal(fm["name"], stops.status(cause, at), started, run=run_id,
                cause=cause, spend=run.budget.summary(), why=why,
                origin=origin, handoff=run_id + "/" + summary.FILE)
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

    switched = False
    try:
        while step:
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
            if waits:
                why = (waits[0] + ", completion " + completion(record, order)
                       + ", " + waits[1])
                print("paused before " + step + ": " + why)
                return stop(stops.BUDGET, why, "parked",
                            index="PARKED  " + flow + "  at " + step,
                            handed=came_from or "the task")
            allowed = set()
            unchecked = False
            pre = run.preflight_for(step)
            # the planner is the step that fetches the map, so before it runs
            # there is no ranking yet to read its handed text against
            if pre and not (step == "planner.md" and fm.get("context")):
                threshold = float(pre.get("threshold",
                                          preflight.DEFAULT_THRESHOLD))
                ahead = preflight.check(out.output, risk_text,
                                        threshold=threshold)
                if ahead is None:
                    unchecked = True
                    if step != cleared:
                        print("preflight: " + preflight.NO_RANKING + ", "
                              + step + " not checked")
                        if pre.get("mode", "flag") in ("park", "refuse"):
                            return stop(stops.PARKED, step + " was not checked: "
                                        + preflight.NO_RANKING, "parked",
                                        index="PARKED  " + flow + "  at " + step,
                                        waiting="user",
                                        handed=came_from or "the task")
                elif ahead and step == cleared:
                    allowed = set(p for p, _ in ahead)
                elif ahead:
                    print("preflight: " + step + " was handed " + str(len(ahead))
                          + " hot file(s)")
                    for path, score in ahead:
                        print("  " + path + "  " + str(score))
                    mode = pre.get("mode", "flag")
                    if mode == "refuse":
                        return stop(stops.REFUSED, "hot blast radius: "
                                    + ", ".join(p for p, _ in ahead),
                                    "refused", index="REFUSED  " + flow + "  "
                                    + ahead[0][0])
                    if mode == "park":
                        return stop(stops.PARKED, step + " was handed "
                                    + ", ".join(p + " (" + str(s) + ")"
                                                for p, s in ahead)
                                    + ", at or above the " + str(threshold)
                                    + " the risk map counts as hot, and was"
                                    " parked before it ran", "parked",
                                    index="PARKED  " + flow + "  at " + step,
                                    waiting="user",
                                    handed=came_from or "the task")
            cleared = None
            run.order.watch(step, writes)
            print("started " + step)
            handed = out
            given[step] = handed
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

            fenced = run.fenced(step)
            if fenced:
                print("fenced at " + step + ": " + fenced)
                return stop(stops.PARKED, fenced, "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user")


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
                return stop(stops.NO_ANSWER, why or nothing_why(step, entry),
                            "failed", entry,
                            index="FAILED  " + flow + "  at "
                            + (blamed or step), at=blamed)

            wrong = wrongtest.judge(out.output, step, run, route)
            if wrong and wrong[0] == "back":
                _, writer, test, told = wrong
                print(step + " says " + test + " is wrong, sent back to "
                      + writer)
                trail.close(entry, "redo", why=test + " is wrong, back to "
                            + writer, to=writer)
                record.mark(step, manifest.REDO, run_id, out.output)
                record.save(run.budget)
                run.wrong_back(step, writer, test, told)
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

            said = ruling.asked_of(out.output, run.workdir)
            if said and said[0] == ruling.DECLINED:
                print("refused at " + step + ": " + said[1])
                return stop(stops.DECLINED, said[1], "refused", entry)
            if said:
                print(step + " asks for a ruling")
                return stop(stops.PARKED, "needs a ruling: "
                            + said[1].split(NEWLINE)[0][len("NEEDS: "):],
                            "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=said[1])

            failed, blocked = check_step(run, route, step, out,
                                         run_dir=step_dir)
            entry.gates = out.meta.get("gates", [])
            entry.ungated = out.meta.get("ungated")
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
                run.order.save(folder)

            hot = []
            if run.preflight_for(step):
                hot = preflight.check(out.output, risk_text,
                                      threshold=float(run.preflight_for(step).get(
                                          "threshold", preflight.DEFAULT_THRESHOLD)))
                if hot is None and not unchecked:
                    mode = run.preflight_for(step).get("mode", "flag")
                    print("preflight: " + preflight.NO_RANKING + ", " + step
                          + " not checked")
                    if mode in ("park", "refuse"):
                        return stop(stops.PARKED, step + " was not checked: "
                                    + preflight.NO_RANKING, "parked", entry,
                                    index="PARKED  " + flow + "  at " + step,
                                    waiting="user")
                elif hot:
                    mode = run.preflight_for(step).get("mode", "flag")
                    print("preflight: " + str(len(hot)) + " hot file(s) in that step")
                    for path, score in hot:
                        print("  " + path + "  " + str(score))
                    fresh = [h for h in hot if h[0] not in allowed]
                    if fresh and mode == "refuse":
                        return stop(stops.REFUSED, "hot blast radius: "
                                    + ", ".join(p for p, _ in fresh), "refused",
                                    entry, index="REFUSED  " + flow + "  "
                                    + fresh[0][0])
                    if fresh and mode == "park":
                        why = (step + " touches " + ", ".join(
                            p + " (" + str(s) + ")" for p, s in fresh)
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
            trail.close(entry, "redo" if sent_back else "ok", to=nxt)
            record.mark(step, manifest.REDO if sent_back else manifest.PASSED,
                        run_id, out.output)
            record.save(run.budget)
            came_from = step
            step = nxt
        return finish(flow, fm, run, out, started, run_id, pick_up, leave,
                      record, origin)
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


CAPS = (("--max-calls", "max_calls"), ("--max-tokens", "max_tokens"))


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


def completion(record, order):
    passed = [s for s in record.data["steps"] if s["state"] == manifest.PASSED]
    return str(len(passed)) + "/" + str(len(order)) + " steps"


def passes(trail, run, fm):
    """-> every pass the trail closed, in the shape the handoff is built
    from: its gates with their commands, its block, its outcome."""
    out = []
    for entry, outcome in trail.closed:
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
                                  summary._gates(entry.gates, commands),
                                  entry.ungated, outcome, said))
    return out


def show(note):
    """the run's last words: the top of its handoff, then where the whole
    of it is. the path is the last line so a person or a script scrolling up
    from the end finds it first."""
    path, lines = note
    for line in summary.top(lines):
        print(line)
    print("handoff: " + str(path))


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
           origin=None):
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

    note = leave()
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


if __name__ == "__main__":
    sys.exit(main())
