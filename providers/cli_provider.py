import shutil
import subprocess

from .base import Provider, Reply, register


@register
class CliProvider(Provider):
    """the original. shells out to the cli, which is how this started."""

    name = "cli"

    def ask(self, prompt, timeout=None):
        argv = [self.opts.get("command", "claude"), "-p", prompt]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return Reply("", detail=r.stderr.strip()[:200])
        return Reply(r.stdout)

    def check(self):
        cmd = self.opts.get("command", "claude")
        if shutil.which(cmd) is None:
            return False, cmd + " is not on PATH"
        return True, cmd
