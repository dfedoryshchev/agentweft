import os

import httpx

from .base import (CUT, Provider, Reply, Usage, again, effort_said, env_for,
                   model_for, register)

VERSION = "2023-06-01"

# thinking is spent inside the cap, so a level that thinks longer gets a cap
# that leaves room to answer after it
TOKENS = 32000
DEEP_TOKENS = 64000
DEEP = ("high", "xhigh", "max")


@register
class ApiProvider(Provider):
    """http, no sdk. the model id comes from config or the environment and is
    never written down in here - a version string in the source is a thing that
    rots quietly."""

    name = "api"

    def _model(self):
        return model_for(self.opts)

    def asks_for(self):
        return self._model() or None

    def chooses_model(self):
        return True

    def chooses_effort(self):
        return True

    def ask(self, prompt, timeout=None):
        key = os.environ.get("API_KEY", "")
        if not key:
            return Reply("", detail="no API_KEY set", retryable=False)
        url = self.opts.get("url") or os.environ.get("API_URL", "")
        effort = self.asks_effort()
        cap = DEEP_TOKENS if effort in DEEP else TOKENS
        body = {"model": self._model(),
                "max_tokens": int(self.opts.get("max_tokens", cap)),
                "messages": [{"role": "user", "content": prompt}]}
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
