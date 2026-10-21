"""where a setting comes from, decided once.

there were three ways to configure something: the flow file, the environment,
and a default sitting in whichever module happened to need it. they disagreed,
and which one won depended on where you looked.

order, highest first: the step, the flow, the environment, the default. the
environment is `AGENTWEFT_<KEY>`, which is what `agentweft init` writes to
`.env`.
"""
import os

DEFAULTS = {"timeout": 300, "retries": 3, "workers": 3,
            "max_calls": 25, "max_tokens": 0, "max_turns": 50,
            "tests_e2e": False, "tests_integration": "auto",
            "commits": "none",
            "provider": "cli", "permission_mode": "dontAsk",
            "co_author": False,
            "spec_globs": ("TASK.md", "SPEC*.md", "docs/spec*")}

PREFIX = "AGENTWEFT_"
TRUE = ("1", "true", "yes", "on")
FALSE = ("0", "false", "no", "off")


def env_name(key):
    return PREFIX + key.upper()


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
