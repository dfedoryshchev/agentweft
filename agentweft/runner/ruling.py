"""a step that asks for a ruling, and the answer that carries the run on.

a step that cannot do its work without someone deciding something says so on
a line of its own: `NEEDS: <the question>`, with `CITES:` and `OPTIONS:` under
it if it has them, or a first line of `VERDICT: park`. the run parks before
that step's gates, because a step that stopped to ask has produced nothing to
gate, and it waits for a ruling; a step that changed the place first has its
gates run on that before the park. a question that says what it would pick
(`RECOMMEND:`) and whose `SIZE:` for that pick changes no code parks nothing:
it is the step's call, and goes on as a doubt with that answer taken
(`demoted`).
`--resume <run id> --answer "<text>"` (or `--answer-file <path>`) runs that
same step again with the answer at the end of its prompt, and the question,
the answer and who gave it go into decisions.md in the place the run works
in. a flow with a `lead:` step asks
that step first, and parks only when it does not decide (`lead`). a judge
whose file lists `VERDICT: spec change request` and answers it asks the same
way, with the lines after its verdict as the reason.

`REFUSED: <file>:<line> "<the line>"` is a step declining the work because
the spec says otherwise. with a cite of a line that is there, the run ends on
it as a finished run: the refusal is the answer. without one it is read as a
question, because a refusal nobody can check is somebody's opinion.

`CONFLICT: <file>:<line> "<the line>"`, with `request: <the request's
words>` on the line after it, is a step finding that the request contradicts
the spec. the older one-line form, `| <the request's words>` after the quote,
still reads. the quote is checked against
that line as the run found it, from the start snapshot, so a step cannot make
its own cite true by editing the file first. a quote that is there stops the
run on a conflict, with the question in handoff.md; one that is not fails the
step, and so does a plan line marked `spec: contradicts` with no CONFLICT
line. the answer to a conflict says which one holds: `override: <the new
rule>` lets the request win and authorises that spec line to change, and
nothing else; `request: <what to do instead>` keeps the spec, adds the words
to the request, and starts again from the first step that reads it.

the lines are read by `verbs`, so one inside a code fence or a `>` quote is
not a question: a test that asserts on the string "NEEDS:" asks nothing.
"""
import getpass
import hashlib
import re
from pathlib import Path

from . import lead, verbs
from .config import SPEC_CHANGE, verdict
from .handoff import KEYS, KNOWN, NONE_WORDS, bounds, without

PARK = "park"
ASKED = "ruling"
DECLINED = "declined"
OVERRIDE = "override"
REQUEST = "request"
ANSWERS = (OVERRIDE, REQUEST)

CITE = re.compile(r"""^\s*[`'"]?([^\s:`'"]+):(\d+)\b""")
# the quote runs to the last `"` that only a `|` or the end of the line
# follows, so a quote may hold quotes of its own
CONFLICT = re.compile(r"""^[`'"]?([^\s:`'"]+):(\d+)(?:-(\d+))?[`'"]?\s+"(.*?)"\s*"""
                      r"""(?:\|\s*(.*?))?\s*$""")
CONTRADICTS = re.compile(r"^\s*(?:-\s*)?spec:\s*contradicts\b", re.I)
CITED = re.compile(r"""^-\s*([^\s:`'"]+:\d+(?:-\d+)?)\b""")


def question_of(v):
    """-> the question as it is shown and kept: the NEEDS line, then the
    cites and options under it."""
    out = ["NEEDS: " + v.needs]
    if v.cites:
        out.append("CITES:")
        out.extend("- " + c for c in v.cites)
    if v.options:
        out.append("OPTIONS:")
        out.extend("- " + o for o in v.options)
    return "\n".join(out)


def cited(said, cites, workdir):
    """-> the first of `said` and `cites` that names a line in a file under
    `workdir` that is there, or None."""
    root = Path(workdir).resolve()
    for text in [said] + list(cites or []):
        m = CITE.match(text or "")
        if not m:
            continue
        path = (root / m.group(1)).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            count = len(path.read_text(encoding="utf-8",
                                       errors="replace").split("\n"))
        except OSError:
            continue
        if 1 <= int(m.group(2)) <= count:
            return text
    return None


def spec_change_of(output):
    """-> the question a `VERDICT: spec change request` answer stops on, with
    the judge's reason: the lines after its verdict line, up to the next
    one."""
    lines = without(output).split("\n")
    reason = []
    for i, line in enumerate(lines):
        if verdict(line) != SPEC_CHANGE:
            continue
        for rest in lines[i + 1:]:
            if verdict(rest, asked=True):
                break
            if rest.strip():
                reason.append(rest.strip())
        break
    said = flat(" ".join(reason)) or "the judge did not say why"
    return ("NEEDS: the judge answered " + SPEC_CHANGE + ": the request"
            " changes the spec rather than working under it. " + said
            + "\nOPTIONS:\n- the spec may change: say which lines, and how"
            "\n- the spec holds: say what to do instead")


def asked_of(output, workdir, word=None, allowed=None, start=None):
    """-> (ASKED, the question), (DECLINED, the cited refusal) or None for an
    answer that did neither. `word` is the step's verdict and `allowed` the
    verdicts its file lists; a spec change request asks only when it is one
    of them, and otherwise is left to fail as an answer the file never
    offered. a refusal quoting what its line does not say is left to fail at
    the gates (`misquoted`)."""
    v = verbs.parse(output)
    if misquoted(output, workdir, start):
        return None
    if v.refused and not v.needs:
        cite = cited(v.refused, v.cites, workdir)
        if cite is not None:
            return DECLINED, "REFUSED: " + v.refused
        v.needs = v.refused + " (refused with no line of the spec cited)"
    if v.needs:
        return ASKED, question_of(v)
    if word == SPEC_CHANGE and SPEC_CHANGE in (allowed or ()):
        return ASKED, spec_change_of(output)
    if verdict(output) == PARK:
        said = [l.strip() for l in without(output).split("\n")[1:]
                if l.strip()]
        return ASKED, "NEEDS: " + (said[0] if said else
                                   "the step parked and did not say on what")
    return None


NO_CODE = re.compile(r"^(zero|none|nothing|no code|no change|0\b)")
ONE_TEST = re.compile(r"^(only )?(one|a|1) (new |unit |optional |regression )*"
                      r"test( function| case)?( only)?$")
# "zero code lines" names no code; "one line in parse.py" or "4 lines for B"
# does, wherever it sits in the SIZE
CODE_LINES = re.compile(r"\b([1-9]\d*|one|two|three|four|five|a few|several)"
                        r" (code )?lines?\b")
ASKING = ("needs", "cites", "options", "recommend", "size")
# "none if left; one line in x.py if it is ruled": a price, then the answer
# it is the price of
BRANCH = re.compile(r"^(.*?)[,\s]+if\s+(.+)$")
PARTS = re.compile(r"\s*(?:,|\bplus\b|\band\b)\s*")
# a recommendation to leave things as they are is the tree the step already
# left, so it costs nothing whatever the SIZE says the other answer costs
KEEPS = re.compile(r"^(leave|keep)( (it|them|this|that|things))?"
                   r"( (as (it|they) (is|are)|as is|alone|unchanged))?$")
SAME = {"left": "leave", "kept": "keep", "ruled": "rule", "counted": "count"}
SMALL = ("the", "and", "but", "for", "its", "it's", "that", "this", "with",
         "should", "would", "will", "is", "are", "be", "as", "if")


def no_code(size):
    """-> whether a question's SIZE says no product code changes, whatever
    the answer: zero, none, no code, or one test and nothing else, each part
    of it read on its own ("one test; no code change")."""
    said = flat(size).lower().rstrip(" .")
    if not said or CODE_LINES.search(said):
        return False
    if NO_CODE.match(said) or ONE_TEST.match(said):
        return True
    parts = [p.strip(" .") for p in PARTS.split(re.sub(r";|\.\s+", ",",
                                                         said))]
    parts = [p for p in parts if p and not p.startswith("if ")]
    return bool(parts) and all(NO_CODE.match(p) or ONE_TEST.match(p)
                               for p in parts)


def words_of(text):
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        w = SAME.get(w, w)
        if len(w) > 2 and w not in SMALL:
            out.add(w)
    return out


def priced(size, recommend):
    """-> the parts of SIZE that price the recommended answer. a SIZE that
    prices each answer on its own ("none if left; one line in x.py if a lone
    CR counts") is read on the answer whose words are nearest the RECOMMEND,
    the first one when none is nearer than the rest; what holds whichever
    answer is taken is kept beside it."""
    said = flat(size).lower().rstrip(" .")
    plain, branches = [], []
    for clause in re.split(r";|\.\s+", said):
        clause = clause.strip(" ,.")
        if not clause:
            continue
        m = BRANCH.match(clause)
        if m and m.group(1).strip(" ,"):
            branches.append((m.group(1).strip(" ,"), m.group(2)))
        else:
            plain.append(clause)
    if not branches:
        return "; ".join(plain)
    asked = words_of(recommend)
    near = [len(asked & words_of(cond)) for _, cond in branches]
    best = max(near)
    pick = branches[0] if best == 0 or near.count(best) > 1 \
        else branches[near.index(best)]
    return "; ".join(plain + [pick[0]])


def costs_nothing(size, recommend):
    """-> whether the answer the step recommends changes no product code:
    it leaves things as they are, or its part of the SIZE says no code."""
    if KEEPS.match(flat(recommend).lower().rstrip(" .")):
        return True
    return no_code(priced(size, recommend))


def demoted(output):
    """-> (the answer with its question taken out and kept as a DOUBTS line,
    that line) for a NEEDS whose recommended answer changes no code and
    which says what it would pick and cites no spec line, else None. such a
    question is the step's call: it goes on with the RECOMMEND as its
    answer. one that cites a spec line is a gap in the spec, which a person
    rules on."""
    where = {}
    v = verbs.parse(output, where)
    if not v.needs or v.refused or v.conflict or v.cites \
            or not v.recommend or not costs_nothing(v.size, v.recommend):
        return None
    doubt = (flat(v.needs) + " assumed: " + flat(v.recommend) + " (size: "
             + flat(v.size) + ")")
    lines = output.split("\n")
    asked = set(i for key in ASKING for i in where.get(key, []))
    first = min(asked)
    kept = [(i, line) for i, line in enumerate(lines) if i not in asked]
    return "\n".join(into_doubts(kept, first, doubt)), doubt


def into_doubts(kept, first, doubt):
    """-> the lines of `kept`, (index, line) pairs, with `doubt` under the
    DOUBTS heading of the HANDOFF block; with no block, where the question
    was, at index `first`."""
    found, _ = handoff_bounds(kept)
    out = [line for _, line in kept]
    if found is None:
        at = len([i for i, _ in kept if i < first])
        return out[:at] + ["DOUBTS: " + doubt] + out[at:]
    start, end = found
    for n in range(start + 1, end):
        head = verbs.key_of(out[n])
        if head is None or head[0] != "DOUBTS" or (head[2] and
                                                   not head[3]):
            continue
        last = n + 1
        while last < end and not heading(out[last]):
            last += 1
        items = [l for l in out[n + 1:last]
                 if not (verbs.BULLET.match(l) and verbs.BULLET.match(l)
                         .group(1).lower() in NONE_WORDS)]
        if head[1].lower() not in NONE_WORDS:
            items.insert(0, "- " + head[1])
        return out[:n] + ["DOUBTS:"] + items + ["- " + doubt] + out[last:]
    return out[:end] + ["DOUBTS:", "- " + doubt] + out[end:]


def heading(line):
    """-> whether the block reads `line` as a heading of its own: a bullet
    is one only when it is a known name in capitals."""
    head = verbs.key_of(line)
    if head is None:
        return False
    return not head[2] or (KEYS.get(head[0]) in KNOWN and head[3])


def handoff_bounds(kept):
    """-> ((start, end) positions in `kept` of its HANDOFF block, None) or
    (None, why), read the way the block itself is."""
    shown = verbs.visible("\n".join(line for _, line in kept))
    found, why = bounds(shown)
    if found is None:
        return None, why
    return (shown[found[0]][0], shown[found[1]][0]), None


def flat(text):
    return " ".join((text or "").split())


def as_found(workdir, rel, start=None):
    """-> the text of `rel`, a path from `workdir`, as the run found it, or
    None when it was not there or cannot be told.

    with a start commit or a file that was already loose, the snapshot gives
    the bytes back. a place hashed outside git has only hashes, so the file
    as it is now counts when its hash is still the one it started with. no
    snapshot at all means the run never changes the place, and the file now
    is the file it found.
    """
    root = Path(workdir).resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if start is None or not getattr(start, "hashed", False):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    try:
        key = path.relative_to(start.root).as_posix()
    except (TypeError, ValueError):
        return None
    if start.start or key in start.loose:
        data = start.before(key)
    else:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        known = (start.tests.get(key) or start.specs.get(key)
                 or start.product.get(key))
        if known != hashlib.sha256(data).hexdigest():
            return None
    if data is None:
        return None
    return data.decode("utf-8", "replace")


def conflict_of(output, workdir, start=None):
    """-> None for an answer with no CONFLICT line, else (the question, "")
    when the quote is at the line it cites as the run found it, or ("", what
    is wrong with it) when it is not. an answer that marks a behaviour
    `spec: contradicts` and has no CONFLICT line is wrong the same way."""
    said = verbs.parse(output).conflict
    if said is None:
        return untyped(output)
    m = CONFLICT.match(said.strip())
    if not m:
        return "", ('the CONFLICT line is not <file>:<line> "<the line>",'
                    " with request: <the request's words> on the next line: "
                    + said)
    rel, first, last, quote, cite = cite_of(m)
    words = flat(m.group(5)) or request_of(output)
    if not quote:
        return "", "the CONFLICT line cites " + cite + " and quotes nothing"
    found, why = at_line(workdir, rel, first, last, start)
    if found is None:
        return "", "the CONFLICT line cites " + cite + ", and " + why
    if quote not in found:
        return "", ('the CONFLICT line quotes "' + quote + '", which is not'
                    " at " + cite + " as the run found it. quote the line"
                    " as it is, or answer without a CONFLICT line")
    return question_of_conflict(cite, quote, words), ""


def untyped(output):
    """-> None, or ("", why) for an answer whose plan marks a behaviour
    `spec: contradicts` with no CONFLICT line to stop the run on it."""
    marked = [line.strip().lstrip("-").strip() for _, line in
              verbs.visible(output) if CONTRADICTS.match(line)]
    if not marked:
        return None
    return "", ("the answer marks " + "; ".join(marked) + " and has no"
                ' CONFLICT line. type it as CONFLICT: <file>:<line> "<the'
                ' line>", with request: <the request\'s words> on the next'
                " line, or mark the behaviour another way")


# the first quoted span after a cite, for a line that goes on past its quote:
# `REFUSED: notes.md:2 "the line" is money, not notes`
FIRST_QUOTE = re.compile(r"""^[`'"]?([^\s:`'"]+):(\d+)(?:-(\d+))?[`'"]?\s+"""
                         r'''"([^"\n]*)"''')


def cite_of(m):
    """-> (the file, first line, last line, the quote, the cite as written)
    from a CONFLICT or FIRST_QUOTE match."""
    rel, first = m.group(1), int(m.group(2))
    last = int(m.group(3) or first)
    cite = rel + ":" + str(first) + ("-" + str(last) if last != first else "")
    return rel, first, last, flat(m.group(4)), cite


def at_line(workdir, rel, first, last, start=None):
    """-> (lines `first` to `last` of `rel` as the run found them, as one
    flat string, "") or (None, why they cannot be read)."""
    text = as_found(workdir, rel, start)
    if text is None:
        return None, rel + " was not there when the run started"
    lines = text.split("\n")
    if not 1 <= first <= last <= len(lines):
        return None, (rel + " had " + str(len(lines)) + " lines when the run"
                      " started")
    return flat(" ".join(lines[first - 1:last])), ""


def misquote(said, workdir, start=None, who="the answer"):
    """-> "" when `said`, `<file>:<line> "<the line>"`, quotes nothing or
    quotes what is at that line as the run found it, else what is wrong."""
    said = (said or "").strip()
    m = CONFLICT.match(said) or FIRST_QUOTE.match(said)
    if not m:
        return ""
    rel, first, last, quote, cite = cite_of(m)
    if not quote:
        return ""
    found, why = at_line(workdir, rel, first, last, start)
    if found is None:
        return who + ' quotes "' + quote + '" from ' + cite + ", and " + why
    if quote in found:
        return ""
    return (who + ' quotes "' + quote + '", which is not at ' + cite
            + " as the run found it")


def misquoted(output, workdir, start=None):
    """-> what is wrong with the quote of a REFUSED line, or "". a cite of a
    line that is not there is no cite, and is read as a question instead."""
    v = verbs.parse(output)
    if not v.refused or v.needs or cited(v.refused, [], workdir) is None:
        return ""
    return misquote(v.refused, workdir, start, "the REFUSED line")


def request_of(output):
    """-> the words on a `request:` line straight after the CONFLICT line,
    or "". a `request:` anywhere else in the answer is not them."""
    seen = verbs.visible(output)
    for i, (_, line) in enumerate(seen):
        head = verbs.key_of(line)
        if head is None or head[0] != "CONFLICT":
            continue
        nxt = verbs.key_of(seen[i + 1][1]) if i + 1 < len(seen) else None
        if nxt is not None and nxt[0] == "REQUEST":
            return flat(verbs.unquoted(nxt[1]))
        return ""
    return ""


def question_of_conflict(cite, quote, words):
    out = ["NEEDS: the request contradicts " + cite
           + ". which one holds?", "CITES:", "- " + cite + ' - "' + quote + '"']
    if words:
        out.append('- the request - "' + words + '"')
    out.extend(["OPTIONS:",
                "- override: <the new rule>. the request wins, and " + cite
                + " may change to match it, nothing else",
                "- request: <what to do instead>. the spec holds; the words"
                " are added to the request and the run starts again from its"
                " first step that reads the request"])
    return "\n".join(out)


def question_of_start_tests(step, red):
    """-> the question a start test gone red stops the run on. `red` is
    [(test id, what it said)]."""
    out = ["NEEDS: " + step + " wrote product code, and "
           + ("a test" if len(red) == 1 else str(len(red)) + " tests")
           + " the run started with, green then, "
           + ("fails" if len(red) == 1 else "fail")
           + " against it now. which one holds?", "CITES:"]
    out.extend("- " + test + ' - "' + flat(said) + '"' for test, said in red)
    out.extend(["OPTIONS:",
                "- override: <why the change holds>. name each test above, or"
                " quote the spec line that decides it, and the change stands",
                "- request: <what to do instead>. the tests hold; the words"
                " are added to the request and the run starts again from its"
                " first step that reads the request"])
    return "\n".join(out)


def kind_of(answer):
    """-> OVERRIDE, REQUEST or None, from the word the answer starts with."""
    m = re.match(r"\s*(\w+)\s*:", answer or "")
    if m and m.group(1).lower() in ANSWERS:
        return m.group(1).lower()
    return None


def authorised(question):
    """-> the spec lines a conflict's question cites, the ones an override
    may change."""
    out = []
    for line in (question or "").split("\n"):
        m = CITED.match(line.strip())
        if m:
            out.append(m.group(1))
    return out


def amended(task, answer):
    """-> the request with a `request:` answer added after it. the request
    as it was given stays word for word, first."""
    words = answer.strip()[len(REQUEST) + 1:].strip()
    return ((task or "").rstrip("\n") + "\n\nadded after a spec conflict, and"
            " it decides where the two disagree:\n\n" + words + "\n")


QUOTED = re.compile(r'"([^"\n]+)"')
# a quote of two words or fewer is in almost any spec, and would cover
# every test the ruling was asked about by accident
QUOTE_WORDS = 3


ANSWERED = "\n\nanswered:\n\n"
ANSWERED_BY = "\n\nanswered by "
ANSWERED_END = ", with --answer"


def asked_and_answered(d):
    """-> (the body up to the answer, the answer) of a decisions.md entry
    written by --answer, None for an entry written any other way."""
    why = d.why
    if not why.startswith("asked by ") or not why.endswith(ANSWERED_END):
        return None
    # the question before the answer is a step's words and may hold the
    # markers itself; the runner's own are the last ones in the body
    asked, sep, rest = why.rpartition(ANSWERED)
    if not sep:
        return None
    return asked, rest.rpartition(ANSWERED_BY)[0].strip()


def answered(d):
    """-> the answer in a decisions.md entry written by --answer, "" for an
    entry written any other way."""
    found = asked_and_answered(d)
    return found[1] if found else ""


CAPPED = re.compile(r"^carried \S+ on with the ")


def capped(run_id, moved, why):
    """-> (the decisions.md heading, its body) for caps raised to carry
    `run_id` on: `moved` names them, `why` is why that run stopped."""
    return ("carried " + run_id + " on with the " + ", the ".join(moved),
            why or "the caps were changed before carrying on.")


def own_words(d):
    """-> what a decisions.md entry itself says, keyed on how the runner
    wrote it: for --answer its heading and the answer, for the lead its
    heading and its DECIDED and why lines, never the question either was
    asked; for raised caps the heading alone, never the stop it carried on
    from. an entry written any other way (by hand) is all its own words."""
    said = answered(d)
    if said:
        return d.decided + "\n" + said
    decided = lead.decided_of(d.why)
    if decided is not None:
        return d.decided + "\n" + decided
    if CAPPED.match(d.decided):
        return d.decided
    return d.decided + "\n" + d.why


def names_test(text, test):
    """whether `text` names `test` by its id, with or without the folders
    before the file and the parameters after the name."""
    short = test.rsplit("/", 1)[-1]
    for t in (short, short.split("[")[0]):
        if re.search(r"(?<![\w.-])" + re.escape(t) + r"(?!\w)", text or "",
                     re.I):
            return True
    return False


def spec_quoted(text, workdir, start):
    """whether `text` quotes, between double quotes, a line of a spec file
    as the run found it."""
    quotes = [flat(q) for q in QUOTED.findall(text or "")
              if len(q.split()) >= QUOTE_WORDS]
    if not quotes or start is None or not getattr(start, "hashed", False):
        return False
    for rel in sorted(start.specs):
        try:
            found = as_found(workdir, start.from_place(rel), start)
        except ValueError:
            continue
        lines = [flat(l) for l in (found or "").split("\n")]
        if any(q in l for q in quotes for l in lines):
            return True
    return False


def covering(decided, test, workdir, start=None):
    """-> the decisions.md entry that lets `test`, green when the run started,
    be red now, or None. it names the test in its own words, or it is an
    --answer that quotes the spec line that decides it as the run found it
    and answers a question naming the test. a lead decides inside the tests
    it was given, so its quote never covers one by the question alone. an
    answer of `request:` keeps what the run started with, so it never covers
    one."""
    for d in decided:
        said = answered(d)
        if kind_of(said or d.decided) == REQUEST:
            continue
        own = own_words(d)
        if names_test(own, test):
            return d
        if said and names_test(d.why, test) and \
                spec_quoted(own, workdir, start):
            return d
    return None


ASKED_IN = re.compile(r"^asked by \S+ in (\S+):\n")
EDITS_ASKED = " the run started with. may "


def answers_edits(d, test, runs):
    """whether `d` is an `override:` answer, given with --answer, to the
    question a test edit parked one of `runs` on, and that question cites
    `test`."""
    found = asked_and_answered(d)
    m = ASKED_IN.match(d.why)
    if not found or kind_of(found[1]) != OVERRIDE or not m \
            or m.group(1) not in runs:
        return False
    question = found[0]
    return EDITS_ASKED in question and any(
        line.startswith("- " + test + " - ") for line in question.split("\n"))


def edit_ruled(decided, test, workdir, start=None, runs=()):
    """-> the decisions.md entry that lets `test`, a test the run started
    with, be changed or removed, or None. `test` is a test id, or a file when
    the change is the file's. an `override:` answer to the question a test
    edit in one of `runs` (this run, the one it picked up) parked on covers
    what that question cites. a test id is also covered by what covers a
    start test gone red, and by an entry naming the test by its name alone.
    naming the file covers nothing: a ruling on where a new case goes names
    it too. an answer of `request:` never covers one."""
    for d in decided:
        if answers_edits(d, test, runs):
            return d
    path, sep, name = test.partition("::")
    if not sep:
        return None
    found = covering(decided, test, workdir, start)
    if found is not None:
        return found
    for d in decided:
        if kind_of(answered(d) or d.decided) == REQUEST:
            continue
        if names_test(own_words(d), name.rsplit("::", 1)[-1]):
            return d
    return None


def question_of_test_edits(step, left):
    """-> the question a step that still changes tests the run started with
    on its last go parks the run on. `left` is [(test id or file, how it
    changed)]."""
    one = len(left) == 1
    out = ["NEEDS: " + step + " changed "
           + ("a test" if one else str(len(left)) + " tests")
           + EDITS_ASKED + ("it" if one else "they")
           + " change?", "CITES:"]
    out.extend("- " + test + " - " + how for test, how in left)
    out.extend(["OPTIONS:",
                "- override: <why the change holds>. name each test above, or"
                " quote the spec line that decides it, and the change stands",
                "- anything else is told to " + step + ", which runs again:"
                " to keep the tests as they were, say put them back"])
    return "\n".join(out)


def quotes_line(text, line):
    """whether `text` quotes `line`, between double quotes: all of it, or
    QUOTE_WORDS words of it or more."""
    line = flat(line)
    for q in QUOTED.findall(text or ""):
        q = flat(q)
        if q == line or (len(q.split()) >= QUOTE_WORDS and q in line):
            return True
    return False


def spec_line_ruled(decided, line):
    """-> the decisions.md entry that lets a spec line the run started with
    be removed or rewritten, or None. it quotes the line in its own words,
    or it is an `override:` answer to the question that quoted it. an
    answer of `request:` keeps the spec, so it never rules one."""
    for d in decided:
        said = answered(d)
        kind = kind_of(said or d.decided)
        if kind == REQUEST:
            continue
        if quotes_line(own_words(d), line):
            return d
        if said and kind == OVERRIDE and quotes_line(d.why, line):
            return d
    return None


def question_of_spec_lines(step, left):
    """-> the question a removed or rewritten spec line parks the run on.
    `left` is [(path, line number, the line as the run found it, what is
    there now or None)]."""
    one = len(left) == 1
    out = ["NEEDS: " + step + " removed or rewrote "
           + ("a line" if one else str(len(left)) + " lines")
           + " of the spec the run started with. may "
           + ("it" if one else "they") + " change?", "CITES:"]
    for rel, n, was, now in left:
        out.append("- " + rel + ":" + str(n) + ' - was "' + flat(was) + '", '
                   + ('now "' + flat(now) + '"' if now is not None
                      else "now removed"))
    out.extend(["OPTIONS:",
                "- override: <why the change holds>. the lines above may"
                " change as shown, and nothing else",
                "- anything else is told to " + step + ", which runs again:"
                " to keep the spec as it was, say put it back"])
    return "\n".join(out)


def answer_of(argv):
    """-> (the answer or None, what is wrong with how it was given or "")."""
    if "--answer" in argv and "--answer-file" in argv:
        return None, "--answer or --answer-file, not both"
    if "--answer" in argv:
        i = argv.index("--answer")
        text = argv[i + 1] if len(argv) > i + 1 else ""
    elif "--answer-file" in argv:
        i = argv.index("--answer-file")
        if len(argv) <= i + 1:
            return None, "--answer-file needs a file"
        try:
            text = Path(argv[i + 1]).read_text(encoding="utf-8")
        except OSError as e:
            return None, "--answer-file " + argv[i + 1] + ": " + str(e)
    else:
        return None, ""
    if not text.strip():
        return None, "an empty answer rules nothing"
    return text.strip(), ""


def who():
    """-> who gave the answer, as far as the machine knows."""
    try:
        return getpass.getuser()
    except Exception:
        return "the operator"


def decided(step, answer):
    """-> the decisions.md heading: one line."""
    first = " ".join(answer.split("\n")[0].split())
    return "ruling for " + step + ": " + first


def scope(question, kind):
    """-> the sentence saying what a conflict's answer lets change, or ""
    for any other answer."""
    if kind == OVERRIDE and authorised(question):
        return ("this authorises changing " + ", ".join(authorised(question))
                + ", and nothing else.")
    if kind == REQUEST:
        return ("the spec holds. the request is amended with these words, and"
                " the run starts again from its first step that reads it.")
    return ""


def why(step, run_id, question, answer, by, kind=None):
    said = scope(question, kind)
    return ("asked by " + step + " in " + run_id + ":\n\n" + question
            + ANSWERED + answer + ("\n\n" + said if said else "")
            + ANSWERED_BY + by + ANSWERED_END)


def told(question, answer, kind=None):
    """-> the end of the step's prompt on the run that carries on: last, so
    the answer is the final thing the step reads."""
    said = scope(question, kind)
    return ("\n\nRULING. when this step last ran it asked:\n\n" + question
            + "\n\nthe answer, which decides it:\n\n" + answer
            + ("\n\n" + said if said else "") + "\n")
