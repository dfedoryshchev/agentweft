import sys

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.orchestrate import project, workflow


def example():
    return project.read(project.example())


def test_the_example_file_loads():
    p = example()
    assert p.name == "example-app"
    assert p.stack == ["python", "react"]


def test_this_repo_has_no_project_file_of_its_own():
    """the roles were written for a codebase that is not this one.

    shipping a project.yml here would answer for agentweft, and the note the
    file comes out of is that pointing a role at agentweft's own docs is the
    wrong answer rather than a missing one.
    """
    assert not project.path().exists()
    assert project.example().exists()


def test_the_pre_work_is_per_role_and_a_role_it_says_nothing_about_gets_nothing():
    p = example()
    assert p.read_first("architect") == ["docs/architecture.md", "docs/patterns.md"]
    assert p.read_first("test-qa") == ["docs/testing.md"]
    assert p.read_first("business-analyst") == []


def test_every_role_the_file_names_is_a_role_this_repo_has():
    """the file answers for named seats, so a name with no seat answers for

    nothing and nothing would say so. the agents are the ones on disk beside
    the workflow, not a list written twice.
    """
    p = example()
    have = set(workflow.load().agents())
    for key in ("read_first", "roles"):
        for role in p.raw.get(key) or {}:
            assert role in have, (key, role)


def test_a_gate_is_argv_and_not_a_line_for_a_shell():
    p = example()
    assert p.gate("tests") == ["pytest", "-q"]
    assert p.gate("nothing-called-this") == []


def test_the_standards_are_prose_and_the_coverage_is_numbers():
    p = example()
    assert p.coverage("critical") == 100
    assert p.coverage("overall") == 80
    assert p.coverage("nothing-called-this") is None
    assert all(isinstance(s, str) for s in p.standards("forbidden"))
    assert p.standards("immediate_reject")


def test_a_typo_at_the_top_level_is_refused_and_not_ignored():
    assert project.check({"project": {"name": "x"}, "conventions": {}}) == \
        ["unknown key conventions"]


def test_the_file_has_to_say_which_project_it_is_for():
    assert "missing project" in project.check({})
    # a bare `project:` is in the file and answers for nothing
    assert "missing project" in project.check({"project": None})
    assert "project: missing name" in project.check({"project": {}})
    assert "project: unknown key language" in \
        project.check({"project": {"name": "x", "language": "python"}})


def test_a_tier_the_runner_has_no_name_for_is_refused():
    bad = project.check({"project": {"name": "x"},
                         "roles": {"architect": {"model": "huge"}}})
    assert bad == ["roles: architect: model should be one of high, mid, low"]


def test_a_grant_the_runner_has_no_name_for_is_refused():
    bad = project.check({"project": {"name": "x"},
                         "roles": {"architect": {"tools": ["read", "shel"]}}})
    assert bad == ["roles: architect: no such tool shel. there is: "
                   "read, grep, write, edit, shell, browser"]


def test_the_tier_and_the_grant_are_the_flow_loaders_words_not_a_second_set():
    """a second vocabulary for the same two ideas is how the repo ends up with

    two answers to what `high` means. these are read off the flow spec's lists,
    so adding a tier there adds it here and nowhere else.
    """
    bad = project.check({"project": {"name": "x"},
                         "roles": {"architect": {"model": "huge"}}})
    assert ", ".join(spec.TIERS) in bad[0]
    bad = project.check({"project": {"name": "x"},
                         "roles": {"architect": {"tools": ["nope"]}}})
    assert ", ".join(spec.GRANTS) in bad[0]


def test_a_grant_of_nothing_is_a_grant():
    assert project.check({"project": {"name": "x"},
                          "roles": {"architect": {"tools": []}}}) == []


def test_a_role_key_nothing_reads_is_refused():
    bad = project.check({"project": {"name": "x"},
                         "roles": {"architect": {"personality": "minimalist"}}})
    assert bad == ["roles: architect: unknown key personality"]


def test_a_coverage_number_off_the_scale_is_refused():
    base = {"project": {"name": "x"}}
    assert project.check(dict(base, coverage={"overall": 120})) == \
        ["coverage: overall should be 0 to 100"]
    assert project.check(dict(base, coverage={"overall": "eighty"})) == \
        ["coverage: overall should be int"]
    assert project.check(dict(base, coverage={"critical": 0})) == []


def test_a_coverage_number_written_as_yes_is_not_a_number():
    """`critical: yes` loads as True, and True is an int in python.

    without the bool check it passes the type test and then passes the range
    test as 1, which is a coverage floor of one percent that nobody typed.
    """
    assert yaml.safe_load("critical: yes") == {"critical": True}
    assert project.check({"project": {"name": "x"},
                          "coverage": {"critical": True}}) == \
        ["coverage: critical should be int"]


def test_a_gate_that_runs_nothing_is_refused():
    base = {"project": {"name": "x"}}
    assert project.check(dict(base, gates={"tests": []})) == ["gates: tests is empty"]
    assert project.check(dict(base, gates={"tests": "pytest -q"})) == \
        ["gates: tests should be a list"]
    assert project.check(dict(base, gates={"tests": ["pytest", 2]})) == \
        ["gates: tests: 2 should be str"]


def test_the_pre_work_and_the_standards_are_lists_of_strings():
    base = {"project": {"name": "x"}}
    assert project.check(dict(base, read_first={"architect": "docs/x.md"})) == \
        ["read_first: architect should be a list"]
    assert project.check(dict(base, standards={"forbidden": "no globals"})) == \
        ["standards: forbidden should be a list"]
    assert project.check(dict(base, standards={"style": ["x"]})) == \
        ["standards: unknown key style"]


def test_the_whole_file_is_refused_at_once_in_the_flow_loaders_words():
    with pytest.raises(ValueError) as caught:
        project.load({"conventions": {}, "coverage": {"overall": 120}})
    assert str(caught.value) == ("project.yml: missing project; "
                                 "unknown key conventions; "
                                 "coverage: overall should be 0 to 100")


def test_the_same_reader_refuses_a_duplicate_key(tmp_path):
    """safe_load keeps the LAST of two identical keys and says nothing.

    a project file with two `gates:` blocks would quietly run half of what it
    says it runs, which is the one half of this file that is supposed to be
    impossible to ignore.
    """
    path = tmp_path / "project.yml"
    path.write_text("project:\n  name: x\ngates:\n  tests: [pytest]\n"
                    "gates:\n  lint: [ruff]\n", encoding="utf-8")
    assert list(yaml.safe_load(path.read_text())["gates"]) == ["lint"]
    with pytest.raises(yaml.YAMLError):
        project.read(path)


def test_the_seats_that_name_a_path_in_their_own_prose_are_countable():
    """the gap the file exists to close, as a number rather than a reading.

    countable rather than raised, the same as `ungranted()` and `misnamed()`:
    a seat naming a path works in one codebase and reports as though it read
    something in every other one.
    """
    seats = project.hardcoded()
    assert sorted(set(a.name for a in seats)) == [
        "architect", "business-analyst", "code-reviewer", "developer",
        "doc-researcher", "doc-updater", "product-qa", "test-qa",
    ]
    assert len(seats) == 17


def test_the_paths_named_in_prose_are_the_three_the_note_found():
    found = set()
    for agent in project.hardcoded():
        found.update(project.in_prose(agent.prompt().read_text(encoding="utf-8")))
    assert sorted(p for p in found if p.endswith(".md")) == [
        "docs/architecture.md", "docs/patterns.md", "docs/testing.md",
    ]


def test_pre_work_prefers_the_project_over_the_seats_own_prose():
    """the project's order, not the alphabetical order prose falls into.

    developer's prompt names `docs/patterns.md` first and `docs/architecture.md`
    second; `in_prose()` sorts, so reading the prose back would lose that. the
    project's answer is the one meant to win, in the order it gives it.
    """
    developer = workflow.Agent("developer")
    assert project.in_prose(developer.prompt().read_text(encoding="utf-8")) == \
        ["docs/architecture.md", "docs/patterns.md"]
    assert project.pre_work(developer, example()) == \
        ["docs/patterns.md", "docs/architecture.md"]


def test_pre_work_falls_back_to_the_seats_own_prose_when_the_project_says_nothing():
    analyst = workflow.Agent("business-analyst")
    proj = example()
    assert proj.read_first("business-analyst") == []
    assert project.pre_work(analyst, proj) == ["docs/architecture.md"]


def test_pre_work_with_no_project_is_the_seats_own_prose():
    architect = workflow.Agent("architect")
    assert project.pre_work(architect, None) == \
        ["docs/architecture.md", "docs/patterns.md"]


def test_pre_work_is_empty_when_neither_side_says_anything():
    consistency = workflow.Agent("e2e-consistency")
    assert project.pre_work(consistency, example()) == []
    assert project.pre_work(consistency, None) == []


def test_two_of_those_three_do_not_exist_here_and_the_third_is_the_wrong_document():
    import pathlib

    assert not pathlib.Path("docs/patterns.md").exists()
    assert not pathlib.Path("docs/testing.md").exists()
    # the one that resolves is this repo's own layering, not the layering the
    # architect was written to rule on, and reading it fails silently
    assert pathlib.Path("docs/architecture.md").exists()
