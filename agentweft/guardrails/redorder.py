"""no product code is written before a red test exists.

a step says what it writes: `writes: tests`, `writes: product` or `writes:
none`. the run holds a red proof once a red-test gate has seen a test fail by
running it, or a red-first gate has shown a new test red without the fix, on
a test file whose content is not what it was when the run started (the start
snapshot). the proof keeps the new test ids there were when it was shown, so
a test added after that is known as one (the red-first gate replays it). a
`writes: product` step does not start until there is one, and a
`writes: tests` step that changes a product file fails. it is fail-closed:
no start snapshot, no proof record or a gate that ran nothing is no proof.

two ways round it, both said in the record. `--skip tests "<reason>"`
(`--skip-tests "<reason>"` for short, `guardrails/skips.py`) is a person
deciding the run has no tests, and then none of the test checks apply.
`--continue <run>` carries the proof an earlier run of the same place holds,
and `--continue <commit>` carries tests the start commit added since that
commit plus the test files changed but not committed when the run started
(`--continue HEAD` for those alone), once each of them is seen failing in the
place as it starts. neither is assumed: a carried test whose content moved
since, or one that does not fail, carries nothing. a resumed run re-reads the
proved test files too, and a moved one drops the proof.

the proof is kept as runs/<id>/red-proof.json beside the start snapshot, so
a run picked up later has both.
"""
import json
import os
import posixpath
from pathlib import Path

from agentweft.guardrails.snapshot import _git, _sha, changed, is_test

from .gates.redfirst_gate import RedFirstGate
from .gates.redtest_gate import named_test

FILE = "red-proof.json"
TEST_GATES = ("red-test", "red-first")


def ordered(fm):
    """whether any step of the flow says it writes tests or product code."""
    return any(s.get("writes") in ("tests", "product") for s in fm.steps)


def test_command(fm):
    """-> the first command of a red-test or red-first gate in the flow that
    runs one test, or None."""
    for s in fm.steps:
        for g in s.get("gates") or []:
            cmd = g.get("command")
            if g.get("gate") in TEST_GATES and isinstance(cmd, (list, tuple)) \
                    and "{test}" in cmd:
                return list(cmd)
    return None


def norm(path):
    """a test path as one key, however a step wrote it: `/` for `\\`, no
    `./`, and case-folded where the file system ignores case."""
    out = posixpath.normpath((path or "").replace("\\", "/"))
    return out.casefold() if os.name == "nt" else out


class Order(object):
    """what the run holds: the start snapshot, a red proof or a skip."""

    def __init__(self, start, skip="", proof=None):
        self.start = start
        self.skip = skip
        self.proof = proof
        self.lost = ""
        self.watching = {}

    def before(self, step, writes):
        """why `step` may not start, or "" when it may."""
        if self.skip or writes != "product":
            return ""
        if self.start is None or not self.start.hashed:
            return (step + " writes product code, and the run has no start"
                    " snapshot to tell a test it wrote from one that was"
                    " there: no start snapshot, so no red test can be shown")
        if self.lost:
            return step + " writes product code, and " + self.lost
        if not self.proof:
            return (step + " writes product code, and the run holds no red"
                    " test yet: no red-test gate with red: true and a command"
                    " on a tests step has seen a test it wrote fail."
                    " --skip-tests \"<reason>\" runs without tests,"
                    " --continue <run or commit> carries them")
        return ""

    def watch(self, step, writes):
        """note the product files' hashes before a `writes: tests` step. a
        step sent back keeps the hashes from before its first go, so it is
        held to undoing what it changed then."""
        if self.skip or writes != "tests" or self.start is None \
                or not self.start.hashed:
            return
        if step not in self.watching:
            self.watching[step] = self.start.product_now()

    def after(self, step, writes):
        """why a `writes: tests` step fails for what it changed, or ""."""
        if self.skip or writes != "tests":
            return ""
        if step not in self.watching:
            return (step + " writes tests only, and with no start snapshot"
                    " nothing shows it left product code alone")
        moved = changed(self.watching[step], self.start.product_now())
        if moved:
            return (step + " writes tests only and changed product code: "
                    + ", ".join(moved))
        return ""

    def passed(self, step):
        self.watching.pop(step, None)

    def proven(self, step, results, output):
        """record the run's red proof from what `step`'s gates ran, the first
        time there is one. -> whether one was recorded now."""
        if self.proof or self.skip or self.start is None \
                or not self.start.hashed:
            return False
        moved = dict((norm(self.start.from_place(rel)),
                      (self.start.from_place(rel), _sha(now)))
                     for rel, now in self.start.test_changes())
        for r in results:
            if not r.ok:
                continue
            files = []
            if r.gate == "red-test" and r.detail.startswith("red, exit"):
                files = [named_test(output or "").split("::")[0]]
            elif r.gate == "red-first" and r.tests:
                files = [t["test"].split("::")[0] for t in r.tests
                         if t["before"] == "red"]
            found = [moved[k] for k in sorted(set(norm(f) for f in files))
                     if k in moved]
            if found:
                self.proof = {"how": "gate", "step": step, "gate": r.gate,
                              "tests": dict(found),
                              "ids": self.start.new_test_ids()
                              if self.start.start else None}
                self.lost = ""
                return True
        return False

    def recheck(self):
        """drop a proof whose proved test files are not the content it
        proved, saying why in `lost`. -> the why, "" when it holds."""
        if not self.proof or self.start is None:
            return ""
        moved = []
        for f, sha in sorted((self.proof.get("tests") or {}).items()):
            try:
                now = _sha((self.start.place / f).read_bytes())
            except OSError:
                now = None
            if now != sha:
                moved.append(f)
        if moved:
            self.lost = ("the tests its red proof was shown on are not as"
                         " they were: " + ", ".join(moved))
            self.proof = None
        return self.lost

    def first_ids(self):
        """-> the new test ids there were when the red was first shown by a
        gate in this run, or None when the proof was carried, came from no
        gate or is older than this record."""
        if not self.proof or self.proof.get("how") != "gate":
            return None
        ids = self.proof.get("ids")
        return list(ids) if isinstance(ids, list) else None

    def carried(self):
        """-> the carried test files as {path from the place: sha256}, or
        {} when the proof was not carried."""
        if not self.proof or self.proof.get("how") != "carried":
            return {}
        return dict(self.proof.get("tests") or {})

    def said(self):
        """-> the handoff's line on the order, "" when nothing is held."""
        if self.skip:
            return ("tests skipped: " + self.skip + " (--skip tests), so no"
                    " test check applied")
        if not self.proof:
            return ""
        files = ", ".join(sorted(self.proof.get("tests") or {}))
        if self.proof.get("how") == "carried":
            return "tests carried from " + self.proof["from"] + " (" + files \
                + ")"
        return ("red before any product code: " + self.proof["gate"] + " on "
                + self.proof["step"] + " (" + files + ")")

    def save(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / FILE).write_text(
            json.dumps({"skip": self.skip, "proof": self.proof}, indent=1,
                       sort_keys=True), encoding="utf-8")


def load(folder):
    """-> (skip, proof) a run saved in `folder`; ("", None) for none."""
    try:
        data = json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
        return data.get("skip") or "", data.get("proof") or None
    except (OSError, ValueError, AttributeError):
        return "", None


def carry_run(folder, run_id, start):
    """-> (proof, "") carried from an earlier run's record, or (None, why)."""
    _, proof = load(folder)
    if not proof:
        return None, run_id + " holds no red proof to carry"
    if start is None or not start.hashed:
        return None, "the run has no start snapshot to check " + run_id \
            + "'s tests against"
    now = dict((start.from_place(rel), sha)
               for rel, sha in start.tests.items())
    moved = [f for f, sha in sorted(proof["tests"].items())
             if now.get(f) != sha]
    if moved:
        return None, ("the tests " + run_id + " proved red are not as they"
                      " were: " + ", ".join(moved))
    return {"how": "carried", "from": "run " + run_id,
            "tests": dict(proof["tests"])}, ""


def carry_commit(start, rev, cmd):
    """-> (proof, "") for the tests the start commit added or changed since
    `rev`, and those changed but not committed when the run started, each
    seen failing in the place as it starts, or (None, why). a test file new
    since `rev` that cannot even be collected (an ImportError, exit 2) counts
    as red, with its kind kept in the proof."""
    if start is None or not start.start:
        return None, "the place has no start commit to carry tests from"
    if not cmd:
        return None, ("the flow has no red-test or red-first gate command to"
                      " run the carried tests with")
    if not _git(start.root, "rev-parse", "--verify", "--quiet",
                rev + "^{commit}"):
        return None, rev + " is not a commit or a run of this place"
    diff = _git(start.root, "diff", "--name-only", "-z", rev, start.start,
                "--")
    if diff is None:
        return None, "git could not tell what changed since " + rev
    rels = set(rel for rel in diff.split("\0") if rel)
    rels.update(rel for rel, data in start.loose.items() if data is not None)
    rels = sorted(rel for rel in rels if is_test(rel) and rel in start.tests)
    if not rels:
        return None, ("no test file changed between " + rev + " and the place"
                      " as it starts")
    gate = RedFirstGate(command=cmd)
    carried, kinds = {}, {}
    for rel in rels:
        f = start.from_place(rel)
        said, kind = gate.one(cmd, f, start.place, "")
        new = _git(start.root, "cat-file", "-e", rev + ":" + rel) is None
        # a test file that did not exist at `rev` failing to import is the
        # usual red of a feature not written yet: the name it imports is
        # what the product step adds
        if said == "error" and new:
            said = "red"
        if said != "red":
            return None, (f + " is not red in the place as it starts (" + said
                          + (", " + kind if kind else "") + ")")
        carried[f] = start.tests[rel]
        kinds[f] = kind or "assertion"
    return {"how": "carried", "from": rev[:12], "tests": carried,
            "kinds": kinds}, ""
