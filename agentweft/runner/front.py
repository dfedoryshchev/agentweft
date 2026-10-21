"""the top of handoff.md: what a person reads by default, before the record.

the record below it is long and in the runner's order; this is in the
reader's. it opens with the outcome and one sentence and the suite, then the
one decision the run leaves (on a stop, the question it waits on or the stop
itself), then why (what the last working step did and what the steps
assumed), what was not done (what nobody verified and the doubts left as
they are), and the spec lines an open question turns on. it is held to
BUDGET tokens, about four characters to a token; a list that does not fit
is cut, and the line that cuts it points at the full record below.

a question asked seven times is one decision. questions are gathered from a
step's NEEDS and CONFLICT lines, from the QUESTION lines of its block (which
never stop the run), from doubts that are questions, from what
the investigator leaves to a person and from a spec or test change nobody
ruled on; two are the same when they cite the same spec line (`TASK.md:12`,
or a range holding it) or say the same thing once case, punctuation and the
cited line are taken out. each is printed once, with every role that raised
it and the recommendation and size the first of them gave. doubts are made
one the same way. a question a ruling on record answered is not open.
"""
import re

from . import handoff, stops, verbs

BUDGET = 900
CHARS_PER_TOKEN = 4

SPEC_REF = re.compile(r"[\w./-]+\.md:\d+(?:-\d+)?")
WORD = re.compile(r"[a-z0-9]+")
MORE = "more in the full record below"
CARRY = ("what it needs from you and the command to carry on are under"
         " needs you, below.")
DECLINED = ("nothing carries it on; the step's reason is under needs you,"
            " below.")
# the kinds a stopped run waits on: they lead the decisions, before any
# question that did not stop it
WAITS = ("needs", "conflict")

# (most items per list, widest line) tried in turn until the view fits
STEPS = ((6, 300), (4, 240), (3, 200), (2, 160), (1, 120), (1, 80))


def tokens(lines):
    return (len("\n".join(lines)) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def refs(*texts):
    """-> the spec lines the texts cite, `path.md:n`, first seen first."""
    out = []
    for text in texts:
        for ref in SPEC_REF.findall(text or ""):
            ref = ref[2:] if ref.startswith("./") else ref
            if ref not in out:
                out.append(ref)
    return out


def norm(text):
    """-> the words of `text` with the cited spec lines taken out, in lower
    case: what two lines that say the same thing have in common."""
    return " ".join(WORD.findall(SPEC_REF.sub(" ", text or "").lower()))


def parts(item):
    """-> (text, recommendation, size) of a line that may carry
    `| recommend: <answer> | size: <cost>` after it."""
    bits = [b.strip() for b in (item or "").split("|")]
    text, rec, size = bits[0], "", ""
    for bit in bits[1:]:
        low = bit.lower()
        if low.startswith("recommendation:"):
            rec = bit[len("recommendation:"):].strip()
        elif low.startswith("recommend:"):
            rec = bit[len("recommend:"):].strip()
        elif low.startswith("size:"):
            size = bit[len("size:"):].strip()
        else:
            text = text + " | " + bit
    return text, rec, size


def point(role, text, cited=(), rec="", size="", options=(), kind="",
          by="", beside=None):
    """`by` names who the recommendation is from when it is not the role
    that raised the point; `beside` is (role, rec, size) of the asker's own
    recommendation, shown under it."""
    return {"role": role, "text": text, "refs": refs(text, *cited),
            "rec": rec or "", "size": size or "", "options": list(options),
            "kind": kind, "by": by, "beside": beside}


def is_question(text, rec=""):
    return bool(rec) or SPEC_REF.sub("", text).rstrip(" .()").endswith("?")


def clusters(points, by_line=True):
    """-> the points made one: a point joins the first cluster it shares a
    cited line with or says the same as, else starts its own. the same words
    about two different spec lines are two. the clusters holding what the run
    stopped on (a NEEDS or CONFLICT nobody answered) come first; the rest
    keep the order they were raised in. each keeps every wording it was
    given under `said`, so a question joined to another by its line is
    still on record. `by_line` False joins only on the words."""
    out = []
    for p in points:
        key = norm(p["text"])
        home = None
        for c in out:
            if by_line and shares(p["refs"], c["refs"]) \
                    or key in c["keys"] and same_lines(p, c):
                home = c
                break
        if home is None:
            home = {"text": p["text"], "roles": [], "count": 0, "refs": [],
                    "keys": [], "rec": "", "size": "", "options": [],
                    "kind": p["kind"], "said": [], "by": "", "beside": None}
            out.append(home)
        if key == norm(home["text"]):
            home["count"] += 1
        if p["role"] not in home["roles"]:
            home["roles"].append(p["role"])
        home["refs"].extend(r for r in p["refs"] if r not in home["refs"])
        if key not in home["keys"]:
            home["keys"].append(key)
        if p["rec"] and not home["rec"]:
            home["rec"], home["size"] = p["rec"], p["size"]
            home["by"], home["beside"] = p.get("by", ""), p.get("beside")
        elif p["size"] and not home["size"] and not home["rec"]:
            home["size"] = p["size"]
        home["options"].extend(o for o in p["options"]
                               if o not in home["options"])
        home["kind"] = home["kind"] or p["kind"]
        wording(home["said"], p)
    return sorted(out, key=lambda c: c["kind"] not in WAITS)


def same_lines(p, c):
    """whether a point that says what cluster `c` says is about its line: it
    cites none, `c` cites none, or they share one."""
    return not p["refs"] or not c["refs"] or shares(p["refs"], c["refs"])


def shares(a, b):
    """whether two lists of cited spec lines share a line: `TASK.md:3` and
    `TASK.md:3-4` do."""
    return any(x == y or overlaps(x, y) for x in a for y in b)


def same(p, q):
    """whether points `p` and `q` are one question, as `clusters` joins
    them."""
    return shares(p["refs"], q["refs"]) or \
        norm(p["text"]) == norm(q["text"]) and same_lines(p, q)


def asked_point(question):
    """-> the question a stop wrote to question.md, as a point."""
    v = verbs.parse(question)
    return point("", parts(v.needs or v.conflict or question.strip())[0],
                 v.cites)


def wording(said, p):
    """add point `p` to `said`, the wordings of one cluster, as a role more
    on the wording it repeats or as a wording of its own."""
    for w in said:
        if norm(w["text"]) == norm(p["text"]) and same_lines(p, w):
            if p["role"] not in w["roles"]:
                w["roles"].append(p["role"])
            if p["rec"] and not w["rec"]:
                w["rec"], w["size"] = p["rec"], p["size"]
            w["options"].extend(o for o in p["options"]
                                if o not in w["options"])
            return
    said.append({"text": p["text"], "roles": [p["role"]], "refs": p["refs"],
                 "rec": p["rec"], "size": p["size"],
                 "options": list(p["options"])})


ESCALATED = re.compile(r"the flow's lead did not decide it: (\S+) escalated"
                       r" it: ")
SPAN = re.compile(r"^(.+):(\d+)(?:-(\d+))?$")


def overlaps(a, b):
    """whether two cited spec lines, `path.md:n` or `path.md:n-m`, share a
    line."""
    ma, mb = SPAN.match(a), SPAN.match(b)
    if not ma or not mb or ma.group(1) != mb.group(1):
        return False
    a1, b1 = int(ma.group(2)), int(mb.group(2))
    a2, b2 = int(ma.group(3) or a1), int(mb.group(3) or b1)
    return a1 <= b2 and b1 <= a2


def block_rec(p, cited):
    """-> (rec, size) of the first question in pass `p`'s block that cites
    a line `cited` cites too and recommends something, else ("", "")."""
    b = p["block"]
    if b.get("state") not in (handoff.PRESENT, handoff.PARTIAL):
        return "", ""
    for q in b.get("questions") or []:
        if q.get("recommend") and any(overlaps(r, c) for r in refs(
                q.get("question")) for c in cited):
            return q["recommend"], q.get("size") or ""
    return "", ""


def lead_rec(said, passes):
    """-> (the lead's role, rec, size) when the lead escalated the question
    `said` and recommended an answer, else None: its own RECOMMEND, or the
    one its block gives the question it escalated."""
    m = ESCALATED.search(said or "")
    if not m:
        return None
    mine = [p for p in passes if p["step"] == m.group(1)]
    if not mine:
        return None
    p = mine[-1]
    rec, size = p["verbs"].recommend, p["verbs"].size
    if not rec:
        b = p["block"]
        if b.get("state") in (handoff.PRESENT, handoff.PARTIAL):
            for q in b.get("questions") or []:
                if q.get("recommend"):
                    rec, size = q["recommend"], q.get("size")
                    break
    return (p["role"], rec, size or "") if rec else None


def stopped_on(stopped, asking=(), passes=()):
    """-> the question a stop waits on, as a point, None when the stop asked
    none. it is read from the question the stop wrote to question.md, so a
    park on a verdict, a refusal with no cite and a spec change request are
    asked as much as a NEEDS line is. `asking` is the passes of the step it
    stopped at and `passes` every pass of the run.

    the recommendation shown is the deciding role's: the lead's when the
    lead escalated the question with one, the asker's then shown beside it.
    a conflict's step that recommends in its block, on a question citing a
    line the conflict cites, has that recommendation shown."""
    said = (stopped or {}).get("question")
    if not said:
        return None
    v = verbs.parse(said)
    text, rec, size = parts(v.needs or said.strip())
    role = stopped["at"]
    kind = "conflict" if stopped["cause"] == stops.CONFLICT else "needs"
    cited = refs(text, *v.cites)
    for p in asking:
        role = p["role"]
        rec, size = rec or p["verbs"].recommend, size or p["verbs"].size
        if kind == "conflict" and not rec:
            rec, size = block_rec(p, cited)
    led = lead_rec(said, passes)
    if led:
        beside = (role, rec, size) if rec else None
        return point(role, text, v.cites, led[1], led[2], v.options, kind,
                     by=led[0] + ", the flow's lead", beside=beside)
    return point(role, text, v.cites, rec, size, v.options, kind)


def questions(passes, extra=(), asking=None, settled=()):
    """-> (the open questions as points, the ids of the doubts taken in
    as questions) from every pass, then `extra` points the runner adds.
    `asking` is the passes whose NEEDS / CONFLICT nobody has answered yet;
    None takes them from every pass. `settled` is the questions a ruling on
    record answered, as points: one of them asked again is not open, and a
    doubt that asks it is not a doubt either."""
    out, taken = [], set()

    def add(p):
        if not any(same(p, q) for q in settled):
            out.append(p)

    for p in passes:
        v = p["verbs"]
        for said, kind in ((v.needs, "needs"), (v.conflict, "conflict")):
            if not said or (asking is not None
                            and not any(p is a for a in asking)):
                continue
            text, rec, size = parts(said)
            add(point(p["role"], text, v.cites, rec or v.recommend,
                      size or v.size, v.options, kind))
        b = p["block"]
        if b.get("state") not in (handoff.PRESENT, handoff.PARTIAL):
            continue
        for q in b.get("questions") or []:
            if q.get("question"):
                add(point(p["role"], q["question"], (), q.get("recommend"),
                          q.get("size")))
        for n, item in enumerate(b["doubts"]):
            text, rec, size = parts(item)
            if is_question(text, rec):
                add(point(p["role"], text, (), rec, size))
                taken.add((id(b), n))
    out.extend(extra)
    return out, taken


def shown(found, lines):
    """-> the indices of the clusters in `found` whose words the one decision
    in `lines`, the default view, prints in full: not cut to its width and
    not past the line that points at the full record."""
    if "## the one decision" not in lines:
        return set()
    block = lines[lines.index("## the one decision") + 1:]
    block = block[:next((n for n, l in enumerate(block)
                         if l.startswith("## ")), len(block))]
    return set(n for n, c in enumerate(found)
               if "- " + c["text"] in block
               or any(l.startswith("  - " + c["text"] + " (") for l in block))


def unprinted(found, printed=()):
    """-> the lines of the full record's open questions: every wording the
    default view does not print in full, each once with the roles that
    asked it, so a question joined to another by its spec line, cut to fit
    or past the cut is still on record. `printed` is `shown`."""
    out = []
    for n, c in enumerate(found):
        for w in c["said"][1 if n in printed else 0:]:
            out.append("- " + ", ".join(w["roles"]) + ": " + w["text"] + " ("
                       + recommended(w) + ")")
    return out


def doubts(passes, taken=(), by_line=True):
    """-> the doubts that are not questions, made one: [(text, who)], `who`
    the roles that raised it and how many times when a role raised it more
    than once: a doubt still there after a send-back was not fixed.
    `by_line` False keeps two that cite the same line apart, as the full
    record does."""
    found = []
    for p in passes:
        b = p["block"]
        if b.get("state") not in (handoff.PRESENT, handoff.PARTIAL):
            continue
        for n, item in enumerate(b["doubts"]):
            if (id(b), n) not in taken:
                found.append(point(p["role"], parts(item)[0]))
    return [(c["text"], raised_by(c)) for c in clusters(found, by_line)]


def raised_by(c):
    out = ", ".join(c["roles"])
    if c["count"] > len(c["roles"]):
        out = out + ", " + str(c["count"]) + " times"
    return out


def _cut(line, width):
    return line if len(line) <= width else line[:width - 3].rstrip() + "..."


def _list(items, most, width, indent="- "):
    out = [_cut(indent + i, width) for i in items[:most]]
    if len(items) > most:
        out.append(indent + "(+" + str(len(items) - most) + " " + MORE + ")")
    return out


def _decision(found, most, width, stop=None):
    out = ["## the one decision"]
    if stop:
        out.append(_cut("- " + stop[0], width))
        out.append("  " + stop[1])
        return out + _also(found, most, width)
    if not found:
        out.append("- none: nothing waits on you.")
        return out
    first = found[0]
    out.append(_cut("- " + first["text"], width))
    raised = "  raised by " + raised_by(first)
    if first["refs"]:
        raised = raised + "; cites " + ", ".join(first["refs"])
    out.append(_cut(raised, width))
    out.append(_cut("  " + recommended(first), width))
    if first.get("beside"):
        who, rec, size = first["beside"]
        out.append(_cut("  " + who + "'s recommendation: " + rec
                        + (" (size: " + size + ")" if size else ""), width))
    return out + _also(found[1:], most, width)


def _also(found, most, width):
    if not found:
        return []
    return ["  also open:"] + _list(
        [c["text"] + " (" + ", ".join(c["roles"]) + "; " + recommended(c)
         + ")" for c in found], most, width, "  - ")


def recommended(c):
    if c["rec"]:
        return ("recommendation" + (" (" + c["by"] + ")" if c.get("by")
                                    else "") + ": " + c["rec"]
                + (" (size: " + c["size"] + ")" if c["size"] else
                   " (size not given)")
                + ("; options: " + " / ".join(c["options"])
                   if c.get("kind") == "conflict" and c["options"] else ""))
    if c["options"]:
        return "recommendation: none given; options: " + " / ".join(
            c["options"])
    return "recommendation: none given by a step that raised it"


def _section(title, groups, most, width):
    out = ["## " + title]
    for label, items in groups:
        if not items:
            continue
        if label:
            out.append(_cut(label, width))
        out.extend(_list(items, most, width))
    if len(out) == 1:
        out.append("- none")
    return out


def gaps(found, spec_changed=(), lead=True):
    """-> the product gaps: each spec line an open question turns on, and
    each spec file the run changed. `lead` False is a decision that is the
    stop, not the first question."""
    out = []
    for n, c in enumerate(found):
        for ref in c["refs"]:
            line = ref + (" - the one decision turns on it" if n == 0 and lead
                          else
                          " - an open question turns on it")
            if c["kind"] == "conflict":
                line = line + "; the request contradicts it"
            if line not in out:
                out.append(line)
    out.extend(path + " +" + str(a) + " -" + str(d) + " - the spec text"
               " changed in this run" for path, a, d in spec_changed)
    return out


def view(head, found, why, not_done, product_gaps, stop=None):
    """-> the default view: `head` as it is, then the one decision, why,
    not done and product gaps, cut until it fits BUDGET. `why` and
    `not_done` are [(label or None, [items])]. `stop` is (how the run
    stopped, what to do about it) for a stop no step asked a question on,
    and is then the decision itself: a gate or a cap is what the person
    decides on, not a question a step left open. the head is cut too, last,
    when cutting the lists is not enough: a long task line or stop reason is
    in full in the record below."""
    out = []
    for most, width, cut in [step + (False,) for step in STEPS] + [
            step + (True,) for step in STEPS]:
        out = [_cut(l, width) for l in head] if cut else list(head)
        out.append("")
        out.extend(_decision(found, most, width, stop))
        out.append("")
        out.extend(_section("why", why, most, width))
        out.append("")
        out.extend(_section("not done", not_done, most, width))
        out.append("")
        out.extend(_section("product gaps", [(None, product_gaps)], most,
                            width))
        if tokens(out) <= BUDGET:
            break
    return out


def pointer(run_id):
    return ["## full record",
            "every line the run left, section by section; each step's own"
            " answer is in runs/" + run_id + "/steps/ and its record in"
            " runs/" + run_id + "/steps.jsonl."]
