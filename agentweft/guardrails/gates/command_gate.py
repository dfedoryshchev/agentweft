import re
import subprocess
import tempfile
from pathlib import Path

from agentweft.guardrails import hostfault
from agentweft.mcp import preflight

from .base import Gate, fresh_python, register

QUOTE = 160
# pytest draws its section rules to the terminal's width, one column less on
# windows. redrawn as it draws them with no terminal, not shorter: a short rule
# lets the line above it into the cut, a path in the machine's own separator
WIDTH = 80
TITLED_RULE = re.compile(r"(?m)^([=_-])\1{2,} (\S.*?) \1{2,}(?=\r?$)")
BARE_RULE = re.compile(r"(?m)^([=_-])\1{9,}(?=\r?$)")


def drawn(m):
    sep = m.group(1)
    if m.re is BARE_RULE:
        return sep * WIDTH
    title = m.group(2)
    n = max((WIDTH - len(title) - 2) // 2, 1)
    line = sep * n + " " + title + " " + sep * n
    return line + sep if len(line) < WIDTH else line


def tail(output, limit=QUOTE):
    """-> the end of `output` in at most `limit` characters, from the start of
    the oldest line that fits whole, or from a word in the first half of the
    cut when the last line alone is longer, else the cut as it falls. a
    section rule is redrawn `WIDTH` wide first."""
    text = BARE_RULE.sub(drawn, TITLED_RULE.sub(drawn, output)).strip()
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    if text[-limit - 1] == "\n":
        return cut.lstrip("\r\n")
    at = cut.find("\n")
    if at != -1 and cut[at + 1:].strip():
        return cut[at + 1:].lstrip("\r\n")
    at = cut.find(" ")
    if at != -1 and at < limit // 2:
        return cut[at + 1:]
    return cut


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

        said = (" (" + why + ")") if why else ""
        r = self.once(argv, want, said)
        fault = r.host
        if not fault:
            return r
        again = self.once(argv, want, said)
        if again.ok:
            again.detail = again.detail + " (run again: the first run failed" \
                " on " + fault + ")"
            return again
        if again.host:
            return hostfault.held(again, "run " + argv[0], again.host)
        return again

    def once(self, argv, want, said):
        """-> what one run of `argv` shows. a fail whose every red is the
        host's own fault carries it as `host`, to be run again."""
        try:
            with fresh_python() as env:
                r = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   cwd=str(self.where) if self.where else None,
                                   env=env,
                                   timeout=int(self.opts.get("timeout", 60)))
        except FileNotFoundError:
            return self.broke("not on PATH: " + argv[0])
        except OSError as e:
            out = self.broke("cannot start " + argv[0] + ": "
                             + (e.strerror or str(e)))
            out.host = hostfault.line(hostfault.named(e))
            return out
        except subprocess.TimeoutExpired:
            return self.could_not(False, "timed out",
                                  "could not finish: timed out after "
                                  + str(int(self.opts.get("timeout", 60)))
                                  + "s")

        if r.returncode == want:
            return self.ok("exit " + str(r.returncode) + said)
        # a test runner's verdict is at the end of what it prints
        out = self.fail("exit " + str(r.returncode) + ": "
                        + tail(r.stderr or r.stdout) + said)
        out.host = hostfault.of_run(r.stdout + "\n" + r.stderr)
        return out
