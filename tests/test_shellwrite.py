"""a step granted a shell writes files with the write tool, not the shell."""
import importlib
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.guardrails import boundary
from agentweft.providers import cli_provider
from agentweft.runner import engine, handoff

from test_grant import claude, flag
from test_trace import a_flow, answer, folders, lines


def check():
    """the module, asserted rather than imported, so its absence is a failed
    test and not an error at collection."""
    found = importlib.util.find_spec("agentweft.guardrails.shellwrite")
    assert found is not None, "there is no shell-write check"
    return importlib.import_module("agentweft.guardrails.shellwrite")


def bash(command, session="s-1", tool="Bash", cwd=None):
    data = {"session_id": session, "hook_event_name": "PreToolUse",
            "tool_name": tool, "tool_input": {"command": command}}
    if cwd:
        data["cwd"] = str(cwd)
    return json.dumps(data)


def hook_of(argv):
    said = json.loads(flag(argv, "--settings"))
    assert "hooks" in said, "no hook handed to the cli"
    [entry] = said["hooks"]["PreToolUse"]
    [hook] = entry["hooks"]
    return entry["matcher"], hook


# the hook itself


def test_a_heredoc_into_a_file_is_refused_naming_write_and_noted(tmp_path):
    sw = check()
    denials = tmp_path / "tool-denials.jsonl"
    code, said = sw.decide([str(denials)],
                           bash("cat > notes.md <<EOF\na\\nb\nEOF\n",
                                cwd=tmp_path))
    assert code == 2
    assert "Write" in said and "Edit" in said
    [line] = [json.loads(l) for l in denials.read_text("utf-8").splitlines()]
    assert line["session"] == "s-1" and line["tool"] == "Bash"
    assert "notes.md" in line["refused"]


@pytest.mark.parametrize("command", [
    "echo x > out.txt",
    "printf 'a' >> calc.py",
    "cat <<'EOF' > calc.py\nimport os\nEOF",
    "echo hi | tee log.txt",
    "cp a.py b.py",
    "mv old.py new.py 2>/dev/null",
    "install -m 644 a b",
    "sed -i 's/a/b/' calc.py",
    "sed -Ei.bak 's/a/b/' calc.py",
    "perl -pi -e 's/a/b/' calc.py",
    "python -c \"open('calc.py', 'w').write('x')\"",
    "python3 -c \"import pathlib; pathlib.Path('a').write_text('x')\"",
    "python - <<EOF\nwith open('calc.py', 'a') as out:\n    out.write('x')\nEOF",
    "cd src && echo x > a.py",
    "FOO=1 echo x &> both.log",
])
def test_the_shells_write_shapes_are_refused(command, tmp_path):
    code, said = check().decide([], bash(command, cwd=tmp_path))
    assert code == 2, command
    assert "Write" in said


@pytest.mark.parametrize("command", [
    "Set-Content -Path calc.py -Value 'x'",
    "'x' | Out-File calc.py",
    "Add-Content calc.py 'x'",
    "[IO.File]::WriteAllText('calc.py', 'x')",
])
def test_powershells_writers_are_refused_too(command, tmp_path):
    code, _ = check().decide([], bash(command, tool="PowerShell",
                                      cwd=tmp_path))
    assert code == 2, command


@pytest.mark.parametrize("command", [
    "echo x > /dev/null",
    "git status 2>&1",
    "python -m pytest -q 2>&1 | tail -5",
    "echo oops >&2",
    "grep -n \">\" calc.py",
    "sed -n '1,5p' calc.py",
    "python -c \"print(open('calc.py').read())\"",
    "cat calc.py | head -3",
    "echo x > /tmp/scratch.txt",
    "echo x > \"$TMPDIR/scratch.txt\"",
    "# a note > not a redirect\ngit diff",
    "ls > $null",
    "perl -Mstrict -e 'print 1'",
])
def test_reading_and_the_sinks_pass(command, tmp_path):
    code, said = check().decide([], bash(command, cwd=tmp_path))
    assert (code, said) == (0, ""), command


PRODUCT_REWRITE = ("python - <<'EOF'\n"
                   "p='pkg/filters.py'\n"
                   "s=open(p,encoding='utf-8').read()\n"
                   "s=s.replace('''a\n''','''b\n''',1)\n"
                   "open(p,'w',encoding='utf-8',newline='\\n').write(s)\n"
                   "EOF\n"
                   "git diff --stat; python -m pytest -q tests 2>&1 | tail -3")


def test_a_python_heredoc_that_rewrites_a_product_file_is_refused(tmp_path):
    code, said = check().decide([], bash(PRODUCT_REWRITE, cwd=tmp_path))
    assert code == 2
    assert "Write tool" in said and "Edit" in said


def run_folder(tmp_path, monkeypatch):
    """-> (the denials file, the run's tmp), with the system's temp folder
    somewhere else, so only the run's tmp can let a write through."""
    elsewhere = str(tmp_path / "system-temp")
    monkeypatch.setattr(check().tempfile, "gettempdir", lambda: elsewhere)
    run = tmp_path / "runs" / "r-1"
    run.mkdir(parents=True)
    return run / "tool-denials.jsonl", run / "tmp"


@pytest.mark.parametrize("shape", [
    "cat > {0}/notes.txt <<'EOF'\na\nEOF",
    "printf 'x' >> {0}/out.log",
    "echo hi | tee {0}/seen.txt",
    "cp calc.py {0}/calc.py.orig",
])
def test_a_write_into_the_runs_own_tmp_passes(tmp_path, monkeypatch, shape):
    denials, scratch = run_folder(tmp_path, monkeypatch)
    place = tmp_path / "place"
    place.mkdir()
    command = shape.format(scratch.as_posix())
    assert check().decide([str(denials)], bash(command, cwd=place)) \
        == (0, ""), command


def test_a_climb_out_of_the_runs_tmp_is_refused(tmp_path, monkeypatch):
    denials, scratch = run_folder(tmp_path, monkeypatch)
    place = tmp_path / "place"
    place.mkdir()
    command = "echo x > " + scratch.as_posix() + "/../../calc.py"
    assert check().decide([str(denials)], bash(command, cwd=place))[0] == 2


@pytest.mark.parametrize("command", [
    "python -m pytest -q",
    "git commit -m 'add the option'",
    "git add pkg/a.py tests/test_a.py && git commit -m x",
    "cat pkg/a.py | grep -n def",
])
def test_the_work_a_step_runs_passes(command, tmp_path, monkeypatch):
    denials, _ = run_folder(tmp_path, monkeypatch)
    assert check().decide([str(denials)], bash(command, cwd=tmp_path)) \
        == (0, ""), command


def test_a_temp_path_that_climbs_back_out_is_refused(tmp_path):
    code, _ = check().decide([], bash("echo x > /tmp/../calc.py",
                                      cwd=tmp_path))
    assert code == 2


def test_an_append_to_a_tracked_file_is_refused_and_the_file_is_unchanged(
        tmp_path):
    kept = tmp_path / "calc.py"
    kept.write_bytes(b"def add(a, b):\n    return a + b\n")
    before = kept.read_bytes()
    code, _ = check().decide([], bash("echo '# more' >> calc.py",
                                      cwd=tmp_path))
    assert code == 2
    assert kept.read_bytes() == before


def test_input_it_cannot_read_is_refused_not_let_through():
    sw = check()
    assert sw.decide([], "this is not json")[0] == 2
    assert sw.decide([], json.dumps({"tool_name": "Bash",
                                     "tool_input": {}}))[0] == 2
    assert sw.decide([], bash("echo 'unclosed"))[0] == 2


def test_an_error_inside_the_check_refuses_the_call(monkeypatch):
    sw = check()

    def broken(command, cwd=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(sw, "writes", broken)
    code, said = sw.decide([], bash("ls"))
    assert code == 2 and "Write" in said


CALLS = json.loads((Path(__file__).parent / "shell_calls.json").read_text(
    encoding="utf-8").replace("SECTION SIGN", "\xa7"))


def lines_of(denials):
    if not denials.is_file():
        return []
    return [json.loads(l) for l in denials.read_text("utf-8").splitlines()]


@pytest.mark.parametrize("call", CALLS["read"], ids=lambda c: c["what"])
def test_a_recorded_command_the_shell_runs_and_that_writes_nothing_passes(
        call, tmp_path):
    denials = tmp_path / "tool-denials.jsonl"
    got = check().decide([str(denials)], bash(call["command"], cwd=tmp_path))
    assert got == (0, ""), call["what"]
    assert lines_of(denials) == []


@pytest.mark.parametrize("call", CALLS["refused"], ids=lambda c: c["what"])
def test_a_recorded_shell_write_stays_refused_and_noted(call, tmp_path):
    denials = tmp_path / "tool-denials.jsonl"
    code, said = check().decide([str(denials)],
                                bash(call["command"], cwd=tmp_path))
    assert code == 2, call["what"]
    assert "Write tool" in said
    [line] = lines_of(denials)
    assert line["refused"] and "unread" not in line


@pytest.mark.parametrize("command", [
    "echo \"$(cat > notes.txt)\"",
    "x=$(echo hi > out.txt)",
    "echo `tee log.txt < a`",
    "printf '%s' \"a\\\"b\" > calc.py",
    "echo $'it\\'s' > calc.py",
    "echo x > work\\out.txt",
])
def test_a_write_inside_a_substitution_or_after_an_escaped_quote_is_seen(
        command, tmp_path):
    code, said = check().decide([], bash(command, cwd=tmp_path))
    assert code == 2, command
    assert "Write tool" in said


@pytest.mark.parametrize("command", [
    "echo \"a \\\"quoted\\\" word\" | grep -c quoted",
    "echo \"$(git rev-parse HEAD)\" \"`date`\"",
    "printf %s $'tab\\there' | od -c",
    "type notes\\a.txt",
    "echo \"caf\xe9 \\\"x\\\"\" | head -1",
])
def test_quotes_escapes_and_substitutions_that_write_nothing_pass(command,
                                                                  tmp_path):
    assert check().decide([], bash(command, cwd=tmp_path)) == (0, ""), command


@pytest.mark.parametrize("command", [
    "echo a;>out.txt",
    "(echo a)>out.txt",
    "(cd sub && echo x)>out.txt",
    "true&&>out.txt",
    "echo a|>out.txt",
    "echo \"<<EOF\"\necho hi > out.txt",
    "echo '<<EOF'\necho hi > out.txt",
    "echo $((x<<y))\necho hi > out.txt",
    "bash -c 'echo a > out.txt'",
    "sh -c \"echo a > out.txt\"",
    "bash -lc 'cd sub && tee log.txt < a'",
    "zsh -c 'sed -i s/a/b/ calc.py'",
    "bash <<'EOF'\necho a > out.txt\nEOF",
    "sh -c 'echo \"$(cat > notes.txt)\"'",
])
def test_a_write_behind_joined_operators_a_quoted_marker_or_a_shell_c_is_seen(
        command, tmp_path):
    code, said = check().decide([], bash(command, cwd=tmp_path))
    assert code == 2, command
    assert "Write tool" in said


@pytest.mark.parametrize("command", [
    "echo a; ls -la",
    "(cd sub && ls)|head -3",
    "echo \"<<EOF\" | grep -c EOF",
    "bash -c 'git status 2>&1 | head -3'",
    "sh -c \"echo a > /dev/null\"",
    "bash -c 'python -m pytest -q'",
    "echo $(( 3 > 2 ))",
    "test $(( a << 2 )) -gt 3 && echo ok",
])
def test_joined_operators_quoted_markers_and_shell_c_that_write_nothing_pass(
        command, tmp_path):
    assert check().decide([], bash(command, cwd=tmp_path)) == (0, ""), command


def test_a_call_the_check_cannot_read_is_noted_as_unread(tmp_path):
    sw = check()
    denials = tmp_path / sw.FILE
    code, said = sw.decide([str(denials)], bash("echo 'unclosed",
                                                session="s-9"))
    assert code == 2 and "could not read" in said
    code, _ = sw.decide([str(denials)], "this is not json")
    assert code == 2
    first, second = lines_of(denials)
    assert first["session"] == "s-9" and first["unread"] == "ValueError"
    assert first["command"] == "echo 'unclosed" and not first["refused"]
    assert second["session"] is None and second["unread"] == "JSONDecodeError"
    assert sw.denied(tmp_path, {"s-9"}) == 1


def test_an_unreadable_call_with_no_denials_file_is_still_refused():
    assert check().decide([], bash("echo 'unclosed"))[0] == 2


def test_another_tool_is_not_its_business():
    code, _ = check().decide([], json.dumps({"tool_name": "Edit",
                                             "tool_input": {}}))
    assert code == 0


def test_the_script_refuses_by_exit_code_when_run_as_the_cli_runs_it(
        tmp_path):
    sw = check()
    denials = tmp_path / "tool-denials.jsonl"
    r = subprocess.run([sys.executable, "-I", sw.__file__, str(denials)],
                       input=bash("echo x > a.txt", cwd=tmp_path),
                       capture_output=True, encoding="utf-8", timeout=60)
    assert r.returncode == 2
    assert "Write tool" in r.stderr
    assert denials.is_file()
    ok = subprocess.run([sys.executable, "-I", sw.__file__, str(denials)],
                        input=bash("git status", cwd=tmp_path),
                        capture_output=True, encoding="utf-8", timeout=60)
    assert ok.returncode == 0 and ok.stderr == ""


# what the cli is handed


def test_a_step_granted_a_shell_gets_the_hook_in_its_settings(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    p = claude(grant=["read", "shell"])
    p.denials = Path("runs/r-1/tool-denials.jsonl")
    p.ask("run it")
    argv = cli_.calls[0]["argv"]
    matcher, hook = hook_of(argv)
    assert matcher == "Bash|PowerShell"
    assert hook["type"] == "command"
    assert hook["command"] == Path(sys.executable).as_posix()
    assert hook["args"][0] == "-I"
    assert hook["args"][1].endswith("guardrails/shellwrite.py")
    assert hook["args"][2] == "runs/r-1/tool-denials.jsonl"
    # the attribution stays off alongside it
    assert json.loads(flag(argv, "--settings"))["attribution"]["commit"] == ""


def test_the_hook_reaches_the_write_or_edit_tool_only_with_a_kept_file(
        fake_cli, tmp_path):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read", "edit", "write", "shell"]).ask("x")
    matcher, hook = hook_of(cli_.calls[0]["argv"])
    for tool in ("Edit", "Write", "NotebookEdit"):
        assert tool not in matcher.split("|")
    placed = claude(grant=["read", "edit", "write", "shell"])
    placed.where = tmp_path
    placed.ask("x")
    matcher, hook = hook_of(cli_.calls[1]["argv"])
    assert matcher.split("|")[:2] == ["Bash", "PowerShell"]
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert tool in matcher.split("|")
    assert "--keep" in hook["args"]


def test_a_step_granted_nothing_in_a_place_gets_the_shell_hook(fake_cli,
                                                                tmp_path):
    cli_ = fake_cli(answer("ok\n"))
    p = claude()
    p.where = tmp_path
    p.ask("x")
    matcher, _ = hook_of(cli_.calls[0]["argv"])
    assert matcher.split("|")[:2] == ["Bash", "PowerShell"]
    assert p.refuses_shell_writes()


def test_a_run_that_opts_into_the_trailer_still_gets_the_hook(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["shell"], co_author=True).ask("x")
    assert "--settings" in cli_.calls[0]["argv"]
    said = json.loads(flag(cli_.calls[0]["argv"], "--settings"))
    assert "attribution" not in said and "hooks" in said


def test_a_step_without_a_shell_gets_no_shell_hook(fake_cli, tmp_path):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read", "edit"]).ask("x")
    claude(grant=["read"]).ask("x")
    claude().ask("x")
    for call in cli_.calls:
        assert "hooks" not in json.loads(flag(call["argv"], "--settings"))
    placed = claude(grant=["read", "edit"])
    placed.where = tmp_path
    placed.ask("x")
    matcher, _ = hook_of(cli_.calls[-1]["argv"])
    assert "Bash" not in matcher.split("|")


def test_the_record_says_whether_shell_writes_were_refused(fake_cli):
    fake_cli(answer("ok\n"))
    assert claude(grant=["read", "shell"]).granted().get("shell_writes") \
        == "refused"
    assert claude(grant=["read"]).granted().get("shell_writes", "unsaid") \
        is None
    other = providers.build({"provider": "cli", "command": "echo"},
                            grant=["shell"])
    assert other.granted().get("shell_writes") == "not enforced"
    assert "--settings" not in other.argv("x")[0]


# the prompt


def test_the_prompt_says_shell_writes_are_refused_when_they_are():
    assert "shell_writes" in inspect.signature(boundary.as_prompt).parameters
    said = boundary.as_prompt(["read", "shell", "edit"], shell_writes="refused")
    assert "refused" in said and "Edit" in said
    loose = boundary.as_prompt(["read", "shell"], shell_writes="not enforced")
    assert "refused" not in loose


def test_a_step_that_writes_is_told_the_write_tools_escape_trap():
    said = boundary.as_prompt(["read", "write"])
    assert "U+2028" in said
    assert "U+2028" not in boundary.as_prompt(["read", "shell"])


# a run


def refusing(cli_, monkeypatch, session):
    """every claude call with the hook refuses one write, as the cli would
    when the model tries one."""
    real = cli_provider.call

    def call(argv, **kw):
        if "--settings" in argv:
            said = json.loads(flag(argv, "--settings"))
            if "hooks" in said:
                path = said["hooks"]["PreToolUse"][0]["hooks"][0]["args"][2]
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"session": session,
                                        "refused": "echo x > a"}) + "\n")
        return real(argv, **kw)

    monkeypatch.setattr(cli_provider, "call", call)


def test_a_run_counts_the_refused_writes_on_the_steps_line(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "shelled",
           ["worker\ntools: [read, shell]", "reviewer"])
    cli_ = fake_cli(answer("did it\n", session="s-1"),
                    answer("VERDICT: ok\n\nfine\n", session="s-2"))
    refusing(cli_, monkeypatch, "s-1")
    engine.main()
    [folder] = folders(tmp_path)
    first, second = lines(folder)
    assert first.get("shell_writes_denied") == 1
    assert second.get("shell_writes_denied", "unsaid") == 0
    _, hook = hook_of(cli_.calls[0]["argv"])
    assert Path(hook["args"][2]) == folder / "tool-denials.jsonl"


def test_a_step_granted_nothing_has_its_refused_writes_counted(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "open", ["worker"])
    cli_ = fake_cli(answer("did it\n", session="s-1"))
    refusing(cli_, monkeypatch, "s-1")
    engine.main()
    [line] = lines(folders(tmp_path)[0])
    assert line["grant"] is None
    assert line.get("shell_writes_denied") == 1


def transcript(home, session, said):
    d = home / "a-project"
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "message": {"role": "user", "content": "go"}}]
    for n, text in enumerate(said):
        rows.append({"type": "assistant", "sessionId": session,
                     "message": {"id": "m-" + str(n), "role": "assistant",
                                 "content": [{"type": "text", "text": text}]}})
    (d / (session + ".jsonl")).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_a_run_counts_the_shell_traps_the_step_recovered_from(
        tmp_path, monkeypatch, fake_cli):
    home = tmp_path / "projects"
    transcript(home, "s-1", [
        "The heredoc turned the \\n escapes into real newlines; rewriting.",
        "sed didn't match anything, the file still has the old line.",
        "The python script flipped the file to CRLF line endings.",
        "All tests pass now.",
    ])
    monkeypatch.setattr(handoff, "PROJECTS", str(home))
    a_flow(tmp_path, monkeypatch, "trapped",
           ["worker\ntools: [read, shell]", "reviewer"])
    fake_cli(answer("did it\n", session="s-1"),
             answer("VERDICT: ok\n\nfine\n", session="s-2"))
    engine.main()
    first, second = lines(folders(tmp_path)[0])
    assert first.get("shell_trap_recoveries") == 3
    assert second.get("shell_trap_recoveries", "unsaid") is None
