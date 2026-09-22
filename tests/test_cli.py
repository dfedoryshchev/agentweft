import sys

sys.path.insert(0, ".")
from agentweft.runner import cli


def run(argv):
    """call a command the way run.py does, with argv set up for it."""
    old = sys.argv
    sys.argv = argv
    try:
        return cli.COMMANDS[argv[1]]()
    finally:
        sys.argv = old


def test_show_without_a_flow_says_so(capsys):
    code = run(["run.py", "show"])
    assert code == 1
    assert "usage" in capsys.readouterr().out


def test_step_without_a_role_says_so(capsys):
    code = run(["run.py", "step", "weekly-digest"])
    assert code == 1
    assert "usage" in capsys.readouterr().out


def test_show_still_works_with_a_flow(capsys):
    assert run(["run.py", "show", "weekly-digest"]) == 0
    assert "weekly digest" in capsys.readouterr().out


def test_vocab_prints_the_two_vocabularies(capsys):
    assert run(["run.py", "vocab"]) == 0
    out = capsys.readouterr().out
    assert "one idea, two names" in out
    assert "step.gates" in out and "phase.gate" in out
