import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates


def test_a_zero_exit_passes():
    g = gates.build({"gate": "command", "command": [sys.executable, "-c", "pass"]})
    assert g.run("anything")


def test_a_nonzero_exit_fails_and_says_why():
    g = gates.build({"gate": "command",
                     "command": [sys.executable, "-c",
                                 "import sys; sys.stderr.write('nope'); sys.exit(3)"]})
    r = g.run("anything")
    assert not r
    assert "exit 3" in r.detail
    assert "nope" in r.detail


def test_expect_lets_you_want_a_failure():
    g = gates.build({"gate": "command", "expect": 1,
                     "command": [sys.executable, "-c", "raise SystemExit(1)"]})
    assert g.run("anything")


def test_the_output_reaches_the_command():
    g = gates.build({"gate": "command", "command": [
        sys.executable, "-c",
        "import sys; sys.exit(0 if 'needle' in open(sys.argv[1]).read() else 1)",
        "{file}"]})
    assert g.run("a needle in here")
    assert not g.run("nothing of interest")


def test_a_missing_binary_fails_rather_than_raising():
    g = gates.build({"gate": "command", "command": ["definitely-not-a-real-binary"]})
    r = g.run("x")
    assert not r
    assert "not on PATH" in r.detail
