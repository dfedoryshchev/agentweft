"""a provider block declared once, under a name a step picks it by.

a step's `provider:` is either a block, as it always was, or the name of a
connector: one of the built-ins below, or one declared under `connectors:` in
project.yml or in the flow. the flow's declaration wins over project.yml's,
and both merge over a built-in of the same name.

`auth` decides the credential the step's process gets and no other:
`subscription` strips every key and auth token, so the cli falls to its own
login; `api-key` hands it the key read at the call from the connector's
`key_file`, else from the file `AGENTWEFT_KEY_FILE` names, and no login
token; `inherit` (the default) passes what the run holds.

where a credential comes from and where it goes is the person's to say, in
the flow or their own environment: project.yml is the repo's file, which a
clone ships and a step can write for the next run, so a connector it
declares sets none of `PERSONAL` and no `auth: api-key`.
"""
import os
import shutil
from pathlib import Path

SUBSCRIPTION = "subscription"
API_KEY = "api-key"
INHERIT = "inherit"
AUTHS = (SUBSCRIPTION, API_KEY, INHERIT)
KINDS = ("cli", "api", "fake")

BUILT_IN = {"claude-sub": {"provider": "cli", "auth": SUBSCRIPTION},
            "claude-api": {"provider": "cli", "auth": API_KEY},
            "stub": {"provider": "fake"}}

# the keys a connector adds to a provider block; the rest are the provider's
OWN = ("connector", "auth", "key_file")
# the block's keys that pick a credential, a process handed one, or where a
# request carrying one is sent
PERSONAL = ("key_file", "command", "url", "env")
# the setting that names the key file of a connector that names none
KEY_FILE = "key_file"
# every key a connector in project.yml may set, by the provider it runs on:
# which provider and model, a subscription or inherited login, and the
# provider's own tuning. a key a provider grows is refused there until listed
PROJECT_CONNECTOR_KEYS = {
    "cli": ("provider", "model", "tier", "effort", "auth", "max_turns"),
    "api": ("provider", "model", "tier", "effort", "auth", "max_tokens"),
    "fake": ("provider", "replies", "reply", "file", "default", "auth")}


def merged(declared=None):
    """-> every connector there is: the built-ins, each declared block merged
    over the one of its name."""
    out = {name: dict(block) for name, block in BUILT_IN.items()}
    for name, block in (declared or {}).items():
        out[name] = dict(out.get(name) or {}, **(block or {}))
    return out


def check_block(name, block):
    """-> complaints about one connector, each led by its name."""
    at = str(name) + ": "
    if not isinstance(block, dict):
        return [at + "should be a mapping"]
    if name in KINDS:
        return [at + "is a provider's own name; call the connector something"
                " else"]
    whole = dict(BUILT_IN.get(name) or {}, **block)
    bad = []
    kind = whole.get("provider")
    if kind not in KINDS:
        bad.append(at + "provider should be one of " + ", ".join(KINDS))
    auth = whole.get("auth", INHERIT)
    if auth not in AUTHS:
        bad.append(at + "auth should be one of " + ", ".join(AUTHS))
    elif kind == "fake" and auth != INHERIT:
        bad.append(at + "fake answers without a login, so its auth is "
                   + INHERIT)
    elif kind == "api" and auth == SUBSCRIPTION:
        bad.append(at + "the api provider has no subscription login: "
                   + API_KEY + " or " + INHERIT)
    path = whole.get("key_file")
    if path is not None and not full(path):
        bad.append(at + "key_file should be a full path (or start with ~),"
                   " not " + repr(path))
    command = whole.get("command")
    if name in BUILT_IN and command is not None:
        bad.append(at + "is a built-in connector, which starts claude; its"
                   " command is not declared again: declare a connector of"
                   " another name")
    elif kind == "cli" and auth == API_KEY and command is not None \
            and not claude(command):
        bad.append(at + "hands its key to claude only, never to "
                   + str(command))
    return bad


def claude(command):
    from .cli_provider import is_claude

    return isinstance(command, str) and is_claude(command)


def full(path):
    return isinstance(path, str) and bool(path.strip()) \
        and Path(path).expanduser().is_absolute()


def check(declared):
    """-> complaints about a `connectors:` block."""
    if not isinstance(declared, dict):
        return ["should be a mapping of name to provider block"]
    bad = []
    for name, block in declared.items():
        bad.extend(check_block(name, block))
    return bad


def check_project(declared):
    """-> complaints about project.yml's `connectors:` block: what any
    declaration gets, and each key off `PROJECT_CONNECTOR_KEYS` for its
    provider, `auth: api-key`, or a `max_turns` looser than the run's own."""
    from agentweft.runner import settings

    bad = check(declared)
    if bad and not isinstance(declared, dict):
        return bad
    for name, block in declared.items():
        if not isinstance(block, dict):
            continue
        at = str(name) + ": "
        listed = PROJECT_CONNECTOR_KEYS.get(
            dict(BUILT_IN.get(name) or {}, **block).get("provider"), ())
        persons = (["auth: " + API_KEY] if block.get("auth") == API_KEY
                   else []) + [key for key in PERSONAL if key in block]
        bad.extend(at + key + " is the person's to set, in the flow or their"
                   " own environment, never in the project's file"
                   for key in persons)
        bad.extend(at + str(key) + " is not a key project.yml may set on a"
                   " connector" for key in block
                   if key not in listed and key not in PERSONAL)
        turns = block.get("max_turns")
        if "max_turns" in listed and turns is not None and not (
                isinstance(turns, int) and not isinstance(turns, bool)
                and settings.no_looser("max_turns", str(turns),
                                       os.environ.get(settings.env_name(
                                           "max_turns")))):
            bad.append(at + "max_turns: " + str(turns) + " is looser than the"
                       " run's own runaway guard")
    return bad


def declared(fm=None, held=None):
    """-> the connectors a run declares: project.yml's, then the flow's over
    them. `held` is project.yml as the run read it at its start."""
    out = {}
    said = held.read().raw.get("connectors") \
        if held is not None and held.text is not None else None
    for source in (said, (fm or {}).get("connectors")):
        for name, block in (source or {}).items():
            out[name] = dict(out.get(name) or {}, **(block or {}))
    return out


def block_of(value, declared=None):
    """-> the provider block `value` stands for: a block as it is, a
    connector's name as its block with `connector` set, nothing as {}."""
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    known = merged(declared)
    if isinstance(value, str) and value in known:
        bad = check_block(value, known[value])
        if bad:
            raise ValueError("connector " + "; ".join(bad))
        return dict(known[value], connector=value)
    raise ValueError(str(value) + " names no connector. there is: "
                     + ", ".join(sorted(known)))


def kind(value, declared=None):
    """-> the provider a block or a connector's name runs on, None when it
    names none."""
    if isinstance(value, dict):
        return value.get("provider")
    if isinstance(value, str):
        return (merged(declared).get(value) or {}).get("provider", value)
    return None


def label(p):
    """-> what a cost line calls p's calls: its provider's name for a block
    written inline that inherits, else its connector and its auth."""
    connector = getattr(p, "connector", None)
    auth = getattr(p, "auth", INHERIT)
    if connector is None and auth == INHERIT:
        return p.name
    return (connector or p.name) + ":" + auth


def command_refused(p):
    """-> why p's command may not be handed the credential its auth names,
    "" when it may: a key goes to claude only, and no credential goes to a
    claude a step could have written: one inside the place, or in
    agentweft's runs folder, whose runs' `tmp` the steps write and which
    outlives each run. a bare `claude` is judged where PATH finds it."""
    command = getattr(p, "command", None)
    if p.auth == INHERIT or command is None:
        return ""
    who = p.connector or p.name
    if not claude(command):
        return (who + " hands its key to claude only, never to " + command) \
            if p.auth == API_KEY else ""
    path = started(p)
    if path is None:
        return ""
    from agentweft.runner import state

    if p.where is not None and inside(path, p.where):
        return (who + " starts " + shown(command, path) + ", inside the"
                " place, where a step can write it: a credential goes only to"
                " a claude outside the place")
    if inside(path, state.RUNS):
        return (who + " starts " + shown(command, path) + ", in agentweft's"
                " runs folder, where a step can write it: a credential goes"
                " only to a claude outside the place and the runs folder")
    return ""


def started(p):
    """-> the file p's command starts, as a resolved path, found once per
    provider (a run builds its own), put on `p.command_path` for its step
    line; None when PATH has no such command. a path that cannot be
    resolved is kept as written, and `inside` counts it as inside."""
    if p.command_path is not None:
        return p.command_path
    command = p.command
    if "/" in command or "\\" in command:
        path = Path(command).expanduser()
        if not path.is_absolute() and p.where is not None:
            path = Path(p.where) / path
    else:
        found = shutil.which(command)
        if not found:
            return None
        path = Path(found)
    try:
        p.command_path = str(path.resolve())
    except OSError:
        p.command_path = str(path)
    return p.command_path


def shown(command, path):
    return command if command == path else command + " (" + path + ")"


# what `claude auth status --json` says in `authMethod` for each auth. the cli
# ranks a key helper, an `env` block in the person's settings and a named
# profile above its login, and none of those is an environment name to strip.
# `oauth_token` is also a profile's, so it is the subscription only while
# the step's environment holds the subscription's own token.
LOGIN = "claude.ai"
TOKEN = "oauth_token"
TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"
KEYED = "api_key"


def method_refused(p):
    """-> why a step on p may not start because the cli says it logs in
    another way than p's auth, "" when it may. `inherit` is never
    refused; a method that could not be read is refused."""
    if p.auth == INHERIT or not claude(getattr(p, "command", None)):
        return ""
    said = p.auth_method
    if p.auth == API_KEY:
        if said == KEYED:
            return ""
        fix = "the key from its key_file did not reach the cli"
    else:
        token = any(k.upper() == TOKEN_VAR and v.strip()
                    for k, v in os.environ.items())
        if said == LOGIN or (said == TOKEN and token):
            return ""
        fix = ("a key helper, an env block in the settings, a saved key or a"
               " profile ranks above the login: take it out, or pick a"
               " connector with auth: " + API_KEY)
    return ((p.connector or p.name) + " has auth: " + p.auth + ", and `claude"
            " auth status` says it logs in with "
            + (said or "nothing it could read") + ": " + fix)


def key_refused(p):
    """-> why p cannot be handed its key, "" when it can or needs none."""
    why = command_refused(p)
    if why or p.auth != API_KEY:
        return why
    who = p.connector or p.name
    named, var = key_file_of(p)
    if not named:
        return (who + " has auth: " + API_KEY + " and no key file: set "
                + key_var() + " in your environment, or key_file on the"
                " connector in your flow")
    if var:
        if not full(named):
            return (who + " reads its key from " + var + ", which should be a"
                    " full path (or start with ~), not " + repr(named))
    path = Path(named).expanduser()
    if p.where is not None:
        place = Path(p.where).resolve()
        try:
            within = path.resolve() == place or place in path.resolve().parents
        except OSError:
            within = False
        if within:
            return (who + " reads its key from " + str(path) + ", inside the"
                    " place, where every step's tools can read it: keep the"
                    " key file outside the place")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (who + " reads its key from " + str(path) + ", which is not"
                " there: write the key into it, or pick another connector")
    except OSError as e:
        return (who + " could not read its key file " + str(path) + ": "
                + type(e).__name__)
    if not text.strip():
        return str(path) + " is empty, and " + who + " reads its key from it"
    from agentweft.guardrails.redact import SHORTEST

    if len(text.strip()) < SHORTEST:
        return (str(path) + " holds " + str(len(text.strip())) + " characters,"
                " and a key is " + str(SHORTEST) + " or more: " + who
                + " reads its key from it")
    return ""


class NoKey(Exception):
    """the step's key could not be read at the call."""


def key_of(p):
    """-> the key p's step is handed, read now. its value is kept nowhere
    but this process's memory, where the redaction looks for it."""
    from agentweft.guardrails import redact

    why = key_refused(p)
    if why:
        raise NoKey(why)
    named, _ = key_file_of(p)
    key = Path(named).expanduser().read_text(encoding="utf-8").strip()
    redact.handed(key)
    return key


def key_var():
    from agentweft.runner import settings

    return settings.env_name(KEY_FILE)


def key_file_of(p):
    """-> (the key file p reads, the environment name it came from or None
    when the connector names it itself); ("", None) when there is none."""
    if p.key_file:
        return p.key_file, None
    said = os.environ.get(key_var(), "").strip()
    return (said, key_var()) if said else ("", None)


def inside(path, place):
    """-> whether `path` is the place or under it; a path that cannot be
    resolved counts as inside."""
    try:
        here = Path(place).resolve()
        there = Path(path).expanduser().resolve()
    except OSError:
        return True
    return there == here or here in there.parents
