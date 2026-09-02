import os
from pathlib import Path


def load_prompt(flow, name, rules):
    text = read(flow, name) + "\n\n" + rules
    return substitute(text)


def substitute(text):
    """{INBOX} and friends. string.Template with $ would mean escaping every
    dollar in a prompt, and safe_substitute swallows typos, so: explicit."""
    for key in ENV_KEYS:
        text = text.replace("{" + key + "}", os.environ.get(key, ""))
    return text


def read(flow, name):
    """this flow's words for the role, then the library's words for the role.

    the flow goes first because it says what the material is, and the library
    last because it says how to answer - which is where every flow had already
    put it by hand. a flow with nothing of its own to add needs no file at
    all, which is the point: the role is the library's, the flow only differs.
    """
    from agentweft.roles import resolver

    own = flow_path(flow, name)
    shared = resolver.role_prompt(name)
    if not own.exists():
        if not shared:
            raise FileNotFoundError(str(own))
        return shared
    text = own.read_text(encoding="utf-8")
    if not shared:
        return text
    return text.rstrip("\n") + "\n\n" + shared

FLOW_ROOT = ["flows"]
ENV_KEYS = ("INBOX", "LOGS", "WATCH")


def flow_path(flow, *parts):
    return Path(FLOW_ROOT[0]).joinpath(flow, *parts)
