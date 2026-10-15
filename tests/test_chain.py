"""the run record is chained: each steps.jsonl line carries the hash of the
line before it, so a line edited, dropped or put out of order after it was
written is named by `python run.py verify <run id>`, and a resume refuses it.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import cli, stops
from test_manifest_resume import CHECK, a_flow, asking, folders, run, steps_of

NL = chr(10)
GATED = [("a", []), ("b", []),
         ("c", ["gates:", "  - gate: command",
                "    command: " + json.dumps(CHECK)])]
FALSE = '"gate": "command", "ok": false'
TRUE = '"gate": "command", "ok": true'


def stopped_run(tmp_path, monkeypatch):
    """-> the folder of a run that stopped at c.md's gate, sent back once:
    a, b, c (gate failed), c (gate failed)."""
    a_flow(tmp_path, monkeypatch, "gated", GATED)
    asking(monkeypatch)
    assert run(monkeypatch, "gated", "--force") == stops.EXIT_STOP
    [first] = folders(tmp_path)
    return first


def lines_of(folder):
    raw = (folder / "steps.jsonl").read_bytes().decode("utf-8")
    return [l for l in raw.replace("\r\n", NL).split(NL) if l.strip()]


def rewrite(folder, lines):
    (folder / "steps.jsonl").write_bytes((NL.join(lines) + NL).encode("utf-8"))


def verify(monkeypatch, capsys, run_id):
    monkeypatch.setattr(sys, "argv", ["run.py", "verify", run_id])
    capsys.readouterr()
    code = cli.entrypoint()
    return code, capsys.readouterr().out


def test_a_clean_run_verifies(tmp_path, monkeypatch, capsys):
    first = stopped_run(tmp_path, monkeypatch)
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 0
    assert "4 lines" in said


def test_a_gate_line_turned_from_failed_to_passed_is_named(tmp_path,
                                                          monkeypatch, capsys):
    first = stopped_run(tmp_path, monkeypatch)
    lines = lines_of(first)
    assert FALSE in lines[2]
    lines[2] = lines[2].replace(FALSE, TRUE, 1)
    rewrite(first, lines)
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 1
    assert "line 3" in said and "edited" in said


def test_the_last_gate_line_edited_is_named_too(tmp_path, monkeypatch, capsys):
    first = stopped_run(tmp_path, monkeypatch)
    lines = lines_of(first)
    lines[3] = lines[3].replace(FALSE, TRUE, 1)
    rewrite(first, lines)
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 1
    assert "line 4" in said and "edited" in said


def test_a_dropped_line_is_named(tmp_path, monkeypatch, capsys):
    first = stopped_run(tmp_path, monkeypatch)
    lines = lines_of(first)
    rewrite(first, lines[:1] + lines[2:])
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 1
    assert "dropped" in said and "seq 2" in said


def test_a_dropped_last_line_is_named(tmp_path, monkeypatch, capsys):
    first = stopped_run(tmp_path, monkeypatch)
    rewrite(first, lines_of(first)[:-1])
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 1
    assert "dropped" in said and "4" in said


def test_two_lines_swapped_are_named_as_out_of_order(tmp_path, monkeypatch,
                                                     capsys):
    first = stopped_run(tmp_path, monkeypatch)
    lines = lines_of(first)
    rewrite(first, [lines[0], lines[2], lines[1], lines[3]])
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 1
    assert "out of order" in said and "line 2" in said


def test_a_start_snapshot_rewritten_after_the_lines_is_named(
        tmp_path, monkeypatch, capsys):
    first = stopped_run(tmp_path, monkeypatch)
    (first / "start-snapshot.json").write_text("{}", encoding="utf-8")
    code, said = verify(monkeypatch, capsys, first.name)
    assert code == 1
    assert "start-snapshot.json" in said


def test_a_resume_of_a_tampered_run_refuses_and_says_why(tmp_path, monkeypatch,
                                                         capsys):
    first = stopped_run(tmp_path, monkeypatch)
    lines = lines_of(first)
    lines[2] = lines[2].replace(FALSE, TRUE, 1)
    rewrite(first, lines)
    asked = asking(monkeypatch)
    (tmp_path / "ok").write_text("", encoding="utf-8")
    capsys.readouterr()
    assert run(monkeypatch, "gated", "--resume", first.name) == 1
    said = capsys.readouterr().out
    assert "line 3" in said and "--force" in said
    assert asked == []
    assert len(folders(tmp_path)) == 1


def test_a_forced_resume_of_a_tampered_run_writes_the_break_down(
        tmp_path, monkeypatch):
    first = stopped_run(tmp_path, monkeypatch)
    lines = lines_of(first)
    rewrite(first, lines[:1] + lines[2:])
    asked = asking(monkeypatch)
    (tmp_path / "ok").write_text("", encoding="utf-8")
    assert run(monkeypatch, "gated", "--force", "--resume",
               first.name) == stops.EXIT_OK
    assert steps_of(asked) == ["c.md"]
    resumed = [p for p in folders(tmp_path) if p != first][-1]
    said = decisions.read(resumed)
    assert [d.decided for d in said] == ["carried " + first.name
                                         + " on over a broken record"]
    assert "dropped" in said[0].why


def test_the_handoff_names_the_head_it_was_written_from(tmp_path, monkeypatch):
    first = stopped_run(tmp_path, monkeypatch)
    note = (first / "handoff.md").read_text(encoding="utf-8")
    chained = [l for l in note.split(NL) if l.startswith("- chain: ")]
    assert len(chained) == 1 and "4 lines" in chained[0]
    head = json.loads((first / "manifest.json").read_text(
        encoding="utf-8"))["chain"]["head"]
    assert head[:16] in chained[0]
