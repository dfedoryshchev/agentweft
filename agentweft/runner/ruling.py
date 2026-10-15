"""a step that asks for a ruling, and the answer that carries the run on.

a step that cannot do its work without someone deciding something says so on
a line of its own: `NEEDS: <the question>`, with `CITES:` and `OPTIONS:` under
it if it has them, or a first line of `VERDICT: park`. the run parks before
that step's gates, because a step that stopped to ask has produced nothing to
gate, and it waits for a ruling. `--resume <run id> --answer "<text>"` (or
`--answer-file <path>`) runs that same step again with the answer at the end
of its prompt, and the question, the answer and who gave it go into
decisions.md in the place the run works in. a flow with a `lead:` step asks
that step first, and parks only when it does not decide (`lead`).

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
step. the answer to a conflict says which one holds: `override: <the new
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

from . import verbs
from .config import verdict
from .handoff import without

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


def asked_of(output, workdir):
    """-> (ASKED, the question), (DECLINED, the cited refusal) or None for an
    answer that did neither."""
    v = verbs.parse(output)
    if v.refused and not v.needs:
        cite = cited(v.refused, v.cites, workdir)
        if cite is not None:
            return DECLINED, "REFUSED: " + v.refused
        v.needs = v.refused + " (refused with no line of the spec cited)"
    if v.needs:
        return ASKED, question_of(v)
    if verdict(output) == PARK:
        said = [l.strip() for l in without(output).split("\n")[1:]
                if l.strip()]
        return ASKED, "NEEDS: " + (said[0] if said else
                                   "the step parked and did not say on what")
    return None


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
    is wrong with it) when it is not."""
    said = verbs.parse(output).conflict
    if said is None:
        return None
    m = CONFLICT.match(said.strip())
    if not m:
        return "", ('the CONFLICT line is not <file>:<line> "<the line>",'
                    " with request: <the request's words> on the next line: "
                    + said)
    rel, first = m.group(1), int(m.group(2))
    last = int(m.group(3) or first)
    quote = flat(m.group(4))
    words = flat(m.group(5)) or request_of(output)
    cite = rel + ":" + str(first) + ("-" + str(last) if last != first else "")
    if not quote:
        return "", "the CONFLICT line cites " + cite + " and quotes nothing"
    text = as_found(workdir, rel, start)
    if text is None:
        return "", ("the CONFLICT line cites " + cite + ", and " + rel
                    + " was not there when the run started")
    lines = text.split("\n")
    if not 1 <= first <= last <= len(lines):
        return "", ("the CONFLICT line cites " + cite + ", and " + rel
                    + " had " + str(len(lines)) + " lines when the run"
                    " started")
    if quote not in flat(" ".join(lines[first - 1:last])):
        return "", ('the CONFLICT line quotes "' + quote + '", which is not'
                    " at " + cite + " as the run found it. quote the line"
                    " as it is, or answer without a CONFLICT line")
    return question_of_conflict(cite, quote, words), ""


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


def answered(d):
    """-> the answer in a decisions.md entry written by --answer, "" for an
    entry written any other way."""
    _, sep, rest = d.why.partition("\nanswered:\n")
    return rest.split("\n\nanswered by ")[0].strip() if sep else ""


def own_words(d):
    """-> what a decisions.md entry itself says: its heading and its why, or
    for one written by --answer the answer, without the question it
    answered."""
    return d.decided + "\n" + (answered(d) or d.why)


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
    be red now, or None. it names the test in its own words, or it quotes the
    spec line that decides it as the run found it and the entry (with the
    question it answered) names the test. an answer of `request:` keeps
    what the run started with, so it never covers one."""
    for d in decided:
        if kind_of(answered(d) or d.decided) == REQUEST:
            continue
        own = own_words(d)
        if names_test(own, test):
            return d
        if names_test(d.decided + "\n" + d.why, test) and \
                spec_quoted(own, workdir, start):
            return d
    return None


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
            + "\n\nanswered:\n\n" + answer + ("\n\n" + said if said else "")
            + "\n\nanswered by " + by + ", with --answer")


def told(question, answer, kind=None):
    """-> the end of the step's prompt on the run that carries on: last, so
    the answer is the final thing the step reads."""
    said = scope(question, kind)
    return ("\n\nRULING. when this step last ran it asked:\n\n" + question
            + "\n\nthe answer, which decides it:\n\n" + answer
            + ("\n\n" + said if said else "") + "\n")
