import datetime
import io
import json
import os
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates
from agentweft.runner import cli, engine, prompts, resume

# an en dash, which cp1252 has under another byte, and a CJK word, which it
# has no byte for at all
SAID = chr(0x2013) + " " + chr(0x6f22) + chr(0x5b57)


def answer(text):
    return (0, json.dumps({"type": "result", "is_error": False, "result": text,
                           "session_id": "s", "usage": {"input_tokens": 1,
                                                        "output_tokens": 1}},
                          ensure_ascii=False).encode("utf-8"), b"")


def a_flow(tmp_path, monkeypatch, gate=None):
    flow = tmp_path / "flows" / "wide"
    flow.mkdir(parents=True)
    for step in ("worker.md", "reviewer.md"):
        (flow / step).write_text("# step\n\ndo the thing.\n", encoding="utf-8")
    (flow / "instructions.md").write_text("two steps.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: wide\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "    tools: [read]\n"
        + ("    gates:\n      - gate: command\n        command: "
           + json.dumps(gate) + "\n" if gate else "")
        + "  - role: reviewer\n"
        "    prompt: reviewer.md\n"
        "timeout: 120\n"
        "provider:\n"
        "  provider: cli\n"
        "  command: claude\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "wide", "--force"])


def run_folder(tmp_path):
    return [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]


def test_an_answer_outside_cp1252_reaches_the_files_and_the_next_prompt(
        tmp_path, monkeypatch, fake_cli, cp1252):
    """the step file, the boundary note, the saved run and the next step's
    prompt all carry it as it was said, on a machine whose default is cp1252."""
    a_flow(tmp_path, monkeypatch)
    asked = fake_cli(answer("VERDICT: ok\n\n$ echo " + SAID + "\n"),
                     answer("VERDICT: ok\n\nsaw " + SAID + "\n"))
    engine.main()
    where = run_folder(tmp_path)
    assert SAID in (where / "worker.md").read_text(encoding="utf-8")
    assert SAID in (where / "boundary.md").read_text(encoding="utf-8")
    assert SAID in asked.calls[1]["stdin"].decode("utf-8")
    saved = [p for p in (tmp_path / "runs").iterdir() if p.suffix == ".md"
             and p.name.startswith("wide-")]
    assert SAID in saved[0].read_text(encoding="utf-8")
    assert "  wide  ok  " in (tmp_path / "runs" / "journal.md").read_text(
        encoding="utf-8")


# a Cyrillic letter as well: its second UTF-8 byte is one cp1252 has no
# character for, so that decode does not just garble it, it raises
CRASH = "crash: " + SAID + " " + chr(0x41d)
SHOUTS = ("import sys; sys.stdout.buffer.write('crash: \\u2013 \\u6f22\\u5b57 "
          "\\u041d'.encode('utf-8')); sys.exit(1)")


def test_a_gate_command_that_answers_outside_cp1252_is_written_down_intact(
        tmp_path, monkeypatch, fake_cli, cp1252):
    """the failing command's own words are the finding. decoding them as the
    machine's default turned them into something else, and they were the only
    copy."""
    a_flow(tmp_path, monkeypatch, gate=[sys.executable, "-c", SHOUTS])
    fake_cli(answer("VERDICT: ok\n\ndone\n"))
    engine.main()
    note = (run_folder(tmp_path) / "gates.md").read_text(encoding="utf-8")
    assert CRASH in note


def test_the_red_test_gate_reads_its_command_as_utf8(tmp_path, cp1252):
    g = gates.build({"gate": "red-test", "red": False,
                     "command": [sys.executable, "-c", SHOUTS.replace(
                         "sys.exit(1)", "sys.exit(2)")]},
                    where=tmp_path)
    r = g.run("patched it")
    assert not r
    assert CRASH in r.detail


def test_a_journal_line_outside_cp1252_is_written_and_read_back(cp1252,
                                                                capsys):
    """a flow named outside cp1252 could not be written down, and once it was,
    resume read it back as something that matched no flow."""
    name = "digest-" + SAID
    engine.journal(name, "failed at worker.md", datetime.datetime.now(),
                   run="digest-1", cause="no answer", spend="1 call",
                   why="nothing came out of worker.md")
    stop = resume.last_stop(name)
    assert stop is not None and stop.step == "worker.md"
    cli.cmd_spend()
    assert name in capsys.readouterr().out


def end_lines(tmp_path):
    text = (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")
    return [l for l in text.split("\n") if l and "  running  " not in l]


def test_an_answer_the_console_cannot_show_does_not_fail_a_finished_run(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch)
    fake_cli(answer("VERDICT: ok\n\nmoved " + SAID + "\n"))
    monkeypatch.setattr(sys, "stdout",
                        io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    assert engine.main() == 0
    [end] = end_lines(tmp_path)
    assert "  wide  ok  " in end


def test_a_run_that_breaks_after_its_last_step_writes_one_end_line(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch)
    fake_cli(answer("VERDICT: ok\n\nthe last words\n"))

    def shows(*args, **kw):
        if "the last words" in " ".join(str(a) for a in args):
            raise OSError("the console went away")
        print(*args, **kw)

    monkeypatch.setattr("agentweft.runner.ending.print", shows, raising=False)
    assert engine.main() == 2
    [end] = end_lines(tmp_path)
    assert "  exception  " in end


def test_the_env_file_is_read_as_utf8(tmp_path, monkeypatch, cp1252):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AW_SAID", "")
    (tmp_path / ".env").write_bytes(("AW_SAID=" + SAID + "\n").encode("utf-8"))
    engine.load_env()
    assert os.environ["AW_SAID"] == SAID


def test_a_piped_console_gets_utf8_bytes(monkeypatch):
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout",
                        io.TextIOWrapper(raw, encoding="cp1252"))
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    engine.console()
    print(SAID)
    sys.stdout.flush()
    assert raw.getvalue().replace(b"\r\n", b"\n") == \
        (SAID + "\n").encode("utf-8")


def test_a_piped_run_on_an_ascii_locale_prints_utf8():
    import subprocess
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUTF8="0",
               PYTHONCOERCECLOCALE="0")
    env.pop("PYTHONIOENCODING", None)
    out = subprocess.run(
        [sys.executable, "-c", "from agentweft.runner import engine;"
         " engine.console(); print(" + ascii(SAID) + ")"],
        capture_output=True, env=env, cwd=os.getcwd()).stdout
    assert out.replace(b"\r\n", b"\n") == (SAID + "\n").encode("utf-8")
