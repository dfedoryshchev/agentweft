"""the run record is chained, so a line changed after it was written shows.

every `steps.jsonl` line ends on a `chain` field: `prev`, the sha256 of the
line written before it as it stands in the file (null on the first), and
`files`, the sha256 of the run's start snapshot and red proof as they were on
disk when the line was written (null for one the run never wrote). the test
hashes those files hold are then in the chain, so the step that rewrites a
test cannot quietly rewrite the hash it was held to as well.

the run's manifest keeps the count and the head (the hash of the newest
line) each time the handoff is written, and the handoff names the head, so a
dropped or edited last line shows too: nothing comes after it to say so.

`python run.py verify <run id>` reads the chain back and names the first line
that breaks it; `--resume` refuses a run whose chain breaks, unless --force.

the limit: there is no key. a writer who rewrites a line and every hash after
it, the manifest's head and the handoff's line included, is not caught. this
catches an edit, a drop or a reorder, not a determined forger.
"""
import hashlib
import json
from pathlib import Path

from . import manifest

FIELD = "chain"
FILES = ("start-snapshot.json", "red-proof.json")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def files(folder):
    """-> {name: sha256 or None} of the files in FILES, as they are now."""
    out = {}
    for name in FILES:
        p = Path(folder) / name
        out[name] = manifest.of_file(p) if p.is_file() else None
    return out


def raw(folder):
    """-> each line of folder's steps.jsonl as written, without its newline."""
    from .trace import FILE

    path = Path(folder) / FILE
    if not path.exists():
        return []
    text = path.read_bytes().decode("utf-8", "replace")
    return [l[:-1] if l.endswith("\r") else l
            for l in text.split("\n") if l.strip()]


def head(lines):
    """-> {"lines": n, "head": sha256 of the last line or None}."""
    return {"lines": len(lines), "head": digest(lines[-1]) if lines else None}


def said(at, line):
    """-> "line 3 (seq 3, reviewer.md)" for a parsed line."""
    return ("line " + str(at) + " (seq " + str(line.get("seq")) + ", "
            + str(line.get("step")) + ")")


class Read(object):
    """what verify found: `broken` is the first break said in words, None
    when the chain holds; `lines` is how many lines it read; `head` the hash
    of the last one; `unchained` is true for a record written before lines
    were chained, which has nothing to check."""

    __slots__ = ("broken", "lines", "head", "unchained")

    def __init__(self, broken=None, lines=0, head=None, unchained=False):
        self.broken = broken
        self.lines = lines
        self.head = head
        self.unchained = unchained


def parsed(texts):
    """-> ([(text, line)], why) - why is the first line that is not json."""
    out = []
    for i, text in enumerate(texts):
        try:
            line = json.loads(text)
            if not isinstance(line, dict):
                raise ValueError(text)
        except ValueError:
            if i == len(texts) - 1:
                # cut short by the process dying under it, the same line
                # trace.last_seq reads past
                break
            return out, "line " + str(i + 1) + " is not a whole record line"
        out.append((text, line))
    return out, None


def where_broken(pairs, at):
    """-> words for a break between line at-1 and line at (1-based)."""
    text, line = pairs[at - 1]
    before = pairs[at - 2][1]
    wanted = line[FIELD].get("prev")
    hashes = [digest(t) for t, _ in pairs]
    if wanted in hashes[at - 1:]:
        return said(at, line) + " is out of order: it was written after " \
            + said(hashes.index(wanted) + 1, pairs[hashes.index(wanted)][1])
    seq, last = line.get("seq"), before.get("seq")
    if isinstance(seq, int) and isinstance(last, int) and seq > last + 1:
        gone = "seq " + str(last + 1) if seq == last + 2 else \
            "seq " + str(last + 1) + " to " + str(seq - 1)
        return "the line of " + gone + " was dropped, before " + said(at, line)
    return said(at - 1, before) + " was edited after it was written"


def verify(folder):
    """-> Read of folder's steps.jsonl against its own chain, the files it
    names and the head its manifest kept."""
    texts = raw(folder)
    pairs, bad = parsed(texts)
    if bad:
        return Read(bad, len(pairs))
    if not pairs:
        return Read(lines=0)
    chained = [FIELD in line for _, line in pairs]
    if not any(chained):
        return Read(lines=len(pairs), unchained=True)
    for at, (text, line) in enumerate(pairs, 1):
        if not isinstance(line.get(FIELD), dict):
            return Read(said(at, line) + " has no chain field: it was edited"
                        " or put in by hand", len(pairs))
        prev = line[FIELD].get("prev")
        if at == 1:
            if prev is not None:
                return Read("a line was dropped before " + said(at, line)
                            + ": it is not the first line written",
                            len(pairs))
            continue
        if prev != digest(pairs[at - 2][0]):
            return Read(where_broken(pairs, at), len(pairs))
    lines = [t for t, _ in pairs]
    record = manifest.load(folder)
    kept = (record.data.get(FIELD) or {}) if record else {}
    n = kept.get("lines")
    if isinstance(n, int) and n > 0:
        if len(lines) < n:
            return Read(str(n - len(lines)) + " line(s) dropped from the end:"
                        " the record held " + str(n) + " when its handoff was"
                        " written, " + str(len(lines)) + " are left",
                        len(lines))
        if digest(lines[n - 1]) != kept.get("head"):
            return Read(said(n, pairs[n - 1][1]) + " was edited after it was"
                        " written", len(lines))
    last = pairs[-1][1][FIELD].get("files") or {}
    now = files(folder)
    for name in FILES:
        if last.get(name) != now[name]:
            return Read(name + (" was changed" if now[name] else " is gone")
                        + " after " + said(len(pairs), pairs[-1][1])
                        + " was written", len(lines))
    return Read(lines=len(lines), head=digest(lines[-1]))
