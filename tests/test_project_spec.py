"""a project names its spec files in orchestrate/project.yml.

`spec:` is a list of globs from the top of the place. the run reads it once,
from the project.yml it started with, and every check that asks which files
are the spec reads that list: the start snapshot, the spec-files gate, the
conflict cite's coverage. `AGENTWEFT_SPEC_GLOBS` still wins when it is set,
and a project.yml with no `spec:` leaves the shipped default standing.
"""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot
from agentweft.orchestrate import project
from agentweft.runner import stops

from test_spec_conflict import a_place, folders, go, plain

NL = chr(10)
API_LINE = "- Every list takes `?page=&per_page=`."
API = "# api" + NL + NL + API_LINE + NL
FILES = {"TASK.md": "# task" + NL, "docs/api.md": API,
         "rules/api-shape.md": "Every list pages." + NL,
         "pages.py": "def page():" + NL + "    return 1" + NL,
         "conftest.py": "",
         "tests/test_pages.py": "def test_page():" + NL + "    assert 1" + NL}
STOP = 'CONFLICT: docs/api.md:3 "' + API_LINE + '"' + NL \
    + "request: cursor paging" + NL


def project_yml(spec=None):
    text = "project:" + NL + "  name: pages" + NL
    if spec is not None:
        text += "spec: [" + ", ".join(spec) + "]" + NL
    return text


@pytest.fixture
def held(monkeypatch):
    monkeypatch.delenv("AGENTWEFT_SPEC_GLOBS", raising=False)
    monkeypatch.setattr(snapshot, "project_globs", None, raising=False)


def started(tmp_path, monkeypatch, spec=None):
    """-> (exit code, the spec files the start snapshot holds, steps asked)
    of a build-feature run on a place whose project.yml names `spec`."""
    files = dict(FILES)
    files["orchestrate/project.yml"] = project_yml(spec)
    a_place(tmp_path / "project", files)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [STOP]}), lambda s, n: None,
                        "--task", "cursor paging")
    runs = tmp_path / "runs"
    if not runs.is_dir() or not folders(tmp_path):
        return code, None, asked
    kept = json.loads((folders(tmp_path)[-1] / snapshot.FILE).read_text(
        encoding="utf-8"))
    return code, sorted(kept["specs"]), asked


def test_a_project_yml_spec_list_makes_its_files_the_spec(
        tmp_path, monkeypatch, held):
    code, specs, asked = started(tmp_path, monkeypatch,
                                 ["docs/*.md", "rules"])
    assert specs == ["docs/api.md", "rules/api-shape.md"], \
        "the start snapshot does not hold the files project.yml names"
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)


def test_with_no_spec_key_the_default_stands(tmp_path, monkeypatch, held):
    code, specs, _ = started(tmp_path, monkeypatch)
    assert specs == ["TASK.md"]
    assert code == stops.EXIT_STOP


def test_the_environment_still_wins_over_the_project(tmp_path, monkeypatch,
                                                     held):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", "rules/*.md")
    code, specs, _ = started(tmp_path, monkeypatch, ["docs/*.md"])
    assert specs == ["rules/api-shape.md"]


def test_a_bad_glob_stops_the_run_before_any_step(tmp_path, monkeypatch,
                                                  held, capsys):
    code, _, asked = started(tmp_path, monkeypatch, ["../outside/*.md"])
    assert asked == []
    assert code != stops.EXIT_OK
    assert "project.yml: spec: ../outside/*.md" in capsys.readouterr().out


@pytest.mark.parametrize("said,complaint", [
    ("docs/*.md", "spec: should be a list"),
    ([], "spec: names no file; leave it out for the default"),
    (["docs/*.md", 3], "spec: 3 should be str"),
    ([""], "spec:  should be a glob from the top of the place"),
    (["/etc/*.md"], "spec: /etc/*.md should be a glob from the top of the"
                    " place"),
    (["c:docs/*.md"], "spec: c:docs/*.md should be a glob from the top of"
                      " the place"),
    (["docs/../../x.md"], "spec: docs/../../x.md should be a glob from the"
                          " top of the place"),
    (["docs\\api.md"], "spec: docs\\api.md should be a glob from the top of"
                       " the place"),
])
def test_a_spec_list_that_names_no_file_of_the_place_is_refused(said,
                                                                complaint):
    assert project.check({"project": {"name": "x"}, "spec": said}) == \
        [complaint]


def test_a_spec_list_reads_back_and_absent_is_none():
    assert project.load({"project": {"name": "x"},
                         "spec": ["docs/*.md", "rules"]}).spec() == \
        ["docs/*.md", "rules"]
    assert project.load({"project": {"name": "x"}}).spec() is None
    assert project.read(project.example()).spec() == \
        ["TASK.md", "docs/architecture.md", "docs/api"]
    assert project.check({"project": {"name": "x"},
                          "spec": ["TASK.md", "docs/spec*", "rules"]}) == []
