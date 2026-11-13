"""a provider block declared once, under a name a step picks it by.

a step's `provider:` is either a block, as it always was, or the name of a
connector: one of the built-ins below, or one declared under `connectors:` in
project.yml or in the flow. the flow's declaration wins over project.yml's,
and both merge over a built-in of the same name, so `claude-api` needs only
its `key_file` said.

`auth` decides the credential the step's process gets and no other:
`subscription` strips every key and auth token, so the cli falls to its own
login; `api-key` hands it the key read from `key_file` at the call, and no
login token; `inherit` (the default) passes what the run holds, as before.
"""
import os
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
    claude a step could have written, one inside the place."""
    command = getattr(p, "command", None)
    if p.auth == INHERIT or command is None:
        return ""
    who = p.connector or p.name
    if not claude(command):
        return (who + " hands its key to claude only, never to " + command) \
            if p.auth == API_KEY else ""
    if p.where is None or not ("/" in command or "\\" in command):
        return ""
    path = Path(command).expanduser()
    if not path.is_absolute():
        path = Path(p.where) / path
    try:
        place = Path(p.where).resolve()
        inside = place in path.resolve().parents
    except OSError:
        inside = True
    if not inside:
        return ""
    return (who + " starts " + command + ", inside the place, where a step"
            " can write it: a credential goes only to a claude outside the"
            " place")


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
    if not p.key_file:
        return (who + " has auth: " + API_KEY + " and no key_file: declare"
                " one under connectors:")
    path = Path(p.key_file).expanduser()
    if p.where is not None:
        place = Path(p.where).resolve()
        try:
            inside = path.resolve() == place or place in path.resolve().parents
        except OSError:
            inside = False
        if inside:
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
    key = Path(p.key_file).expanduser().read_text(encoding="utf-8").strip()
    redact.handed(key)
    return key
