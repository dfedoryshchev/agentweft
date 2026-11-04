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
the way it does on a NEEDS line, quoting the claim. an answer may hold
several claims, each opened by its own WRONG TEST line: the tests one step
wrote go back to it together, in one round.

the spec line has to be a line that is there: a claim nobody can check is a
question, the way a REFUSED line without a cite is. its quote has to be what
that line says as the run found it, or start there and run on into the lines
of its paragraph, and then the claim cites them all: a claim on words the
spec does not hold goes nowhere, and fails the step the way a gate does. a
line the run left as it was may be cited at its number now, where lines the
run added moved it (`ruling.moved_to`).

under an override the run holds, a test the run started with that pins a line
the override lets change is wrong with that line: a claim on it, quoting the
line as the run found it or as the run's own ruled edit left it
(`ruling.ruled_quote`), is no question when the step changed the test, and
lets the change stand at the test-edits check (`ruled_claim`).
"""
from pathlib import Path

from agentweft.flow.spec import step_id
from agentweft.guardrails import testedits
from agentweft.guardrails.snapshot import test_ids

from . import verbs
from .ruling import cited, misquote, ruled_quote, spanned

WRONG = "WRONG TEST"
WHY = "WHY"
SPEC = "SPEC"


def claims(output):
    """-> every (the test, why, the spec line) a WRONG TEST line opens, in
    the order given, one per test. `why` and `spec` are the first of each
    after its WRONG TEST line and before the next, "" when absent."""
    out, seen = [], set()
    now = None
    for _, line in verbs.visible(output):
        head = verbs.key_of(line)
        if head is None:
            continue
        name, rest = head[0], head[1]
        if name == WRONG:
            now = None
            test = rest.strip("`")
            if test and test not in seen:
                seen.add(test)
                now = [test, "", ""]
                out.append(now)
        elif now is None:
            continue
        elif name == WHY and not now[1]:
            now[1] = rest
        elif name == SPEC and not now[2]:
            now[2] = rest
    return [tuple(c) for c in out]


def read(output):
    """-> the first claim of `claims`, or None."""
    said = claims(output)
    return said[0] if said else None


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


def told(step, said):
    """-> the end of the writer's prompt: the claims last, so they are the
    final thing the step reads. `said` is the (test, why, spec) claims."""
    if len(said) == 1:
        return ("\n\n" + step + " found a test this step wrote wrong, so this"
                " step runs again. change the test only where the spec line"
                " says it is wrong; it has to fail again on the code as it is,"
                " and it is run to show that. what " + step + " said:\n\n"
                + claimed(*said[0]) + "\n")
    return ("\n\n" + step + " found " + str(len(said)) + " tests this step"
            " wrote wrong, so this step runs again. change each test only"
            " where its spec line says it is wrong; each has to fail again on"
            " the code as it is, and they are run to show that. what " + step
            + " said:\n\n" + "\n\n".join(claimed(*c) for c in said) + "\n")


def back_to(writer, tests):
    """-> the end of the claimant's next prompt, once the writer has gone."""
    if len(tests) == 1:
        return ("\n\nyou said " + tests[0] + " was wrong. it went back to "
                + writer + ", which wrote it, and the test as it is now is"
                " what " + writer + " handed over above.\n")
    return ("\n\nyou said " + ", ".join(tests) + " were wrong. they went back"
            " to " + writer + ", which wrote them, and the tests as they are"
            " now are what " + writer + " handed over above.\n")


def misquoted(output, workdir, start=None, ruled=None):
    """-> what is wrong with the quote on each claim's `spec:` line, or "".
    a claim citing a line that is not there is a question, not this, and
    with `ruled` a quote of lines a ruling covers (`ruled_quote`) is right
    as the ruled edit left them too."""
    wrong = []
    for _, _, spec in claims(output):
        if not spec or cited(spec, [], workdir) is None:
            continue
        said = misquote(spec, workdir, start, "the WRONG TEST spec: line")
        if said and ruled_quote(spec, workdir, start, ruled) is not None:
            continue
        if said and said not in wrong:
            wrong.append(said)
    return "; ".join(wrong)


def same_test(said, test):
    """whether a claim's test, as a step wrote it, is `test`, a test id or a
    file the test-edits check reads whole: the claim names a test in it."""
    said = said.replace("\\", "/")
    said = said[2:] if said.startswith("./") else said
    if "::" not in test:
        return said.partition("::")[0] == test
    path, _, name = said.partition("::")
    return path + "::" + name.split("[")[0] == test


def ruled_claim(outputs, test, workdir, start=None, ruled=None):
    """-> the ruling that lets `test`, one the run started with, change
    because an answer of this run names it on a WRONG TEST line whose spec:
    line quotes spec lines that ruling covers (`ruled_quote`), else None."""
    for output in outputs:
        for said, _, spec in claims(output or ""):
            if spec and same_test(said, test):
                d = ruled_quote(spec, workdir, start, ruled)
                if d is not None:
                    return d
    return None


def judge(output, step, run, route):
    """-> None when `output` claims no wrong test, ("back", writer, the
    tests, the end of the writer's prompt) to send them to the step that
    wrote them, or ("ask", the question) for a ruling.

    every claim of one answer is judged together: one claim that has to be
    a ruling parks the answer, so nothing goes back that a person is about
    to rule on. the claims whose writer is the first claim's go back in one
    round; a claim on another writer's test is made again on the next go.
    a claim on a test the run started with, which the step changed, whose
    spec: line quotes lines a ruling of this run covers (`ruled_quote`) is
    no question: it is already ruled, and the test-edits check holds it."""
    said = claims(output)
    if not said:
        return None
    for test, why, spec in said:
        if not spec or cited(spec, [], run.workdir) is None:
            return "ask", asked(step, test, why, spec,
                                "no line of the spec that is there was cited")
    start = getattr(run, "start", None)
    ruled = getattr(run, "spec_line_covered", None)
    if misquoted(output, run.workdir, start, ruled):
        return None
    changed = [t for e in testedits.changes(start) for t, how in e.items
               if testedits.claimable(t, how)] if ruled is not None else []
    said = [(test, why, spec) for test, why, spec in said
            if born(start, test)
            or not any(same_test(test, t) for t in changed)
            or ruled_quote(spec, run.workdir, start, ruled) is None]
    if not said:
        return None
    said = [(test, why, spanned(spec, run.workdir, start))
            for test, why, spec in said]
    for test, why, spec in said:
        if not born(getattr(run, "start", None), test):
            return "ask", asked(step, test, why, spec,
                                "it was in the place when the run started, so"
                                " the run will not rewrite it: which holds,"
                                " the test or the spec line?")
    writers = []
    for test, why, spec in said:
        writer = author(getattr(run, "authors", {}), run.fm, step, test)
        if writer is None:
            return "ask", asked(step, test, why, spec,
                                "no step of this run is known to have"
                                " written it")
        writers.append(writer)
    batch = [c for c, w in zip(said, writers) if w == writers[0]]
    for test, why, spec in batch:
        n = route.wrong_tries.get(test, 0)
        if n >= route.gate_limit:
            return "ask", asked(step, test, why, spec,
                                "it went back to " + writers[0] + " " + str(n)
                                + " time" + ("" if n == 1 else "s")
                                + " already (send_backs: "
                                + str(route.gate_limit) + ")")
    for test, _, _ in batch:
        route.wrong_back(test)
    return "back", writers[0], [c[0] for c in batch], told(step, batch)
