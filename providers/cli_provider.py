import shutil
import subprocess

from .base import Provider, Reply, register


@register
class CliProvider(Provider):
    """the original. shells out to the cli, which is how this started."""

    name = "cli"

    def ask(self, prompt, timeout=None):
        argv = [self.opts.get("command", "claude"), "-p", prompt]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return Reply("", detail=argv[0] + " is not on PATH")
        except subprocess.TimeoutExpired:
            return Reply("", detail="timed out after " + str(timeout) + "s")
        if r.returncode != 0:
            # some failures say nothing on stderr and everything on stdout, and
            # i was throwing that away and reporting an empty error
            detail = (r.stderr.strip() or r.stdout.strip())[:200]
            return Reply("", detail=detail or ("exit " + str(r.returncode)))
        return Reply(r.stdout)

    def check(self):
        cmd = self.opts.get("command", "claude")
        if shutil.which(cmd) is None:
            return False, cmd + " is not on PATH"
        return True, cmd
