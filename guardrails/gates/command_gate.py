import subprocess
import tempfile
from pathlib import Path

from .base import Gate, register


@register
class CommandGate(Gate):
    """run something and look at the exit code.

    this is the one that matters. anything with a cli is now a check without
    me writing an adapter for it: a linter, a spell checker, a test runner,
    whatever i have not thought of.
    """

    name = "command"

    def run(self, text):
        cmd = self.opts.get("command")
        if not cmd:
            return self.fail("no command")
        want = int(self.opts.get("expect", 0))

        tmp = Path(tempfile.mkdtemp()) / "output.md"
        tmp.write_text(text, encoding="utf-8")
        argv = [str(tmp) if a == "{file}" else a for a in cmd]

        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=int(self.opts.get("timeout", 60)))
        except FileNotFoundError:
            return self.fail("not on PATH: " + argv[0])
        except subprocess.TimeoutExpired:
            return self.fail("timed out")

        if r.returncode == want:
            return self.ok("exit " + str(r.returncode))
        return self.fail("exit " + str(r.returncode) + ": "
                         + (r.stderr or r.stdout).strip()[:160])
