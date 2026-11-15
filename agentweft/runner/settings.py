"""where a setting comes from, decided once.

there were three ways to configure something: the flow file, the environment,
and a default sitting in whichever module happened to need it. they disagreed,
and which one won depended on where you looked.

order, highest first: the step, the flow, the environment, the default. the
environment is `AGENTWEFT_<KEY>`, which is what `agentweft init` writes to
`.env`.

`.env` is read where agentweft is started, which can be the place itself,
and a place's files are the project's: a clone ships them and a step can
write them for the next run. so a `.env` inside the place may set a
preference, a model or effort name, or one of these settings at the value the
run would use anyway or a tighter cap; a name its project.yml declares under
`env:` is kept for the gates' child, which runs the project's own tests, and
never reaches agentweft's own environment; anything else refuses the run
before any process starts (`sorted_out`). a `.env` outside the place is the
person's, and every name in it is applied.
"""
import os
import re
from pathlib import Path

DEFAULTS = {"timeout": 300, "retries": 3, "workers": 3,
            "max_calls": 25, "max_tokens": 0, "max_turns": 50,
            "tests_e2e": False, "tests_integration": "auto",
            "commits": "none",
            "provider": "cli", "permission_mode": "dontAsk",
            "co_author": False,
            "spec_globs": ("TASK.md", "SPEC*.md", "docs/spec*")}

PREFIX = "AGENTWEFT_"
# the names a `.env` inside the place set that its project.yml declares
# under `env:`, for the gates' child only (`gates/base.fresh_python`)
PLACE_ENV = {}
# whether agentweft started in the run's place or under it, as `load_env`
# decided; None before it has
STARTED_IN_PLACE = None
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
            "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "NODE_OPTIONS",
            "BASH_ENV", "ENV")
# git, python and the loader read these to pick the program or the code a
# process runs
STEERING_UNDER = ("GIT_", "PYTHON", "LD_", "DYLD_")
# a model or effort, alone or per tier (`MODEL_HIGH`), the names `init` writes
TIERED = ("MODEL", "EFFORT")
NOT_READ = ("is not a preference agentweft reads; declare it under `env:` in"
            " project.yml if the project's tests read it")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_name(key):
    return PREFIX + key.upper()


def allowed(name, value):
    """-> whether a `.env` inside the place may set `name` to `value` in
    agentweft's own environment: a preference, a model or effort name, or
    one of agentweft's settings at what the run would use without the file or
    tighter (`agentweft init --yes` writes the defaults where it is started,
    which is often the place)."""
    from agentweft.flow import spec

    upper = name.upper()
    if upper in PREFERENCES or upper == "PYTHONIOENCODING":
        return True
    if upper in TIERED or any(upper == word + "_" + tier.upper()
                              for word in TIERED for tier in spec.TIERS):
        return True
    key = upper[len(PREFIX):].lower() if upper.startswith(PREFIX) else None
    return key in DEFAULTS and no_looser(key, value, os.environ.get(name))


def class_of(name):
    """-> what setting `name` would do that is the person's to decide, None
    for a name agentweft has no class for."""
    upper = name.upper()
    if upper in PERSONS:
        return PERSONS[upper]
    for prefix, why in PERSONS_UNDER.items():
        if upper.startswith(prefix):
            return why
    if upper in STEERING or upper.startswith(STEERING_UNDER):
        return STEERS
    if upper.startswith(PREFIX):
        return UNCLASSED
    return None


def refusal(name, whose):
    why = class_of(name)
    said = name + " is set by " + whose + ", inside the place: it "
    if why is None:
        return said + NOT_READ
    return (said + why + ", which is yours to set, in your own environment"
            " or a .env outside the place")


def inside(folder, place):
    """-> whether `folder` is the place or under it; one that cannot be
    resolved counts as inside."""
    try:
        here = Path(place).resolve()
        there = Path(folder).resolve()
    except OSError:
        return True
    return there == here or here in there.parents


def declared(place):
    """-> the names the place's project.yml lists under `env:`, upper case."""
    from agentweft.orchestrate import project

    held = project.hold(place)
    if held.text is None:
        return set()
    return set(n.upper() for n in held.read().env())


def sorted_out(pairs, whose, place):
    """-> (the (name, value) pairs for agentweft's own environment, {name:
    value} for the gates' child only), for the lines of the `.env` `whose`
    read from the folder agentweft started in. raises ValueError naming
    `whose` and every name refused, so nothing is applied from a file with
    one."""
    if not inside(Path(whose).parent, place):
        return list(pairs), {}
    keep, aside, refused, listed = [], {}, [], None
    for name, value in pairs:
        if allowed(name, value):
            keep.append((name, value))
            continue
        if class_of(name) is None and NAME.match(name):
            if listed is None:
                listed = declared(place)
            if name.upper() in listed:
                aside[name] = value
                continue
        refused.append(refusal(name, whose))
    if refused:
        raise ValueError("; ".join(dict.fromkeys(refused)))
    return keep, aside


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
