"""the fan-out charges one budget from as many threads as it has workers.

a charge reads a total and writes it back one higher. two threads that both
read before either writes leave it one short, so the summary lies about where
the calls went and the cap fires late or not at all.

the interleave is forced, not waited for: the read is replaced by one that
holds every thread at a barrier until all of them have read. once charging is
serialised the first thread through can never meet the others there, so the
barrier times out once, breaks, and lets the rest straight past.
"""
import sys
import threading

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails.budget import Budget
from agentweft.runner import engine, prompts

NL = chr(10)
PLAN = "a.py | look at a" + NL + "b.py | look at b" + NL + "c.py | look at c" + NL
WIDTH = 3
WAIT = 0.5


class Held(dict):
    """a dict whose read waits until every charging thread has read too."""

    def __init__(self, parties, *args):
        dict.__init__(self, *args)
        self.barrier = threading.Barrier(parties, timeout=WAIT)

    def get(self, key, default=None):
        seen = dict.get(self, key, default)
        if threading.current_thread() is not threading.main_thread():
            try:
                self.barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return seen


def charge_together(b, n, **kw):
    threads = [threading.Thread(target=b.charge, args=("p" * 8, "a" * 8),
                                kwargs=kw) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_three_threads_count_three_calls_to_the_provider():
    b = Budget()
    b.by_provider = Held(3)
    charge_together(b, 3, provider="fake")
    assert b.calls == 3
    assert b.by_provider == {"fake": 3}
    assert b.summary().endswith("(fake x3)")


def test_three_failed_goes_from_three_threads_are_three_failed_goes():
    b = Budget()
    b.unreported = Held(3)
    charge_together(b, 3, provider="fake", error="transient")
    assert b.unreported == {"transient": 3}
    assert "3 failed calls charged 0 (transient x3)" in b.summary()


class HeldCalls(Budget):
    """`calls` read through a barrier: the interleave a build without the GIL
    can take inside `self.calls += 1` with nothing patched at all."""

    def __init__(self, *a, **kw):
        self.barrier = threading.Barrier(3, timeout=WAIT)
        self._calls = 0
        Budget.__init__(self, *a, **kw)

    @property
    def calls(self):
        seen = self._calls
        if threading.current_thread() is not threading.main_thread():
            try:
                self.barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return seen

    @calls.setter
    def calls(self, n):
        self._calls = n


def test_the_call_cap_sees_every_call_charged_from_three_threads():
    b = HeldCalls(max_calls=2)
    charge_together(b, 3, provider="fake")
    assert b.calls == 3
    assert b.over() == "call cap: 3 > 2"


# through the runner: a fan-out wider than the cap


def a_flow(tmp_path, name):
    root = tmp_path / "flows"
    d = root / name
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(
        "name: " + name + NL
        + "steps:" + NL
        + "  - role: planner" + NL
        + "    prompt: planner.md" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "    fanout: true" + NL
        + "    workers: " + str(WIDTH) + NL
        + "  - role: merge" + NL
        + "    prompt: merge.md" + NL
        + "journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL
        + "max_calls: 2" + NL, encoding="utf-8")
    (d / "instructions.md").write_text("do what you are given." + NL,
                                       encoding="utf-8")
    for role in ("planner", "worker", "merge"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return root


@pytest.mark.parametrize("order", [(1, 2, 3), (3, 2, 1)],
                         ids=["first-task-first", "last-task-first"])
def test_a_fanout_wider_than_the_cap_stops_at_one_count(tmp_path, monkeypatch,
                                                         order):
    name = "fan-cap"
    root = a_flow(tmp_path, name)
    asked = []
    made = []
    # each task's call returns only once the one before it in `order` has
    # returned, so the threads finish in exactly that order
    done = {i: threading.Event() for i in order}
    after = dict(zip(order[1:], order[:-1]))

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step != "worker.md":
            return "plan" + NL + PLAN if step == "planner.md" else "ok", False
        task = "abc".index(prompt.rsplit("look at ", 1)[1][0]) + 1
        if task in after:
            assert done[after[task]].wait(5)
        done[task].set()
        return "did " + str(task), False

    class Seen(Budget):
        def __init__(self, *a, **kw):
            Budget.__init__(self, *a, **kw)
            self.by_provider = Held(WIDTH)
            made.append(self)

    monkeypatch.setattr(engine, "Budget", Seen)
    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", name, "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()

    index = (tmp_path / "runs" / "index.md").read_text(encoding="utf-8")
    assert "OVER  fan-cap  call cap: 4 > 2" in index
    assert "merge.md" not in asked
    spent = made[0]
    assert (spent.calls, spent.by_provider) == (4, {"fake": 4})
    assert spent.summary().endswith("(fake x4)")
