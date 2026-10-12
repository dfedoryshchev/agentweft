import os

import httpx

from .base import Provider, Reply, Usage, again, env_for, model_for, register


@register
class ApiProvider(Provider):
    """http, no sdk. the model id comes from config or the environment and is
    never written down in here - a version string in the source is a thing that
    rots quietly."""

    name = "api"

    def _model(self):
        return model_for(self.opts)

    def ask(self, prompt, timeout=None):
        key = os.environ.get("API_KEY", "")
        if not key:
            return Reply("", detail="no API_KEY set")
        url = self.opts.get("url") or os.environ.get("API_URL", "")
        body = {"model": self._model(),
                "max_tokens": int(self.opts.get("max_tokens", 4096)),
                "messages": [{"role": "user", "content": prompt}]}
        try:
            # this was httpx.Timeout(timeout, read=None), which is a real
            # setting and means wait forever for the body. connect was honored,
            # so it never failed - it just never came back. the flow said 300
            # and meant 300 to answer the phone and unlimited to talk.
            r = httpx.post(url, json=body, timeout=httpx.Timeout(timeout),
                           headers={"x-api-key": key,
                                    "content-type": "application/json"})
        except httpx.HTTPError as e:
            lost = isinstance(e, (httpx.TimeoutException, httpx.NetworkError))
            return Reply("", detail=str(e)[:200], retryable=True if lost else None)
        if r.status_code >= 400:
            return Reply("", detail=str(r.status_code) + " " + r.text[:160],
                         retryable=again(r.status_code))
        data = r.json()
        parts = [b.get("text", "") for b in data.get("content", [])]
        return Reply("".join(parts), usage=Usage.of(data.get("usage")),
                     model=data.get("model") or None)

    def check(self):
        if not os.environ.get("API_KEY"):
            return False, "no API_KEY set"
        if not self._model():
            tier = self.opts.get("tier")
            if tier:
                return False, ("no model for tier " + tier + " (config, "
                               + env_for(tier) + " or MODEL)")
            return False, "no model configured (config or MODEL)"
        return True, self._model()
