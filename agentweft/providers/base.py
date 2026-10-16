"""who answers a prompt.

one method. everything else - a cli, an http api, a canned file - is a detail
of whatever is implementing it, and the engine is not allowed to know.
"""


import os

from agentweft.flow.spec import LEVELS


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

    `requests` is how many requests the block sums, None when the provider
    did not say: the claude cli reports one block for a whole session.
    """

    __slots__ = ("raw", "input_tokens", "output_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens", "reasoning_output_tokens",
                 "requests")

    def __init__(self, raw, requests=None):
        self.raw = raw
        self.requests = requests
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
    def of(cls, raw, requests=None):
        """-> Usage, or None when there is no usage block to read."""
        return cls(raw, requests) if isinstance(raw, dict) else None

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
    "unknown". `models` is the usage per model when more than one answered,
    None otherwise. `killed` is how many processes the call left running that
    were ended with it, None when it started none or could not tell.

    `metered` is None when what the reply says it used came with the answer.
    a go that never answered says where its figure came from instead:
    "transcript" when its usage was read back from what the session wrote
    down, "estimate" when there was nothing to read and `guess` input tokens
    were worked out from the length of the prompt.

    `writes` is {path: content} for the files a scripted answer left in the
    place, None for an answer that left none.

    `kept` is what the session this call wrote has used as a whole, for a
    call made to be carried on: {"usage": the raw block, "models": the raw
    per-model block, "cost"}. None for a call that keeps no session.
    """

    __slots__ = ("text", "cached", "detail", "usage", "cost", "session", "model",
                 "retryable", "outage", "models", "killed", "metered", "guess",
                 "writes", "kept")

    def __init__(self, text, cached=False, detail="", usage=None, cost=None,
                 session=None, model=None, retryable=None, outage=None,
                 models=None, killed=None, metered=None, guess=None,
                 writes=None, kept=None):
        self.kept = kept
        self.writes = writes
        self.text = text
        self.cached = cached
        self.detail = detail
        self.usage = usage
        self.cost = cost
        self.session = session
        self.model = model
        self.retryable = retryable
        self.outage = outage
        self.models = models
        self.killed = killed
        self.metered = metered
        self.guess = guess

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


# a step that was sent back is raised this far and no further. `max` is only
# ever asked for by name.
CEILING = "xhigh"

# an answer that came back whole as far as the http status goes, and is not
CUT = {"max_tokens": "the answer was cut off at its token cap "
                     "(stop_reason max_tokens)",
       "refusal": "the model declined to answer (stop_reason refusal)"}


# thinking is spent inside the cap, so a level that thinks longer gets a cap
# that leaves room to answer after it
TOKENS = 32000
DEEP_TOKENS = 64000
DEEP = ("high", "xhigh", "max")
# a terse step keeps this share of that cap: room to think, none for an essay
TERSE_SHARE = 4


def cap_for(effort):
    """-> the token cap a call at `effort` is given when nothing names one."""
    return DEEP_TOKENS if effort in DEEP else TOKENS


def effort_env_for(tier):
    """the variable a tier's effort reads. `high` -> EFFORT_HIGH."""
    return "EFFORT_" + tier.upper()


def effort_for(opts):
    """the level the provider block names, then the tier's, then the one
    level there is, or "" for none: the provider's own default answers."""
    named = opts.get("effort")
    if named:
        return named
    tier = opts.get("tier")
    if tier:
        return os.environ.get(effort_env_for(tier), "") \
            or os.environ.get("EFFORT", "")
    return os.environ.get("EFFORT", "")


def effort_said(p, default="provider default"):
    """-> what `python run.py provider` says about p's effort."""
    return "effort " + (p.asks_effort() or default)


def raised(level, times):
    """-> `level` raised `times` levels, stopping at CEILING. a level at or
    above the ceiling, or one this does not know, is left as it is."""
    if not times or level not in LEVELS:
        return level
    i, top = LEVELS.index(level), LEVELS.index(CEILING)
    if i >= top:
        return level
    return LEVELS[min(i + times, top)]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def less(now, then):
    """-> `now` with what `then` already counted taken out, number by number
    and through nested blocks; None when any count in `now` is below its
    own in `then`, which a running total never is."""
    if not isinstance(now, dict):
        return now
    then = then if isinstance(then, dict) else {}
    out = {}
    for key, value in now.items():
        was = then.get(key)
        if isinstance(value, dict):
            value = less(value, was)
            if value is None:
                return None
        elif number(value) and number(was):
            if value < was:
                return None
            value = value - was
        out[key] = value
    return out


def carry_of(kept):
    """-> the carry for a call that goes on from `kept`, a session the runner
    noted down."""
    return {"from": kept["id"], "usage": kept.get("usage"),
            "models": kept.get("models"), "cost": kept.get("cost")}


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
    grant = None
    denials = None
    # the level the runner settled on for the call about to be made
    going = None
    # whether the step about to ask said `verbosity: terse`
    terse = False

    # the session the call about to be made carries on: None for a call that
    # keeps none, else {"from": the session's id or None to start one, and
    # what it had used as a whole: "usage", "models", "cost"}
    carry = None

    def __init__(self, **opts):
        self.opts = opts

    def granted(self):
        """-> what the run record keeps about the step's grant: None when the
        step declared none, else the grant and whether anything below this
        process was handed it. here nothing was; a provider that passes it on
        says so itself."""
        if self.grant is None:
            return None
        return {"tools": list(self.grant), "enforced": False, "argv": None,
                "cli_version": None,
                "shell_writes": "not enforced" if "shell" in self.grant
                else None}

    def refuses(self):
        """-> why a step on this provider may not be asked at all, or ""."""
        return ""

    def ask(self, prompt, timeout=None):
        raise NotImplementedError

    def at(self, step, task):
        """the step about to ask, and the task when it is fanned out. only a
        recording has any use for it."""

    def asks_for(self):
        """-> the model id this provider sends with a prompt, None for none."""
        return None

    def chooses_model(self):
        """-> whether a model asked for by name or tier can reach the call."""
        return False

    def asks_effort(self):
        """-> the effort level this provider sends with a prompt, None for
        none."""
        return self.going or self.own_effort() or None

    def own_effort(self):
        """-> the level this provider's config sets, "" for none."""
        return effort_for(self.opts)

    def chooses_effort(self):
        """-> whether an effort level can reach the call."""
        return False

    def output_limit(self):
        """-> the token cap a terse step's answer is held to, None when the
        step is not terse or this provider cannot hold an answer to one."""
        return None

    def continues(self):
        """-> whether a call can carry an earlier session on."""
        return False

    def holds(self, session):
        """-> whether `session` can be carried on from here."""
        return False

    def check(self):
        """-> (ok, detail). is this thing usable right now."""
        return True, "no check implemented"


registry = {}


def register(cls):
    registry[cls.name] = cls
    return cls


def build(config, tier="", where=None, grant=None):
    """the provider a step talks to, and which class of model it should ask for.

    the tier is not part of the provider block on purpose. the block says HOW
    to ask - which provider, which url, how many tokens - and the tier says
    what to ask FOR, and it is declared by whoever declared the step. a
    provider that has nothing to choose between ignores it.

    `where` is the run's place, and it is not in the block either: the flow
    file says who answers, the run says where. None is the directory this
    process was started in.

    `grant` is the step's `tools`, None when it declared none. it belongs to
    the step for the same reason the tier does, so a step with a grant gets a
    provider of its own.
    """
    from agentweft.runner import settings

    name = settings.get("provider", flow=config or {})
    if name not in registry:
        raise ValueError("unknown provider: " + str(name) + ". there is: "
                         + ", ".join(sorted(registry)))
    opts = dict(config or {})
    opts.pop("provider", None)
    if tier:
        opts["tier"] = tier
    p = registry[name](**opts)
    p.where = where
    p.grant = list(grant) if grant is not None else None
    return p
