import runpy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.runner import cli, prompts

REPO = Path(__file__).resolve().parent.parent


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


@pytest.fixture
def flow_root():
    """FLOW_ROOT is one list shared by reference, so it is put back by hand."""
    was = prompts.FLOW_ROOT[0]
    yield prompts.FLOW_ROOT
    prompts.FLOW_ROOT[0] = was


def from_run_py(argv, monkeypatch):
    """-> the exit code of run.py itself, argv and all."""
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(REPO / "run.py"), run_name="__main__")
    return e.value.code


def test_show_reads_the_flows_folder_it_is_given(capsys, monkeypatch,
                                                 flow_root):
    code = from_run_py(["run.py", "show", "risky-edit", "--flows",
                        str(REPO / "tests" / "flows")], monkeypatch)
    assert code == 0
    assert capsys.readouterr().out.startswith("risky-edit\n")


def test_show_of_a_flow_that_is_not_there_says_so(capsys):
    assert run(["run.py", "show", "no-such-flow"]) == 1
    assert "no flow called no-such-flow" in capsys.readouterr().out


def test_the_provider_check_says_each_provider_once(tmp_path, capsys,
                                                     flow_root):
    """a block that names the default provider and one that leaves it out
    build the same thing."""
    for name, block in (("bare", "provider:\n  command: python\n"),
                        ("named", "provider:\n  provider: cli\n"
                                  "  command: python\n")):
        d = tmp_path / name
        d.mkdir()
        (d / "flow.yaml").write_text(
            "name: " + name + "\nsteps:\n  - role: worker\n"
            "    prompt: worker.md\n" + block, encoding="utf-8")
        (d / "worker.md").write_text("# worker\n", encoding="utf-8")
    flow_root[0] = str(tmp_path)
    assert cli.cmd_provider() == 0
    lines = [l for l in capsys.readouterr().out.split("\n") if l.strip()]
    assert len(lines) == 1 and " cli " in lines[0]


def test_vocab_prints_the_two_vocabularies(capsys):
    assert run(["run.py", "vocab"]) == 0
    out = capsys.readouterr().out
    assert "one idea, two names" in out
    assert "step.gates" in out and "phase.gate" in out
