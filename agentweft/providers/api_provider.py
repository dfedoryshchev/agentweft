import os
import threading
import uuid

import httpx

from .base import (CUT, TERSE_SHARE, Provider, Reply, Usage, again, cap_for,
                   effort_said, env_for, model_for, register)

VERSION = "2023-06-01"

# a step that carries its session on marks the end of each prompt for the
# cache, with the long lifetime: its next go may be a whole step away
HOUR = {"type": "ephemeral", "ttl": "1h"}
WARM = "reply with the one word ok."
WARM_EFFORT = "low"
WARM_TOKENS = 256


def said(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


def marked(messages):
    """-> messages with the last block of the last one marked for the
    cache. the kept history stays unmarked, so the marks never pile up."""
    last = dict(messages[-1])
    blocks = [dict(b) for b in last["content"]]
    blocks[-1]["cache_control"] = HOUR
    last["content"] = blocks
    return list(messages[:-1]) + [last]


@register
class ApiProvider(Provider):
    """http, no sdk. the model id comes from config or the environment and is
    never written down in here - a version string in the source is a thing that
    rots quietly."""

    name = "api"

    def __init__(self, **opts):
        Provider.__init__(self, **opts)
        # the messages of each session a step can carry on, by id. they live
        # as long as this process: a run carried on in another one starts
        # the step afresh
        self.kept = {}
        self.lock = threading.Lock()

    def _model(self):
        return model_for(self.opts)

    def asks_for(self):
        return self._model() or None

    def chooses_model(self):
        return True

    def chooses_effort(self):
        return True

    def _cap(self, effort=None):
        return int(self.opts.get("max_tokens",
                                 cap_for(effort or self.asks_effort())))

    def output_limit(self):
        if not self.terse:
            return None
        return min(self._cap(), cap_for(self.asks_effort()) // TERSE_SHARE)

    def continues(self):
        return True

    def holds(self, session):
        with self.lock:
            return session in self.kept

    def history(self, carry):
        with self.lock:
            return list(self.kept.get(carry.get("from")) or [])

    def ask(self, prompt, timeout=None):
        carry = self.carry
        if carry is None:
            return self.post([{"role": "user", "content": prompt}], timeout)
        sent = self.history(carry) + [said("user", prompt)]
        reply = self.post(marked(sent), timeout)
        if reply:
            # a new id for every answer: the session carried on is left as
            # it was, so a go that fails goes again from the same point
            chosen = str(uuid.uuid4())
            with self.lock:
                self.kept[chosen] = sent + [said("assistant", reply.text)]
                # the runner goes on only from a step's newest session
                self.kept.pop(carry.get("from"), None)
            reply.session = chosen
            reply.kept = {"usage": reply.usage.raw if reply.usage else None,
                          "models": None, "cost": None}
        return reply

    def warm(self, carry, timeout=None, stop=None):
        before = self.history(carry)
        if not before:
            return None
        return self.post(marked(before + [said("user", WARM)]), timeout,
                         WARM_EFFORT, WARM_TOKENS)

    def post(self, messages, timeout, effort=None, cap=None):
        key = os.environ.get("API_KEY", "")
        if not key:
            return Reply("", detail="no API_KEY set", retryable=False)
        url = self.opts.get("url") or os.environ.get("API_URL", "")
        effort = effort or self.asks_effort()
        cap = cap or self.output_limit() or self._cap(effort)
        body = {"model": self._model(), "max_tokens": cap,
                "messages": messages}
        if effort:
            body["output_config"] = {"effort": effort}
        try:
            # this was httpx.Timeout(timeout, read=None), which is a real
            # setting and means wait forever for the body. connect was honored,
            # so it never failed - it just never came back. the flow said 300
            # and meant 300 to answer the phone and unlimited to talk.
            r = httpx.post(url, json=body, timeout=httpx.Timeout(timeout),
                           headers={"x-api-key": key,
                                    "anthropic-version": VERSION,
                                    "content-type": "application/json"})
        except httpx.HTTPError as e:
            lost = isinstance(e, (httpx.TimeoutException, httpx.NetworkError,
                                  httpx.RemoteProtocolError))
            return Reply("", detail=str(e)[:200], retryable=lost)
        if r.status_code >= 400:
            return Reply("", detail=str(r.status_code) + " " + r.text[:160],
                         retryable=again(r.status_code))
        data = r.json()
        said = dict(usage=Usage.of(data.get("usage"), requests=1),
                    model=data.get("model") or None)
        # a 200 that stopped at the cap or declined is not a whole answer
        cut = CUT.get(data.get("stop_reason"))
        if cut:
            return Reply("", detail=cut, retryable=False, **said)
        parts = [b.get("text", "") for b in data.get("content", [])]
        return Reply("".join(parts), **said)

    def check(self):
        if not os.environ.get("API_KEY"):
            return False, "no API_KEY set"
        if not self._model():
            tier = self.opts.get("tier")
            if tier:
                return False, ("no model for tier " + tier + " (config, "
                               + env_for(tier) + " or MODEL)")
            return False, "no model configured (config or MODEL)"
        return True, self._model() + ", " + effort_said(self)
