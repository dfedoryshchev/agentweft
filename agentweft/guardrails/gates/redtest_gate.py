import os
import re
import subprocess
from pathlib import Path

from agentweft.guardrails import worktree
from agentweft.guardrails.snapshot import changed

from .base import Gate, fresh_python, register

TEST = "TEST:"


@register
class RedTestGate(Gate):
    """red before green, checked rather than asked for.

    fix-with-test says the test must fail before the patch. with a `command` the claim is not enough. the worker names the test on a
    `TEST:` line, as a file or as `file::name` (whatever the command takes to
    run one test), or in prose as "file - name", "file, name" or "name in
    file", which is run as `file::name` once the file defines that name. a
    line that reads as none of these fails quoting it. the file has to be
    there in the run's place, and the command
    is run there with `{test}` replaced by the whole of it. red is the exit a
    failing test gives (`expect`, default 1, which is pytest's), not any
    non-zero one: a runner that collected nothing or was called wrong has not
    shown a test failing. `red: false` wants exit 0, and is how the patcher is
    held to the test it was given: with no `TEST:` line of its own it runs the
    one the newest earlier step of the run named. red never borrows one, since
    the step that says a test fails is the one that has to name it.

    red is shown on the code as the run found it. while every product file
    is as the start snapshot hashed it, the test runs in the place. once one
    is not (a step wrote code, then the test went back to be fixed), the
    test changes are laid onto a temporary checkout of the start commit and
    it runs there, so code written since cannot turn it green.

    without a command it is still only the marker, and the pass says so. an
    empty answer fails as one, not as a test that never failed.
    """

    name = "red-test"
    options = ("marker", "red", "command", "timeout", "expect")

    def run(self, text):
        marker = self.opts.get("marker", "FAILS:")
        want_red = truth(self.opts.get("red", True))
        if want_red is None:
            return self.broke("red: " + repr(self.opts.get("red"))
                             + " is not true or false")
        if not (text or "").strip():
            return self.fail("the step answered nothing")
        has = marker in text
        if want_red and not has:
            return self.fail("no " + marker + " line, so the test never failed")
        if not want_red and has:
            return self.fail(marker + " still there after the patch")
        said = "red" if want_red else "green"
        cmd = self.opts.get("command")
        if not cmd:
            return self.ok(said + ", as claimed - nothing was run")
        return self.ran(cmd, text, want_red, said)

    def ran(self, cmd, text, want_red, said):
        place = Path(self.where) if self.where else Path.cwd()
        argv = list(cmd)
        if "{test}" in argv:
            named, name, why = read_test(text)
            if not named and not why and not want_red:
                for answer in reversed(self.earlier):
                    named, name, why = read_test(answer or "")
                    if named or why:
                        break
            if why:
                return self.fail(why)
            if not named:
                return self.fail("no " + TEST + " line, so there is no test to run")
            path = (place / named.split("::")[0]).resolve()
            try:
                path.relative_to(place.resolve())
            except ValueError:
                return self.fail(named + " is outside " + str(place))
            if not path.is_file():
                return self.fail(named.split("::")[0] + " is not in "
                                 + str(place)
                                 + ", so the test was never written")
            if name and not defines(path, name):
                return self.fail(name + " is not a test in "
                                 + named.split("::")[0])
            argv = [named if a == "{test}" else a for a in argv]
        if want_red and self.product_moved():
            return self.on_start(argv, said)
        return self.judged(argv, place, want_red, said, {})

    def product_moved(self):
        """whether a product file is not as the start snapshot hashed it."""
        s = self.start
        if s is None or not s.hashed or not s.start:
            return False
        return bool(changed(s.product, s.product_now()))

    def on_start(self, argv, said):
        """run the test on a checkout of the start commit holding the place
        as it started and the run's test changes, and no other change."""
        s = self.start
        try:
            with worktree.temporary(s.root, s.start) as tree:
                s.lay_out(tree, s.test_changes())
                there = s.place_in(tree)
                # an editable install puts the person's own tree on sys.path,
                # and the checkout would import the changed code from there
                path = [str(there), str(there / "src")]
                if os.environ.get("PYTHONPATH"):
                    path.append(os.environ["PYTHONPATH"])
                r = self.judged(argv, there, True, said,
                                {"PYTHONPATH": os.pathsep.join(path)})
        except ValueError as e:
            return self.broke("could not set out the start to run it on: "
                              + str(e))
        r.detail = r.detail + " (on the start commit, without the product" \
            " code written since)"
        return r

    def judged(self, argv, place, want_red, said, extra):
        try:
            with fresh_python(dict(os.environ, **extra)) as env:
                r = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   cwd=str(place), env=env,
                                   timeout=int(self.opts.get("timeout", 120)))
        except FileNotFoundError:
            return self.broke("not on PATH: " + argv[0])
        except subprocess.TimeoutExpired:
            return self.fail("timed out")

        code = r.returncode
        want = int(self.opts.get("expect", 1)) if want_red else 0
        if code == want:
            return self.ok(said + ", exit " + str(code))
        if want_red and code == 0:
            return self.fail("the test passed before the patch")
        return self.fail("exit " + str(code) + ", wanted " + str(want) + ": "
                         + (r.stderr or r.stdout).strip()[-160:])


def truth(value):
    """True, False, or None for a value that is neither.

    `bool("false")` is True, and a flow written as json or with the yaml
    quoted hands the gate a string.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        said = value.strip().lower()
        if said in ("true", "yes", "on", "1"):
            return True
        if said in ("false", "no", "off", "0"):
            return False
    return None


NAME = r"[A-Za-z_]\w*"
FILE = r"[^\s,]+\.\w+"
DASHES = "-" + "".join(chr(c) for c in range(0x2010, 0x2016)) + chr(0x2212)
FILE_THEN_NAME = re.compile(
    r"^(?P<file>" + FILE + r")(?:\s+[" + re.escape(DASHES) + r"]\s+|\s*,\s*"
    r"|\s*::\s*)(?P<name>" + NAME + r")$")
NAME_IN_FILE = re.compile(
    r"^(?P<name>" + NAME + r")\s+in\s+(?P<file>" + FILE + r")$")


def read_test(text):
    """-> (named, name, why) for the first `TEST:` line.

    `named` is what `{test}` becomes: the line as written when it is one
    token (a file or a node id), or `file::name` when the file and the name
    were written apart ("file - name", "file, name", "file :: name", "name
    in file"). `name` is set only then, for the caller to look for in the
    file. a line that reads as neither is `why`, never a guessed id.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(TEST):
            continue
        said = line[len(TEST):].strip()
        bare = said.replace("`", "").strip().rstrip(".")
        if not bare:
            return "", "", ""
        if not any(c.isspace() for c in bare):
            return said.strip("`"), "", ""
        m = FILE_THEN_NAME.match(bare) or NAME_IN_FILE.match(bare)
        if m:
            return m["file"] + "::" + m["name"], m["name"], ""
        return "", "", ("cannot read " + repr(said) + " as a test: write the"
                        " " + TEST + " line as file or file::name")
    return "", "", ""


def named_test(text):
    return read_test(text)[0]


def defines(path, name):
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return re.search(r"^\s*(?:async\s+)?(?:def|class)\s+" + re.escape(name)
                     + r"\b", source, re.M) is not None
