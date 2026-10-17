"""a step that finds a test it was given wrong, and where that goes.

a step that cannot make a test pass because the test contradicts the spec
says so on lines of its own:

    WRONG TEST: <the test, file::name>
    why: <what is wrong with it>
    spec: <file>:<line> "<the line>"

where it goes depends on who wrote the test, read from the run's start
snapshot. a test that was not in the place when the run started is the run's
own, so it goes back to the step that wrote it, with the claim at the end of
that step's prompt, as many times as the flow's `send_backs` allows (once when
it says nothing), and that step's gates have to show it red again. a test the
run started with is somebody else's decision, so it is a ruling: the run parks
the way it does on a NEEDS line, quoting the claim.

the spec line has to be a line that is there: a claim nobody can check is a
question, the way a REFUSED line without a cite is. its quote has to be what
that line says as the run found it: a claim on words the spec does not hold
goes nowhere, and fails the step the way a gate does.
"""
from pathlib import Path

from agentweft.flow.spec import step_id
from agentweft.guardrails.snapshot import test_ids

from . import verbs
from .ruling import cited, misquote

WRONG = "WRONG TEST"
WHY = "WHY"
SPEC = "SPEC"


def read(output):
    """-> (the test, why, the spec line) for the first WRONG TEST line, or
    None. `why` and `spec` are the first of each after it, "" when absent."""
    found = None
    why = spec = ""
    for _, line in verbs.visible(output):
        head = verbs.key_of(line)
        if head is None:
            continue
        name, rest = head[0], head[1]
        if found is None:
            if name == WRONG and rest:
                found = rest.strip("`")
            continue
        if name == WHY and not why:
            why = rest
        elif name == SPEC and not spec:
            spec = rest
        elif name == WRONG:
            break
    if found is None:
        return None
    return found, why, spec


def born(start, test):
    """whether `test` (file or file::name, from the place) was written in this
    run: its file was not there when the run started, or the file was and the
    test in it was not. a start the run cannot read says no, so a test whose
    history is unknown is never rewritten without a person."""
    if start is None or not start.hashed or start.root is None:
        return False
    path, _, name = test.partition("::")
    try:
        rel = (start.place / path).resolve().relative_to(
            Path(start.root).resolve()).as_posix()
    except (ValueError, OSError):
        return False
    if not (Path(start.root) / rel).is_file():
        return False
    if rel not in start.tests:
        return True
    if not name or not start.start:
        return False
    was = start.before(rel)
    if was is None:
        return False
    had = test_ids(was, start.from_place(rel))
    return had is not None and \
        start.from_place(rel) + "::" + name not in had


def author(authors, fm, step, test):
    """-> the step that wrote the file of `test`, or None. a run picked up
    later did not see it written, so then it is the nearest step before
    `step` that writes tests."""
    path = test.partition("::")[0].replace("\\", "/")
    if path in authors:
        return authors[path]
    order = [step_id(s) for s in fm.steps]
    if step not in order:
        return None
    for s in reversed(fm.steps[:order.index(step)]):
        if s.get("writes") == "tests":
            return step_id(s)
    return None


def claimed(test, why, spec):
    out = [WRONG + ": " + test]
    if why:
        out.append("why: " + why)
    if spec:
        out.append("spec: " + spec)
    return "\n".join(out)


def asked(step, test, why, spec, said):
    """-> a ruling's question: the NEEDS line, the spec line under CITES."""
    out = "NEEDS: " + step + " says " + test + " is wrong" \
        + (" (" + why + ")" if why else "") + ", and " + said
    if spec:
        out = out + "\nCITES:\n- " + spec
    return out


def told(step, test, why, spec):
    """-> the end of the writer's prompt: the claim last, so it is the final
    thing the step reads."""
    return ("\n\n" + step + " found a test this step wrote wrong, so this step"
            " runs again. change the test only where the spec line says it is"
            " wrong; it has to fail again on the code as it is, and it is run"
            " to show that. what " + step + " said:\n\n"
            + claimed(test, why, spec) + "\n")


def back_to(writer, test):
    """-> the end of the claimant's next prompt, once the writer has gone."""
    return ("\n\nyou said " + test + " was wrong. it went back to " + writer
            + ", which wrote it, and the test as it is now is what " + writer
            + " handed over above.\n")


def misquoted(output, workdir, start=None):
    """-> what is wrong with the quote on the claim's `spec:` line, or "".
    a claim citing a line that is not there is a question, not this."""
    said = read(output)
    if said is None or not said[2] or cited(said[2], [], workdir) is None:
        return ""
    return misquote(said[2], workdir, start, "the WRONG TEST spec: line")


def judge(output, step, run, route):
    """-> None when `output` claims no wrong test, ("back", writer, test,
    the end of the writer's prompt) to send it to the step that wrote it, or
    ("ask", the question) for a ruling."""
    said = read(output)
    if said is None:
        return None
    test, why, spec = said
    if not spec or cited(spec, [], run.workdir) is None:
        return "ask", asked(step, test, why, spec,
                            "no line of the spec that is there was cited")
    if misquoted(output, run.workdir, getattr(run, "start", None)):
        return None
    if not born(getattr(run, "start", None), test):
        return "ask", asked(step, test, why, spec,
                            "it was in the place when the run started, so"
                            " the run will not rewrite it: which holds, the"
                            " test or the spec line?")
    writer = author(getattr(run, "authors", {}), run.fm, step, test)
    if writer is None:
        return "ask", asked(step, test, why, spec,
                            "no step of this run is known to have written it")
    if not route.wrong_back(test):
        n = route.wrong_tries.get(test, 0)
        return "ask", asked(step, test, why, spec,
                            "it went back to " + writer + " " + str(n)
                            + " time" + ("" if n == 1 else "s")
                            + " already (send_backs: "
                            + str(route.gate_limit) + ")")
    return "back", writer, test, told(step, test, why, spec)
