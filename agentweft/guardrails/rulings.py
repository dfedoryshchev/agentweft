"""the rulings the runner wrote, kept where no step can reach them.

decisions.md lives in the place the run works in, and several checks let a
change stand when an entry there names the test or quotes the spec line: the
spec-files rule, the start-tests replay, the reviewer's spec diff and an
`override:` answer to a conflict. a step with file tools can write that file
too, so a step could write the ruling that lets its own change through.

so the runner keeps its own account: a sha256 of every entry that was there
when the run started, and of every entry it writes itself, from `--answer`,
the lead's decision or a raised cap. it is saved as runs/<id>/rulings.json,
outside the place. every check that reads a ruling reads only entries whose
hash is in that account. after each step the file is compared with what the
runner last wrote; a step that added, edited or removed an entry fails like a
gate, and the file is put back as the runner left it.

entries already there when the run started count: between runs the file is
the person's to edit, and a ruling written by hand is still theirs. a resume
carries the record of the run it picks up, so an entry that run wrote keeps
who wrote it; with that record gone or unreadable, none counts.

the lead's decisions are rulings for the step that asked, not over the spec:
the checks that let a spec line or a start test change read every entry but
the lead's (`read(but=(LEAD,))`).
"""
import hashlib
import json
import threading
from pathlib import Path

from agentweft.orchestrate import decisions

FILE = "rulings.json"
GATE = "rulings"
LEAD = "lead"


def digest(d):
    """-> the sha256 of one entry as it reads back: stamp, heading, why."""
    text = d.at.strftime(decisions.STAMP) + "\n" + d.decided + "\n" + d.why
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Kept(object):
    """the runner's own record of the rulings in one place."""

    def __init__(self, workdir):
        self.root = Path(workdir)
        self.path = self.root / decisions.FILE
        self.data = self.now()
        self.found = [digest(d) for d in decisions.read(self.root)]
        self.written = []
        self.folder = None
        self.lock = threading.Lock()

    def now(self):
        try:
            return self.path.read_bytes()
        except OSError:
            return None

    def known(self, but=()):
        return set(self.found) | set(w["sha256"] for w in self.written
                                     if w.get("by") not in but)

    def record(self, decided, why, by, at=None):
        """write one entry to decisions.md and to the runner's record."""
        with self.lock:
            path = decisions.record(self.root, decided, why, at)
            d = decisions.read(self.root)[-1]
            self.written.append({"at": d.at.strftime(decisions.STAMP),
                                 "decided": d.decided, "by": by,
                                 "sha256": digest(d)})
            self.data = self.now()
            self.save()
            return path

    def read(self, but=()):
        """-> the entries of decisions.md the runner has on record, oldest
        first, less those written by any of `but`. anything else in the file
        is not a ruling."""
        known = self.known(but)
        return [d for d in decisions.read(self.root) if digest(d) in known]

    def check(self, step, how=""):
        """-> "" when decisions.md is as the runner left it, else why `step`
        fails, with the file put back. `how` says what of the step changed
        it, when that was not its answer."""
        with self.lock:
            now = self.now()
            if now == self.data:
                return ""
            known = self.known()
            there = decisions.read(self.root) if now is not None else []
            seen = set(digest(d) for d in there)
            added = [d.decided for d in there if digest(d) not in known]
            gone = len(self.held() - seen)
            self.put_back()
        said = []
        if added:
            said.append("added or edited " + "; ".join(
                '"' + a + '"' for a in added))
        if gone:
            said.append("removed " + str(gone) + (" entry" if gone == 1
                                                  else " entries"))
        return (decisions.FILE + " was changed by " + step + how
                + "; rulings come"
                " only from --answer or the lead. "
                + (", ".join(said) + ". " if said else "")
                + "it was put back, and the change counts for nothing")

    def held(self):
        """-> the hashes of the entries in the file as the runner left it."""
        if self.data is None:
            return set()
        text = self.data.decode("utf-8", "replace").replace("\r\n", "\n")
        return set(digest(d) for d in decisions.parse(text))

    def put_back(self):
        if self.data is None:
            try:
                self.path.unlink()
            except OSError:
                pass
            return
        self.path.write_bytes(self.data)

    def carry(self, folder):
        """take who wrote each entry from the record of the run this one
        picks up, so an entry a run wrote is not read as one there at the
        start. with no record to read, no entry can be told apart, so none
        found at the start counts as a ruling on this leg."""
        try:
            data = json.loads((Path(folder) / FILE).read_text(
                encoding="utf-8"))
            earlier = [w for w in data.get("written") or []
                       if w.get("sha256") in self.found]
        except (OSError, ValueError, AttributeError, TypeError):
            self.found = []
            self.save()
            return
        taken = set(w["sha256"] for w in earlier)
        self.found = [f for f in self.found if f not in taken]
        self.written = earlier + self.written
        self.save()

    def keep_in(self, folder):
        self.folder = Path(folder)
        self.save()

    def save(self):
        if self.folder is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / FILE).write_text(
            json.dumps({"found": self.found, "written": self.written},
                       indent=2) + "\n", encoding="utf-8")
