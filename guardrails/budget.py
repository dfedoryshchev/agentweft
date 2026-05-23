"""what a run is allowed to cost.

the digest is eight calls on a full inbox and a redo makes it twelve. i have
been running this for nine months with no idea what that adds up to, which is
fine right up until a prompt bug puts it in a loop.
"""


class OverBudget(Exception):
    pass


# rough, and deliberately so. i want an order of magnitude, not an invoice.
CHARS_PER_TOKEN = 4


class Budget(object):
    def __init__(self, max_calls=0, max_tokens=0):
        self.max_calls = int(max_calls or 0)
        self.max_tokens = int(max_tokens or 0)
        self.calls = 0
        self.tokens = 0
        self.by_provider = {}

    def charge(self, prompt, answer, provider="cli"):
        self.calls = self.calls + 1
        self.tokens = self.tokens + (len(prompt) + len(answer)) // CHARS_PER_TOKEN
        self.by_provider[provider] = self.by_provider.get(provider, 0) + 1
        return self

    def over(self):
        if self.max_calls and self.calls > self.max_calls:
            return "call cap: " + str(self.calls) + " > " + str(self.max_calls)
        if self.max_tokens and self.tokens > self.max_tokens:
            return "token cap: " + str(self.tokens) + " > " + str(self.max_tokens)
        return None

    def summary(self):
        where = ", ".join(k + " x" + str(v) for k, v in sorted(self.by_provider.items()))
        return (str(self.calls) + " calls, ~" + str(self.tokens) + " tokens"
                + (" (" + where + ")" if where else ""))
