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
    f = open(flow_path(flow, name))
    text = f.read()
    f.close()
    return text

FLOW_ROOT = ["flows"]
ENV_KEYS = ("INBOX", "LOGS", "WATCH")


def flow_path(flow, *parts):
    return Path(FLOW_ROOT[0]).joinpath(flow, *parts)
