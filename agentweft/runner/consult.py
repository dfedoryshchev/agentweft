"""the lead's ad hoc consult: one typed question to an architect or a
business analyst role that is in no step of the route, asked by a line under
the lead's own QUESTION:

    CONSULT: architect <the one thing it needs to know>
    CONSULT: ba <the one thing it needs to know>

the question is read for every risk first (`asking.lead_parks`), so a
question that names a start test, sits beside an unruled spec mark, carries
a SPLIT line or a line the runner cannot read never reaches a consult. the
consult answers in a typed block:

    FOUND: <what it found>
    from: <file>:<line> "<the line, word for word>"
    RISK: none | spec <file>:<line> "<line>" | test <file>::<name>
          | split <a quote> reads as <one>, or as <the other> | person <what>
    AGREES: yes | no <what it would answer instead>

a RISK line in a taught form other than `none` parks the question with the
risk found; a RISK line in no taught form, two of them, none, an empty
answer, an answer it could not pay for or one that changed a file parks it
too. with `RISK: none` the lead goes once more, the consult's answer last in
its prompt, and its final page is read as any lead page is. the consult
decides nothing: a `from:` line whose quote is on its line is the reason
recorded beside the lead's decision, and `AGREES: no` only goes on the
record beside it. `consults:` in flow.yaml caps the calls of a run, one per
question; 0, the default, turns the rung off.
"""
import re

from agentweft.flow.spec import OFF_ROUTE

from . import goal, lead, ruling, trace

ROLES = OFF_ROUTE
GRANT = ["read", "grep"]
ASKED = re.compile(r"^(architect|ba)\s+(\S.*)$")
FROM = re.compile(r"^\s*[-*]?\s*from\s*:\s*(.*?)\s*$", re.I)
KEYED = re.compile(r"^\s*[-*]?\s*[*_`]*\s*(FOUND|RISK|AGREES)\b[*_`]*\s*"
                   r"(?:[:=]|-\s|\s|$)\s*(.*?)\s*$", re.I)
SPEC = re.compile(r"^spec\s+(\S.*)$")
TEST = re.compile(r"^test\s+(\S.*)$")
SPLIT = re.compile(r"^split\s+(\S.*)$")
PERSON = re.compile(r"^person\s+(\S.*)$")
NO = re.compile(r"^no\b\s*(.*)$", re.I)
YES = re.compile(r"^yes\s*[.!]?$", re.I)
UNREAD = "UNREAD"


def step_of(role):
    """-> the name a consult's call goes under: the role's file."""
    return role + ".md"


def cap_of(fm):
    """-> how many consults a run of this flow may make, 0 when off."""
    said = (fm or {}).get("consults") if hasattr(fm, "get") else None
    return said if isinstance(said, int) and not isinstance(said, bool) \
        and said > 0 else 0


def asked_of(value):
    """-> (the role, what it is asked) of a CONSULT line, or None for one
    in no taught form."""
    m = ASKED.match(" ".join((value or "").split()))
    return (m.group(1), m.group(2)) if m else None


def wanted(run, step, out):
    """-> [(the question as a NEEDS line, its RECOMMEND, its cites, its
    SIZE, the CONSULT value)] for each QUESTION of the lead's own handoff
    that carries a CONSULT line, and was not put to the operator already."""
    from .asking import answered_here, lead_questions

    if step != getattr(run, "lead", None):
        return []
    lines = {}
    for q in out.block.get("questions") or []:
        said = ruling.flat(q.get("consult") or "")
        if said:
            lines[lead.key("NEEDS: " + ruling.flat(q.get("question") or ""))] \
                = said
    found = []
    for asked, rec, cites, size, _, _ in lead_questions(
            run, step, out, answered_here(run)):
        said = lines.get(lead.key(asked))
        if said:
            found.append((asked, rec, cites, size, said))
    return found


def hands_on(rec):
    """whether a RECOMMEND hands the answer to someone else by its words
    ("the operator names a date"): such a question is person-only, and no
    consult can hold its answer."""
    from .asking import HANDED_ON, PERSON_HOLDS, no_recommendation

    said = " ".join((rec or "").split()).strip(" .,;:!").lower()
    if not no_recommendation(rec):
        return False
    return bool(HANDED_ON.search(said)) or any(
        PERSON_HOLDS.match(s) for s in re.split(r"[.;:!?\n]", said))


def before(run, step, out):
    """-> the questions of `wanted` a consult may be called on, [] when any
    risk is on the page: the page is read by `asking.lead_parks` with only
    those questions' missing recommendation held back, so evidence found
    anywhere on it parks the run first and no consult is called. a question
    whose RECOMMEND hands the answer on, or one already consulted, waits
    for no consult; nor does any once the run's cap is spent."""
    from .asking import lead_parks

    cap = cap_of(getattr(run, "fm", None))
    asked = wanted(run, step, out)
    done = consulted(run)
    left = cap - len(done)
    if not asked or left <= 0:
        return []
    open_ = [q for q in asked if lead.key(q[0]) not in done
             and not hands_on(q[1])][:left]
    if not open_:
        return []
    if lead_parks(run, step, out, consulting=frozenset(
            lead.key(q[0]) for q in open_))[0]:
        return []
    return open_


def consulted(run):
    """-> the questions, by `lead.key`, the run has consulted on."""
    if not isinstance(getattr(run, "consulted", None), set):
        run.consulted = set()
    return run.consulted


def brief(run, role, what, asked, rec, cites):
    """-> what the consult is handed, built by the runner: its role's
    words, the one thing asked, the question with each cited line as the
    run found it, the request, the lead's RECOMMEND, the rulings in force,
    and how to answer."""
    from agentweft.roles import resolver

    start = getattr(run, "start", None)
    shown = []
    for cite in cites:
        rel, _, n = cite.rpartition(":")
        try:
            first = int(n.split("-")[0])
        except ValueError:
            continue
        lines, _ = ruling.lines_of(run.workdir, ruling.path_of(rel), first,
                                   first, start)
        if lines and len(lines) >= first:
            shown.append("- " + cite + ' "' + lines[first - 1].strip() + '"')
    rulings_now = run.rulings() if callable(getattr(run, "rulings", None)) \
        else []
    return (resolver.role_prompt(role + ".md").rstrip("\n")
            + "\n\nCONSULT: " + role + " " + what
            + "\n\nthe lead's question:\n\n" + asked
            + ("\n\nthe lines it cites, as the run found them:\n"
               + "\n".join(shown) if shown else "")
            + "\n\nthe request:\n\n" + (getattr(run, "task_text", None)
                                        or "(none given)")
            + (goal.fragment(getattr(run, "goal", None)) if role == "ba"
               else "")
            + "\n\nthe lead recommends: " + (rec or "none")
            + "\n\nrulings in force:\n" + ("\n".join(
                "- " + r for r in rulings_now) or "- none")
            + "\n\nyou decide nothing: say what you found, where, and whether"
            " it is one of the four risks. answer with these lines, each on"
            " its own:\n\n"
            "    FOUND: <what you found, one line>\n"
            '    from: <file>:<line> "<the line, word for word>"   (one to'
            " three)\n"
            "    RISK: none\n"
            '      or RISK: spec <file>:<line> "<the spec line, word for'
            ' word>" (a line of the spec the answer would break)\n'
            "      or RISK: test <file>::<name> (a test the run started with"
            " that would change)\n"
            '      or RISK: split the request "<its words>" reads as <one>, or'
            " as <the other>\n"
            "      or RISK: person <what only the operator holds>\n"
            + ("    AGREES: yes, or AGREES: no <what you would answer"
               " instead>\n" if rec and not ruling.says_none(rec) else ""))


def read(run, said):
    """-> {"found", "froms": [(cite, quote)], "dropped": [line], "risk":
    (kind, value) or (UNREAD, why), "agrees": None | "" | words}: the
    consult's answer read line by line. exactly one RISK line in a taught
    form is a risk read; none, two, or one in no taught form is UNREAD."""
    from . import verbs

    out = {"found": "", "froms": [], "dropped": [], "risk": None,
           "agrees": None}
    risks, unread = [], []
    for _, line in verbs.visible(said or ""):
        m = FROM.match(line)
        if m:
            cite, quote = ruling.settled_by(m.group(1), run.workdir,
                                            getattr(run, "start", None))
            if cite:
                out["froms"].append((cite, quote))
            else:
                out["dropped"].append(m.group(1))
            continue
        m = KEYED.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        typed = re.match(r"^\s*" + key + r":", line.strip()) is not None \
            and key.isupper()
        if key.upper() == "RISK":
            if typed:
                risks.append(value)
            else:
                unread.append(line.strip())
        elif key.upper() == "FOUND" and typed:
            out["found"] = value
        elif key.upper() == "AGREES":
            out["agrees"] = agrees(value) if typed else value or "unread"
    if unread or len(risks) != 1:
        out["risk"] = (UNREAD, "the consult's RISK line " + (
            "is not in the form taught for it: " + unread[0] if unread
            else "is missing" if not risks else "is given more than once"))
        return out
    out["risk"] = risk_of(risks[0])
    return out


def agrees(value):
    """-> "" for `AGREES: yes`, else what it would answer instead; an
    AGREES line that reads as neither is a no."""
    if YES.match(value.strip()):
        return ""
    m = NO.match(value.strip())
    return (m.group(1) or "it did not say") if m else (value.strip()
                                                       or "unread")


def risk_of(value):
    """-> (the kind, its words) of one RISK line's value, or (UNREAD,
    why)."""
    said = value.strip()
    if said.lower().strip(" .`") == "none":
        return "none", ""
    for kind, form in (("spec", SPEC), ("test", TEST), ("split", SPLIT),
                       ("person", PERSON)):
        m = form.match(said)
        if m:
            return kind, m.group(1)
    return UNREAD, ("the consult's RISK line is not in the form taught for"
                    " it: RISK: " + said)


def goes_up(run, step, role, asked, rec, cites, size, risk):
    """-> (the question as the operator gets it, what the run's record
    keeps of it or None) for a consult that found a risk, or that cannot be
    read: the run parks on it whatever the lead would say."""
    from .asking import asked_as, risk_of as risk_read, spec_cites

    kind, words = risk
    by = "found by the " + role
    if kind == "test":
        said, record = risk_read(run, step, asked, cites, rec, size, [words],
                                 "")
        if said:
            return said.replace("CITES:", "CITES:\n- " + by + ": RISK: test "
                                + words, 1), record
        return asked_as(asked, cites + [by + ": RISK: test " + words
                                        + " (not a test the run started"
                                        " with: not checked)"], rec, size), \
            None
    if kind == "split":
        said, _ = risk_read(run, step, asked, cites, rec, size, [], words)
        return said.replace("SPLIT: ", "SPLIT (" + by + "): ", 1), None
    if kind == "spec":
        line, _ = ruling.settled_by(words, run.workdir,
                                    getattr(run, "start", None))
        typed = line and (not getattr(getattr(run, "start", None), "specs",
                                      None) or spec_cites(
            line, run.workdir, run.start))
        return asked_as(asked, cites + [by + ": RISK: spec " + words + (
            " (the line is in the spec as the run found it)" if typed
            else " (not checked: not a spec line as the run found it)")],
            rec, size), None
    if kind == "person":
        return asked_as(asked, cites + [by + ": only the operator holds "
                                        + words], rec, size), None
    return asked_as(asked, cites + [by + ": " + words], rec, size), None


def told(role, asked, said, found):
    """-> the end of the lead's prompt on its second go."""
    kept = "; ".join(c + ' "' + q + '"' for c, q in found["froms"]) or "none"
    dropped = "; ".join(found["dropped"]) or "none"
    return ("\n\nCONSULTED. you asked the " + role + " about your question:"
            "\n\n" + asked + "\n\nit answered:\n\n" + said.strip()
            + "\n\nthe runner checked its lines: from lines on their line as"
            " the run found them: " + kept + "; not found there, dropped: "
            + dropped + "; it found no risk. you make the decision: answer"
            " as before, the whole of it, and finish that question with a"
            " RECOMMEND you stand behind, or `RECOMMEND: none` when it still"
            " holds no choice. it is not consulted on again.\n")


def call(run, role, text, leads=False):
    """-> (what the consult said, why it gave nothing or ""): one read-only
    call under the role's own step name, priced on the run like any step,
    the place held to `writes: none`. `leads` is the flow's lead that is no
    step of its route: its go goes on the lead's own trail line, so it joins
    the run's attempts instead of a consult line."""
    from agentweft.guardrails import snapshot
    from agentweft.providers import connectors
    from . import engine, state
    from .errors import Fatal, Outage

    name = step_of(role)
    used = run.by_step.get(name, run.provider)
    tried = trace.Attempt()
    if leads:
        run.attempts.append(tried)
    used.at(name, None)
    if hasattr(run, "read_auth"):
        run.read_auth(used)
    tried.effort = run.effort_for(name, used)
    used.going = tried.effort["base"] and tried.effort["asked"]
    was = snapshot.fingerprint(run.workdir, own=state.RUNS)
    print("started " + name + (", the flow's lead" if leads
                               else ", consulted by " + run.lead))
    said, why = "", ""
    try:
        answer = tried.answered(ask(run, text, name, used))
        said = answer[0] or ""
        if not answer[1]:
            run.charge(text, answer, connectors.label(used),
                       used.asks_for())
    except (Outage, Fatal) as e:
        run.charge(text, tried.answered(engine.Answer(
            "", False, e.replies, e.retries)), connectors.label(used),
            used.asks_for())
        why = type(e).__name__ + ": " + str(e)
    if not why and snapshot.fingerprint(run.workdir, own=state.RUNS) != was:
        why = name + " changed a file, and a consult writes none"
    if not why and not said.strip():
        why = "nothing came out of " + name
    if not leads:
        run.consult_tried = (name, tried, used, said)
    return said, why


def lead_go(run, last):
    """-> (the off-route lead's answer as a Handoff, why it is not held or
    ""): one read-only go of the role the flow names as `lead:`, handed the
    request, where the spec is, and `last`."""
    from agentweft.guardrails import snapshot
    from .handoff import Handoff

    role = run.lead[:-len(".md")]
    said, why = call(run, role, lead.off_route(
        getattr(run, "task_text", None), snapshot.spec_globs()) + last,
        leads=True)
    out = Handoff(role, said, meta={"police": None})
    if why:
        out.meta["passed"] = why
    return out, why


def ask(run, text, name, used):
    return run.ask(text, name, used)


def rung(run, step, out, given, trail):
    """the consult rung for the lead's own page `out`. -> (the lead's page
    to read from here on, (the question, the record) it parks on or None).
    with nothing to consult, `out` as it was and None."""
    open_ = before(run, step, out)
    if not open_:
        return out, None
    from .asking import keep_state, lead_questions

    asked, rec, cites, size, value = open_[0]
    key = lead.key(asked)
    consulted(run).add(key)
    keep_state(run)
    how = asked_of(value)
    if how is None:
        return out, (goes_up(run, step, "lead", asked, rec, cites, size, (
            UNREAD, "the CONSULT line is not in the form taught for it: "
            "CONSULT: " + value)))
    role, what = how
    waits = run.budget.ahead(1)
    if waits:
        print("the run cannot pay for the " + role + " consult: " + waits[1])
        return out, goes_up(run, step, role, asked, rec, cites, size, (
            UNREAD, "the run cannot pay for the consult, " + waits[1]))
    said, why = call(run, role, brief(run, role, what, asked, rec, cites))
    found = read(run, said) if not why else None
    risk = (UNREAD, why) if why else found["risk"]
    if risk[0] != "none":
        note(run, trail, role, step, "evidence" if not why else "none", why)
        return out, goes_up(run, step, role, asked, rec, cites, size, risk)
    run.consult_said = dict(getattr(run, "consult_said", None) or {})
    run.consult_said[key] = {"role": role, "froms": found["froms"],
                             "agrees": found["agrees"]}
    waits = run.budget.ahead(1)
    if waits:
        note(run, trail, role, step, "none", None)
        return out, goes_up(run, step, role, asked, rec, cites, size, (
            UNREAD, "the run cannot pay for " + step + " to go again on"
            " the consult, " + waits[1]))
    again = run.step(step, previous=given.get(step), last=told(
        role, asked, said, found))
    final = [q for q in lead_questions(run, step, again) if lead.key(q[0])
             == key] if again else []
    note(run, trail, role, step, won_of(run, step, again, final, found),
         None)
    entry = trail.open(step, run.taken(), run.by_step.get(step, run.provider),
                       step_of(role), output=again.output or None)
    entry.handoff = again.block
    trail.close(entry, "ok" if again else "failed", planned=False,
                why=None if again else "nothing came out of " + step)
    if not final:
        return out, (asked_line(asked, cites, rec, size, step), None)
    return again, None


def won_of(run, step, again, final, found):
    """-> cite when a checked `from:` line becomes the reason of the lead's
    decision on its final page (it decides, and its SETTLED BY gives no
    reason of its own), else none."""
    from .asking import lead_parks, settled_reason

    if not final or not found["froms"] or lead_parks(run, step, again)[0]:
        return "none"
    return "none" if settled_reason(run, final[0][4])[0] else "cite"


def asked_line(asked, cites, rec, size, step):
    """-> the question as the operator gets it when the lead's second go
    gave no page, or one that no longer asks it: a question it was unsure
    of is never dropped by leaving it out."""
    from .asking import asked_as

    return asked_as(asked, cites + [step + "'s go after the consult left"
                                    " the question out, so it is the"
                                    " operator's"], rec, size)


def note(run, trail, role, asker, won, why):
    """write the consult's call into the trail as its own line, its `won`
    read from what the runner did with its answer: evidence (a RISK line
    sent the question to the operator), cite (a `from:` line on its line was handed to
    the lead's decision) or none."""
    name, tried, used, said = getattr(run, "consult_tried", (
        step_of(role), trace.Attempt(), run.provider, ""))
    entry = trail.open(name, [tried], used, asker, output=said or None)
    entry.consulted = won
    trail.close(entry, "failed" if why else "ok", why=why, planned=False)


def reason(run, step, asked, settled_line):
    """-> (the cite, the quote, the words beside the decision) a consult
    gives the lead's decision of `asked`: its first checked `from:` line
    when the SETTLED BY gave none, and what it would answer otherwise."""
    said = (getattr(run, "consult_said", None) or {}).get(lead.key(asked))
    if not said:
        return "", "", ""
    cite, quote = ("", "")
    if not settled_line and said["froms"]:
        cite, quote = said["froms"][0]
    beside = " after asking the " + said["role"]
    if said["agrees"]:
        beside += (" (the " + said["role"] + " would answer otherwise: "
                   + " ".join(said["agrees"].split()).replace(", which",
                                                              "; which")
                   + ")")
    return cite, quote, beside
