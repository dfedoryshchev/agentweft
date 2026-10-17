"""the tests a run that stopped short leaves red in the tree.

a stop can be the right answer and still leave a test the run wrote failing:
the step that would have made it pass stopped on a conflict, a ruling, the
budget. git says a file changed and nothing more. so on every stop the tests
the run added or changed since it started (`snapshot.new_test_ids`) are run
once each, in a fresh python and with no model asked, and each one that is not
green is named.

nothing is put back unless the run asks for it: `on_stop: revert-tests` in
the flow, or `--on-stop revert-tests` for one run, writes every test file the
run changed back to its bytes at the start and deletes the ones it added. the
tests are run first, so what was red is still said.
"""
from agentweft.flow.spec import ON_STOP as CHOICES
from agentweft.guardrails import redorder, snapshot
from agentweft.guardrails.gates.redfirst_gate import RedFirstGate

KEEP, REVERT = CHOICES
KEY = "on_stop"
FLAG = "--on-stop"
RAN = "the tests the stop ran"


def given(argv):
    """-> the value after FLAG on the command line, "" when it has none,
    None when it was not given."""
    if FLAG not in argv:
        return None
    i = argv.index(FLAG)
    said = argv[i + 1].strip() if len(argv) > i + 1 else ""
    return "" if said.startswith("-") else said


def chosen(fm, argv):
    """-> what a stop does with the tests: the run's FLAG over the flow's
    KEY, KEEP when neither says."""
    return given(argv) or fm.get(KEY) or KEEP


def check(start, fm, choice=KEEP, timeout=120):
    """-> what the stop leaves: {"ids": the tests the run added or changed,
    "red": [(id, what it did)] for each not green, "command": whether there
    was one to run them with, "reverted": the files put back, "kept": the
    files that could not be}. None when there is no start to compare with
    or the run changed no test file."""
    if start is None or not start.hashed:
        return None
    changes = start.test_changes()
    if not changes:
        return None
    ids = new_ids(start, changes)
    cmd = redorder.test_command(fm)
    red = []
    if cmd:
        runner = RedFirstGate(command=cmd, timeout=timeout)
        for i in ids:
            did, kind = runner.one(cmd, i, start.place)
            if did != "green":
                red.append((i, did + (" (" + kind + ")" if kind else "")))
    out = {"ids": ids, "red": red, "command": bool(cmd), "reverted": [],
           "kept": []}
    if choice == REVERT:
        out["reverted"], out["kept"] = revert(start, changes)
    return out


def new_ids(start, changes):
    """-> the ids of the tests the run added or changed. with no commit to
    read a file's start from, every test in a changed file counts."""
    if start.start:
        return start.new_test_ids(changes)
    out = []
    for rel, now in changes:
        name = start.from_place(rel)
        found = snapshot.test_ids(now, name) if rel.endswith(".py") else None
        if found:
            out.extend(found)
        elif snapshot.TEST_MODULE.search(rel.rsplit("/", 1)[-1]) or \
                snapshot.WHOLE_FILE.search(rel.rsplit("/", 1)[-1]):
            out.append(name)
    return out


def revert(start, changes):
    """write each changed test file back to its bytes at the start, delete
    each one the run added. -> (paths put back, paths whose start bytes are
    not known), as paths from the place."""
    done, kept = [], []
    for rel, _ in changes:
        was = at_start(start, rel)
        if was is False:
            kept.append(start.from_place(rel))
            continue
        target = start.root / rel
        if was is None:
            target.unlink()
        else:
            target.write_bytes(was)
        done.append(start.from_place(rel))
    return done, kept


def at_start(start, rel):
    """-> the bytes `rel` had at the start, None when it was not there, False
    when they cannot be known: outside git, or no copy whose hash is the one
    the start recorded."""
    if rel in start.loose:
        return start.loose[rel]
    if not start.start:
        return False
    if rel not in start.tests:
        return None
    # the blob is what was committed; the file on disk is it after the
    # checkout's line-ending and other filters, which is what the hash is of
    was = snapshot._git(start.root, "cat-file", "--filters",
                        start.start + ":" + rel, text=False)
    if was is None or snapshot._sha(was) != start.tests[rel]:
        return False
    return was


def count(left):
    """-> the words for the changed line, "" when no test was left red."""
    if not left or not left["red"]:
        return ""
    n = len(left["red"])
    return (str(n) + " test" + (" the run added or changed is red" if n == 1
                                else "s the run added or changed are red"))


def lines(left):
    """-> the lines the "needs you" section gets, [] when there is nothing
    to say: no test changed, or every new one is green and nothing was put
    back."""
    if not left:
        return []
    out = []
    if left["red"]:
        out.append("left red when the run stopped (run once after the stop):")
        out.extend("- " + i + ": " + did for i, did in left["red"])
    elif not left["command"] and left["ids"]:
        out.append("the run added or changed " + str(len(left["ids"]))
                   + " test" + ("" if len(left["ids"]) == 1 else "s")
                   + " and the flow names no command that runs one, so"
                   " whether they pass is not known: "
                   + ", ".join(left["ids"]))
    if left["reverted"] or left["kept"]:
        if left["reverted"]:
            out.append(KEY + ": " + REVERT + " put the test files back to"
                       " their bytes at the start: "
                       + "; ".join(left["reverted"]))
        if left["kept"]:
            out.append("not put back, their bytes at the start are not known:"
                       " " + "; ".join(left["kept"]))
    elif left["red"]:
        out.append("nothing was reverted; " + FLAG + " " + REVERT
                   + " puts the test files back to their bytes at the start.")
    if left.get("forged"):
        out.append(left["forged"] + ".")
    return out
