"""a step that asks for a ruling, and the answer that carries the run on.

a step that cannot do its work without someone deciding something says so on
a line of its own: `NEEDS: <the question>`, with `CITES:` and `OPTIONS:` under
it if it has them, or a first line of `VERDICT: park`. the run parks before
that step's gates, because a step that stopped to ask has produced nothing to
gate, and it waits for a ruling. `--resume <run id> --answer "<text>"` (or
`--answer-file <path>`) runs that same step again with the answer at the end
of its prompt, and the question, the answer and who gave it go into
decisions.md in the place the run works in.

`REFUSED: <file>:<line> "<the line>"` is a step declining the work because
the spec says otherwise. with a cite of a line that is there, the run ends on
it as a finished run: the refusal is the answer. without one it is read as a
question, because a refusal nobody can check is somebody's opinion.

the lines are read by `verbs`, so one inside a code fence or a `>` quote is
not a question: a test that asserts on the string "NEEDS:" asks nothing.
"""
import getpass
import re
from pathlib import Path

from . import verbs
from .config import verdict
from .handoff import without

PARK = "park"
ASKED = "ruling"
DECLINED = "declined"

CITE = re.compile(r"""^\s*[`'"]?([^\s:`'"]+):(\d+)\b""")


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


def why(step, run_id, question, answer, by):
    return ("asked by " + step + " in " + run_id + ":\n\n" + question
            + "\n\nanswered:\n\n" + answer + "\n\nanswered by " + by
            + ", with --answer")


def told(question, answer):
    """-> the end of the step's prompt on the run that carries on: last, so
    the answer is the final thing the step reads."""
    return ("\n\nRULING. when this step last ran it asked:\n\n" + question
            + "\n\nthe answer, which decides it:\n\n" + answer + "\n")
