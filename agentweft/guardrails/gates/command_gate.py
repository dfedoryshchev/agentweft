import subprocess
import tempfile
from pathlib import Path

from agentweft.mcp import preflight

from .base import Gate, fresh_python, register


@register
class CommandGate(Gate):
    """run something and look at the exit code.

    this is the one that matters. anything with a cli is now a check without
    me writing an adapter for it: a linter, a spell checker, a test runner,
    whatever i have not thought of.

    with a `cold:` block it can also pick which command. `command` is the long
    one and runs unless the run's risk map says otherwise: when the step names
    at least one file and none of them is at the threshold, `cold`'s own
    command runs instead. no ranking, or a step that names nothing, is no
    evidence the change is small, so it gets the long one.
    """

    name = "command"
    options = ("command", "expect", "timeout", "cold")

    def pick(self, text):
        """-> (argv, why), argv None when `cold` cannot be run."""
        cold = self.opts.get("cold")
        if not cold:
            return self.opts.get("command"), ""
        if not isinstance(cold, dict) or not cold.get("command"):
            return None, "cold needs a command of its own"
        threshold = float(cold.get("threshold", preflight.DEFAULT_THRESHOLD))
        if not preflight.parse_ranking(self.ranking):
            return self.opts.get("command"), "no risk map, so the long command"
        if not preflight.files_mentioned(text):
            return self.opts.get("command"), "names no file, so the long command"
        hot = preflight.check(text, self.ranking, threshold=threshold)
        if hot:
            return self.opts.get("command"), (
                ", ".join(p + " at " + str(s) for p, s in hot)
                + ", so the long command")
        return cold["command"], ("nothing it touches is at " + str(threshold)
                                 + ", so the short command")

    def run(self, text):
        if not self.opts.get("command"):
            return self.broke("no command")
        cmd, why = self.pick(text)
        if cmd is None:
            return self.broke(why)
        want = int(self.opts.get("expect", 0))

        tmp = Path(tempfile.mkdtemp()) / "output.md"
        tmp.write_text(text, encoding="utf-8")
        argv = [str(tmp) if a == "{file}" else a for a in cmd]

        try:
            with fresh_python() as env:
                r = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   cwd=str(self.where) if self.where else None,
                                   env=env,
                                   timeout=int(self.opts.get("timeout", 60)))
        except FileNotFoundError:
            return self.broke("not on PATH: " + argv[0])
        except subprocess.TimeoutExpired:
            return self.fail("timed out")

        said = (" (" + why + ")") if why else ""
        if r.returncode == want:
            return self.ok("exit " + str(r.returncode) + said)
        # a test runner's verdict is at the end of what it prints
        return self.fail("exit " + str(r.returncode) + ": "
                         + (r.stderr or r.stdout).strip()[-160:] + said)
