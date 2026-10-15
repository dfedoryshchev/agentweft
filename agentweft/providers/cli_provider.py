import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .base import (CUT, Provider, Reply, Usage, again, effort_said, model_for,
                   register)

PIPE = subprocess.PIPE
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

# a cli that has answered may still be writing its session down, and the
# transcript is read back after the step, so it gets this long to exit itself.
GRACE = 5

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

# what a process needs to start, find its home folder and reach the network
# through the machine's proxy. names are held upper case: Windows has no other.
BASE = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
        "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
        "PROGRAMFILES(X86)", "USER", "USERNAME", "LOGNAME", "SHELL", "LANG",
        "LC_ALL", "LC_CTYPE", "TERM", "TZ", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
        "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "HTTP_PROXY", "HTTPS_PROXY",
        "NO_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE")

# `claude` reads its login, config folder, endpoint and provider switch from
# names under these.
OWN = ("ANTHROPIC_", "CLAUDE_")

# the cli ranks this beside `--effort` without saying which wins, so a call
# that names a level does not take it along
EFFORT_VAR = "CLAUDE_CODE_EFFORT_LEVEL"


def shell_hook(denials):
    """-> the `hooks` setting that hands every Bash and PowerShell call to the
    shell-write check before it runs (`guardrails/shellwrite.py`).

    the exec form, `args`, spawns python with no shell between, so no quoting
    differs by platform. `-I` keeps the script's own folder off the import
    path. the denials file is an argument, never the environment."""
    from agentweft.guardrails import shellwrite

    args = ["-I", Path(shellwrite.__file__).as_posix()]
    if denials is not None:
        args.append(Path(denials).as_posix())
    return {"PreToolUse": [{"matcher": "|".join(shellwrite.TOOLS),
                            "hooks": [{"type": "command",
                                       "command": Path(sys.executable)
                                       .as_posix(),
                                       "args": args}]}]}


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


SUMMED = ("input_tokens", "output_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens")
WRITES = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")

# a file's time can be coarser than the clock it is held against
SLACK = 2


def first_prompt(rows):
    """-> the text of the first user message among a transcript's rows."""
    from agentweft.runner.handoff import _text

    for data in rows:
        message = data.get("message")
        if data.get("type") == "user" and isinstance(message, dict):
            return _text(message.get("content"))
    return None


def rows_of(path):
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def summed(blocks):
    """-> one usage block adding up the requests' own."""
    out = dict.fromkeys(SUMMED, 0)
    writes = dict.fromkeys(WRITES, 0)
    split = True
    searches = 0
    for block in blocks:
        for key in SUMMED:
            out[key] += count(block.get(key))
        said = block.get("cache_creation")
        if isinstance(said, dict):
            for key in WRITES:
                writes[key] += count(said.get(key))
        elif count(block.get("cache_creation_input_tokens")):
            split = False
        tools = block.get("server_tool_use")
        if isinstance(tools, dict):
            searches += count(tools.get("web_search_requests"))
    if split:
        out["cache_creation"] = writes
    if searches:
        out["server_tool_use"] = {"web_search_requests": searches}
    return out


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def spent_in(rows):
    """-> (Usage, {model: Usage} or None, model) for the requests a
    transcript records, or None when it records none.

    the cli writes one row per piece of an answer and every row of one
    message repeats its usage, so a message is counted once, by its last row.
    """
    last = {}
    for n, data in enumerate(rows):
        message = data.get("message")
        if data.get("type") != "assistant" or not isinstance(message, dict):
            continue
        if not isinstance(message.get("usage"), dict):
            continue
        key = message.get("id") or data.get("requestId") or n
        last[key] = message
    if not last:
        return None
    by_model = {}
    for message in last.values():
        name = message.get("model") or ""
        by_model.setdefault(name, []).append(message["usage"])
    blocks = [b for group in by_model.values() for b in group]
    usage = Usage(summed(blocks), requests=len(blocks))
    named = sorted(n for n in by_model if n)
    models = None
    if len(by_model) > 1:
        models = {n: Usage(summed(g), requests=len(g))
                  for n, g in by_model.items() if n}
    return usage, models, ", ".join(named) or None


def read_back(prompt, since):
    """-> (Usage, models, model, session) from the transcript the cli wrote
    for this prompt since `since`, or None when there is none to read.

    a go that never answered printed no session id, so its file is the one
    started in this window whose first message is the prompt. the folder is
    never guessed: every project's sessions are looked at.
    """
    from agentweft.runner.handoff import projects

    found = []
    try:
        for path in projects().glob("*/*.jsonl"):
            try:
                when = path.stat().st_mtime
            except OSError:
                continue
            if when >= since - SLACK:
                found.append((when, path))
    except OSError:
        return None
    for _, path in sorted(found, reverse=True):
        try:
            rows = rows_of(path)
        except OSError:
            continue
        if (first_prompt(rows) or "").strip() != prompt.strip():
            continue
        spent = spent_in(rows)
        if spent is None:
            return None
        session = next((d.get("sessionId") for d in rows
                        if d.get("sessionId")), None) or path.stem
        return spent + (session,)
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


class Ran(object):
    """what a call left: its exit code, both outputs as text, how many of the
    processes it started were still running and were ended (None when that
    could not be told), and whether it ran out of time."""

    __slots__ = ("returncode", "stdout", "stderr", "killed", "timed_out")

    def __init__(self, returncode, stdout, stderr, killed, timed_out=False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.killed = killed
        self.timed_out = timed_out


def text(raw):
    """utf-8 whatever the platform default, line ends as text mode gives them."""
    return raw.decode("utf-8", "replace").replace("\r\n", "\n") \
        .replace("\r", "\n")


def call(argv, stdin=None, cwd=None, timeout=None, done=None, env=None):
    """-> Ran. argv runs in a process group of its own, both pipes are read as
    they come so neither fills up and stalls it, and the call is over when
    `done` says the output so far is the whole answer, when the process exits,
    or at the timeout, whichever is first. whatever it started that is still
    running then is ended.

    waiting for the pipes to close is not enough: a shell the process left in
    the background holds them open, and the call would last as long as it.
    """
    if os.name == "nt":
        group = {"creationflags": NEW_GROUP}
    else:
        group = {"start_new_session": True}
    proc = subprocess.Popen(argv, stdin=PIPE if stdin is not None else None,
                            stdout=PIPE, stderr=PIPE, cwd=cwd, env=env,
                            **group)
    job = job_for(proc.pid) if os.name == "nt" else None
    out, err = [], []
    answer, eof, woke = threading.Event(), threading.Event(), threading.Event()

    def take(pipe, into, watch):
        try:
            while True:
                chunk = pipe.read1(65536)
                if not chunk:
                    break
                into.append(chunk)
                if watch and done and done(text(b"".join(into))):
                    answer.set()
                    woke.set()
        except (OSError, ValueError):
            pass
        if watch:
            eof.set()
            woke.set()

    def give(data):
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except OSError:
            pass

    hands = [threading.Thread(target=take, args=(proc.stdout, out, True)),
             threading.Thread(target=take, args=(proc.stderr, err, False))]
    if stdin is not None:
        hands.append(threading.Thread(target=give,
                                      args=(stdin.encode("utf-8"),)))
    for t in hands:
        t.daemon = True
        t.start()

    end = None if timeout is None else time.monotonic() + timeout

    def left(most=None):
        if end is None:
            return most
        rest = max(0.0, end - time.monotonic())
        return rest if most is None else min(most, rest)

    timed_out = False
    ended_it = False
    try:
        while not woke.is_set() and proc.poll() is None:
            if end is not None and left() <= 0:
                timed_out = True
                break
            woke.wait(left(0.05))
        if not timed_out and proc.poll() is None:
            try:
                proc.wait(left(GRACE) if answer.is_set() else left())
            except subprocess.TimeoutExpired:
                ended_it = answer.is_set()
                timed_out = not ended_it
    except BaseException:
        # in a group of its own it no longer hears the ctrl-c the runner got
        end_tree(proc, job)
        raise
    killed = end_tree(proc, job)
    for t in hands:
        t.join(5)
    try:
        code = proc.wait(5)
    except subprocess.TimeoutExpired:
        code = None
    if ended_it:
        code = 0
    return Ran(code, text(b"".join(out)), text(b"".join(err)), killed,
               timed_out)


def end_tree(proc, job):
    """-> how many processes besides proc were still running, None when that
    could not be told. all of them, proc too, are ended."""
    if os.name == "nt":
        return end_job(proc, job)
    return end_group(proc.pid)


KERNEL32 = []


def kernel32():
    if not KERNEL32:
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL,
                                  wintypes.DWORD)
        k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE,
                                               wintypes.HANDLE)
        k.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p)
        k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        KERNEL32.append(k)
    return KERNEL32[0]


def job_for(pid):
    """-> a job object holding pid, and every process it starts from here on,
    or None when one could not be made.

    on Windows a process group is no handle on the tree: `taskkill /T` walks
    parent ids, and a shell whose parent has already exited is not found by
    it. a job keeps every descendant, orphaned or not.
    """
    try:
        k = kernel32()
    except (OSError, AttributeError):
        return None
    job = k.CreateJobObjectW(None, None)
    if not job:
        return None
    # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    handle = k.OpenProcess(0x0100 | 0x0001, False, pid)
    ok = bool(handle) and bool(k.AssignProcessToJobObject(job, handle))
    if handle:
        k.CloseHandle(handle)
    if not ok:
        k.CloseHandle(job)
        return None
    return job


def end_job(proc, job):
    if job is None:
        if proc.poll() is None:
            import subprocess as stdlib

            try:
                stdlib.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
            except (OSError, stdlib.SubprocessError):
                pass
        return None
    import ctypes

    class Listed(ctypes.Structure):
        _fields_ = [("assigned", ctypes.c_ulong), ("listed", ctypes.c_ulong),
                    ("ids", ctypes.c_size_t * 1024)]

    k = kernel32()
    seen = Listed()
    # 3: JobObjectBasicProcessIdList
    if k.QueryInformationJobObject(job, 3, ctypes.byref(seen),
                                   ctypes.sizeof(seen), None):
        killed = len([i for i in seen.ids[:seen.listed] if i != proc.pid])
    else:
        killed = None
    k.TerminateJobObject(job, 1)
    k.CloseHandle(job)
    return killed


def end_group(pgid):
    import subprocess as stdlib

    try:
        ps = stdlib.run(["ps", "-A", "-o", "pid=,pgid="], capture_output=True,
                        encoding="utf-8", errors="replace", timeout=10).stdout
        killed = 0
        for row in ps.split("\n"):
            ids = row.split()
            if len(ids) == 2 and ids[1] == str(pgid) and ids[0] != str(pgid):
                killed = killed + 1
    except (OSError, stdlib.SubprocessError):
        killed = None
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    return killed


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

    def child_env(self):
        """-> the environment the command starts with: what any process needs,
        for `claude` its own login and settings, and the names the provider's
        `env` lists. nothing else the run holds, its keys and tokens included,
        reaches the model's process."""
        keep = set(BASE)
        listed = self.opts.get("env") or ()
        if isinstance(listed, str):
            listed = [listed]
        keep.update(str(name).upper() for name in listed)
        own = OWN if is_claude(self.command) else ()
        drop = EFFORT_VAR if self.chooses_effort() and self.asks_effort() \
            else None
        return {k: v for k, v in os.environ.items()
                if (k.upper() in keep or k.upper().startswith(own))
                and k.upper() != drop}

    def version(self):
        """-> the cli's version, None when it could not be read. asked once
        per provider, and only of `claude`."""
        if self.seen_version is not None or self.version_said:
            return self.seen_version
        cmd = self.command
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=30,
                               env=self.child_env())
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
                if self.seen_version else None,
                "shell_writes": "refused" if self.refuses_shell_writes()
                else None}

    def refuses_shell_writes(self):
        return self.grant is not None and "shell" in self.grant \
            and is_claude(self.command)

    def asks_for(self):
        return (model_for(self.opts) or None) if is_claude(self.command) \
            else None

    def chooses_model(self):
        return is_claude(self.command)

    def chooses_effort(self):
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
        settings = {}
        if not self.opts.get("co_author"):
            settings.update(NO_TRAILER)
        if self.refuses_shell_writes():
            settings["hooks"] = shell_hook(self.denials)
        if settings:
            argv = argv + ["--settings",
                           json.dumps(settings, separators=(",", ":"))]
        if self.grant is not None:
            argv = argv + fence(self.grant)
        model = self.asks_for()
        if model:
            argv = argv + ["--model", model]
        effort = self.asks_effort()
        if effort:
            argv = argv + ["--effort", effort]
        # Windows caps a whole command line at about 32k characters, and a
        # prompt with a diff in it is past that long before the model minds.
        return argv, prompt

    def ask(self, prompt, timeout=None):
        refused = self.refuses()
        if refused:
            return Reply("", detail=refused, retryable=False)
        argv, stdin = self.argv(prompt)
        since = time.time()
        try:
            r = call(argv, stdin=stdin,
                     cwd=str(self.where) if self.where else None,
                     timeout=timeout,
                     done=answered if stdin is not None else None,
                     env=self.child_env())
        except FileNotFoundError:
            return Reply("", detail=argv[0] + " is not on PATH", retryable=False)
        except OSError as e:
            return Reply("", detail=(argv[0] + ": " + str(e))[:200],
                         retryable=False)
        if r.timed_out:
            reply = Reply("", detail="timed out after " + str(timeout) + "s",
                          retryable=True, killed=r.killed)
            if stdin is not None:
                self.unanswered(reply, prompt, since, ran=True)
            return reply
        data = answered(r.stdout) if stdin is not None else None
        if data is not None:
            return self.read(data, r)
        if r.returncode != 0:
            # some failures say nothing on stderr and everything on stdout, and
            # i was throwing that away and reporting an empty error
            detail = (r.stderr.strip() or r.stdout.strip())[:200]
            reply = Reply("", detail=detail or ("exit " + str(r.returncode)),
                          killed=r.killed)
            if stdin is not None:
                # an exit with no transcript most likely never reached a model
                self.unanswered(reply, prompt, since, ran=False)
            return reply
        return Reply(r.stdout, killed=r.killed)

    def unanswered(self, reply, prompt, since, ran):
        """fills in what a go the cli never answered for used: read back from
        its transcript, else, when it is known to have run, estimated from the
        prompt."""
        found = read_back(prompt, since)
        if found is not None:
            reply.usage, reply.models, reply.model, reply.session = found
            reply.metered = "transcript"
        elif ran:
            from agentweft.guardrails.budget import CHARS_PER_TOKEN

            reply.metered = "estimate"
            reply.guess = len(prompt) // CHARS_PER_TOKEN
        return reply

    def read(self, data, r):
        models = data.get("modelUsage")
        cost = data.get("total_cost_usd")
        said = dict(usage=Usage.of(data.get("usage")),
                    cost=cost if isinstance(cost, (int, float)) else None,
                    session=data.get("session_id") or None,
                    model=", ".join(sorted(models)) if isinstance(models, dict)
                    and models else None,
                    models=per_model(models, data.get("usage")),
                    killed=r.killed)
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
        cut = CUT.get(data.get("stop_reason"))
        if cut:
            return Reply("", detail=cut, retryable=False, **said)
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
        said.append(effort_said(self, "the cli's default"))
        return ok, ", ".join(said)

    def login(self):
        """-> (logged in, what to say). the account itself is never repeated."""
        try:
            r = subprocess.run([self.command, "auth", "status"],
                               capture_output=True, encoding="utf-8",
                               errors="replace", timeout=30,
                               env=self.child_env())
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
