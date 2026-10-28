"""what a run did, one json line per step it ran.

`runs/<run id>/steps.jsonl` gets a line every time a step is run - a redo's
second pass is a second line - and it is written whatever happened next: the
run went on, sent the work back, parked, stopped or crashed. what the pass
produced is kept beside it as `steps/<seq>-<step>.md` and the line names that
file, so a redo no longer writes over the review that asked for it.

a line is the same shape every time and in the same key order, so two runs
of the same flow differ only in the time, the ids and the seconds. a gate's
entry carries `tests` only when that gate ran tests one by one. `handoff`
is the step's HANDOFF block as `runner/handoff.py` parsed it, with each
VERIFIED claim marked against the step's transcript; null only on a line
closed before the step answered. `budget` is the pass against the run's
budget plan (spent, planned, buffer, risk), null when there is no plan and
on the retro's line, which the plan never held.
every line ends on `chain`, which ties it to the line before it
(`runner/chain.py`).

each gate a step ran is a line of its own in `gates.jsonl`: the step's seq,
the step, the gate, whether it passed and its seconds. a step's seconds are
its model's time only, so the gates' seconds sit beside them.
"""
import datetime
import json
import time
from decimal import Decimal

from . import chain
from .task import FILE as TASK

FILE = "steps.jsonl"
GATES = "gates.jsonl"
FOLDER = "steps"
# the outcome of a line holding only the warm calls a step was kept warm
# with (`warm.py`), when no later go of it took them; it is not a pass
WARM = "warm"
# the outcome of a reviewer's line that let the work through and named a
# wrong implementation the tests would pass: the case goes to the test writer
ROUTED = "routed"


class Attempt(object):
    """one go at a step, from the moment it was asked until it answered.

    `replies` is every reply it took, failed goes included, because each of
    them was paid for. `retries` stays None until there is an answer: a step
    that crashed went some number of times, and nothing here knows how many.
    """

    __slots__ = ("task", "began", "started", "seconds", "cached", "replies",
                 "retries", "effort", "verbosity", "continued", "lapsed",
                 "facts")

    def __init__(self, task=None):
        self.task = task
        self.effort = None
        # the ids of the project's facts this go was handed in its brief
        self.facts = None
        self.verbosity = None
        # the session this go carried on, None for one started fresh
        self.continued = None
        # seconds that session had waited, when that was past its cache's
        # lifetime
        self.lapsed = None
        self.began = datetime.datetime.now()
        self.started = time.time()
        self.seconds = None
        self.cached = False
        self.replies = []
        self.retries = None

    def answered(self, answer):
        """-> the answer, untouched, once what came with it is noted."""
        self.seconds = round(time.time() - self.started, 1)
        self.cached = bool(answer[1])
        self.replies = list(getattr(answer, "replies", ()))
        self.retries = dict(getattr(answer, "retries", None) or {})
        return answer

    def took(self):
        if self.seconds is not None:
            return self.seconds
        return round(time.time() - self.started, 1)


def tokens(attempts):
    """counted only when every reply was counted by whoever answered it. a sum
    with one estimate in it would read as a count."""
    replies = [r for a in attempts for r in a.replies]
    if not replies or any(r.usage is None for r in replies):
        return {"counted": False}
    return {"counted": True,
            "input": sum(r.usage.input_tokens for r in replies),
            "output": sum(r.usage.output_tokens for r in replies),
            "cache_read": sum(r.usage.cache_read_input_tokens for r in replies),
            "cache_creation": sum(r.usage.cache_creation_input_tokens
                                  for r in replies)}


def stated(r):
    c = r.cost
    return isinstance(c, (int, float)) and not isinstance(c, bool)


def one_go(table, r, model):
    """-> Priced for a go the provider never answered for."""
    from agentweft.guardrails import prices

    if r.usage is not None:
        return prices.of_reply(table, r, asked=model)
    return table.estimate(r.model or model, r.guess or 0, 0)


def cost(attempts, model=None):
    """USD as the providers stated it, None when any of them did not say.

    a go that never answered has no stated figure, and is priced from its
    transcript or its estimate instead: it was paid for all the same.
    `cost_from` says which figures the sum holds.
    """
    from agentweft.guardrails import prices

    if attempts and all(a.cached for a in attempts):
        return 0
    replies = [r for a in attempts if not a.cached for r in a.replies]
    if not replies:
        return None
    total = sum(r.cost for r in replies if stated(r))
    rest = [r for r in replies if not stated(r)]
    if any(getattr(r, "metered", None) is None for r in rest):
        return None
    if rest:
        table = prices.load()
        filled = prices.Priced(Decimal(0))
        for r in rest:
            filled = filled + one_go(table, r, model)
        if filled.usd is None:
            return None
        total = total + float(filled.usd)
    return round(total, 6)


def cost_from(attempts):
    """-> how many goes each figure in `cost` came from, None when every go
    stated its own or nothing was asked."""
    out = {}
    for a in attempts:
        if a.cached:
            continue
        for r in a.replies:
            if stated(r):
                kind = "provider"
            else:
                kind = getattr(r, "metered", None) or "unreported"
            out[kind] = out.get(kind, 0) + 1
    if not out or list(out) == ["provider"]:
        return None
    return out


def cost_parts(attempts, model=None):
    """-> `cost` split by where each figure came from, the keys of
    `cost_from`; None when `cost_from` is, or `cost` is."""
    from agentweft.guardrails import prices

    came = cost_from(attempts)
    if came is None or cost(attempts, model) is None:
        return None
    table = None
    out = {}
    for a in attempts:
        if a.cached:
            continue
        for r in a.replies:
            if stated(r):
                kind, usd = "provider", Decimal(str(r.cost))
            else:
                table = table or prices.load()
                kind, usd = r.metered, one_go(table, r, model).usd
            out[kind] = out.get(kind, Decimal(0)) + usd
    return dict((k, round(float(v), 6)) for k, v in out.items())


def priced(attempts, model=None):
    """USD by the price table, None when any reply was not counted or could
    not be priced. `model` is the id asked for, for a reply that names none."""
    from agentweft.guardrails import prices

    if attempts and all(a.cached for a in attempts):
        return 0
    replies = [r for a in attempts if not a.cached for r in a.replies]
    if not replies or any(r.usage is None for r in replies):
        return None
    table = prices.load()
    total = prices.Priced(Decimal(0))
    for r in replies:
        total = total + prices.of_reply(table, r, asked=model)
    return prices.stored(total.usd)


def retries(attempts):
    out = {}
    for a in attempts:
        if a.retries is None:
            return None
        for cause, n in a.retries.items():
            out[cause] = out.get(cause, 0) + n
    return out


def killed(attempts):
    """the processes a step left running that were ended with it. None when no
    reply said, which a step that started no process never does."""
    said = [getattr(r, "killed", None) for a in attempts for r in a.replies]
    said = [n for n in said if n is not None]
    return sum(said) if said else None


def last(attempt, what):
    said = [getattr(r, what) for r in attempt.replies if getattr(r, what)]
    return said[-1] if said else None


def turns(attempts):
    """-> the turns the provider says every reply took, summed; None unless
    each one said."""
    said = [getattr(r, "turns", None) for a in attempts for r in a.replies]
    if not said or any(t is None for t in said):
        return None
    return sum(said)


def thinking(attempts):
    """-> the thinking tokens every reply says it spent, summed; None unless
    each one said."""
    said = [r.usage.reasoning_output_tokens if r.usage is not None else None
            for a in attempts for r in a.replies]
    if not said or any(t is None for t in said):
        return None
    return sum(said)


def seconds(attempts):
    if not attempts:
        return 0.0
    start = min(a.started for a in attempts)
    return round(max(a.started + a.took() for a in attempts) - start, 1)


def facts(attempts, model=None):
    return {"tokens": tokens(attempts), "cost": cost(attempts, model),
            "priced": priced(attempts, model),
            "cost_from": cost_from(attempts),
            "cost_parts": cost_parts(attempts, model),
            "seconds": seconds(attempts),
            "cached": bool(attempts) and all(a.cached for a in attempts),
            "retries": retries(attempts),
            "background_killed": killed(attempts),
            "turns": turns(attempts), "thinking": thinking(attempts)}


def last_seq(folder):
    """-> the highest seq written into folder's steps.jsonl, 0 when none."""
    path = folder / FILE
    if not path.exists():
        return 0
    seen = [0]
    for text in path.read_text(encoding="utf-8").split("\n"):
        try:
            seen.append(int(json.loads(text)["seq"]))
        except (ValueError, KeyError, TypeError):
            # a line cut short by the process dying under it
            continue
    return max(seen)


class Entry(object):
    """a line that has a number and a file but not yet an outcome."""

    __slots__ = ("seq", "step", "attempts", "provider", "came_from", "file",
                 "fanned", "gates", "ungated", "handoff", "written", "took",
                 "proved", "changed", "decided", "police", "facts",
                 "conformance", "case", "held")

    def __init__(self, seq, step, attempts, provider, came_from, file, fanned):
        self.written = None
        self.seq = seq
        self.step = step
        self.attempts = sorted(attempts, key=lambda a: a.task or 0)
        self.provider = provider
        self.came_from = came_from
        self.file = file
        self.fanned = fanned
        self.gates = []
        self.ungated = None
        self.handoff = None
        self.took = None
        # what the record says of the pass, for `won`: the run's red proof
        # was written by it, the place differs from before it ran (None when
        # not read), a lead decision of it is on record
        self.proved = False
        self.changed = None
        self.decided = False
        self.police = None
        # on the retro's pass only: what the runner did with its FACTS block
        self.facts = None
        # what each fact's check said after this pass changed its scope
        self.conformance = None
        # on the test writer's pass only: the case a reviewer named, as held
        # to the code (`wouldpass.held`)
        self.case = None
        # what the runner held back of a pass another model answered, under
        # `on_fallback: park`
        self.held = None


class Trail(object):
    """the steps.jsonl of one run folder, and the per-pass step files.

    `after` is where the numbering carries on from: a resumed run counts on
    from the run it picked up, so the two files read as one sequence.
    """

    def __init__(self, folder, after=0, plan=None):
        self.folder = folder
        self.plan = plan
        self.seq = max(after, last_seq(folder))
        self.unclosed = []
        self.closed = []
        self.held = []
        self.gate_seconds = 0.0
        self.gated = []
        self.task_file = TASK if (folder / TASK).is_file() else None
        self.lines = chain.raw(folder)
        chain.kept(folder)

    def head(self):
        """-> {"lines": n, "head": hash of the newest line} of the chain."""
        return chain.head(self.lines)

    def open(self, step, attempts, provider, came_from, output=None,
             fanned=False):
        self.seq = self.seq + 1
        kept = None
        if output is not None:
            name = step if step.endswith(".md") else step + ".md"
            kept = FOLDER + "/" + "%03d" % self.seq + "-" + name
            path = self.folder / kept
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output, encoding="utf-8")
        entry = Entry(self.seq, step, attempts, provider, came_from, kept,
                      fanned)
        if self.plan is not None:
            entry.took = self.plan.opened()
        self.unclosed.append(entry)
        return entry

    def close(self, entry, outcome, why=None, to=None, cause=None,
              planned=True):
        """write entry's line, after the line of every entry opened before it
        that is still open: the lead's pass closes inside the pass of the
        step that asked it, and the file keeps the order the steps ran in.
        a pass that is not `planned` is kept off the budget plan."""
        self.folder.mkdir(parents=True, exist_ok=True)
        if entry in self.unclosed:
            self.unclosed.remove(entry)
        entry.written = line(entry, outcome, why, to, cause, self.task_file,
                             self.folder)
        if self.plan is not None and planned:
            entry.written["budget"] = self.plan.closed(entry.step, outcome,
                                                       entry.took)
        if entry.police is not None:
            entry.written["police"] = entry.police
        if entry.facts is not None:
            entry.written["facts"] = entry.facts
        if entry.conformance:
            entry.written["conformance"] = entry.conformance
        if entry.written.get("fallback"):
            print(switched_said(entry.step, entry.written["fallback"]))
        self.held.append((entry, outcome))
        first = min(e.seq for e in self.unclosed) if self.unclosed else None
        ready = sorted((h for h in self.held
                        if first is None or h[0].seq < first),
                       key=lambda h: h[0].seq)
        self.held = [h for h in self.held if h not in ready]
        with open(self.folder / FILE, "a", encoding="utf-8") as f:
            for done, said in ready:
                self.closed.append((done, said))
                done.written[chain.FIELD] = {
                    "prev": chain.head(self.lines)["head"],
                    "files": chain.kept(self.folder)}
                text = json.dumps(done.written, ensure_ascii=False)
                f.write(text + "\n")
                self.lines.append(text)
        for done, _ in ready:
            for g in done.gates:
                self.timed(g.gate, done.step, g.seconds, g.ok, done.seq,
                           issue_of(g), getattr(g, "began", None))

    def timed(self, gate, step, seconds, ok, seq=None, issue="", began=None):
        """write one gate's seconds to gates.jsonl, and what it could not do
        when there was something. a gate the runner did not time and that
        says no issue has no line. `began` is when it started, None when
        nothing said: it is then taken to have ended now."""
        if seconds is None and not issue:
            return
        if seconds is not None:
            self.gate_seconds = self.gate_seconds + seconds
            began = time.time() - seconds if began is None else began
            self.gated.append((began, began + seconds))
        line = {"seq": seq, "step": step, "gate": gate, "ok": bool(ok),
                "seconds": seconds}
        if issue:
            line["issue"] = issue
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.folder / GATES, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def busy(self):
        """-> (start, end) of every go of a pass this trail closed and of
        every gate it timed: the seconds the wall puts under steps and
        gates, the rest being the runner's own."""
        out = list(self.gated)
        for entry, outcome in self.closed:
            if outcome == WARM:
                continue
            out.extend((a.started, a.started + a.took())
                       for a in entry.attempts)
        return out

    def still_open(self):
        """-> the entry opened and not yet given an outcome, or None."""
        return self.unclosed[-1] if self.unclosed else None


def issue_of(g):
    from agentweft.guardrails.gates.base import issue_of as said

    return said(g)


def gate_line(g):
    out = {"gate": g.gate, "ok": bool(g.ok), "detail": g.detail}
    if g.unproven:
        out["unproven"] = list(g.unproven)
    if getattr(g, "tests", None) is not None:
        out["tests"] = g.tests
    if getattr(g, "skipped", False):
        out["skipped"] = True
    if getattr(g, "broke", False):
        out["broke"] = True
    said = issue_of(g)
    if said:
        out["issue"] = said
    if not out["ok"] and not out.get("broke") and not out.get("skipped"):
        out["prevented"] = g.detail or g.gate
    return out


def sessions(attempts):
    return {r.session for a in attempts for r in a.replies
            if getattr(r, "session", None)}


FALLBACK = "model_refusal_fallback"


def transcript(session):
    """-> every record of `session`'s transcript, None when there is none
    to read."""
    from agentweft.runner.handoff import projects

    try:
        found = sorted(projects().glob("*/" + session + ".jsonl"))
    except OSError:
        return None
    if not found:
        return None
    out = []
    for raw in found[0].read_text(encoding="utf-8",
                                  errors="replace").split("\n"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def effort_used(attempts):
    """-> the level the step's sessions ran at, as the newest model turn of
    each transcript names it; None when no transcript names one."""
    used = set()
    for s in sessions(attempts):
        turns = [d.get("effort") for d in transcript(s) or ()
                 if d.get("type") == "assistant"
                 and isinstance(d.get("effort"), str) and d.get("effort")]
        if turns:
            used.add(turns[-1])
    return ", ".join(sorted(used)) or None


def fallback(attempts):
    """-> {"asked", "answered_by"} when a session of the step records the
    provider's fallback, the model it switched to answering in place of the
    one asked; None for a step answered by the model it asked, or with no
    transcript to tell."""
    for s in sorted(sessions(attempts)):
        records = transcript(s)
        if records is None:
            continue
        fell = switched = None
        for data in records:
            if data.get("type") == "system" and data.get("subtype") == FALLBACK:
                fell = True
            message = data.get("message")
            asked = data.get("requestedModel")
            if switched is None and data.get("type") == "assistant" \
                    and isinstance(message, dict) and asked \
                    and message.get("model") and message["model"] != asked:
                switched = {"asked": asked, "answered_by": message["model"]}
        if fell and switched:
            return switched
    return None


SWITCHED = ": the provider switched models; its output is that model's"


def switched_said(where, fell):
    """-> the line that says another model answered `where`."""
    return (where + " was answered by " + str(fell.get("answered_by"))
            + ", not " + str(fell.get("asked")) + SWITCHED)


def shell_writes_denied(p, attempts, folder):
    """-> how many shell writes the cli refused this step, None when it was
    not handed the check or no session says which refusals were its own."""
    from agentweft.guardrails import shellwrite

    granted = p.granted()
    if not granted or granted.get("shell_writes") != "refused":
        return None
    seen = sessions(attempts)
    if folder is None or not seen:
        return None
    return shellwrite.denied(folder, seen)


def shell_trap_recoveries(attempts):
    """-> the model's messages naming a shell trap it walked into, summed over
    the step's sessions; None when no transcript could be read. a session
    carried on is a copy of the one before it, whose messages are not this
    go's."""
    from agentweft.guardrails import shellwrite

    found = []
    for a in attempts:
        before = shellwrite.recovered(a.continued) if a.continued else None
        for s in sorted(sessions([a])):
            n = shellwrite.recovered(s)
            if n is not None:
                found.append(max(0, n - (before or 0)))
    return sum(found) if found else None


WON = ("caught", "stopped", "delivered", "proved", "decided", "none")


def won(outcome, cause=None, gates=(), to=None, proved=False, changed=None,
        decided=False):
    """-> what a pass bought, one of WON, from its line and what the record
    says of it, never from what a gate or the model wrote.

    caught: a gate failed on the step's work, or the step sent the work
    back. a gate that broke (it could not run) caught nothing. proved: the
    run's red proof was written by this pass. a stop the step made is
    stopped when the place is as the step found it, and delivered when the
    step's work is in it. a pass that went on is delivered too when its work
    is in the place and a gate that ran, and did not break, passed it having
    done its job: a pass from a gate that could not (a replay with no start,
    say) checked nothing. decided: the lead's decision is on record. a stop
    for the budget, an outage, a crash or no answer bought nothing; a redo
    that only switched the cause step on was the runner's choice, not a
    defect the step found. a reviewer's `routed` line bought nothing yet: its
    case is held to the code on the test writer's line (`case`), and the
    reviewer caught something only when that case failed there
    (`summary.passes_of` reads it so).
    """
    from .investigate import STEP
    from .stops import CONFLICT, DECLINED, OFF_TASK, PARKED, REFUSED

    failed = [g for g in gates or () if not g.get("ok")]
    if any(not g.get("broke") for g in failed):
        return "caught"
    if outcome == "gate failed" and not failed:
        return "caught"
    if outcome == "redo" and to and to != STEP:
        return "caught"
    if cause == OFF_TASK:
        return "stopped"
    if proved:
        return "proved"
    if cause in (CONFLICT, REFUSED, DECLINED, PARKED):
        return "delivered" if changed else "stopped"
    if decided:
        return "decided"
    if outcome == "ok" and changed and any(
            g.get("ok") and not g.get("skipped") and not g.get("broke")
            and not g.get("issue") for g in gates or ()):
        return "delivered"
    return "none"


def checked(block, gates=()):
    """-> what a pass checked, whatever it won: the VERIFIED lines of its
    HANDOFF block its transcript backed, by any kind, and the gates that ran
    on its work, skipped or broken ones not counted."""
    verified = (block or {}).get("verified") if isinstance(block, dict) \
        else None
    backed = sum(1 for i in verified or ()
                 if isinstance(i, dict) and i.get("backed") == "backed")
    return backed + sum(1 for g in gates or ()
                        if not g.get("skipped") and not g.get("broke"))


def line(entry, outcome, why=None, to=None, cause=None, task_file=None,
         folder=None):
    attempts = entry.attempts
    first = attempts[0] if attempts else None
    p = entry.provider
    said = facts(attempts, p.asks_for())
    one = attempts[0] if len(attempts) == 1 and not entry.fanned else None
    tasks = None
    if entry.fanned:
        tasks = []
        for a in attempts:
            task = {"task": a.task}
            task.update(facts([a], p.asks_for()))
            for key in ("turns", "thinking"):
                if task[key] is None:
                    del task[key]
            task["session"] = last(a, "session")
            task["model_reported"] = last(a, "model")
            tasks.append(task)
    gates = [gate_line(g) for g in entry.gates]
    effort = first.effort if first else None
    used = effort_used(attempts) if isinstance(effort, dict) else None
    if used:
        effort = dict(effort, used=used)
    out = {"seq": entry.seq,
           "time": (first.began if first else datetime.datetime.now())
           .isoformat(timespec="seconds"),
           "step": entry.step,
           "from": entry.came_from,
           "to": to,
           "provider": p.name,
           "command": p.command,
           "model": p.asks_for(),
           "model_reported": last(one, "model") if one else None,
           "model_choice": getattr(p, "choice", None),
           "effort": effort,
           "verbosity": first.verbosity if first else None,
           "grant": p.granted(),
           "tokens": said["tokens"],
           "cost": said["cost"],
           "priced": said["priced"],
           "cost_from": said["cost_from"],
           "cost_parts": said["cost_parts"],
           "budget": None,
           "session": last(one, "session") if one else None,
           "seconds": said["seconds"],
           "cached": said["cached"],
           "retries": said["retries"],
           "background_killed": said["background_killed"],
           "shell_writes_denied": shell_writes_denied(p, attempts, folder),
           "shell_trap_recoveries": shell_trap_recoveries(attempts),
           "gates": gates,
           "ungated": entry.ungated,
           "outcome": outcome,
           "won": won(outcome, cause, gates, to, entry.proved, entry.changed,
                      entry.decided),
           "checked": checked(entry.handoff, gates),
           "cause": cause,
           "why": why,
           "file": entry.file,
           "task_file": task_file,
           "tasks": tasks,
           "handoff": entry.handoff}
    if said["turns"] is not None:
        out["turns"] = said["turns"]
    if said["thinking"] is not None:
        out["thinking"] = said["thinking"]
    from .stops import OFF_TASK

    if cause == OFF_TASK and why:
        out["prevented"] = why
    went_on = [a.continued for a in attempts if a.continued]
    if went_on:
        out["continued"] = went_on[-1]
    lapsed = [a.lapsed for a in attempts if getattr(a, "lapsed", None)]
    if lapsed:
        out["lapsed"] = lapsed[-1]
    handed = []
    for a in attempts:
        handed.extend(i for i in getattr(a, "facts", None) or []
                      if i not in handed)
    if handed:
        out["facts_attached"] = handed
    if entry.case:
        out["case"] = entry.case
    fell = fallback(attempts)
    if fell:
        if entry.held:
            fell["held"] = entry.held
        out["fallback"] = fell
    return out
