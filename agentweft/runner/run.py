"""everything a step needs for one run, and the step itself."""
import threading
import time
from pathlib import Path

from agentweft.roles import resolver

from .config import asks_for_verdict, declared, fanout_step, verdict, where
from agentweft import providers
from agentweft.flow.spec import (RESUME, REVIEWER, brief_on,
                                 check_project_gates, grant_of, lead_of,
                                 step_id, step_name, steps_named)
from agentweft.guardrails import (baseline, boundary, briefing, defaults,
                                  fence, gates, redorder, rulings,
                                  shellwrite, snapshot, specfiles, starttests,
                                  testedits, worktree)
from agentweft.guardrails import writes as bounds
from agentweft.guardrails.gates.base import Result
from agentweft.orchestrate import decisions, project, synthesise
from agentweft.guardrails.budget import Budget
from agentweft.guardrails import police, sacrifice

from .handoff import EMPTY, Handoff, back, parse, to_files, transcript
from . import brief as kept
from . import investigate
from .errors import Fatal, Outage, kind_of
from . import prompts
from .prompts import load_prompt
from . import commits
from . import (fan, levels, manifest, models, retro, ruling, warm)
from . import settings
from . import state
from . import summary
from . import trace
from . import wrongtest


# seconds after which a kept session is not carried on: the place and the
# files its earlier reads saw have had time to move on
STALE = 24 * 3600


def replays(fm):
    """whether any step of the flow has a red-first gate, which needs the
    place as the run found it."""
    return any(g.get("gate") == "red-first" for s in fm.steps
               for g in (s.get("gates") or []))


class Run(object):
    """everything a step needs, built once. fm and by_role were being threaded
    through five functions just so two of them could read a timeout."""

    def __init__(self, flow, fm, by_role, provider=None, workdir=None,
                 task=None, chosen=None, efforts=None, held=None):
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
            grant = grant_of(s)
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
        self.project = held or project.hold(self.workdir)
        bad = check_project_gates(fm.steps, self.workdir, self.project)
        if bad:
            raise ValueError(flow + "/flow.yaml is wrong: " + "; ".join(bad))
        bad = self.cuts_a_check()
        if bad:
            raise ValueError(flow + "/flow.yaml is wrong: " + "; ".join(bad))
        self.fence = fence.at(self.workdir, own=state.RUNS, held=self.project)
        self.start = None
        self.suite = baseline.mode(fm)
        self.baseline = None
        if replays(fm) or self.suite == baseline.ON:
            worktree.prune(self.workdir)
        self.commits = commits.mode(fm)
        if replays(fm) or bounds.declared(fm) or fm.get("spec_files") \
                or self.suite == baseline.ON or self.reads_spec() \
                or self.commits != commits.NONE:
            self.start = snapshot.take(self.workdir, own=state.RUNS)
        self.order = redorder.Order(self.start,
                                    additions=fm.get("spec_files")
                                    == specfiles.ADDITIONS,
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
        # the steps in a call now; the warmer reads both from its own thread,
        # and leaves the warm calls it made in `warm_calls`, by step
        self.sessions = {}
        self.busy = set()
        self.warm_calls = {}
        self.lock = threading.Lock()
        self.record = None
        self.policing = police.mode(fm)
        self.network = police.allowed(fm)
        self.policed = []
        self.police_lines = {}
        self.police_lock = threading.Lock()
        self.shadowed = []
        self.shadow_read = 0
        self.told_read = []

    def decided(self):
        """-> the rulings in decisions.md the runner has on record."""
        kept = getattr(self, "kept", None)
        if kept is None:
            return decisions.read(Path(self.workdir))
        return kept.read()

    def spec_rulings(self):
        """-> the rulings that can let a spec line change, or a start test
        change in its file or its result: every one on record but the
        lead's, which decides inside them."""
        kept = getattr(self, "kept", None)
        if kept is None:
            return self.decided()
        return kept.read(but=(rulings.LEAD,))

    def rule(self, decided, why, by):
        """write a ruling to decisions.md and to the runner's own record. a
        step that asked and acts on it is held to the file as the runner
        left it, not as it was before the step's first go."""
        kept = getattr(self, "kept", None)
        if kept is None:
            path = decisions.record(Path(self.workdir), decided, why)
            data = snapshot._read(path)
        else:
            path = kept.record(decided, why, by)
            data = kept.data
        order = getattr(self, "order", None)
        if order is not None:
            order.runner_wrote(path, data)
        return path

    def held_rulings(self, step):
        """note why `step` fails when it changed decisions.md."""
        kept = getattr(self, "kept", None)
        said = kept.check(step) if kept is not None else ""
        if said:
            forged = getattr(self, "forged", None)
            if forged is None:
                forged = self.forged = {}
            forged[step] = said

    def look(self):
        """note the place as it is before a step runs, when the run keeps a
        snapshot of it to compare with."""
        start = getattr(self, "start", None)
        self.looked = start.hashes() if start is not None and start.hashed \
            else None

    def changed_tree(self):
        """-> whether the place differs from when `look` last saw it. False
        when the run keeps no snapshot: it cannot tell."""
        looked = getattr(self, "looked", None)
        return looked is not None and self.start.hashes() != looked

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

    def wrong_back(self, step, writer, tests, told):
        """send the tests `step` called wrong back to `writer`: the claims at
        the end of its prompt, and the red proof they gave dropped, so the
        corrected tests have to be shown red again before product code."""
        self.gate_said[writer] = told
        self.ups[writer] = self.ups.get(writer, 0) + 1
        if writer != step:
            self.gate_said[step] = wrongtest.back_to(writer, tests)
        proof = self.order.proof
        paths = set(redorder.norm(t.partition("::")[0]) for t in tests)
        if proof and proof.get("how") == "gate" and paths & set(
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
        decided = self.spec_rulings()
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
        decided = self.spec_rulings()
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

    def cuts_a_check(self):
        """-> complaints about a `sacrifice:` name whose step checks the spec
        in its prompt: the redo for a spec line moved with no ruling. made
        here and not at load, where the prompt files are not read."""
        bad = []
        for name in sacrifice.listed(self.fm):
            for s in steps_named(self.fm.steps, name):
                try:
                    text = load_prompt(self.flow, step_id(s),
                                       self.by_role.get(s["role"], ""),
                                       s["role"])
                except (FileNotFoundError, KeyError, AttributeError,
                        TypeError):
                    continue
                if asks_for_verdict(text) and prompts.reads_spec(text):
                    bad.append("sacrifice: " + name + " is never cut: "
                               + step_id(s) + " checks the spec for a line"
                               " that moved with no ruling")
                    break
        return bad

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
        decided = self.spec_rulings()
        return [rel + ":" + str(n) for rel, was, now in found
                for n, line in specfiles.moved(was, now, mode)
                if ruling.spec_line_ruled(decided, line) is None]

    def tests_held(self, step, last=False):
        """-> (the line for the record when a test file the run started with
        changed, else None; (why, question, what the run's record keeps of
        the question) when it changed in a way no ruling covers and this is
        the step's `last` go, else None). a step
        with a go left fails like a gate and goes back. the lead's decisions
        are not read: one that names the test does not let it change."""
        start = getattr(self, "start", None)
        found = testedits.changes(start)
        if not found:
            return None, None
        decided = self.spec_rulings()
        record = getattr(self, "record", None)
        asked = {}
        if getattr(record, "folder", None) is not None:
            for leg in manifest.legs(record.folder)[0]:
                m = manifest.load(leg)
                if m is not None:
                    asked[leg.name] = ruling.asked_edits(m.data.get("stopped"))
        left, ruled = [], []
        for edit in found:
            for test, how in edit.items:
                d = ruling.edit_ruled(decided, test, self.workdir, start,
                                      asked)
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
                      ruling.question_of_test_edits(step, left),
                      ruling.edits_asked(test for test, _ in left))

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
        whole prompt and the handoff in it, and so does a session kept
        longer ago than `STALE`, saying so. one kept past its cache's
        lifetime still carries on, with "lapsed" set to how long it waited:
        its call writes the whole session to the cache again, which is not
        what a warm carry-on costs."""
        if not self.continues(step) or not used.continues():
            return None
        with self.lock:
            kept = dict(self.sessions.get(step) or {})
        if kept and kept.get("model") == used.asks_for() \
                and kept.get("head") == manifest.of_text(head) \
                and used.holds(kept.get("id")):
            idle = time.time() - kept.get("at", time.time())
            if idle >= STALE:
                print(step + " starts fresh from the handoff: the session it"
                      " would carry on was kept " + str(int(idle // 3600))
                      + " h ago, and one is carried on for "
                      + str(STALE // 3600) + " h at most")
                return {"from": None}
            carry = providers.base.carry_of(kept)
            span = kept.get("lifetime")
            if span and idle >= span:
                carry["lapsed"] = int(idle)
            return carry
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
                    "effort": used.asks_effort() or "",
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
                return grant_of(s)
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
                                    order=getattr(self, "order", None),
                                    project=getattr(self, "project", None))
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

    def briefs(self, step):
        """whether this step is sent the brief."""
        for s in self.fm.steps:
            if step_id(s) == step:
                return brief_on(s, self.fm)
        return True

    def lens_for(self, step):
        """-> what this reviewer reads for and what the others in the run
        read for, or "" when it is not one of two or more with a lens."""
        mine, others = None, []
        for s in self.fm.steps:
            if s.get("role") != REVIEWER or not s.get("lens"):
                continue
            if step_id(s) == step:
                mine = s["lens"].strip()
            else:
                others.append(s["lens"].strip())
        if mine is None or not others:
            return ""
        return ("\n\nyou are one of " + str(len(others) + 1) + " reviewers of"
                " this change, and each reads for something the others do"
                " not.\nyou read for: " + mine + "\nthe others read for: "
                + "; ".join(others) + "\nleave their part to them. something"
                " plainly wrong outside your part still goes in.\n")

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
        # read off engine at each go, not imported: a fake put in its place
        # there has to be the one asked
        from . import engine

        key = (used, prompt, used.going, (used.carry or {}).get("from"))
        if key in self.answers:
            print("step " + step + " came from the cache")
            return engine.Answer(self.answers[key], True)
        answer = engine.call(prompt, timeout=self.timeout, cap=self.retries,
                             step=step, provider=used)
        if answer[0]:
            self.answers[key] = answer[0]
        return answer

    def policed_now(self):
        """-> what the off task check found since this was last asked."""
        with self.police_lock:
            out, self.policed = self.policed, []
        return out

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
        prompt = prompt + self.lens_for(step)
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
        briefed = ""
        if not self.briefs(step):
            prompt = prompts.drop_brief(prompt, resolver.fragment("brief"))
        else:
            briefed = notes.text(step) if notes else ""
            prompt = prompts.put_brief(prompt, briefed)
        prompt = prompts.put_task(prompt, self.task_text)
        if self.writes_tests(step):
            prompt = prompt + levels.as_prompt(self.fm, self.workdir)
        if self.writes_for(step) == "spec":
            prompt = prompt + bounds.as_prompt(snapshot.spec_globs())
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
        if carry:
            tried.lapsed = carry.pop("lapsed", None)
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
            from .engine import Answer

            refused = tried.answered(Answer("", False, e.replies, e.retries))
            self.charge(sent, refused, used.name, used.asks_for())
            if carry and isinstance(e, Fatal):
                self.keep_session(step, used, held, refused, carry)
            tried.replies[:0] = warm.taken(self, step)
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
        if getattr(self, "policing", police.OFF) != police.OFF and not cached:
            seen = police.report(step, used, self.grant_for(step),
                                 trace.sessions([tried]), self.network,
                                 prompt)
            with self.police_lock:
                self.policed.append(seen)
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
        block = to_files(back(parse(text),
                              transcript(trace.last(tried, "session"),
                                         tried.continued)),
                         self.workdir, getattr(self, "start", None))
        self.keep(role, block)
        if notes is not None:
            notes.add(step, task, role, block)
            if getattr(self, "folder", None) is not None:
                notes.save(self.folder)
        # after the police and the transcript have read this go's own
        # sessions: a warm call's copy is never written to disk
        tried.replies[:0] = warm.taken(self, step)
        return Handoff(role, text, said,
                       meta={"seconds": round(_t.time() - began, 1),
                             "cached": cached, "provider": used.name,
                             "asked": asked,
                             "allowed": declared(prompt) if asked else (),
                             "rulings": self.rulings()},
                       block=block, carried=list(self.constraints))
