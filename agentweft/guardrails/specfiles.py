"""the spec files a run started with, held to the flow's rule for them.

`spec_files:` in flow.yaml says what a step may do to the spec (`TASK.md`,
`SPEC*.md` and `docs/spec*` from the top of the place, `snapshot.is_spec`):

- `read-only`: nothing. a step that changes a spec file fails like a gate,
  goes back once with the file named, and the run stops if it is still
  changed after that. a fix has no business moving the line it is fixed
  against.
- `additions`: a step may add lines. a line the run started with that is
  removed or rewritten stops the run for a ruling, each line quoted as it
  was and as it is now, unless a ruling in decisions.md quotes that line.

the files are read by content: the start snapshot's hashes say which spec
files changed, and the text they had is read from the start commit (or from
the snapshot, for a file already loose or a place with no commit). a step
that commits its edit is read the same as one that leaves it in the work
tree, and a commit cannot make an edit look like the start.
"""
import difflib

from agentweft.guardrails.gates.base import Result
from agentweft.guardrails.snapshot import _read, changed

NAME = "spec-files"
READ_ONLY = "read-only"
ADDITIONS = "additions"
MODES = (READ_ONLY, ADDITIONS)


def _text(data):
    return "" if data is None else data.decode("utf-8", "replace")


def changes(start):
    """-> [(path from the place, its text at the start, its text now)] for
    each spec file that is not as the run found it. a file that was not
    there, or is gone, has "" for that side."""
    if start is None or not start.hashed:
        return []
    now = start.hashes()[1]
    out = []
    for rel in changed(start.specs, now):
        was = start.before(rel) if rel in start.specs else None
        out.append((start.from_place(rel), _text(was),
                    _text(_read(start.root / rel)) if rel in now else ""))
    return out


def lost(was, now):
    """-> [(its line number at the start, the line, what is there now or
    None when it is gone)] for each line of `was` that `now` removed or
    rewrote. blank lines and trailing spaces do not count."""
    old = [l.rstrip() for l in was.split("\n")]
    new = [l.rstrip() for l in now.split("\n")]
    out = []
    match = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for op, i1, i2, j1, j2 in match.get_opcodes():
        if op not in ("replace", "delete"):
            continue
        took = [l for l in new[j1:j2] if l.strip()] if op == "replace" else []
        for k in range(i1, i2):
            if not old[k].strip():
                continue
            out.append((k + 1, old[k], took.pop(0) if took else None))
    return out


def added(was, now):
    """-> how many lines `now` has that `was` did not, blank ones left out."""
    old = [l.rstrip() for l in was.split("\n")]
    new = [l.rstrip() for l in now.split("\n")]
    match = difflib.SequenceMatcher(None, old, new, autojunk=False)
    count = 0
    for op, i1, i2, j1, j2 in match.get_opcodes():
        if op in ("insert", "replace"):
            taken = len([l for l in old[i1:i2] if l.strip()])
            count += max(0, len([l for l in new[j1:j2] if l.strip()]) - taken)
    return count


def read_only(step, found):
    """-> the failed gate for a step that changed a read-only spec file."""
    return Result(NAME, False, step + " changed " + ", ".join(
        rel for rel, _, _ in found) + ", and this flow keeps the spec files"
        " read-only. put each back as the run found it")


def lines(n):
    return str(n) + " line" + ("" if n == 1 else "s")


def passed(found, ruled):
    """-> the passing line for spec files that only gained lines, or whose
    removed and rewritten lines a ruling covers. `ruled` is [(path, line
    number, the ruling's stamp)]."""
    said = []
    for rel, was, now in found:
        said.append(rel + ": " + lines(added(was, now)) + " added")
    line = "; ".join(said) + ", no line the run started with removed or" \
        " changed"
    if ruled:
        line = "; ".join(said) + ". removed or changed, each covered by a" \
            " ruling: " + ", ".join(rel + ":" + str(n) + " (ruling " + by
                                    + ")" for rel, n, by in ruled)
    return Result(NAME, True, line)


def held(left):
    """-> the line for the record when lines the run started with are gone
    or rewritten and no ruling covers them. `left` is [(path, line number,
    the line, what is there now or None)]."""
    return Result(NAME, False, lines(len(left)) + " of the spec the run"
                  " started with removed or rewritten, and no ruling quotes "
                  + ("it" if len(left) == 1 else "them") + ": " + ", ".join(
                      rel + ":" + str(n) for rel, n, _, _ in left))
