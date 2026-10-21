"""the facts store: an entry keyed to a file, a folder, a glob or the
project, found for the files inside its scope, and healed at run start."""
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import facts

CODE = ["import os", "", "def parse(line):", "    if not line:",
        "        raise ValueError('empty')", "    return line.split()", ""]


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def entry(id, scope, claim, anchor=None, status="live", kind="convention"):
    out = ["## " + id + " " + status, "scope: " + scope, "kind: " + kind,
           "claim: " + claim, "why: the spec says so"]
    if anchor:
        out.append("anchor: " + anchor)
    return "\n".join(out) + "\n"


def anchor_on(root, rel, first, last):
    return str(facts.anchored(root, rel, first, last))


def test_a_fact_on_a_folder_holds_for_a_file_inside_it(tmp_path):
    put(tmp_path, "pkg/a.py", "x = 1\n")
    put(tmp_path, "facts/pkg/_folder.md",
        entry("F-0001", "pkg/", "errors are raised, never printed"))
    put(tmp_path, "facts/other/_folder.md",
        entry("F-0002", "other/", "not about pkg"))
    found = facts.lookup(tmp_path, "pkg/a.py")
    assert [f.id for f in found] == ["F-0001"]
    assert found[0].claim == "errors are raised, never printed"


def test_lookup_goes_from_the_file_out_to_the_project(tmp_path):
    put(tmp_path, "facts/_project.md",
        entry("F-0004", ".", "the whole project") + "\n"
        + entry("F-0005", "pkg/**", "every file under pkg"))
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0003", "pkg/", "pkg"))
    put(tmp_path, "facts/pkg/sub/_folder.md",
        entry("F-0002", "pkg/sub/", "sub"))
    put(tmp_path, "facts/pkg/sub/a.py.md", entry("F-0001", "pkg/sub/a.py",
                                                  "a itself"))
    assert [f.id for f in facts.lookup(tmp_path, "pkg/sub/a.py")] == \
        ["F-0001", "F-0002", "F-0003", "F-0005", "F-0004"]
    assert [f.id for f in facts.lookup(tmp_path, "top.py")] == ["F-0004"]


def test_a_scope_written_with_a_backslash_matches(tmp_path):
    name = "donn" + chr(0xE9) + "es.py"
    put(tmp_path, "facts/pkg/" + name + ".md",
        entry("F-0001", "pkg\\" + name, "a windows path"))
    assert [f.id for f in facts.lookup(tmp_path, "pkg/" + name)] == \
        ["F-0001"]
    assert [f.id for f in facts.lookup(tmp_path, ".\\pkg\\" + name)] == \
        ["F-0001"]
    assert [f.id for f in facts.lookup(tmp_path, tmp_path / "pkg" / name)] \
        == ["F-0001"]


def test_a_fact_whose_anchored_lines_moved_is_anchored_again(tmp_path):
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    store = put(tmp_path, "facts/pkg/a.py.md",
                entry("F-0001", "pkg/a.py", "empty lines raise", at))
    put(tmp_path, "pkg/a.py", "\n".join(["# a header", "# more"] + CODE))
    changes = facts.heal(tmp_path, today="2026-10-22")
    assert [(c.id, c.how) for c in changes] == [("F-0001", "moved")]
    [fact] = facts.read(tmp_path)
    assert fact.status == "live"
    assert facts.anchor_of(fact).first == 5
    assert facts.anchor_of(fact).last == 7
    assert fact.get("healed") == "2026-10-22 moved 3-5 to 5-7"
    assert "why: the spec says so" in store.read_text(encoding="utf-8")


def test_a_fact_whose_anchored_lines_changed_is_stale(tmp_path):
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    put(tmp_path, "facts/pkg/a.py.md",
        entry("F-0001", "pkg/a.py", "empty lines raise", at))
    put(tmp_path, "pkg/a.py", "\n".join(CODE).replace("ValueError",
                                                      "KeyError"))
    changes = facts.heal(tmp_path, today="2026-10-22")
    assert [(c.id, c.how) for c in changes] == [("F-0001", "stale")]
    [fact] = facts.read(tmp_path)
    assert fact.status == "stale"
    assert fact.get("stale") == "2026-10-22 lines changed since it was" \
        " anchored"
    assert [(f.id, f.status) for f in facts.lookup(tmp_path, "pkg/a.py")] \
        == [("F-0001", "stale")]
    assert facts.heal(tmp_path, today="2026-10-23") == []


def test_a_fact_whose_file_is_gone_is_stale_then_retired(tmp_path):
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    put(tmp_path, "facts/pkg/a.py.md",
        entry("F-0001", "pkg/a.py", "empty lines raise", at))
    (tmp_path / "pkg" / "a.py").unlink()
    [first] = facts.heal(tmp_path, today="2026-10-22")
    assert (first.how, first.said) == ("stale", "pkg/a.py is gone")
    [fact] = facts.read(tmp_path)
    assert fact.status == "stale"
    assert fact.get("stale") == "2026-10-22 file gone in 1 run"
    [second] = facts.heal(tmp_path, today="2026-10-23")
    assert second.how == "retired"
    [fact] = facts.read(tmp_path)
    assert fact.status == "retired"
    assert facts.lookup(tmp_path, "pkg/a.py") == []


def test_lines_that_now_read_the_same_in_two_places_make_it_stale(tmp_path):
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    put(tmp_path, "facts/pkg/a.py.md",
        entry("F-0001", "pkg/a.py", "empty lines raise", at))
    put(tmp_path, "pkg/a.py", "\n".join(["x"] + CODE[2:5] + CODE[2:5]))
    [change] = facts.heal(tmp_path, today="2026-10-22")
    assert change.how == "stale"
    assert "in 2 places" in change.said


def test_an_unchanged_anchor_and_an_unanchored_fact_are_left_alone(tmp_path):
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    text = (entry("F-0001", "pkg/a.py", "empty lines raise", at) + "\n"
            + entry("F-0002", "pkg/a.py", "no anchor"))
    store = put(tmp_path, "facts/pkg/a.py.md", text)
    assert facts.heal(tmp_path) == []
    assert store.read_text(encoding="utf-8") == text


def test_a_crlf_checkout_reads_the_same_hash(tmp_path):
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    put(tmp_path, "facts/pkg/a.py.md",
        entry("F-0001", "pkg/a.py", "empty lines raise", at))
    (tmp_path / "pkg" / "a.py").write_bytes("\r\n".join(CODE).encode("utf-8"))
    assert facts.heal(tmp_path) == []


def test_no_facts_folder_is_nothing_to_read_or_heal(tmp_path):
    assert facts.read(tmp_path) == []
    assert facts.lookup(tmp_path, "a.py") == []
    assert facts.heal(tmp_path) == []
    assert not (tmp_path / "facts").exists()


def test_superseded_and_retired_facts_are_not_looked_up(tmp_path):
    put(tmp_path, "facts/pkg/_folder.md",
        entry("F-0001", "pkg/", "old", status="superseded") + "\n"
        + entry("F-0002", "pkg/", "gone", status="retired") + "\n"
        + entry("F-0003", "pkg/", "now"))
    assert [f.id for f in facts.lookup(tmp_path, "pkg/a.py")] == ["F-0003"]


def test_the_index_and_proposals_files_hold_no_facts(tmp_path):
    put(tmp_path, "facts/INDEX.md", entry("F-0009", "pkg/", "an index line"))
    put(tmp_path, "facts/PROPOSED.md", entry("F-0008", "pkg/", "a proposal"))
    assert facts.read(tmp_path) == []


def test_a_file_scope_does_not_hold_for_a_longer_name(tmp_path):
    put(tmp_path, "facts/pkg/a.py.md", entry("F-0001", "pkg/a.py", "a"))
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0002", "pkg/", "pkg"))
    assert [f.id for f in facts.lookup(tmp_path, "pkgx/a.py")] == []
    assert [f.id for f in facts.lookup(tmp_path, "pkg/a.pyc")] == ["F-0002"]


def test_the_run_heals_the_store_before_its_first_step(tmp_path, monkeypatch,
                                                      fake_cli, capsys):
    from agentweft.runner import engine
    from test_stops import CLAUDE, a_flow, answer

    a_flow(tmp_path, monkeypatch, "healing", ["worker"], tail=CLAUDE)
    put(tmp_path, "pkg/a.py", "\n".join(CODE))
    at = anchor_on(tmp_path, "pkg/a.py", 3, 5)
    put(tmp_path, "facts/pkg/a.py.md",
        entry("F-0001", "pkg/a.py", "empty lines raise", at))
    put(tmp_path, "pkg/a.py", "\n".join(["# moved down"] + CODE))
    fake_cli(answer("done\n"))
    assert engine.main() == 0
    [fact] = facts.read(tmp_path)
    assert str(facts.anchor_of(fact)).startswith("pkg/a.py:4-6 ")
    printed = capsys.readouterr().out
    assert "facts: F-0001 moved: pkg/a.py:4-6" in printed
    assert printed.index("facts: F-0001") < printed.index("started worker.md")
