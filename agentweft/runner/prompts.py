import os
from pathlib import Path

from .task import MARK


def load_prompt(flow, name, rules, role=None, task=None):
    text = read(flow, name, role) + "\n\n" + rules
    return substitute(text, task)


def substitute(text, task=None):
    """{INBOX} and friends. string.Template with $ would mean escaping every
    dollar in a prompt, and safe_substitute swallows typos, so: explicit.

    the task goes in last, so a task that quotes {INBOX} reaches the model as
    it was written.
    """
    for key in ENV_KEYS:
        text = text.replace("{" + key + "}", os.environ.get(key, ""))
    return put_task(text, task)


def put_task(text, task):
    """{TASK}, on its own because the runner reads a prompt between the two."""
    if task is None:
        return text
    return text.replace(MARK, task)


def read(flow, name, role=None):
    """this flow's words for the role, then the library's words for the role.

    the flow goes first because it says what the material is, and the library
    last because it says how to answer - which is where every flow had already
    put it by hand. a flow with nothing of its own to add needs no file at
    all, which is the point: the role is the library's, the flow only differs.

    `name` is the file the flow's own words are in and `role` is what the step
    said it is. the library answers to the role: two files for one role are
    two sets of flow words and one contract.
    """
    from agentweft.roles import resolver

    own = flow_path(flow, name)
    shared = resolver.role_prompt(role + ".md" if role else name)
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
