"""a wrong implementation the tests would let pass, and the case that fails it.

green tests show the code does what they check, not that a wrong version of
it would fail them. so a reviewer step with `on_missed: <role>` answers,
under its verdict, the likeliest wrong implementation the tests as they are
let through, and the case that would fail it:

    WOULD PASS: <the wrong implementation, in one line>
    CATCH: <the case that fails it>

or `WOULD PASS: none`. a line under a verdict that lets the work through goes
to the nearest step before the reviewer with that role, the one that wrote
the tests, at the end of its prompt, and its red-test gate shows the new case
red before the code it tests, as on its first go. the steps after it go again
in the flow's order, so the code is held to the new case too, unless the
suite gates of the step that wrote the code pass with the case in: then the
code already holds to it, and the run goes on from the step after the
reviewer, which has read this code already. a go that adds no test id and
changes the code of none it had written added no case: the test writer goes once more for it, and after a second
such go the record says `no case added` and the steps after it go again,
the code never let through on a case that is not there. the reviewer's line
reads `routed`, never a redo, and the test writer's line keeps `case`: the
reviewer caught something only when the case failed on the code. once a run: a
reviewer that names another one the next time is read and not sent. a redo
is the reviewer's verdict on the code and goes where `on_redo` says.
"""
from . import verbs

KEY = "WOULD PASS"
CATCH = "CATCH"
NONE = ("none", "nothing", "n/a", "-")


def read(output):
    """-> (the wrong implementation, the case) of the first `WOULD PASS:`
    line, the case "" when no `CATCH:` line follows it, or None for no line
    or `none`."""
    wrong = None
    catch = ""
    for _, line in verbs.visible(output):
        head = verbs.key_of(line)
        if head is None:
            continue
        name, rest = head[0], head[1]
        if name == KEY and wrong is None:
            wrong = rest
        elif name == CATCH and wrong is not None and not catch:
            catch = rest
        elif name == KEY:
            break
    if wrong is None or wrong.strip().rstrip(".").lower() in NONE + ("",):
        return None
    return wrong, catch


def told(step, wrong, catch):
    """-> the end of the test writer's prompt: what the reviewer named, last,
    so it is the final thing the step reads."""
    return ("\n\n" + step + " read the tests as they are and names one wrong"
            " implementation they would let pass, so this step runs again."
            " add the one case that fails it, beside the tests you wrote, and"
            " change none of them; it has to fail on the code as the run found"
            " it, and it is run to show that. what " + step + " said:\n\n"
            + KEY + ": " + wrong + "\n" + (CATCH + ": " + catch + "\n"
                                           if catch else ""))


def ids(start):
    """-> {test id: its code} for the tests the run has added or changed so
    far, a whole file's id keyed to the file's hash; None when the run took
    no snapshot to read them from."""
    import hashlib

    from agentweft.guardrails.snapshot import test_ids

    if start is None or not getattr(start, "hashed", None):
        return None
    changes = start.test_changes()
    codes = {}
    for rel, now in changes:
        name = start.from_place(rel)
        codes[name] = hashlib.sha256(now).hexdigest()
        if rel.endswith(".py"):
            codes.update(test_ids(now, name) or {})
    return dict((i, codes.get(i, codes.get(i.split("::")[0])))
                for i in start.new_test_ids(changes))


def added(before, start):
    """-> the test ids that are new or whose code changed since `before`
    was read, None when either side could not be read: a case put inside a
    test the writer wrote on its first go is a case too."""
    now = ids(start)
    if before is None or now is None:
        return None
    return sorted(i for i, code in now.items() if before.get(i) != code)


def none_added(step, wrong, catch):
    """-> the end of the test writer's prompt when its go added no test: it
    goes once more for the case."""
    return ("\n\n" + step + " named one wrong implementation the tests would"
            " let pass, and your last go added no case for it: no test id is"
            " new since then. add the one case that fails it as a new test,"
            " beside the tests you wrote, and change none of them. what "
            + step + " said:\n\n" + KEY + ": " + wrong + "\n"
            + (CATCH + ": " + catch + "\n" if catch else ""))


def no_case(writer, step, coder, new):
    """-> the line the record keeps when the test writer added no case for
    what `step` named: `coder` goes again in the flow's order."""
    return ("no case added: " + writer + " added no test for what " + step
            + " named" + (" (no snapshot to read its tests from)"
                          if new is None else "")
            + ", so " + coder + " goes again in the flow's order")


def unheld(step, wrong):
    """-> the end of the next prompt of the step that wrote the code when
    no case was added for what the reviewer named."""
    return ("\n\n" + step + " named a wrong implementation the tests would let"
            " pass: " + wrong + ". no case was added for it, so check the code"
            " is not that one; change the code only where it is.\n")


def green(results):
    """whether the suite gates of the step that wrote the code, run once the
    case is in, pass: one at least, none skipped, none that could not run."""
    return bool(results) and all(
        r.ok and not getattr(r, "skipped", False)
        and not getattr(r, "host", "") for r in results)


def held(case_for, results, alone=None):
    """-> what the test writer's line keeps of the case the reviewer named:
    the reviewer's seq and step, and `red`: true when a suite gate of the
    step that wrote the code failed with the case in and the case failed
    run on its own (`alone`), false when the suite passed or the case did
    not fail, None when the suite failed and the case could not be run on
    its own. only a red case is a wrong implementation the reviewer
    caught."""
    failed = any(not r.ok and not getattr(r, "skipped", False)
                 and not getattr(r, "host", "") for r in results or ())
    red = alone if failed else False
    return {"seq": case_for.get("seq"), "step": case_for["named"], "red": red}


def alone(run, new, timeout=120):
    """-> whether a test in `new`, the ids the test writer added, fails when
    they run on their own with the flow's pytest: True when one FAILED,
    False when none did (a file that does not collect is an error, not the
    case failing), None when they are not python test ids or could not
    run."""
    from agentweft.guardrails import redorder, starttests

    if not new or not all(".py::" in i for i in new):
        return None
    fm = getattr(run, "fm", None)
    cmd = redorder.test_command(fm) if fm is not None else None
    found, _ = starttests.run_tests(starttests.base_of(cmd), list(new),
                                    run.workdir, timeout)
    if found is None:
        return None
    return any(found.get(i, ("",))[0] == "FAILED" for i in new)


def passes_already(coder, results):
    """-> the line the record keeps when the case passes on the code as it
    is, so `coder` does not go again."""
    return ("the case passes on the code as it is, so " + coder + " does not"
            " go again: " + "; ".join(repr(r) for r in results))


def then(writer, step, wrong):
    """-> the end of the next prompt of the step that wrote the code."""
    return ("\n\n" + writer + " added a case after " + step + " named a wrong"
            " implementation the tests would have let pass: " + wrong + ". the"
            " code may pass it already; change the code only where the new case"
            " fails.\n")
