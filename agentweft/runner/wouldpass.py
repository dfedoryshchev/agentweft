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
in the flow's order, so the code is held to the new case too. once a run: a
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


def then(writer, step, wrong):
    """-> the end of the next prompt of the step that wrote the code."""
    return ("\n\n" + writer + " added a case after " + step + " named a wrong"
            " implementation the tests would have let pass: " + wrong + ". the"
            " code may pass it already; change the code only where the new case"
            " fails.\n")
