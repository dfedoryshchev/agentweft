"""what a run is allowed to cost.

the digest is eight calls on a full inbox and a redo makes it twelve. i have
been running this for nine months with no idea what that adds up to, which is
fine right up until a prompt bug puts it in a loop.

a provider that says what a call used is charged exactly that, split the way
it said it. one that says nothing is charged an estimate from the length of
the text. the two are kept apart: a total with an estimate in it says so.

the fan-out charges one budget from every worker thread, so a charge is taken
whole or not at all: a total read by one thread and written back by it after
another has charged is a call that never happened.
"""
import threading


class OverBudget(Exception):
    pass


# rough, and deliberately so. i want an order of magnitude, not an invoice.
CHARS_PER_TOKEN = 4

# named after the OpenTelemetry GenAI usage attributes. `input` is the whole
# input, cache_read and cache_write INCLUDED, and `output` includes reasoning:
# those three are parts of the two totals and are never added to them again.
SPLIT = ("input", "output", "cache_read", "cache_write", "reasoning")


def plural(n, what):
    return str(n) + " " + what + ("" if n == 1 else "s")


class Budget(object):
    def __init__(self, max_calls=0, max_tokens=0):
        self.max_calls = int(max_calls or 0)
        self.max_tokens = int(max_tokens or 0)
        self.calls = 0
        self.by_provider = {}
        self.counted = dict.fromkeys(SPLIT, 0)
        self.counted_calls = 0
        self.estimated = 0
        self.estimated_calls = 0
        # failed goes the provider gave no usage for, by error kind. they are
        # charged as calls and as 0 tokens, which is not the same as free
        self.unreported = {}
        self.lock = threading.Lock()

    def charge(self, prompt, answer, provider="cli", error=None):
        """one go at a model.

        `answer` is the reply, or only its text when that is all there is.
        `error` is the kind of failure when the go failed, None when it
        answered.
        """
        with self.lock:
            return self._charge(prompt, answer, provider, error)

    def _charge(self, prompt, answer, provider, error):
        usage = getattr(answer, "usage", None)
        if usage is not None:
            self.counted["input"] += usage.input_tokens
            self.counted["output"] += usage.output_tokens
            self.counted["cache_read"] += usage.cache_read_input_tokens
            self.counted["cache_write"] += usage.cache_creation_input_tokens
            self.counted["reasoning"] += usage.reasoning_output_tokens or 0
            self.counted_calls += 1
        elif error:
            self.unreported[error] = self.unreported.get(error, 0) + 1
        else:
            text = getattr(answer, "text", answer) or ""
            self.estimated += (len(prompt) + len(text)) // CHARS_PER_TOKEN
            self.estimated_calls += 1
        self.calls += 1
        self.by_provider[provider] = self.by_provider.get(provider, 0) + 1
        return self

    @property
    def tokens(self):
        """what the token cap reads: everything counted plus the estimate."""
        return self.counted["input"] + self.counted["output"] + self.estimated

    def metered(self):
        """-> "counted", "estimated" or "mixed: N estimated calls"."""
        if self.counted_calls and self.estimated_calls:
            return "mixed: " + plural(self.estimated_calls, "estimated call")
        return "counted" if self.counted_calls else "estimated"

    def split(self, parts=True):
        c = self.counted
        n = c["input"] + c["output"]
        if not parts:
            return (str(n) + " counted: input " + str(c["input"])
                    + ", output " + str(c["output"]))
        inside = [k + " " + str(c[k]) for k in ("cache_read", "cache_write")
                  if c[k]]
        out = "input " + str(c["input"]) \
            + (" incl. " + " and ".join(inside) if inside else "")
        out = out + ", output " + str(c["output"]) \
            + (" incl. reasoning " + str(c["reasoning"]) if c["reasoning"]
               else "")
        return str(n) + " tokens counted (" + out + ")"

    def over(self):
        if self.max_calls and self.calls > self.max_calls:
            return "call cap: " + str(self.calls) + " > " + str(self.max_calls)
        if self.max_tokens and self.tokens > self.max_tokens:
            why = []
            if self.counted_calls:
                why.append(self.split(parts=False))
            if self.estimated_calls:
                why.append(("+ " if why else "") + "~" + str(self.estimated)
                           + " estimated")
            return ("token cap: " + str(self.tokens) + " > "
                    + str(self.max_tokens) + " (" + ", ".join(why) + ")")
        return None

    def summary(self):
        if not self.calls:
            return "0 calls, 0 tokens"
        out = plural(self.calls, "call") + ", "
        estimate = "~" + str(self.estimated) + " tokens estimated"
        if self.counted_calls and self.estimated_calls:
            out = (out + self.metered() + ", " + self.split()
                   + " + ~" + str(self.estimated) + " estimated")
        elif self.counted_calls:
            out = out + self.split()
        elif self.estimated_calls:
            out = out + estimate
        else:
            out = out + "0 tokens"
        failed = sum(self.unreported.values())
        if failed:
            out = (out + ", " + plural(failed, "failed call") + " charged 0 ("
                   + ", ".join(k + " x" + str(v)
                               for k, v in sorted(self.unreported.items()))
                   + ")")
        where = ", ".join(k + " x" + str(v)
                          for k, v in sorted(self.by_provider.items()))
        return out + (" (" + where + ")" if where else "")
