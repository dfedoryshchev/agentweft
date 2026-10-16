"""the top of handoff.md: what a person reads by default, before the record.

the record below it is long and in the runner's order; this is in the
reader's. it opens with the outcome and one sentence and the suite, then the
one decision the run leaves, then why (the architect's read), what was not
done (the dev's and the lead's), and the product gaps (the analyst's). it is
held to BUDGET tokens, about four characters to a token; a list that does not
fit is cut, and the line that cuts it points at the full record below.

a question asked seven times is one decision. questions are gathered from a
step's NEEDS and CONFLICT lines, from the QUESTION lines of its block (which
never stop the run), from doubts that are questions, from what
the investigator leaves to a person and from a spec or test change nobody
ruled on; two are the same when they cite the same spec line (`TASK.md:12`)
or say the same thing once case, punctuation and the cited line are taken
out. each is printed once, with every role that raised it and the
recommendation and size the first of them gave. doubts are made one the same
way.
"""
import re

from . import handoff

BUDGET = 900
CHARS_PER_TOKEN = 4

SPEC_REF = re.compile(r"[\w./-]+\.md:\d+(?:-\d+)?")
WORD = re.compile(r"[a-z0-9]+")
MORE = "more in the full record below"
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


def point(role, text, cited=(), rec="", size="", options=(), kind=""):
    return {"role": role, "text": text, "refs": refs(text, *cited),
            "rec": rec or "", "size": size or "", "options": list(options),
            "kind": kind}


def is_question(text, rec=""):
    return bool(rec) or SPEC_REF.sub("", text).rstrip(" .()").endswith("?")


def clusters(points):
    """-> the points made one: a point joins the first cluster it shares a
    cited line with or says the same as, else starts its own. the clusters
    holding what the run stopped on (a NEEDS or CONFLICT nobody answered)
    come first; the rest keep the order they were raised in."""
    out = []
    for p in points:
        key = norm(p["text"])
        home = None
        for c in out:
            if set(p["refs"]) & set(c["refs"]) or key in c["keys"]:
                home = c
                break
        if home is None:
            home = {"text": p["text"], "roles": [], "count": 0, "refs": [],
                    "keys": [], "rec": "", "size": "", "options": [],
                    "kind": p["kind"]}
            out.append(home)
        home["count"] += 1
        if p["role"] not in home["roles"]:
            home["roles"].append(p["role"])
        home["refs"].extend(r for r in p["refs"] if r not in home["refs"])
        if key not in home["keys"]:
            home["keys"].append(key)
        if p["rec"] and not home["rec"]:
            home["rec"], home["size"] = p["rec"], p["size"]
        elif p["size"] and not home["size"] and not home["rec"]:
            home["size"] = p["size"]
        home["options"].extend(o for o in p["options"]
                               if o not in home["options"])
        home["kind"] = home["kind"] or p["kind"]
    return sorted(out, key=lambda c: c["kind"] not in WAITS)


def questions(passes, extra=(), asking=None):
    """-> (the open questions as points, the ids of the doubts taken in
    as questions) from every pass, then `extra` points the runner adds.
    `asking` is the passes whose NEEDS / CONFLICT nobody has answered yet;
    None takes them from every pass."""
    out, taken = [], set()
    for p in passes:
        v = p["verbs"]
        for said, kind in ((v.needs, "needs"), (v.conflict, "conflict")):
            if not said or (asking is not None
                            and not any(p is a for a in asking)):
                continue
            text, rec, size = parts(said)
            out.append(point(p["role"], text, v.cites, rec or v.recommend,
                             size or v.size, v.options, kind))
        b = p["block"]
        if b.get("state") not in (handoff.PRESENT, handoff.PARTIAL):
            continue
        for q in b.get("questions") or []:
            if q.get("question"):
                out.append(point(p["role"], q["question"], (),
                                 q.get("recommend"), q.get("size")))
        for n, item in enumerate(b["doubts"]):
            text, rec, size = parts(item)
            if is_question(text, rec):
                out.append(point(p["role"], text, (), rec, size))
                taken.add((id(b), n))
    out.extend(extra)
    return out, taken


def printed(passes, taken, found):
    """-> the doubts taken in as questions that say what a decision line
    already prints; the full record keeps the rest, worded their own way."""
    said = set(norm(c["text"]) for c in found)
    out = set()
    for p in passes:
        b = p["block"]
        for n, item in enumerate(b.get("doubts") or []):
            if (id(b), n) in taken and norm(parts(item)[0]) in said:
                out.add((id(b), n))
    return out


def doubts(passes, taken=(), by_line=True):
    """-> the doubts that are not questions, made one: [(text, roles)].
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
    if not by_line:
        for p in found:
            p["refs"] = []
    return [(c["text"], c["roles"]) for c in clusters(found)]


def _cut(line, width):
    return line if len(line) <= width else line[:width - 3].rstrip() + "..."


def _list(items, most, width, indent="- "):
    out = [_cut(indent + i, width) for i in items[:most]]
    if len(items) > most:
        out.append(indent + "(+" + str(len(items) - most) + " " + MORE + ")")
    return out


def _decision(found, done, most, width):
    out = ["## the one decision"]
    if not found:
        out.append("- none: nothing waits on you." if done else
                   "- no step asked one; what the stop needs from you is"
                   " under needs you, below.")
        return out
    first = found[0]
    out.append(_cut("- " + first["text"], width))
    raised = "  raised by " + ", ".join(first["roles"])
    if first["count"] > len(first["roles"]):
        raised = raised + ", " + str(first["count"]) + " times"
    if first["refs"]:
        raised = raised + "; cites " + ", ".join(first["refs"])
    out.append(_cut(raised, width))
    out.append(_cut("  " + recommended(first), width))
    if len(found) > 1:
        out.append("  also open:")
        out.extend(_list([c["text"] + " (" + ", ".join(c["roles"]) + "; "
                          + recommended(c) + ")" for c in found[1:]],
                         most, width, "  - "))
    return out


def recommended(c):
    if c["rec"]:
        return ("recommendation: " + c["rec"]
                + (" (size: " + c["size"] + ")" if c["size"] else
                   " (size not given)"))
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


def gaps(found, spec_changed=()):
    """-> the product gaps: each spec line an open question turns on, and
    each spec file the run changed."""
    out = []
    for n, c in enumerate(found):
        for ref in c["refs"]:
            line = ref + (" - the one decision turns on it" if n == 0 else
                          " - an open question turns on it")
            if c["kind"] == "conflict":
                line = line + "; the request contradicts it"
            if line not in out:
                out.append(line)
    out.extend(path + " +" + str(a) + " -" + str(d) + " - the spec text"
               " changed in this run" for path, a, d in spec_changed)
    return out


def view(head, found, done, why, not_done, product_gaps):
    """-> the default view: `head` as it is, then the one decision, why,
    not done and product gaps, cut until it fits BUDGET. `why` and
    `not_done` are [(label or None, [items])]."""
    out = []
    for most, width in STEPS:
        out = list(head)
        out.append("")
        out.extend(_decision(found, done, most, width))
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
