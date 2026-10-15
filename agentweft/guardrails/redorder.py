"""no product code is written before a red test exists.

a step says what it writes: `writes: tests`, `writes: product` or `writes:
none`. the run holds a red proof once a red-test gate has seen a test fail by
running it, or a red-first gate has shown a new test red without the fix, on
a test file whose content is not what it was when the run started (the start
snapshot). a `writes: product` step does not start until there is one, and a
`writes: tests` step that changes a product file fails. it is fail-closed:
no start snapshot, no proof record or a gate that ran nothing is no proof.

two ways round it, both said in the record. `--skip-tests "<reason>"` is a
person deciding the run has no tests, and then none of the test checks apply.
`--continue <run>` carries the proof an earlier run of the same place holds,
and `--continue <commit>` carries tests the start commit added since that
commit, once each of them is seen failing in the place as it starts. neither
is assumed: a carried test whose content moved since, or one that does not
fail, carries nothing.

the proof is kept as runs/<id>/red-proof.json beside the start snapshot, so
a run picked up later has both.
"""
import json
import subprocess
from pathlib import Path

from agentweft.guardrails.snapshot import _sha, changed, is_test

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


class Order(object):
    """what the run holds: the start snapshot, a red proof or a skip."""

    def __init__(self, start, skip="", proof=None):
        self.start = start
        self.skip = skip
        self.proof = proof

    def before(self, step, writes):
        """why `step` may not start, or "" when it may."""
        if self.skip or writes != "product":
            return ""
        if self.start is None or not self.start.hashed:
            return (step + " writes product code, and the run has no start"
                    " snapshot to tell a test it wrote from one that was"
                    " there: no start snapshot, so no red test can be shown")
        if not self.proof:
            return (step + " writes product code, and the run holds no red"
                    " test yet: no red-test or red-first gate has seen a test"
                    " it wrote fail. --skip-tests \"<reason>\" runs without"
                    " tests, --continue <run or commit> carries them")
        return ""

    def watch(self, writes):
        """-> the product files' hashes before a `writes: tests` step, or
        None for any other step."""
        if self.skip or writes != "tests" or self.start is None \
                or not self.start.hashed:
            return None
        return self.start.product_now()

    def after(self, step, writes, before):
        """why a `writes: tests` step fails for what it changed, or ""."""
        if self.skip or writes != "tests":
            return ""
        if before is None:
            return (step + " writes tests only, and with no start snapshot"
                    " nothing shows it left product code alone")
        moved = changed(before, self.start.product_now())
        if moved:
            return (step + " writes tests only and changed product code: "
                    + ", ".join(moved))
        return ""

    def proven(self, step, results, output):
        """record the run's red proof from what `step`'s gates ran, the first
        time there is one. -> whether one was recorded now."""
        if self.proof or self.skip or self.start is None \
                or not self.start.hashed:
            return False
        moved = dict((self.start.from_place(rel), _sha(now))
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
            files = sorted(set(f for f in files if f in moved))
            if files:
                self.proof = {"how": "gate", "step": step, "gate": r.gate,
                              "tests": dict((f, moved[f]) for f in files)}
                return True
        return False

    def said(self):
        """-> the handoff's line on the order, "" when nothing is held."""
        if self.skip:
            return ("tests skipped: " + self.skip + " (--skip-tests), so no"
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
    `rev`, each seen failing in the place as it starts, or (None, why)."""
    if start is None or not start.start:
        return None, "the place has no start commit to carry tests from"
    if not cmd:
        return None, ("the flow has no red-test or red-first gate command to"
                      " run the carried tests with")
    try:
        r = subprocess.run(["git", "-C", str(start.root), "diff", "--name-only",
                            "-z", rev, start.start, "--"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except OSError as e:
        return None, "git could not be run: " + str(e)
    if r.returncode != 0:
        return None, rev + " is not a commit or a run of this place"
    carried = dict((start.from_place(rel), start.tests[rel])
                   for rel in r.stdout.split("\0")
                   if rel and is_test(rel) and rel in start.tests)
    if not carried:
        return None, "no test file changed between " + rev + " and the start"
    gate = RedFirstGate(command=cmd)
    for f in sorted(carried):
        said, kind = gate.one(cmd, f, start.place, "")
        if said != "red":
            return None, (f + " is not red in the place as it starts (" + said
                          + (", " + kind if kind else "") + ")")
    return {"how": "carried", "from": rev[:12], "tests": carried}, ""
