import datetime

import yaml

from .prompts import flow_path


class OrderedLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    # safe_load quietly keeps the LAST of two identical keys, so a flow.yaml
    # with two "steps:" blocks loses the first one and the run order changes
    # under you with nothing in the output to say why
    seen = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in seen:
            raise yaml.YAMLError("duplicate key in flow.yaml: " + str(key))
        seen[key] = loader.construct_object(v, deep=deep)
    return seen


OrderedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


def config(flow):
    return yaml.load(flow_path(flow, "flow.yaml").read_text(), OrderedLoader)


def fanout_step(flow):
    for s in config(flow)["steps"]:
        if s.get("fanout"):
            return s["role"]
    return None


def verdict(text):
    first = text.strip().split("\n")[0].strip()
    if first.startswith("VERDICT:"):
        return first.split(":", 1)[1].strip()
    return "ok"


def steps(flow):
    fm = config(flow)
    return [s.get("prompt", s["role"] + ".md") for s in fm["steps"]]


def due(fm):
    when = fm.get("schedule")
    if not when:
        return True
    if when == "daily":
        return True
    return datetime.date.today().strftime("%A").lower() == when
