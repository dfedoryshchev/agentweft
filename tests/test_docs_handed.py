"""a step handed a file is handed the project's docs that name it, the doc
nearest the file first, under a cap of their own, and the files project.yml
says its role reads first; the docs handed go on the step's line in
steps.jsonl. a line or an entry that names a path on the machine is never
handed."""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import retroedits
from agentweft.runner import engine
from test_facts_attached import CODE, a_run, asked, put
from test_stops import answer, steps_of, the_folder

NL = chr(10)
HEAD = "the project's docs for the files you are handed"


def a_place(tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "TASK.md", "# task" + NL + NL + "errors are raised." + NL)
    put(tmp_path, "docs/arch.md", "# arch" + NL + NL
        + "pkg/parse.py splits a line into words." + NL)
    put(tmp_path, "pkg/README.md", "# pkg" + NL + NL
        + "parse.py raises, it never prints." + NL)
    put(tmp_path, "README.md", "# the tool" + NL + NL + "run it." + NL)


def project(tmp_path, *lines):
    put(tmp_path, "orchestrate/project.yml", NL.join(
        ["project:", "  name: t", "read_first:"] + list(lines)) + NL)


def test_a_step_handed_a_file_gets_the_docs_that_name_it_nearest_first(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert HEAD in prompt
    assert "pkg/README.md:3: parse.py raises, it never prints." in prompt
    assert "docs/arch.md:3: pkg/parse.py splits a line into words." in prompt
    assert prompt.index("pkg/README.md names") \
        < prompt.index("docs/arch.md names")
    assert "README.md names" not in prompt.replace("pkg/README.md names", "")
    [line] = steps_of(the_folder())
    assert line["docs_handed"] == ["pkg/README.md", "docs/arch.md"]


def test_a_doc_the_step_is_handed_itself_is_not_handed_again_as_a_doc(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL),
                 task="make pkg/parse.py stricter, see pkg/README.md")
    assert engine.main() == 0
    [line] = steps_of(the_folder())
    assert line["docs_handed"] == ["docs/arch.md"]
    assert "pkg/README.md:3:" not in asked(fake)[0]


def test_the_files_its_role_reads_first_reach_the_step(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    put(tmp_path, "docs/conventions.md", "# conventions" + NL)
    project(tmp_path, "  planner: [docs/conventions.md, docs/gone.md]",
            "  worker: [docs/worker-only.md]")
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make it stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert ("read these first, as the project names them for the planner:"
            " docs/conventions.md") in prompt
    assert "docs/gone.md (not in the place)" in prompt
    assert "worker-only" not in prompt
    [line] = steps_of(the_folder())
    assert line["docs_handed"] == ["docs/conventions.md"]


def test_a_doc_line_or_a_read_first_entry_on_the_machine_is_never_handed(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    far = "C" + ":/" + "work/notes/parse.md"
    put(tmp_path, "docs/arch.md", "# arch" + NL + NL
        + "pkg/parse.py splits a line into words." + NL
        + "pkg/parse.py notes live at " + far + NL)
    project(tmp_path, "  planner: [\"" + far + "\", ../outside.md]")
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert "docs/arch.md:3: pkg/parse.py splits a line into words." in prompt
    assert far not in prompt
    assert "docs/arch.md:4: (a line that names a path on the machine, not" \
        " quoted)" in prompt
    assert "outside.md" not in prompt
    assert "2 entries outside the place left out" in prompt


def test_past_the_docs_cap_the_rest_are_named(tmp_path, monkeypatch,
                                              fake_cli):
    a_place(tmp_path)
    for n in range(5):
        put(tmp_path, "docs/more-%d.md" % n, "# more" + NL + NL
            + "pkg/parse.py, note %d." % n + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    words = prompt.split(HEAD)[1]
    heads = [l for l in words.split(NL)
             if l.startswith(("- pkg/", "- docs/")) and " names " in l]
    assert len(heads) == retroedits.DOCS_HANDED, heads
    assert "left out at the cap of 3 docs" in words
    [line] = steps_of(the_folder())
    assert len(line["docs_handed"]) == retroedits.DOCS_HANDED


def test_the_docs_left_out_at_the_cap_are_named_in_a_bounded_line(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    for n in range(150):
        put(tmp_path, "docs/guides/working-on-the-parser-%03d.md" % n,
            "# guide" + NL + NL + "pkg/parse.py, note %d." % n + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    words = asked(fake)[0].split(HEAD)[1]
    [left] = [l for l in words.split(NL) if l.startswith("- left out at")]
    assert len(left) <= 300, len(left)
    shown, more = left.split(": ", 1)[1].rsplit(" and ", 1)
    assert more.endswith(" more"), left
    assert len(shown.split(", ")) + int(more.split()[0]) == 152 - 3


def test_with_the_lane_off_no_doc_is_searched_and_read_first_still_reaches(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    put(tmp_path, "docs/conventions.md", "# conventions" + NL)
    project(tmp_path, "  planner: [docs/conventions.md]")
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter",
                 head="lane: off" + NL)
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert "docs/arch.md" not in prompt
    assert "docs/conventions.md" in prompt


def test_a_longer_name_or_a_path_that_is_no_file_of_the_place_names_nothing(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "docs/arch.md", "# arch" + NL + NL
        + "the budget-parse.py helper and notes.md are elsewhere." + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL),
                 task="make pkg/parse.py stricter, see notes.md")
    assert engine.main() == 0
    assert HEAD not in asked(fake)[0]
    assert "docs_handed" not in steps_of(the_folder())[0]


def test_a_place_with_no_doc_naming_a_handed_file_gets_no_docs_section(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "README.md", "# the tool" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert HEAD not in prompt
    assert "docs_handed" not in steps_of(the_folder())[0]
