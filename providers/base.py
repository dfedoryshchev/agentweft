"""who answers a prompt.

one method. everything else - a cli, an http api, a canned file - is a detail
of whatever is implementing it, and the engine is not allowed to know.
"""


class Reply(object):
    __slots__ = ("text", "cached", "detail")

    def __init__(self, text, cached=False, detail=""):
        self.text = text
        self.cached = cached
        self.detail = detail

    def __bool__(self):
        return bool(self.text)


class Provider(object):
    name = "provider"

    def __init__(self, **opts):
        self.opts = opts

    def ask(self, prompt, timeout=None):
        raise NotImplementedError

    def check(self):
        """-> (ok, detail). is this thing usable right now."""
        return True, "no check implemented"


registry = {}


def register(cls):
    registry[cls.name] = cls
    return cls


def build(config):
    name = (config or {}).get("provider", "cli")
    if name not in registry:
        raise ValueError("unknown provider: " + str(name) + ". there is: "
                         + ", ".join(sorted(registry)))
    opts = dict(config or {})
    opts.pop("provider", None)
    return registry[name](**opts)
