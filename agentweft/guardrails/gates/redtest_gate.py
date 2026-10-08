import subprocess
from pathlib import Path

from .base import Gate, register

TEST = "TEST:"


@register
class RedTestGate(Gate):
    """red before green, checked rather than asked for.

    fix-with-test says the test must fail before the patch. with a `command` the claim is not enough. the worker names the file on a
    `TEST:` line, the file has to be there in the run's place, and the command
    is run there with `{test}` replaced by it. red is the exit a failing test
    gives (`expect`, default 1, which is pytest's), not any non-zero one: a
    runner that collected nothing or was called wrong has not shown a test
    failing. `red: false` wants exit 0.

    without a command it is still only the marker, and the pass says so.
    """

    name = "red-test"

    def run(self, text):
        marker = self.opts.get("marker", "FAILS:")
        want_red = bool(self.opts.get("red", True))
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
            named = named_test(text)
            if not named:
                return self.fail("no " + TEST + " line, so there is no test to run")
            path = (place / named).resolve()
            try:
                path.relative_to(place.resolve())
            except ValueError:
                return self.fail(named + " is outside " + str(place))
            if not path.is_file():
                return self.fail(named + " is not in " + str(place)
                                 + ", so the test was never written")
            argv = [named if a == "{test}" else a for a in argv]

        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               cwd=str(place),
                               timeout=int(self.opts.get("timeout", 120)))
        except FileNotFoundError:
            return self.fail("not on PATH: " + argv[0])
        except subprocess.TimeoutExpired:
            return self.fail("timed out")

        code = r.returncode
        want = int(self.opts.get("expect", 1)) if want_red else 0
        if code == want:
            return self.ok(said + ", exit " + str(code))
        if want_red and code == 0:
            return self.fail("the test passed before the patch")
        return self.fail("exit " + str(code) + ", wanted " + str(want) + ": "
                         + (r.stderr or r.stdout).strip()[:160])


def named_test(text):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(TEST):
            return line[len(TEST):].strip().strip("`")
    return ""
