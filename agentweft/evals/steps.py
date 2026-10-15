"""the steps a run took, read off its steps.jsonl, and a case's claim about them.

a pass is one line of the record said as `<step> <outcome>`, then `-> <step>`
when it sent the work on, then each gate as `PASS <gate>` or `FAIL <gate>`:

    planner.md ok -> worker.md
    reviewer.md gate failed  PASS length  FAIL regex

the golden runs are held to the same lines, numbered. a case names the passes
it expects, and an item may stop at any word: `reviewer.md` is any pass at the
reviewer, `reviewer.md ok` one that passed.

the four modes are the trajectory match modes of agentevals:

- strict: these passes, in this order, and no others
- unordered: these passes and no others, in any order
- superset: every one of these ran, and others may have too. "the gate ran"
- subset: nothing ran that is not one of these. "verify never ran"

all four count: two `worker.md` items want two passes at the worker.
"""
import json

from agentweft.runner import trace

MODES = ("strict", "unordered", "subset", "superset")


def read(folder):
    """-> the lines of folder's steps.jsonl, in the order they were written."""
    path = folder / trace.FILE
    if not path.exists():
        return []
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return [json.loads(l) for l in text.split("\n") if l.strip()]


def said(line):
    """-> one line of the record as a pass, unnumbered."""
    return (line["step"] + " " + line["outcome"]
            + (" -> " + line["to"] if line["to"] else "")
            + "".join(("  PASS " if g["ok"] else "  FAIL ") + g["gate"]
                      for g in line["gates"]))


def fits(item, done):
    return done == item or done.startswith(item + " ")


def pair(want, got):
    """-> (the items nothing ran as, the passes no item named).

    the item that says the most goes first: anything it fits, a shorter item
    it starts with fits too, so this order never leaves one unmatched that
    another order would have matched.
    """
    free = list(range(len(got)))
    missing = []
    for n in sorted(range(len(want)), key=lambda n: -len(want[n])):
        hit = [i for i in free if fits(want[n], got[i])]
        if hit:
            free.remove(hit[0])
        else:
            missing.append(n)
    return [want[n] for n in sorted(missing)], [got[i] for i in free]


def told(missing, extra):
    out = []
    if missing:
        out.append("missing " + ", ".join(missing))
    if extra:
        out.append("ran outside the reference: " + ", ".join(extra))
    return "; ".join(out)


def match(mode, want, got):
    """-> "" when the passes in got hold to want under mode, else why not."""
    if mode not in MODES:
        return ("no match mode " + str(mode) + ". there is "
                + ", ".join(MODES))
    missing, extra = pair(want, got)
    if mode == "superset":
        return told(missing, [])
    if mode == "subset":
        return told([], extra)
    if mode == "unordered":
        return told(missing, extra)
    if len(want) != len(got):
        return ("took " + str(len(got)) + " steps, want " + str(len(want))
                + ": " + told(missing, extra))
    for n, (item, done) in enumerate(zip(want, got)):
        if not fits(item, done):
            return "step " + str(n + 1) + " is " + done + ", want " + item
    return ""


def ended(record, stopped):
    """-> the run's outcome word, the one its handoff and manifest carry:
    what the cause on the step that stopped it maps to, else `done`. a run
    stopped with no step to blame, a recording that does not match, is
    `stopped` and nothing more."""
    from agentweft.runner import stops

    for line in reversed(record):
        if line.get("cause"):
            return stops.outcome(line["cause"])
    return "stopped" if stopped else stops.DONE


def rows(expect, record, calls):
    """-> the score rows for what a case expects of the run's steps and its
    number of calls, none when it expects neither."""
    out = []
    claim = expect.get("steps")
    if claim:
        mode = claim.get("match", "strict")
        why = match(mode, [str(i) for i in claim.get("path") or []],
                    [said(l) for l in record])
        out.append({"invariant": "the steps it took (" + str(mode) + ")",
                    "ok": not why, "detail": why or "matched"})
    if expect.get("calls") is not None:
        want = int(expect["calls"])
        out.append({"invariant": "it made " + str(want) + " calls",
                    "ok": calls == want, "detail": "it made " + str(calls)})
    return out
