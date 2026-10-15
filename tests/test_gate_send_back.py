"""a failed gate sends the step back once with what the gate said, then stops."""
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, router
from test_stops import a_flow, answer, ends, no_waiting, steps_of, the_folder

SAYS_TWO = ("import sys; sys.exit('still broken' if 'two' in "
            "open(sys.argv[1]).read() else 0)")
VERIFY = ('verify\ngates:\n  - gate: command\n    command: ["' + sys.executable
          .replace("\\", "/") + '", "-c", "' + SAYS_TWO + '", "{file}"]\n'
          "    expect: 0")
LENGTH = "worker\ngates:\n  - gate: length\n    max_lines: 1"


def sent(cli):
    return [c["stdin"].decode("utf-8", "replace") for c in cli.calls]


def test_a_verify_gate_failing_once_then_passing_finishes_the_run(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fix", ["worker", VERIFY])
    cli = fake_cli(answer("patched\n"), answer("one\ntwo\n"),
                   answer("one\n"))
    assert engine.main() == 0
    prompts = sent(cli)
    assert len(prompts) == 3
    assert prompts[2].rstrip().endswith("exit 1: still broken")
    assert "still broken" not in prompts[1]
    walked = [(s["step"], s["outcome"], s["to"])
              for s in steps_of(the_folder())]
    assert walked[1] == ("verify.md", "gate failed", "verify.md")
    assert walked[2][:2] == ("verify.md", "ok")


def test_an_always_failing_gate_stops_after_one_send_back_with_a_handoff(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated", [LENGTH, "reviewer"])
    cli = fake_cli(answer("one\ntwo\n"))
    assert engine.main() == 2
    assert len(cli.calls) == 2
    [end] = ends()
    assert (end.status, end.cause) == ("failed at worker.md", "gate failed")
    assert end.why.startswith("length: 2 lines, cap is 1")
    assert "sent back 1 time" in end.why
    handoff = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    assert "## needs you" in handoff


def test_a_transient_provider_failure_does_not_spend_the_send_back(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "gated", [LENGTH, "reviewer"])
    no_waiting(monkeypatch)
    cli = fake_cli((1, b"", b"connection reset by peer"),
                   answer("one\ntwo\n"), answer("one\n"), answer("VERDICT: ok\n"))
    assert engine.main() == 0
    assert len(cli.calls) == 4


BUGGY = "def add(a, b):\n    return a - b\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
PYTEST = '["' + sys.executable.replace("\\", "/") + '", "-m", "pytest", "-q", ' \
    '"-p", "no:cacheprovider", "{test}"]'
PROSE = ("add subtracts where it should add. change line 2 of calc.py to "
         "return a + b and the test will pass.\n")


def test_a_patcher_that_answers_in_prose_is_sent_back_once_then_stops(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fix",
           ["worker\ngates:\n  - gate: red-test\n    red: true\n"
            "    command: " + PYTEST,
            "patcher\non_redo: worker\ngates:\n  - gate: red-test\n"
            "    red: false\n    command: " + PYTEST])
    (tmp_path / "calc.py").write_text(BUGGY, encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(TEST, encoding="utf-8")
    cli = fake_cli(answer("FAILS: assert -1 == 3\nTEST: test_calc.py\n"),
                   answer(PROSE))
    assert engine.main() == 2
    prompts = sent(cli)
    assert len(prompts) == 3
    assert "# patcher" in prompts[2] and "# worker" not in prompts[2]
    tail = prompts[2][prompts[2].rindex("red-test"):]
    assert "1 failed" in tail
    [end] = ends()
    assert (end.status, end.cause) == ("failed at patcher.md", "gate failed")


def test_a_command_gate_keeps_the_end_of_what_it_printed(tmp_path):
    from agentweft.guardrails.gates import command_gate
    g = command_gate.CommandGate(command=[
        sys.executable, "-c", "import sys; sys.exit('x' * 300 + ' END')"])
    r = g.run("")
    assert not r.ok
    assert r.detail.endswith("x END")


def test_a_scored_run_sends_a_failed_gate_back_too(tmp_path, monkeypatch,
                                                   fake_cli):
    a_flow(tmp_path, monkeypatch, "gated", [LENGTH, "reviewer"])
    cli = fake_cli(answer("one\ntwo\n"), answer("one\n"), answer("VERDICT: ok\n"))
    out, _, stopped = engine.run_once("gated")
    assert (out, stopped) == ("VERDICT: ok\n", "")
    assert len(cli.calls) == 3


def test_the_send_back_cap_is_one_and_read_in_one_place():
    class Spec(object):
        steps = [{"role": "worker", "prompt": "worker.md"}]
    r = router.Router(Spec())
    assert hasattr(r, "gate_cap") and hasattr(r, "gate_back")
    assert r.gate_cap("worker.md") == 1
    assert r.gate_back("worker.md") == "worker.md"
    assert r.gate_back("worker.md") is None
