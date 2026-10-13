import json
import os
import re
import shutil
import subprocess

from .base import Provider, Reply, Usage, again, model_for, register

# a grant word, as the built-in tools claude calls it by. the keys are
# `spec.GRANTS` in its order, which a test holds them to.
TOOLS = {"read": ("Read", "Glob"),
         "grep": ("Grep",),
         "write": ("Write",),
         "edit": ("Edit", "NotebookEdit"),
         "shell": ("Bash", "PowerShell"),
         "browser": ("WebFetch", "WebSearch")}

# a grant with none of these only looks, and runs `--restricted`.
ACTS = ("write", "edit", "shell")

# below 2.1.295 `--tools` and `--restricted` miss the built-in tools that
# register after launch, so the fence fails open.
FLOOR = (2, 1, 295)

NO_TRAILER = {"attribution": {"commit": "", "pr": "", "sessionUrl": False}}


def version_of(text):
    """-> (major, minor, patch) from what `claude --version` prints, or None."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(n) for n in m.groups()) if m else None


def dotted(version):
    return ".".join(str(n) for n in version)


def fence(grant):
    """-> the flags that hold a `claude` step to its grant.

    `--tools` is the fence: a tool it does not name is not there. under
    `dontAsk` anything that would prompt is denied, so the granted tools are
    also pre-approved with `--allowedTools`, which on its own fences nothing.
    `--tools` does not reach MCP tools, so those are denied by name. only the
    user's own settings load, which keeps the place's `.claude/` hooks, `env`
    and key helper out without switching off hooks the run passes in itself.
    """
    tools = [t for word, names in TOOLS.items() if word in grant
             for t in names]
    out = ["--tools", ",".join(tools)]
    if tools:
        out = out + ["--allowedTools", ",".join(tools)]
    out = out + ["--permission-mode", "dontAsk", "--strict-mcp-config",
                 "--disallowedTools", "mcp__*", "--disable-slash-commands"]
    if any(word in grant for word in ACTS):
        return out + ["--setting-sources", "user"]
    # restricted already loads no user, project or local settings file
    return out + ["--restricted"]


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


PER_MODEL = (("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
             ("cache_read_input_tokens", "cacheReadInputTokens"),
             ("cache_creation_input_tokens", "cacheCreationInputTokens"))


def per_model(models, usage):
    """-> {model: Usage} when more than one model answered, else None.

    `modelUsage` has no cache lifetime per model, so one is given only when
    the whole answer wrote to one lifetime; otherwise a model's cache writes
    stay unsplit and are not priced.
    """
    if not isinstance(models, dict) or len(models) < 2:
        return None
    usage = usage if isinstance(usage, dict) else {}
    said = usage.get("cache_creation")
    one = None
    if isinstance(said, dict):
        five = said.get("ephemeral_5m_input_tokens") or 0
        hour = said.get("ephemeral_1h_input_tokens") or 0
        if not (five and hour):
            one = "ephemeral_1h_input_tokens" if hour \
                else "ephemeral_5m_input_tokens"
    out = {}
    for name, block in models.items():
        block = block if isinstance(block, dict) else {}
        raw = {ours: block.get(theirs) for ours, theirs in PER_MODEL}
        for key in ("speed", "inference_geo"):
            if key in usage:
                raw[key] = usage[key]
        raw["server_tool_use"] = {"web_search_requests":
                                  block.get("webSearchRequests")}
        if one:
            raw["cache_creation"] = {
                "ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0,
                one: block.get("cacheCreationInputTokens") or 0}
        out[name] = Usage(raw)
    return out


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
    seen_version = None
    version_said = ""

    @property
    def command(self):
        return self.opts.get("command", "claude")

    def version(self):
        """-> the cli's version, None when it could not be read. asked once
        per provider, and only of `claude`."""
        if self.seen_version is not None or self.version_said:
            return self.seen_version
        cmd = self.command
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=30)
            said = (r.stdout or "").strip()
            self.seen_version = version_of(said) if r.returncode == 0 else None
            self.version_said = said or ("exit " + str(r.returncode))
        except (OSError, subprocess.TimeoutExpired) as e:
            self.version_said = str(e) or type(e).__name__
        return self.seen_version

    def refuses(self):
        if self.grant is None or not is_claude(self.command):
            return ""
        v = self.version()
        if v is None:
            return ("could not read the version of " + self.command + " ("
                    + self.version_said[:80] + "), and a step with tools needs "
                    + dotted(FLOOR) + " or later")
        if v < FLOOR:
            return (self.command + " is " + dotted(v) + ", and a step with "
                    "tools needs " + dotted(FLOOR) + " or later: below it "
                    "--tools and --restricted miss the tools that register "
                    "after launch")
        return ""

    def granted(self):
        if self.grant is None or not is_claude(self.command):
            return Provider.granted(self)
        return {"tools": list(self.grant), "enforced": True,
                "argv": self.argv("")[0][1:],
                "cli_version": dotted(self.seen_version)
                if self.seen_version else None}

    def asks_for(self):
        return (model_for(self.opts) or None) if is_claude(self.command) \
            else None

    def chooses_model(self):
        return is_claude(self.command)

    def argv(self, prompt):
        """-> (argv, stdin). claude gets the prompt on stdin and is asked for
        json, and never `--resume` or `--continue`: a carried-on session
        reports the whole session's usage, not this call's. any other command
        is called the way it always was, grant or none: which flags it takes
        is not ours to guess."""
        cmd = self.command
        if not is_claude(cmd):
            return [cmd, "-p", prompt], None
        argv = [cmd, "-p", "--output-format", "json"]
        if not self.opts.get("co_author"):
            argv = argv + ["--settings",
                           json.dumps(NO_TRAILER, separators=(",", ":"))]
        if self.grant is not None:
            argv = argv + fence(self.grant)
        model = self.asks_for()
        if model:
            argv = argv + ["--model", model]
        # Windows caps a whole command line at about 32k characters, and a
        # prompt with a diff in it is past that long before the model minds.
        return argv, prompt

    def ask(self, prompt, timeout=None):
        refused = self.refuses()
        if refused:
            return Reply("", detail=refused, retryable=False)
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
                    and models else None,
                    models=per_model(models, data.get("usage")))
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
        """-> (ok, detail). for `claude`: its version against the floor, whether
        it is logged in, and the model a step would ask for. nothing here
        makes a model call."""
        cmd = self.command
        if shutil.which(cmd) is None:
            return False, cmd + " is not on PATH"
        if not is_claude(cmd):
            return True, cmd
        v = self.version()
        if v is None:
            return False, "could not read " + cmd + " --version: " \
                + self.version_said[:80]
        ok, said = True, [cmd + " " + dotted(v)]
        if v < FLOOR:
            ok = False
            said.append("below " + dotted(FLOOR) + ", so a step with tools is "
                        "refused")
        logged, how = self.login()
        ok = ok and logged
        said.append(how)
        said.append("model " + (self.asks_for() or "the cli's default"))
        return ok, ", ".join(said)

    def login(self):
        """-> (logged in, what to say). the account itself is never repeated."""
        try:
            r = subprocess.run([self.command, "auth", "status"],
                               capture_output=True, encoding="utf-8",
                               errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, "could not ask whether it is logged in: " + str(e)
        if r.returncode != 0:
            return False, "not logged in"
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = None
        method = data.get("authMethod") if isinstance(data, dict) else None
        return True, "logged in" + (" (" + method + ")"
                                    if isinstance(method, str) else "")
