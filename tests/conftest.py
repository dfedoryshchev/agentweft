import subprocess
import sys
import types

import httpx
import pytest

sys.path.insert(0, ".")
from agentweft.providers import cli_provider
from agentweft.runner import handoff, state


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true", default=False,
                     help="write tests/golden/ from what the flows do now "
                          "instead of comparing against it")


@pytest.fixture
def update_golden(request):
    return request.config.getoption("--update-golden")


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


def answering(run):
    """-> a `cli_provider.call` that hands each call to a fake shaped like
    `subprocess.run`, for the tests that answer without a process."""
    def call(argv, stdin=None, cwd=None, timeout=None, done=None):
        try:
            r = run(argv, input=stdin, capture_output=True, encoding="utf-8",
                    errors="replace", cwd=cwd, timeout=timeout)
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
