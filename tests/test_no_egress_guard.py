import sys

import pytest

sys.path.insert(0, ".")
from agentweft import providers


def test_the_api_provider_is_refused_under_the_guard(monkeypatch):
    monkeypatch.setenv("API_KEY", "x")
    p = providers.build({"provider": "api"})
    # DID NOT RAISE here would mean ask() stopped going through httpx.post -
    # the only seam the guard patches - and got past this test to a real
    # request instead of the guard's refusal.
    with pytest.raises(pytest.fail.Exception):
        p.ask("hello", timeout=1)


def test_the_cli_provider_is_refused_under_the_guard():
    p = providers.build({"provider": "cli"})
    with pytest.raises(pytest.fail.Exception):
        p.ask("hello", timeout=1)


def test_the_default_provider_is_refused_under_the_guard():
    p = providers.build({})
    with pytest.raises(pytest.fail.Exception):
        p.ask("hello", timeout=1)


# 192.0.2.1 is reserved for documentation and never routed, so a guard that
# stopped firing makes these time out rather than reach anyone.
FAR = ("192.0.2.1", 80)


def test_a_urllib_request_to_a_far_host_is_refused_under_the_guard():
    import urllib.request
    # no proxy: one on loopback would take the connection in the far host's
    # place, and loopback is allowed
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with pytest.raises(pytest.fail.Exception, match="192.0.2.1:80"):
        opener.open("http://%s:%d/" % FAR, timeout=1)


def test_a_raw_socket_to_a_far_host_is_refused_under_the_guard():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        with pytest.raises(pytest.fail.Exception, match="192.0.2.1:80"):
            s.connect(FAR)


def test_loopback_stays_open_under_the_guard():
    import errno
    import socket
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.socket() as s:
            # not waited on: this host's first connect in a process, past its
            # network filter, has taken over a second under load (and 2.8 s
            # once idle), while the guard decides before the real call starts
            s.setblocking(False)
            said = s.connect_ex(server.getsockname())
    assert said in (0, errno.EINPROGRESS, errno.EWOULDBLOCK,
                    getattr(errno, "WSAEWOULDBLOCK", errno.EWOULDBLOCK)), said


@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.8.8", "::1",
                                  "localhost"])
def test_the_guard_hands_a_loopback_connect_to_the_real_one(host):
    from conftest import guarded
    reached = []
    guarded(lambda sock, address: reached.append(address))(None, (host, 80))
    assert reached == [(host, 80)]


@pytest.mark.network
def test_a_test_marked_network_reaches_past_the_guard():
    from conftest import guarded
    reached = []
    # a recording connect in place of the real one: the marker is what is
    # under test here, not the network
    guarded(lambda sock, address: reached.append(address))(None, FAR)
    assert reached == [FAR]
