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
    return bad


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


def key_refused(p):
    """-> why p cannot be handed its key, "" when it can or needs none."""
    if p.auth != API_KEY:
        return ""
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
    """-> the key p's step is handed, read now, never kept anywhere."""
    why = key_refused(p)
    if why:
        raise NoKey(why)
    return Path(p.key_file).expanduser().read_text(encoding="utf-8").strip()
