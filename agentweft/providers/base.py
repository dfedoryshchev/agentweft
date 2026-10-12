"""who answers a prompt.

one method. everything else - a cli, an http api, a canned file - is a detail
of whatever is implementing it, and the engine is not allowed to know.
"""


import os


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class Usage(object):
    """the tokens one call was counted at, by whoever answered it.

    `raw` is the block exactly as the provider sent it. the totals beside it
    are the OpenTelemetry GenAI ones (`gen_ai.usage.*`): there `input_tokens`
    INCLUDES the tokens read from and written to the cache, and anthropic's own
    `input_tokens` does not, so the two numbers named the same thing differ by
    the whole cache. cache read and cache write are parts of the input total,
    never added to it again.
    """

    __slots__ = ("raw", "input_tokens", "output_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens", "reasoning_output_tokens")

    def __init__(self, raw):
        self.raw = raw
        self.cache_read_input_tokens = count(raw.get("cache_read_input_tokens"))
        self.cache_creation_input_tokens = count(
            raw.get("cache_creation_input_tokens"))
        self.input_tokens = (count(raw.get("input_tokens"))
                             + self.cache_read_input_tokens
                             + self.cache_creation_input_tokens)
        self.output_tokens = count(raw.get("output_tokens"))
        thinking = (raw.get("output_tokens_details") or {}).get("thinking_tokens")
        self.reasoning_output_tokens = thinking if isinstance(thinking, int) else None

    @classmethod
    def of(cls, raw):
        """-> Usage, or None when there is no usage block to read."""
        return cls(raw) if isinstance(raw, dict) else None

    def as_otel(self):
        out = {"gen_ai.usage.input_tokens": self.input_tokens,
               "gen_ai.usage.output_tokens": self.output_tokens,
               "gen_ai.usage.cache_read.input_tokens": self.cache_read_input_tokens,
               "gen_ai.usage.cache_creation.input_tokens":
                   self.cache_creation_input_tokens}
        if self.reasoning_output_tokens is not None:
            out["gen_ai.usage.reasoning.output_tokens"] = self.reasoning_output_tokens
        return out


class Reply(object):
    """what came back, and what it cost.

    `usage`, `cost`, `session` and `model` are None when the provider did not
    say, which is not the same as zero: a provider that reports nothing has to
    be estimated, and a zero would read as free. `cost` is in USD as the
    provider stated it. `retryable` is the provider's own word on whether going
    again can help, None when it has none. `outage` is set when the account's
    own limit refused the call: when the provider said it resets, or
    "unknown".
    """

    __slots__ = ("text", "cached", "detail", "usage", "cost", "session", "model",
                 "retryable", "outage")

    def __init__(self, text, cached=False, detail="", usage=None, cost=None,
                 session=None, model=None, retryable=None, outage=None):
        self.text = text
        self.cached = cached
        self.detail = detail
        self.usage = usage
        self.cost = cost
        self.session = session
        self.model = model
        self.retryable = retryable
        self.outage = outage

    def __bool__(self):
        return bool(self.text)

    @property
    def counted(self):
        return self.usage is not None


def env_for(tier):
    """the variable a tier reads. `high` -> MODEL_HIGH."""
    return "MODEL_" + tier.upper()


def model_for(opts):
    """the id it was given, then the tier's id, then the one model there is.

    a named model wins because naming one has already answered the question
    a tier asks. either way the id lives in the environment: a tier buys a
    second place to look, not a place to write a version string down.
    """
    named = opts.get("model")
    if named:
        return named
    tier = opts.get("tier")
    if tier:
        return os.environ.get(env_for(tier), "") or os.environ.get("MODEL", "")
    return os.environ.get("MODEL", "")


def again(status):
    """-> whether an http-style status is worth going again for."""
    if not isinstance(status, int) or isinstance(status, bool):
        return None
    return status in (408, 409, 429) or status >= 500


class Provider(object):
    name = "provider"
    reads_place = False
    where = None
    command = None

    def __init__(self, **opts):
        self.opts = opts

    def ask(self, prompt, timeout=None):
        raise NotImplementedError

    def asks_for(self):
        """-> the model id this provider sends with a prompt, None for none."""
        return None

    def check(self):
        """-> (ok, detail). is this thing usable right now."""
        return True, "no check implemented"


registry = {}


def register(cls):
    registry[cls.name] = cls
    return cls


def build(config, tier="", where=None):
    """the provider a step talks to, and which class of model it should ask for.

    the tier is not part of the provider block on purpose. the block says HOW
    to ask - which provider, which url, how many tokens - and the tier says
    what to ask FOR, and it is declared by whoever declared the step. a
    provider that has nothing to choose between ignores it.

    `where` is the run's place, and it is not in the block either: the flow
    file says who answers, the run says where. None is the directory this
    process was started in.
    """
    name = (config or {}).get("provider", "cli")
    if name not in registry:
        raise ValueError("unknown provider: " + str(name) + ". there is: "
                         + ", ".join(sorted(registry)))
    opts = dict(config or {})
    opts.pop("provider", None)
    if tier:
        opts["tier"] = tier
    p = registry[name](**opts)
    p.where = where
    return p
