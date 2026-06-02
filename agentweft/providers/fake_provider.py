from pathlib import Path

from .base import Provider, Reply, register


@register
class FakeProvider(Provider):
    """replays canned text.

    every test that touched a step used to monkeypatch subprocess.run, which
    meant the tests knew how the call was made. and anyone cloning this could
    not run a single example without a key, which is a bad first five minutes.
    """

    name = "fake"

    def ask(self, prompt, timeout=None):
        canned = self.opts.get("reply")
        if canned:
            return Reply(canned)
        path = self.opts.get("file")
        if path and Path(path).exists():
            return Reply(Path(path).read_text(encoding="utf-8"))
        return Reply(self.opts.get("default", "VERDICT: ok\n\nnothing to report\n"))

    def check(self):
        return True, "fake, answers without asking anything"
