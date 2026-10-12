import json
import os
import shutil
import subprocess

from .base import Provider, Reply, Usage, again, model_for, register


def is_claude(command):
    """`claude`, `claude.cmd`, `/usr/bin/claude`: the one command whose flags
    and output this knows."""
    stem = os.path.splitext(os.path.basename(command.replace("\\", "/")))[0]
    return stem.lower() == "claude"


def answered(stdout):
    """-> the result object a `--output-format json` call prints, or None."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(data, dict) and ("result" in data or "is_error" in data):
        return data
    return None


USAGE_LIMIT = "usage_limit_reached"


def limit(data, why):
    """-> when the account's limit resets, "unknown" when it did not say, or
    None when this error is not that limit.

    claude names the kind in `api_error` and the reset, as an epoch, in
    `api_error_params.rate_limit_info.resetsAt`. a 429 alone is not enough:
    a short throttle is a 429 too, and that one is worth going again for.
    an error result without the field is read by its words.
    """
    from agentweft.runner import errors

    if data.get("api_error") == USAGE_LIMIT:
        params = data.get("api_error_params")
        info = params.get("rate_limit_info") if isinstance(params, dict) \
            else None
        at = errors.when(info.get("resetsAt")) if isinstance(info, dict) \
            else None
        return at or errors.resets(why)
    if errors.classify(why) is errors.Outage:
        return errors.resets(why)
    return None


@register
class CliProvider(Provider):
    """the original. shells out to the cli, which is how this started."""

    name = "cli"
    reads_place = True

    @property
    def command(self):
        return self.opts.get("command", "claude")

    def asks_for(self):
        return (model_for(self.opts) or None) if is_claude(self.command) \
            else None

    def argv(self, prompt):
        """-> (argv, stdin). claude gets the prompt on stdin and is asked for
        json, and never `--resume` or `--continue`: a carried-on session
        reports the whole session's usage, not this call's. any other command
        is called the way it always was."""
        cmd = self.command
        if not is_claude(cmd):
            return [cmd, "-p", prompt], None
        argv = [cmd, "-p", "--output-format", "json"]
        model = self.asks_for()
        if model:
            argv = argv + ["--model", model]
        # Windows caps a whole command line at about 32k characters, and a
        # prompt with a diff in it is past that long before the model minds.
        return argv, prompt

    def ask(self, prompt, timeout=None):
        argv, stdin = self.argv(prompt)
        try:
            # the platform default is cp1252 on Windows, and a reply decoded
            # with it is garbled or, for some bytes, an exception that loses it
            r = subprocess.run(argv, input=stdin, capture_output=True,
                               encoding="utf-8", errors="replace",
                               cwd=str(self.where) if self.where else None,
                               timeout=timeout)
        except FileNotFoundError:
            return Reply("", detail=argv[0] + " is not on PATH", retryable=False)
        except subprocess.TimeoutExpired:
            return Reply("", detail="timed out after " + str(timeout) + "s",
                         retryable=True)
        except OSError as e:
            return Reply("", detail=(argv[0] + ": " + str(e))[:200],
                         retryable=False)
        data = answered(r.stdout) if stdin is not None else None
        if data is not None:
            return self.read(data, r)
        if r.returncode != 0:
            # some failures say nothing on stderr and everything on stdout, and
            # i was throwing that away and reporting an empty error
            detail = (r.stderr.strip() or r.stdout.strip())[:200]
            return Reply("", detail=detail or ("exit " + str(r.returncode)))
        return Reply(r.stdout)

    def read(self, data, r):
        models = data.get("modelUsage")
        cost = data.get("total_cost_usd")
        said = dict(usage=Usage.of(data.get("usage")),
                    cost=cost if isinstance(cost, (int, float)) else None,
                    session=data.get("session_id") or None,
                    model=", ".join(sorted(models)) if isinstance(models, dict)
                    and models else None)
        text = data.get("result")
        if data.get("is_error") or r.returncode != 0:
            why = text if isinstance(text, str) and text.strip() else \
                (data.get("subtype") or "error")
            if r.returncode != 0:
                why = why + " (exit " + str(r.returncode) + ")"
            outage = limit(data, why)
            return Reply("", detail=why[:200], outage=outage,
                         retryable=False if outage
                         else again(data.get("api_error_status")), **said)
        if not isinstance(text, str) or not text:
            return Reply("", detail="an empty answer", **said)
        return Reply(text, **said)

    def check(self):
        cmd = self.command
        if shutil.which(cmd) is None:
            return False, cmd + " is not on PATH"
        return True, cmd
