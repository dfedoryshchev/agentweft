import sys

import httpx

sys.path.insert(0, ".")
import providers


def test_the_timeout_covers_read_not_just_connect(monkeypatch):
    seen = {}

    def fake_post(url, **kw):
        seen["timeout"] = kw["timeout"]
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("API_KEY", "x")
    monkeypatch.setenv("MODEL", "some-model")
    p = providers.build({"provider": "api"})
    p.ask("hello", timeout=30)

    t = seen["timeout"]
    # every phase, not just connect. the read one is what actually bit.
    assert t.connect == 30
    assert t.read == 30


def test_a_transport_error_is_a_detail_not_an_exception(monkeypatch):
    monkeypatch.setattr(httpx, "post",
                        lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))
    monkeypatch.setenv("API_KEY", "x")
    p = providers.build({"provider": "api"})
    reply = p.ask("hello", timeout=1)
    assert not reply
    assert "down" in reply.detail
