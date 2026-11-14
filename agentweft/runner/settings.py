"""where a setting comes from, decided once.

there were three ways to configure something: the flow file, the environment,
and a default sitting in whichever module happened to need it. they disagreed,
and which one won depended on where you looked.

order, highest first: the step, the flow, the environment, the default. the
environment is `AGENTWEFT_<KEY>`, which is what `agentweft init` writes to
`.env`.

`.env` is read where agentweft is started, which can be the place itself,
and a place's files are the project's: a clone ships them and a step can
write them for the next run. so a name that loosens a guard or picks a
credential, a destination or a decision of the person's is refused when a
`.env` inside the place set it (`from_the_place`); a preference is not.
"""
import os
from pathlib import Path

DEFAULTS = {"timeout": 300, "retries": 3, "workers": 3,
            "max_calls": 25, "max_tokens": 0, "max_turns": 50,
            "tests_e2e": False, "tests_integration": "auto",
            "commits": "none",
            "provider": "cli", "permission_mode": "dontAsk",
            "co_author": False,
            "spec_globs": ("TASK.md", "SPEC*.md", "docs/spec*")}

PREFIX = "AGENTWEFT_"
# each name `load_env` set, and the `.env` it read it from: a `.env` in the
# place is the project's file, not the person's
FROM_FILE = {}
# the value each of those names held before the file set it
BEFORE = {}
# 0 is no cap
CAPS = ("max_calls", "max_tokens", "max_turns")
TRUE = ("1", "true", "yes", "on")
FALSE = ("0", "false", "no", "off")

LOOSENS = "loosens a guard"
CREDENTIAL = "picks a credential or where one is sent"
STEERS = "picks which program runs or where its traffic goes"
DECIDES = "makes a decision that is yours"
UNCLASSED = "is a setting agentweft has not classed as a preference"

PREFERENCES = ("AGENTWEFT_TIMEOUT", "AGENTWEFT_RETRIES", "AGENTWEFT_WORKERS",
               "AGENTWEFT_TESTS_E2E", "AGENTWEFT_TESTS_INTEGRATION",
               "AGENTWEFT_SPEC_GLOBS")
PERSONS = {"AGENTWEFT_PERMISSION_MODE": LOOSENS,
           "AGENTWEFT_MAX_CALLS": LOOSENS, "AGENTWEFT_MAX_TOKENS": LOOSENS,
           "AGENTWEFT_MAX_TURNS": LOOSENS, "PRICES": LOOSENS,
           "AGENTWEFT_KEY_FILE": CREDENTIAL, "AGENTWEFT_PROVIDER": CREDENTIAL,
           "API_KEY": CREDENTIAL, "API_URL": CREDENTIAL,
           "AGENTWEFT_COMMITS": DECIDES, "AGENTWEFT_CO_AUTHOR": DECIDES}
# where `claude` reads its login, endpoint, config folder and switches
PERSONS_UNDER = {"ANTHROPIC_": CREDENTIAL, "CLAUDE_": CREDENTIAL}
# the names a model's process keeps (`cli_provider.BASE`) that choose which
# program a bare name starts, where its home and login live, or the route and
# the certificates its requests trust
STEERING = ("PATH", "PATHEXT", "HOME", "USERPROFILE", "HOMEDRIVE",
            "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
            "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "SHELL",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
            "XDG_RUNTIME_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE")


def env_name(key):
    return PREFIX + key.upper()


def class_of(name, value=None):
    """-> why `name` set to `value` is the person's to set, None for a
    preference, a name agentweft does not read (a project's own variable,
    for its own tests), or one of agentweft's settings at its default or
    tighter: `agentweft init --yes` writes the defaults where it is started,
    which is often the place."""
    upper = name.upper()
    if upper in PREFERENCES:
        return None
    key = upper[len(PREFIX):].lower() if upper.startswith(PREFIX) else None
    if value is not None and key in DEFAULTS \
            and no_looser(key, value, BEFORE.get(name)):
        return None
    if upper in PERSONS:
        return PERSONS[upper]
    for prefix, why in PERSONS_UNDER.items():
        if upper.startswith(prefix):
            return why
    if upper in STEERING:
        return STEERS
    if upper.startswith(PREFIX):
        return UNCLASSED
    return None


def no_looser(key, text, before=None):
    """-> whether `text` for `key` is what the run would have used without
    the file (the value it replaced, else the default), or a cap tighter
    than that; text that does not read as a number is no cap."""
    said = parsed(key, text)
    base = parsed(key, before) if before is not None else DEFAULTS[key]
    if key in CAPS:
        if type(said) is not int or said < 0:
            return False
        if type(base) is not int:
            return said == base
        return base == 0 or 0 < said <= base
    return said == base


def from_the_place(place):
    """-> a reason for each name a `.env` inside `place` set that is the
    person's to set; [] when there is none."""
    try:
        here = Path(place).resolve()
    except OSError:
        here = Path(place)
    out = []
    for name, whose in sorted(FROM_FILE.items()):
        why = class_of(name, os.environ.get(name))
        if why is None:
            continue
        there = Path(whose)
        if there != here and here not in there.parents:
            continue
        out.append(name + " is set by " + whose + ", inside the place: it "
                   + why + ", which is yours to set, in your own environment"
                   " or a .env outside the place")
    return out


def parsed(key, text):
    """-> the environment's text as the type the default has. text that does
    not read as that type is left as it is, so the place that uses it says
    what is wrong with it rather than this guessing."""
    like = DEFAULTS.get(key)
    word = text.strip()
    if isinstance(like, bool):
        if word.lower() in TRUE:
            return True
        if word.lower() in FALSE:
            return False
        return word
    if isinstance(like, int):
        try:
            return int(word)
        except ValueError:
            return word
    if isinstance(like, tuple):
        return tuple(p.strip() for p in word.split(",") if p.strip())
    return word


def from_env(key):
    text = os.environ.get(env_name(key))
    if text is None or not text.strip():
        return None
    return parsed(key, text)


def get(key, step=None, flow=None, env=None, default=None):
    for source in (step, flow):
        if source and source.get(key) is not None:
            return source[key]
    if env is None:
        env = from_env(key)
    if env is not None:
        return env
    if default is not None:
        return default
    return DEFAULTS.get(key)
