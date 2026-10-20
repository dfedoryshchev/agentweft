import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import gates
from agentweft.runner import trace

NOTE = "the box fell over on tuesday\nand came back by noon\n"


def gate(where=None, **opts):
    return gates.build(dict({"gate": "quote"}, **opts), where=where)


def inbox(tmp_path, monkeypatch, files):
    box = tmp_path / "inbox"
    for rel, text in files.items():
        (box / rel).parent.mkdir(parents=True, exist_ok=True)
        (box / rel).write_text(text, encoding="utf-8")
    monkeypatch.setenv("INBOX", str(box))
    return box


def test_a_quote_the_source_holds_passes(tmp_path, monkeypatch):
    inbox(tmp_path, monkeypatch, {"infra.md": NOTE})
    r = gate(source="{INBOX}").run('- "the box fell over on tuesday", says'
                                  ' infra.md\n')
    assert r.ok
    assert r.detail.startswith("1 quoted, all in ")


def test_a_quote_no_file_holds_fails_naming_it(tmp_path, monkeypatch):
    inbox(tmp_path, monkeypatch, {"infra.md": NOTE})
    r = gate(source="{INBOX}").run('- "the box caught fire on monday"\n')
    assert not r.ok and not r.broke
    assert r.detail.startswith('"the box caught fire on monday" is in no file')


def test_a_quote_split_over_two_lines_of_the_file_is_held(tmp_path,
                                                          monkeypatch):
    inbox(tmp_path, monkeypatch, {"infra.md": NOTE})
    assert gate(source="{INBOX}").run('"on tuesday and came back"\n').ok


def test_a_quote_in_a_file_of_a_subfolder_is_held(tmp_path, monkeypatch):
    inbox(tmp_path, monkeypatch, {"team/ops/infra.md": NOTE})
    assert gate(source="{INBOX}").run('"came back by noon"\n').ok


def test_short_quotes_and_an_answer_with_none_pass(tmp_path, monkeypatch):
    inbox(tmp_path, monkeypatch, {"infra.md": NOTE})
    assert gate(source="{INBOX}").run('the "fire alarm" went off\n').ok
    r = gate(source="{INBOX}").run("nothing quoted here\n")
    assert r.ok and r.detail == "nothing quoted"
    assert gate(source="{INBOX}").run("").ok


def test_a_quote_with_no_source_to_hold_it_to_fails_and_caught_nothing(
        tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX", "")
    r = gate(source="{INBOX}").run('"the box fell over on tuesday"\n')
    assert not r.ok and r.broke
    assert r.detail.startswith("no source to hold the quotes to")
    assert trace.won("gate failed", None, [trace.gate_line(r)],
                     "reviewer.md") == "none"
    r = gate().run('"the box fell over on tuesday"\n')
    assert not r.ok and r.broke


def test_a_source_that_is_not_there_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX", str(tmp_path / "gone"))
    r = gate(source="{INBOX}").run('"the box fell over on tuesday"\n')
    assert not r.ok and r.broke
    assert "is not there to hold the quotes to" in r.detail


def test_a_relative_source_is_read_from_the_place(tmp_path):
    cafe, at = "caf" + chr(233), chr(224)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / (cafe + ".md")).write_text(
        "le " + cafe + " ferme " + at + " midi le lundi\n", encoding="utf-8")
    g = gate(where=tmp_path, source="notes")
    assert g.run('"le ' + cafe + ' ferme ' + at + ' midi"\n').ok
    assert not g.run('"le ' + cafe + ' ouvre ' + at + ' midi"\n').ok


@pytest.mark.skipif(sys.platform != "win32",
                    reason="a backslash only separates paths on windows")
def test_a_windows_path_source_is_read(tmp_path, monkeypatch):
    box = inbox(tmp_path, monkeypatch, {"infra.md": NOTE})
    monkeypatch.setenv("INBOX", str(box).replace("/", "\\"))
    assert gate(source="{INBOX}").run('"came back by noon"\n').ok
