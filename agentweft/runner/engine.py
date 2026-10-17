import concurrent.futures
import datetime
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

from agentweft.roles import resolver

from .config import (VERDICTS, asks_for_verdict, config, declared, due,
                     fanout_step, steps, verdict, where)
from agentweft import providers
from agentweft.flow.spec import (RESUME, lead_of, step_id, step_name,
                                 steps_named)
from agentweft.guardrails import (baseline, boundary, briefing, defaults,
                                  fence, gates, promises, redorder, rulings,
                                  shellwrite, signoff, skips, snapshot,
                                  specfiles, starttests, testedits, worktree)
from agentweft.guardrails.gates.base import Result
from agentweft.guardrails.gates.redfirst_gate import said_of
from agentweft.guardrails.gates.redtest_gate import named_test
from agentweft.mcp import context, preflight
from agentweft.orchestrate import decisions, park, synthesise

NEWLINE = chr(10)
RED_MARKER = "FAILS:"
from agentweft.guardrails.budget import REACHING, Budget
from agentweft.guardrails import blocks, sacrifice

from .handoff import EMPTY, Handoff, back, merge, parse, transcript, without
from . import brief as kept
from . import errors
from . import investigate
from .errors import Fatal, Outage, kind_of
from . import prompts
from .prompts import flow_path, load_prompt, read
from . import commits
from . import (chain, fan, lead, leftred, levels, manifest, models, resume,
               retro, router, ruling, warm)
from .settings import get as setting  # noqa: F401
from . import settings
from . import state
from . import stops
from . import summary
from . import task
from . import trace
from . import worktrees
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
    """output piped to a file or a program is UTF-8; on a terminal a
    character the console has no byte for is printed as `?`.

    a model answers in any script and a Windows console is often cp1252, so
    printing an answer raised after the run's work was done and written down.
    a PYTHONIOENCODING the person set is kept.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty() or os.environ.get("PYTHONIOENCODING"):
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
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


def first_reader(flow, fm, order, start):
    """-> the first step in `order` that is handed the request, never one
    after `start`. everything from there was done against the request as it
    was, so a request amended by a ruling runs it all again."""
    where = task.places(flow_path(flow), fm)
    for name in order:
        if name == start or "instructions.md" in where or name in where:
            return name
    return start


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
                 task=None, chosen=None, efforts=None):
        self.flow = flow
        self.chosen = dict(chosen or {})
        self.efforts = dict(efforts or {})
        self.ups = {}
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
        self.caps = {}
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
        if retro.on(fm):
            self.by_step[retro.STEP] = pinned if isinstance(
                provider, providers.Provider) else providers.build(
                    provider or fm.get("provider") or {}, where=self.workdir,
                    grant=retro.GRANT)
        self.briefed = briefing.digest(self.workdir)
        self.fence = fence.at(self.workdir, own=state.RUNS)
        self.start = None
        self.suite = baseline.mode(fm)
        self.baseline = None
        if replays(fm) or self.suite == baseline.ON:
            worktree.prune(self.workdir)
        self.commits = commits.mode(fm)
        if replays(fm) or redorder.ordered(fm) or fm.get("spec_files") \
                or self.suite == baseline.ON or self.reads_spec() \
                or self.commits != commits.NONE:
            self.start = snapshot.take(self.workdir, own=state.RUNS)
        self.order = redorder.Order(self.start,
                                    cmd=redorder.test_command(fm))
        self.committer = commits.Committer(commits.NONE, None)
        # what a gate ran and saw, by step, handed to the steps after it
        self.proven = {}
        self.tree = summary.tree(self.workdir)
        # every MUST NOT MISS line any step handed over, as (role, line): a
        # constraint read from the spec by the first step binds the last
        self.constraints = []
        self.brief = kept.Brief(self.workdir, [step_id(s) for s in fm.steps])
        # the step that first wrote each test file, by path from the place
        self.authors = {}
        self.test_seen = {}
        self.start_green = {}
        # the step a question goes to before the operator, and what it
        # decided, by question
        self.lead = lead_of(fm)
        self.led = {}
        self.kept = rulings.Kept(self.workdir)
        self.forged = {}
        # the session each `continue: resume` step carries on, by step, and
        # the steps in a call now; the warmer reads both from its own thread
        self.sessions = {}
        self.busy = set()
        self.lock = threading.Lock()
        self.record = None

    def decided(self):
        """-> the rulings in decisions.md the runner has on record."""
        kept = getattr(self, "kept", None)
        if kept is None:
            return decisions.read(Path(self.workdir))
        return kept.read()

    def rule(self, decided, why, by):
        """write a ruling to decisions.md and to the runner's own record."""
        kept = getattr(self, "kept", None)
        if kept is None:
            return decisions.record(Path(self.workdir), decided, why)
        return kept.record(decided, why, by)

    def held_rulings(self, step):
        """note why `step` fails when it changed decisions.md."""
        kept = getattr(self, "kept", None)
        said = kept.check(step) if kept is not None else ""
        if said:
            forged = getattr(self, "forged", None)
            if forged is None:
                forged = self.forged = {}
            forged[step] = said

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
        self.ups[writer] = self.ups.get(writer, 0) + 1
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
        return [summary.stamp(d) for d in self.decided()]

    def suite_baseline(self):
        """-> the state of the suite the run started from, read from the
        cache or run once and kept in the run's folder; None when the flow
        says `baseline: off` or there is none to have."""
        if self.suite == baseline.OFF or self.order.skip:
            return None
        if self.baseline is None:
            found, why = baseline.ensure(self.start,
                                         redorder.test_command(self.fm),
                                         state.RUNS)
            self.baseline = found or {"why": why}
            if found and self.folder is not None:
                baseline.save(found, self.folder)
        return self.baseline if "tests" in self.baseline else None

    def known_at_start(self):
        found = self.suite_baseline()
        if found is None:
            return starttests.tests_in(
                self.start, starttests.modules(self.start),
                starttests.base_of(redorder.test_command(self.fm)),
                starttests.TIMEOUT, now=False)
        return baseline.outcomes(found), ""

    def replayed(self, step):
        """-> (the start tests' line for the record or None, (why, question)
        when a test green at the start is red now and no ruling covers it,
        else None). only after a `writes: product` step, and never when the
        run skips tests."""
        if self.writes_for(step) != "product" or self.order.skip:
            return None, None
        known = None if self.suite == baseline.OFF else self.known_at_start
        found = starttests.replay(self.start, redorder.test_command(self.fm),
                                  green=self.start_green, known=known)
        if not found.red:
            return found.result, None
        decided = self.decided()
        left, ruled = [], []
        for test, said in found.red:
            d = ruling.covering(decided, test, self.workdir, self.start)
            if d is None:
                left.append((test, said))
            else:
                ruled.append(test + " (ruling " + summary.stamp(d) + ")")
        if not left:
            return Result(starttests.NAME, True, "red now, each covered by a"
                          " ruling: " + ", ".join(ruled)), None
        line = Result(starttests.NAME, False, starttests.said_of(left))
        return line, ("spec conflict: " + line.detail,
                      ruling.question_of_start_tests(step, left))

    def spec_held(self, step, ok=True):
        """-> (the spec files' line for the record or None, (why, question)
        when a line the run started with is removed or rewritten and no
        ruling quotes it, else None). a `read-only` flow fails the step on
        any change; an `additions` flow is only read once the step's other
        gates passed, since one that failed sends the step back anyway."""
        mode = self.fm.get("spec_files")
        if not mode:
            return None, None
        found = specfiles.changes(getattr(self, "start", None))
        if not found:
            return None, None
        if mode == specfiles.READ_ONLY:
            return specfiles.read_only(step, found), None
        if not ok:
            return None, None
        decided = self.decided()
        left, ruled = [], []
        for rel, was, now in found:
            for n, line, there in specfiles.lost(was, now):
                d = ruling.spec_line_ruled(decided, line)
                if d is None:
                    left.append((rel, n, line, there))
                else:
                    ruled.append((rel, n, summary.stamp(d)))
        if not left:
            return specfiles.passed(found, ruled), None
        line = specfiles.held(left)
        return line, ("needs a ruling: " + line.detail,
                      ruling.question_of_spec_lines(step, left))

    def reads_spec(self):
        """whether any step's prompt names the spec as the run found it."""
        for s in self.fm.steps:
            try:
                text = load_prompt(self.flow, step_id(s),
                                   self.by_role.get(s["role"], ""), s["role"])
            except (FileNotFoundError, KeyError, AttributeError, TypeError):
                continue
            if prompts.reads_spec(text):
                return True
        return False

    def spec_unruled(self):
        """-> "path:line" for each line of the spec that moved since the run
        started, added, removed or rewritten, with no ruling in decisions.md
        quoting it. added lines count only when the flow's `spec_files:` is
        not `additions`."""
        found = specfiles.changes(getattr(self, "start", None))
        if not found:
            return []
        mode = self.fm.get("spec_files")
        decided = self.decided()
        return [rel + ":" + str(n) for rel, was, now in found
                for n, line in specfiles.moved(was, now, mode)
                if ruling.spec_line_ruled(decided, line) is None]

    def tests_held(self, step, last=False):
        """-> (the line for the record when a test file the run started with
        changed, else None; (why, question) when it changed in a way no
        ruling covers and this is the step's `last` go, else None). a step
        with a go left fails like a gate and goes back."""
        start = getattr(self, "start", None)
        found = testedits.changes(start)
        if not found:
            return None, None
        decided = self.decided()
        left, ruled = [], []
        for edit in found:
            for test, how in edit.items:
                d = ruling.edit_ruled(decided, test, self.workdir, start)
                if d is None:
                    left.append((test, how))
                else:
                    ruled.append((test, summary.stamp(d)))
        if not left:
            return testedits.passed(found, ruled), None
        line = testedits.held(step, left)
        if not last:
            return line, None
        return line, ("needs a ruling: " + line.detail,
                      ruling.question_of_test_edits(step, left))

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

    def provider_for(self, step):
        return self.by_step.get(step, self.provider)

    def continues(self, step):
        for s in self.fm.steps:
            if step_id(s) == step:
                return s.get("continue") == RESUME
        return False

    def carry_for(self, step, used, head):
        """-> what the call `step` is about to make carries on: None for a
        step that starts fresh every time, {"from": None} for one that
        starts a session to carry on later, else the session it kept.

        the session is carried on only while the step would be started the
        same way: the same model, and the same words before what is new to
        it. a model change or an amended task starts it fresh, with the
        whole prompt and the handoff in it."""
        if not self.continues(step) or not used.continues():
            return None
        with self.lock:
            kept = dict(self.sessions.get(step) or {})
        if kept and kept.get("model") == used.asks_for() \
                and kept.get("head") == manifest.of_text(head) \
                and used.holds(kept.get("id")):
            return providers.base.carry_of(kept)
        return {"from": None}

    def keep_session(self, step, used, head, answer, carry):
        """note the session the step's answer left, for its next call. a
        session that would not carry on is dropped, so the next call starts
        the step fresh rather than failing on it again."""
        if carry is None or answer[1]:
            return
        kept = None
        for reply in getattr(answer, "replies", ()):
            if reply and reply.session and reply.kept is not None:
                kept = reply
        with self.lock:
            was = self.sessions.get(step) or {}
            if kept is not None:
                usage = kept.kept.get("usage")
                self.sessions[step] = {
                    "id": kept.session, "model": used.asks_for(),
                    "head": manifest.of_text(head), "usage": usage,
                    "models": kept.kept.get("models"),
                    "cost": kept.kept.get("cost"), "at": time.time(),
                    "lifetime": warm.lifetime(usage, was.get("lifetime")),
                    "warmed": 0}
            elif carry.get("from"):
                self.sessions.pop(step, None)
            else:
                return
        if self.record is not None:
            self.record.data["sessions"] = self.sessions
            self.record.save(self.budget)

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
        the run skips it by name, or skips tests and it is a test check."""
        reason = (getattr(self, "skipped", None) or {}).get(gate.name)
        if reason:
            return lambda text: Result(gate.name, True, "not run - skipped: "
                                       + reason, skipped=True)
        order = getattr(self, "order", None)
        if order is not None and order.skip and \
                gate.name in redorder.TEST_GATES:
            return lambda text: Result(gate.name, True, "not run - tests"
                                       " skipped: " + order.skip, skipped=True)
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

    def effort_for(self, step, used):
        """-> what the step's line keeps about how hard its model is asked to
        think: the level asked ("provider default" for none), the step's own
        base, how many send-backs raised it, and whether the
        provider acts on it."""
        level = None
        for s in self.fm.steps:
            if step_id(s) == step:
                level, _ = models.effort_of(s, self.fm, self.efforts)
        base = level or used.own_effort() or None
        ups = self.ups.get(step, 0) if base else 0
        return {"asked": providers.base.raised(base, ups) if base
                else "provider default",
                "base": base, "raised": ups,
                "applies": used.chooses_effort()}

    def verbosity_for(self, step):
        """-> the step's `verbosity`, None when it names none."""
        for s in self.fm.steps:
            if step_id(s) == step:
                return s.get("verbosity")
        return None

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
        return max(1, len(fan.tasks(plan.output)) - len(done))

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
        key = (used, prompt, used.going, (used.carry or {}).get("from"))
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

    def step(self, step, previous=EMPTY, extra="", task=None, last=""):
        import time as _t

        began = _t.time()
        role = self.role_for(step)
        prompt = load_prompt(self.flow, step, self.by_role[role], role)
        terse = self.verbosity_for(step) == "terse"
        if terse:
            prompt = prompt + resolver.fragment("terse")
        # read before anything is appended or the task is put in: what an
        # earlier step produced, or a task quoting a review, can carry its own
        # verdict line, and that does not ask this one for one
        asked = asks_for_verdict(prompt)
        reviews_spec = asked and prompts.reads_spec(prompt)
        found = self.produced.get(investigate.STEP, "") \
            if step != investigate.STEP else ""
        prompt = investigate.scope(prompt, found)
        if step == investigate.STEP:
            prompt = prompt + investigate.plan_words(self.fm)
        prompt = prompts.put_spec(prompt, getattr(self, "start", None))
        notes = getattr(self, "brief", None)
        briefed = notes.text(step) if notes else ""
        prompt = prompts.put_brief(prompt, briefed)
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
        # everything after this is what a step carrying its session on has
        # not been sent already
        head = prompt
        # the brief quotes files as they are now, so a step's own edit between
        # its goes would move a head that holds nothing new for it
        held = head.replace(briefed, notes.key(step), 1) if briefed else head
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
        prompt = prompt + getattr(self, "ruled", {}).get(step, "") + last
        tried = trace.Attempt(task)
        self.attempts.append(tried)
        used = self.by_step.get(step, self.provider)
        used.at(step, task)
        tried.effort = self.effort_for(step, used)
        used.going = tried.effort["base"] and tried.effort["asked"]
        used.terse = terse
        if terse:
            limit = used.output_limit()
            tried.verbosity = {"asked": "terse", "limit": limit,
                               "applies": limit is not None}
        carry = getattr(self, "sessions", None) is not None \
            and self.carry_for(step, used, held)
        used.carry = carry or None
        sent = prompt
        if carry and carry.get("from"):
            tried.continued = carry["from"]
            sent = prompts.CARRIED_ON + prompt[len(head):]
        if step != getattr(self, "fan", None):
            getattr(self, "forged", {}).pop(step, None)
        if carry:
            with self.lock:
                self.busy.add(step)
        try:
            answer = tried.answered(self.ask(sent, step, used))
        except (Outage, Fatal) as e:
            refused = tried.answered(Answer("", False, e.replies, e.retries))
            self.charge(sent, refused, used.name, used.asks_for())
            if carry and isinstance(e, Fatal):
                self.keep_session(step, used, held, refused, carry)
            raise
        finally:
            if carry:
                with self.lock:
                    self.busy.discard(step)
            self.held_rulings(step)
        if carry:
            self.keep_session(step, used, held, answer, carry)
        text, cached = answer
        self.produced[step] = text
        if not cached:
            # a cached answer costs nothing and was counting against the cap,
            # so a flow with a redo in it hit the ceiling on work it never did
            self.charge(sent, answer, used.name, used.asks_for())
        said = verdict(text, asked=asked)
        left = self.spec_unruled() if reviews_spec and said == "ok" else []
        if left:
            said = "redo"
            rest = text.strip().split("\n", 1)
            text = ("VERDICT: redo\n\n" + specfiles.unruled_redo(left)
                    + "\n\n" + (rest[1].strip() if len(rest) > 1 else "")
                    ).rstrip() + "\n"
            self.produced[step] = text
        block = back(parse(text), transcript(trace.last(tried, "session"),
                                                  tried.continued))
        self.keep(role, block)
        if notes is not None:
            notes.add(step, task, role, block)
            if getattr(self, "folder", None) is not None:
                notes.save(self.folder)
        return Handoff(role, text, said,
                       meta={"seconds": round(_t.time() - began, 1),
                             "cached": cached, "provider": used.name,
                             "asked": asked,
                             "allowed": declared(prompt) if asked else (),
                             "rulings": self.rulings()},
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


def to_lead(run, step, question, given, where):
    """-> (the lead's Handoff or None, the end of `step`'s next prompt when
    the lead decided or "", the question as the operator gets it when it
    did not). a flow with no lead, and the lead's own question, go to the
    operator as they were asked."""
    head = getattr(run, "lead", None)
    if head is None or head == step:
        return None, "", question
    asked = lead.key(question)
    if asked in run.led:
        return None, "", lead.again(question, head, run.led[asked])
    waits = run.budget.ahead(1)
    if waits:
        return None, "", lead.passed(question, "the run cannot pay for "
                                     + head + " to decide it, " + waits[1])
    run.led[asked] = ""
    was = run.produced.get(head)
    try:
        out = run.step(head, previous=given.get(head, EMPTY),
                       last=lead.brief(step, question))
    finally:
        # the lead's decision is not its work: a step that reads what the
        # lead produced still reads its own pass
        if was is None:
            run.produced.pop(head, None)
        else:
            run.produced[head] = was
    forged = getattr(run, "forged", {}).pop(head, "")
    if forged:
        return out, "", lead.passed(question, forged)
    decided, why, wrong = lead.judged(out.output, head, run.workdir,
                                      run.start)
    if wrong:
        return out, "", lead.passed(question, wrong)
    run.led[asked] = decided
    run.rule(*lead.recorded(head, step, where, question, decided, why),
             by="lead")
    return out, lead.told(head, question, decided, why), ""


def lead_pass(trail, run, out, asker, decided):
    """write the lead's go at a question into the trail, as its own line."""
    entry = trail.open(run.lead, run.taken(),
                       run.by_step.get(run.lead, run.provider), asker,
                       output=out.output)
    entry.handoff = out.block
    trail.close(entry, "decided" if decided else "escalated",
                to=asker if decided else None)


def forged_first(run, step, out):
    """-> what `step` did to decisions.md, "" for nothing, put on `out` as a
    failed rulings gate. read before a fence or an empty answer can stop the
    run, so the stop says it too; `check_step` reads it again after."""
    said = getattr(run, "forged", {}).get(step, "")
    if said:
        out.meta["gates"] = [Result(rulings.GATE, False, said)]
        out.meta["ungated"] = False
    return said


def and_forged(why, forged):
    return why + "; " + forged if forged else why


def forged_by(run, step):
    """whether `step` changed decisions.md, and so fails before anything it
    asked or claimed is read."""
    return bool(getattr(run, "forged", {}).get(step))


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
    said = ruling.conflict_of(out.output, getattr(run, "workdir", "."),
                              getattr(run, "start", None))
    if said and said[1]:
        results.insert(0, Result("conflict", False, said[1]))
    forged = getattr(run, "forged", {}).pop(step, "")
    if forged:
        results.insert(0, Result(rulings.GATE, False, forged))
    guarded = getattr(run, "spec_held", None)
    if guarded is not None:
        line, spec_asks = guarded(step, all(r.ok for r in results))
        if line is not None:
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
        line, held = replayed(step)
        if line is not None:
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
        forged = forged_first(run, step, out)
        fenced = run.fenced(step)
        if fenced:
            fenced = and_forged(fenced, forged)
            note("parked", fenced, stops.PARKED, output=out.output)
            return out.output, run.budget, "fenced at " + step + ": " + fenced
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
        said = ruling.asked_of(out.output, run.workdir, out.verdict,
                               out.meta.get("allowed")) if honest else None
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
    try:
        return run_flow()
    finally:
        warm.stop_all()


def run_flow():
    console()
    if len(sys.argv) < 2:
        from .cli import cmd_help

        return cmd_help()
    load_env()
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
            named = str(inside)
        run = Run(flow, fm, by_role, workdir=started_in or named, task=asked,
                  chosen=chosen, efforts=efforts)
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
    if pick_up:
        run.order.skip, run.order.proof = redorder.load(state.RUNS / pick_up)
        run.skipped = skips.load(state.RUNS / pick_up)
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
            raised = ("carried " + pick_up + " on with the "
                      + ", the ".join(moved),
                      (found.data.get("stopped") or {}).get("why")
                      or "the caps were changed before carrying on.")
    route = router.Router(fm)
    run.ups = route.ups
    try:
        run.committer.begin(run_id)
    except ValueError as e:
        print(str(e))
        return undo(1)
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
        if start == run.fan:
            run.fan_start = fan.load(state.RUNS / pick_up)
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
    plan = blocks.Plan(run.budget, todo, roles_of(run, todo),
                       blocks.history(state.RUNS, flow, run.workdir,
                                      skip=run_id))
    run.cut = sacrifice.earlier(fm, run.skipped)
    for cut in [s for s in todo if s in run.cut]:
        plan.drop(cut, run.skipped[run.cut[cut]])

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
    plan.write(folder)
    if plan.warning():
        print(plan.warning())
    trail = trace.Trail(folder,
                        after=trace.last_seq(state.RUNS / pick_up)
                        if pick_up else 0, plan=plan)
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

    def leave(stopped=None, needs=None, signed=()):
        """write the run's handoff.md from what the runner knows, and hand
        back (its path, its lines)."""
        # a warm call still in flight is ended, and charged, before anything
        # is written down
        warm.stop_all()
        ran = passes(trail, run, fm)
        record.ended(summary.outcome(stopped, summary.unproven(
            list(earlier) + ran)))
        record.data[chain.FIELD] = trail.head()
        record.save(run.budget)
        left = leftred.check(run.start, fm, leftred.chosen(fm, sys.argv)) \
            if stopped else None
        if left and left["red"]:
            run.suite_baseline()
        known = run.baseline if run.baseline and "tests" in run.baseline \
            else None
        left = baseline.label(left, known)
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
                              worktree=worktrees.lines(made, run_id),
                              headline=worktrees.headline(made),
                              signed=signed)
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
             checked=()):
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
        runner made on the answer outside its gates.

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
            conflict = cause == stops.CONFLICT
            needs = park.lines(at, waiting, done,
                               resume.remaining(steps(flow), at),
                               resume_command(flow, run_id, run.caps),
                               question=question, conflict=conflict,
                               replayed=replayed)
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

    def near(step, waits):
        """-> whether the run goes on past the token cap's warning: the
        flow's sacrifice list makes the steps ahead fit what is left."""
        if not sacrifice.listed(fm) or waits[0] != REACHING:
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
    try:
        while step:
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
                                + " is there as the run found it")])
            wrong = wrongtest.judge(out.output, step, run, route) \
                if honest else None
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

            said = ruling.asked_of(out.output, run.workdir, out.verdict,
                                   out.meta.get("allowed")) if honest else None
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
                print(step + " asks for a ruling")
                return stop(stops.PARKED, "needs a ruling: "
                            + said[1].split(NEWLINE)[0][len("NEEDS: "):],
                            "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=question)

            failed, blocked = check_step(run, route, step, out,
                                         run_dir=step_dir)
            entry.gates = out.meta.get("gates", [])
            entry.ungated = out.meta.get("ungated")
            spec_asks = out.meta.pop("spec_ruling", None)
            if spec_asks:
                print(step + " removed or rewrote a line of the spec")
                return stop(stops.PARKED, spec_asks[0], "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=spec_asks[1])
            test_asks = out.meta.pop("test_ruling", None)
            if test_asks:
                print(step + " changed a test the run started with")
                return stop(stops.PARKED, test_asks[0], "parked", entry,
                            index="PARKED  " + flow + "  at " + step,
                            waiting="user", question=test_asks[1])
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
                run.order.save(folder)
                chain.wrote(folder)

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
            run.committer.step(step, flow)
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
FLAG_OF = dict((key, flag) for flag, key in CAPS)


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


if __name__ == "__main__":
    sys.exit(main())
