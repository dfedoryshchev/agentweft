"""a flow says how many times the work can be sent back before a person is
asked, and a run that hits that number says which number it was."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import engine, router
from test_stops import CLAUDE, a_flow, answer, ends, steps_of, the_folder

LENGTH = "worker\ngates:\n  - gate: length\n    max_lines: 1"
REDO = answer("VERDICT: redo\n\nstill wrong\n")


def redos():
    return [(s["step"], s["outcome"]) for s in steps_of(the_folder())].count(
        ("reviewer.md", "redo"))


def stubborn(fake_cli):
    fake_cli(answer("done 1\n"), REDO, answer("done 2\n"), REDO,
             answer("done 3\n"), REDO)


def a_spec(**keys):
    raw = {"name": "f", "steps": [{"role": "worker"}, {"role": "reviewer"}]}
    raw.update(keys)
    return spec.load(raw)


def test_no_key_keeps_two_redos_and_one_gate_send_back():
    r = router.Router(a_spec())
    assert (r.cap, r.gate_cap("worker.md")) == (2, 1)


def test_the_key_sets_both_caps():
    r = router.Router(spec.FlowSpec({"steps": [{"role": "worker"}],
                                     "send_backs": 3}))
    assert (r.cap, r.gate_cap("worker.md")) == (3, 3)


@pytest.mark.parametrize("value", ["two", 1.5, True, -1, None])
def test_a_send_backs_that_is_not_a_count_is_refused_at_load(value):
    with pytest.raises(ValueError) as e:
        a_spec(send_backs=value)
    assert "send_backs should be a whole number, 0 or more" in str(e.value)


def test_a_gate_with_the_key_at_two_sends_the_step_back_twice(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated", [LENGTH, "reviewer"],
           tail="send_backs: 2\n" + CLAUDE)
    fake_cli(answer("one\ntwo\n"))
    assert engine.main() == 2
    walked = [(s["step"], s["outcome"], s["to"]) for s in steps_of(the_folder())]
    assert walked == [("worker.md", "gate failed", "worker.md")] * 2 \
        + [("worker.md", "gate failed", None)]
    [end] = ends()
    assert "worker.md was sent back 2 times already (send_backs: 2)" in end.why


def test_a_gate_with_the_key_at_zero_stops_on_the_first_failure(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated", [LENGTH, "reviewer"],
           tail="send_backs: 0\n" + CLAUDE)
    cli = fake_cli(answer("one\ntwo\n"))
    assert engine.main() == 2
    assert len(cli.calls) == 1
    [end] = ends()
    assert "not sent back (send_backs: 0)" in end.why


def test_a_redo_with_the_key_at_one_parks_after_one_trip(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "judged", ["worker", "reviewer"],
           tail="send_backs: 1\n" + CLAUDE)
    stubborn(fake_cli)
    engine.main()
    assert [e.status for e in ends()] == ["parked at reviewer.md"]
    assert redos() == 1
    [end] = ends()
    assert "gone back 1 time already (send_backs: 1)" in end.why


def test_a_redo_with_no_key_still_goes_back_twice(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "judged", ["worker", "reviewer"])
    stubborn(fake_cli)
    engine.main()
    assert redos() == 2
    [end] = ends()
    assert "gone back 2 times already (send_backs: 2)" in end.why
