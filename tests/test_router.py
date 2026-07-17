import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner.handoff import Handoff
from agentweft.runner.router import Router

OK = Handoff("reviewer", "VERDICT: ok", "ok")
REDO = Handoff("reviewer", "VERDICT: redo", "redo")


def route(flow):
    return Router(runner.config(flow), cap=2)


def test_a_straight_run_walks_the_list():
    r = route("summarise-and-check")
    assert r.first() == "worker.md"
    assert r.next("worker.md", OK) == "reviewer.md"
    assert r.next("reviewer.md", OK) is None


def test_a_redo_goes_back_to_the_worker():
    r = route("summarise-and-check")
    assert r.next("reviewer.md", REDO) == "worker.md"


def test_the_cap_binds():
    r = route("summarise-and-check")
    assert r.next("reviewer.md", REDO) == "worker.md"
    assert r.next("reviewer.md", REDO) == "worker.md"
    # third time it gives up and ends the run
    assert r.next("reviewer.md", REDO) is None


def test_on_redo_is_honoured_when_the_flow_declares_it():
    r = route("fix-with-test")
    assert r.next("verify.md", REDO) == "patcher.md"


def test_a_must_produce_step_is_gated():
    r = route("fix-with-test")
    bad = Handoff("worker", "here is a test", "ok")
    assert r.gate("worker.md", bad)
    good = Handoff("worker", "FAILS: boom" + chr(10) + "test...", "ok")
    assert r.gate("worker.md", good) is None
