import os

import httpx

from .base import Provider, Reply, register


@register
class ApiProvider(Provider):
    """http, no sdk. the model id comes from config or the environment and is
    never written down in here - a version string in the source is a thing that
    rots quietly."""

    name = "api"

    def _model(self):
        return self.opts.get("model") or os.environ.get("MODEL", "")

    def ask(self, prompt, timeout=None):
        key = os.environ.get("API_KEY", "")
        if not key:
            return Reply("", detail="no API_KEY set")
        url = self.opts.get("url") or os.environ.get("API_URL", "")
        body = {"model": self._model(),
                "max_tokens": int(self.opts.get("max_tokens", 4096)),
                "messages": [{"role": "user", "content": prompt}]}
        try:
            r = httpx.post(url, json=body, timeout=httpx.Timeout(connect=timeout),
                           headers={"x-api-key": key,
                                    "content-type": "application/json"})
        except httpx.HTTPError as e:
            return Reply("", detail=str(e)[:200])
        if r.status_code >= 400:
            return Reply("", detail=str(r.status_code) + " " + r.text[:160])
        data = r.json()
        parts = [b.get("text", "") for b in data.get("content", [])]
        return Reply("".join(parts))

    def check(self):
        if not os.environ.get("API_KEY"):
            return False, "no API_KEY set"
        if not self._model():
            return False, "no model configured (config or MODEL)"
        return True, self._model()
