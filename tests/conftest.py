import ipaddress
import socket
import subprocess
import sys
import types
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, ".")
from agentweft.providers import cli_provider
from agentweft.runner import handoff, state


GOLDEN = Path(__file__).resolve().parent / "golden"
REWRITES = pytest.StashKey[list]()


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="append", nargs="?", const="",
                     default=None, metavar="FLOW/PATH",
                     help="write the goldens in tests/golden/ that do not "
                          "exist yet; an existing one is rewritten only when "
                          "named, as flow/path (repeat it or join with ,)")


def golden_names(given):
    """-> None when --update-golden was not passed, else the goldens it
    names, empty for a bare --update-golden."""
    if given is None:
        return None
    return frozenset(n.strip() for v in given for n in v.split(",")
                     if n.strip())


def unknown_goldens(names, folder):
    return sorted(n for n in names if not (folder / (n + ".json")).is_file())


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: the test may open connections beyond loopback")
    config.stash[REWRITES] = []
    unknown = unknown_goldens(
        golden_names(config.getoption("--update-golden")) or frozenset(),
        GOLDEN)
    # a path given after a bare --update-golden is read as its value
    if unknown:
        raise pytest.UsageError(
            "--update-golden names no golden in tests/golden/: "
            + ", ".join(unknown) + ". a missing golden is written without "
            "a name; put a test path before --update-golden")


def pytest_terminal_summary(terminalreporter, config):
    said = config.stash.get(REWRITES, [])
    if said:
        terminalreporter.section("goldens")
        for line in said:
            terminalreporter.write_line(line)


@pytest.fixture
def update_golden(request):
    return golden_names(request.config.getoption("--update-golden"))


@pytest.fixture
def golden_said(request):
    return request.config.stash[REWRITES]


def refuse(what):
    def refused(*args, **kw):
        pytest.fail(what + " was called from a test. a test talks to the fake "
                    "provider, or patches this itself.")
    return refused


@pytest.fixture(autouse=True, scope="session")
def no_real_provider():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "post", refuse("httpx.post"))
        # the provider's own name for the module, not subprocess.run itself:
        # the mcp client, the mcp server and the command gate spawn processes
        # on purpose and share that module.
        mp.setattr(cli_provider, "subprocess", types.SimpleNamespace(
            run=refuse("the cli provider's subprocess.run"),
            Popen=refuse("the cli provider's subprocess.Popen"),
            TimeoutExpired=subprocess.TimeoutExpired))
        # a go that timed out looks for its transcript among the cli's own
        # sessions, and a test is never handed the machine's
        mp.setattr(handoff, "PROJECTS", "no-such-projects-folder")
        yield


def is_loopback(address):
    if not isinstance(address, tuple):
        return True
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


NETWORK = {"allowed": False}


def guarded(real):
    def connect(sock, address):
        if not NETWORK["allowed"] and not is_loopback(address):
            pytest.fail("a test opened a connection to %s:%s. a test stays on "
                        "loopback, or is marked network." % address[:2])
        return real(sock, address)
    return connect


@pytest.fixture(autouse=True, scope="session")
def no_network():
    with pytest.MonkeyPatch.context() as mp:
        for name in ("connect", "connect_ex"):
            mp.setattr(socket.socket, name,
                       guarded(getattr(socket.socket, name)))
        yield


@pytest.fixture(autouse=True, scope="session")
def not_on_ci():
    # pytest prints a longer failure summary when CI or BUILD_NUMBER is set,
    # so the tail a failed gate quotes would differ on a ci runner
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("CI", raising=False)
        mp.delenv("BUILD_NUMBER", raising=False)
        yield


@pytest.fixture(autouse=True)
def network_when_marked(request):
    NETWORK["allowed"] = request.node.get_closest_marker("network") is not None
    yield
    NETWORK["allowed"] = False


@pytest.fixture(autouse=True, scope="session")
def scores_kept_aside(tmp_path_factory):
    """a bench or an eval a test runs keeps its records in a file of the
    session's, never in the repo's own bench/scores.jsonl."""
    from agentweft.bench import history

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(history, "SCORES",
                   [tmp_path_factory.mktemp("kept") / "scores.jsonl"])
        yield


def answering(run):
    """-> a `cli_provider.call` that hands each call to a fake shaped like
    `subprocess.run`, for the tests that answer without a process."""
    def call(argv, stdin=None, cwd=None, timeout=None, done=None, env=None):
        try:
            r = run(argv, input=stdin, capture_output=True, encoding="utf-8",
                    errors="replace", cwd=cwd, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return cli_provider.Ran(None, "", "", 0, timed_out=True)
        return cli_provider.Ran(r.returncode, r.stdout, r.stderr, 0)
    return call


LOCALE = "cp1252"


def as_the_locale_would(kw):
    """-> (encoding, errors) a text-mode call ends up with when it names none.

    what a Windows machine set to cp1252 does, made deterministic: changing the
    real locale from inside a test is not something a test can do.
    """
    return kw.get("encoding") or LOCALE, kw.get("errors") or "strict"


class FakeCli(object):
    """stands in for `subprocess.run` behind the cli provider.

    it answers with bytes, the way a real process does, and turns them into
    text the way subprocess would on a cp1252 machine. so a call that does not
    name its encoding gets what that machine would give it.
    """

    VERSION = (0, b"2.1.296 (Claude Code)\n", b"")
    LOGGED_IN = (0, b'{"loggedIn": true, "authMethod": "claude.ai"}\n', b"")

    def __init__(self, *answers):
        self.answers = list(answers) or [(0, b"ok", b"")]
        self.calls = []
        self.asides = []
        self.version = self.VERSION
        self.auth = self.LOGGED_IN

    def run(self, argv, **kw):
        text = kw.get("text") or kw.get("encoding")
        enc, errors = as_the_locale_would(kw)
        aside = {("--version",): self.version,
                 ("auth", "status"): self.auth}.get(tuple(argv[1:3]))
        if aside is not None:
            self.asides.append(list(argv))
            code, out, err = aside
            if text:
                out, err = out.decode(enc, errors), err.decode(enc, errors)
            return types.SimpleNamespace(returncode=code, stdout=out,
                                         stderr=err)
        sent = kw.get("input")
        if text and sent is not None:
            sent = sent.encode(enc, errors)
        self.calls.append({"argv": list(argv), "stdin": sent, "kw": kw})
        code, out, err = self.answers.pop(0) if len(self.answers) > 1 \
            else self.answers[0]
        if isinstance(code, BaseException):
            raise code
        if text:
            out = out.decode(enc, errors).replace("\r\n", "\n")
            err = err.decode(enc, errors).replace("\r\n", "\n")
        return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)

    def install(self, monkeypatch):
        monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
            run=self.run, TimeoutExpired=subprocess.TimeoutExpired))
        monkeypatch.setattr(cli_provider, "call", answering(self.run))
        return self


@pytest.fixture
def fake_cli(monkeypatch):
    """-> a function taking (exit code, stdout bytes, stderr bytes) answers,
    in order, and putting a FakeCli behind the cli provider."""
    return lambda *answers: FakeCli(*answers).install(monkeypatch)


@pytest.fixture
def cp1252(monkeypatch):
    """the file and process defaults of a cp1252 machine, for the code that
    reads and writes run files and spawns gate commands."""
    import builtins
    import pathlib

    from agentweft.guardrails.gates import command_gate, redtest_gate
    from agentweft.runner import engine

    real_open = builtins.open

    def local_open(file, mode="r", *a, **kw):
        if "b" not in mode and not a and "encoding" not in kw:
            kw["encoding"] = LOCALE
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(engine, "open", local_open, raising=False)

    real_read, real_write = pathlib.Path.read_text, pathlib.Path.write_text

    def read_text(self, encoding=None, errors=None, **kw):
        return real_read(self, encoding=encoding or LOCALE, errors=errors, **kw)

    def write_text(self, data, encoding=None, errors=None, **kw):
        return real_write(self, data, encoding=encoding or LOCALE, errors=errors,
                          **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(pathlib.Path, "write_text", write_text)

    real_run = subprocess.run

    def local_run(argv, **kw):
        if kw.get("text") and not kw.get("encoding"):
            kw["encoding"] = LOCALE
        return real_run(argv, **kw)

    for module in (command_gate, redtest_gate):
        monkeypatch.setattr(module, "subprocess", types.SimpleNamespace(
            run=local_run, TimeoutExpired=subprocess.TimeoutExpired))
    return LOCALE


@pytest.fixture(autouse=True)
def runs_and_state_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
