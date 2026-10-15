import threading
from pathlib import Path

from .base import Provider, Reply, register


def write_into(where, writes):
    """leave each file of `writes` ({path: content}) in the place, the way a
    model working there would. a path that leads out of the place is refused
    before anything is written."""
    if not writes:
        return
    place = Path(where or ".").resolve()
    targets = []
    for name, content in writes.items():
        target = (place / name).resolve()
        if target != place and place not in target.parents:
            raise ValueError(str(name) + " is outside the place, so it was "
                             "not written")
        targets.append((target, content))
    for target, content in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(str(content).encode("utf-8"))


@register
class FakeProvider(Provider):
    """replays canned text.

    every test that touched a step used to monkeypatch subprocess.run, which
    meant the tests knew how the call was made. and anyone cloning this could
    not run a single example without a key, which is a bad first five minutes.

    `replies` answers each step from a list of its own, in order, the last
    one again once the list runs out. an answer there is the text or
    {say, writes}, and `writes` are files left in the place before the
    step's gates look at it.
    """

    name = "fake"

    def __init__(self, **opts):
        Provider.__init__(self, **opts)
        self.now = threading.local()
        self.gone = {}
        self.lock = threading.Lock()

    def at(self, step, task):
        self.now.step = step

    def scripted(self):
        replies = self.opts.get("replies") or {}
        step = getattr(self.now, "step", None)
        if step not in replies:
            return None
        listed = replies[step]
        if not isinstance(listed, list):
            listed = [listed]
        with self.lock:
            go = self.gone.get(step, 0)
            self.gone[step] = go + 1
        said = listed[min(go, len(listed) - 1)]
        if isinstance(said, dict):
            return said.get("say") or "", said.get("writes") or None
        return said, None

    def ask(self, prompt, timeout=None):
        scripted = self.scripted()
        if scripted is not None:
            text, writes = scripted
            write_into(self.where, writes)
            return Reply(text, writes=writes)
        canned = self.opts.get("reply")
        if canned:
            return Reply(canned)
        path = self.opts.get("file")
        if path and Path(path).exists():
            return Reply(Path(path).read_text(encoding="utf-8"))
        return Reply(self.opts.get("default", "VERDICT: ok\n\nnothing to report\n"))

    def check(self):
        return True, "fake, answers without asking anything"
