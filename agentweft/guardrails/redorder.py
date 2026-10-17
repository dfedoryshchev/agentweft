"""no product code is written before a red test exists.

a step says what it writes: `writes: tests`, `writes: product`, `writes:
spec` or `writes: none`. the run holds a red proof once a red-test gate has
seen a test fail by running it, or a red-first gate has shown a new test red
without the fix, on a test file whose content is not what it was when the
run started (the start snapshot). a red-test gate's test may also be one the
run started with and left as it was, a bug report that ships its own failing
test, once it also fails on an assertion in a checkout of the start commit
(`red_at_start`): then the proof says `supplied` rather than `written`. the
proof keeps the new test ids there were when it was shown (none for a
supplied one, which was red at the start), so a test added after that is
known as one (the red-first gate replays it). a `writes: product` step does
not start until there is one, and a step that changes what its `writes:`
does not name fails (`writes.py`). it is fail-closed: no start snapshot, no
proof record or a gate that ran nothing is no proof.

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
import re
from pathlib import Path

from agentweft.guardrails import worktree
from agentweft.guardrails import writes as bounds
from agentweft.guardrails.snapshot import _git, _sha, is_test

from .gates.redfirst_gate import RedFirstGate
from .gates.redtest_gate import named_test

FILE = "red-proof.json"
TEST_GATES = ("red-test", "red-first")
TALLY = re.compile(r"\b(\d+) (failed|errors?)\b")


def failed_only(output):
    """whether pytest's tally says tests failed and none errored: a missing
    fixture or a broken import is an error, not the bug failing."""
    said = dict((kind.rstrip("s"), int(n)) for n, kind in
                TALLY.findall(output or ""))
    return said.get("failed", 0) > 0 and not said.get("error")


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

    def __init__(self, start, skip="", proof=None, cmd=None,
                 additions=False):
        self.start = start
        self.skip = skip
        self.proof = proof
        self.cmd = cmd
        self.additions = additions
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
                    " on a tests step has seen a test it wrote, or one the"
                    " run started with, fail."
                    " --skip-tests \"<reason>\" runs without tests,"
                    " --continue <run or commit> carries them")
        return ""

    def watch(self, step, writes):
        """note what the place holds before a step that says what it writes
        (`writes.py`). a step sent back keeps the hashes from before its
        first go, so it is held to undoing what it changed then."""
        if not self.holds(writes) or self.start is None \
                or not self.start.hashed:
            return
        if step not in self.watching:
            self.watching[step] = self.start.hashes()

    def after(self, step, writes, ruled=None):
        """why a step fails for what it changed against its `writes:`, or
        "". `ruled` says whether a ruling quotes every spec line that moved
        since the run started, asked only of a product step."""
        if not self.holds(writes):
            return ""
        if step not in self.watching:
            return bounds.unseen(step, writes)
        spec_ok = writes == "product" and (
            self.additions or (ruled is not None and ruled()))
        return bounds.held(step, writes, self.watching[step],
                           self.start.hashes(), self.start.from_place,
                           spec_ok)

    def holds(self, writes):
        """whether a step that says `writes` is checked after it: a tests
        step is a test check, which `--skip tests` turns off."""
        return writes in bounds.MAY and \
            not (self.skip and writes == "tests")

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
            files, named = [], ""
            if r.gate == "red-test" and r.detail.startswith("red, exit"):
                named = named_test(output or "")
                files = [named.split("::")[0]]
            elif r.gate == "red-first" and r.tests:
                files = [t["test"].split("::")[0] for t in r.tests
                         if t["before"] == "red"]
            keys = sorted(set(norm(f) for f in files))
            found = [moved[k] for k in keys if k in moved]
            source = "written"
            if not found and named:
                there = self.supplied()
                found = [there[k] for k in keys if k in there]
                source = "supplied"
                if found and not self.red_at_start(named):
                    found = []
            if found:
                # a supplied red was there at the start, so every test the
                # run writes comes after it, even one this step wrote
                ids = [] if source == "supplied" else (
                    self.start.new_test_ids() if self.start.start else None)
                self.proof = {"how": "gate", "step": step, "gate": r.gate,
                              "source": source, "tests": dict(found),
                              "ids": ids}
                self.lost = ""
                return True
        return False

    def supplied(self):
        """-> {key: (path from the place, sha256 at the start)} for the test
        files the run started with."""
        out = {}
        for rel, sha in self.start.tests.items():
            f = self.start.from_place(rel)
            out[norm(f)] = (f, sha)
        return out

    def red_at_start(self, test):
        """whether `test` fails on an assertion in a checkout of the start
        commit holding the place as it started: no conftest, helper or
        tooling a step wrote since. a setup or collection error, no start
        commit, or no command to run it with is no."""
        if not self.cmd or not self.start.start:
            return False
        gate = RedFirstGate(command=self.cmd)
        try:
            with worktree.temporary(self.start.root, self.start.start) as tree:
                self.start.lay_out(tree, [])
                r, _ = gate.ran(self.cmd, test, self.start.place_in(tree))
        except ValueError:
            return False
        return r is not None and r.returncode == 1 and \
            failed_only(r.stdout + "\n" + r.stderr)

    def given(self):
        """-> ({path from the place: sha256}, where they came from) for the
        tests the proof holds that the run did not write, ({}, "") when
        it wrote them."""
        if not self.proof:
            return {}, ""
        if self.proof.get("how") == "carried":
            return dict(self.proof.get("tests") or {}), \
                "carried from " + self.proof["from"]
        if self.proof.get("source") == "supplied":
            return dict(self.proof.get("tests") or {}), \
                "supplied, red at the start"
        return {}, ""

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
        source = self.proof.get("source")
        return ("red before any product code: " + self.proof["gate"] + " on "
                + self.proof["step"] + " (" + files
                + (", " + source if source else "") + ")")

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
        said, kind = gate.one(cmd, f, start.place)
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
