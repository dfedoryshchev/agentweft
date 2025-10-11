import os
from pathlib import Path


def load_prompt(flow, name, rules):
    # pulling this out of main so main stops being the only place that knows
    # how a prompt gets built. half done.
    text = read(flow, name) + "\n\n" + rules
    for key in ["INBOX", "LOGS", "WATCH"]:
        text = text.replace("{" + key + "}", os.environ.get(key, ""))
    return text


def read(flow, name):
    f = open(flow_path(flow, name))
    text = f.read()
    f.close()
    return text

def flow_path(flow, *parts):
    return Path("flows").joinpath(flow, *parts)
