import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import gates
from agentweft.orchestrate import workflow
from agentweft.runner import engine, prompts, resume, state


def report(lines, rate=None):
    """a cobertura report. `lines` is {filename: [hits per line, in order]}."""
    classes = ""
    for name, hits in lines.items():
        rows = "".join('<line number="' + str(i + 1) + '" hits="' + str(h) + '"/>'
                       for i, h in enumerate(hits))
        classes += ('<class name="' + name + '" filename="' + name + '">'
                    "<lines>" + rows + "</lines></class>")
    head = '<coverage line-rate="' + str(rate) + '">' if rate is not None \
        else "<coverage>"
    return (head + '<packages><package name="p"><classes>' + classes
            + "</classes></package></packages></coverage>")


def place(tmp_path, monkeypatch, coverage=None, project=True):
    """a project.yml beside a workflow in tmp_path/orchestrate."""
    home = tmp_path / "orchestrate"
    home.mkdir()
    monkeypatch.setattr(workflow, "ROOT", [str(home)])
    if project:
        text = "project:\n  name: here\n"
        if coverage is not None:
            text += "coverage:\n" + "".join("  " + k + ": " + str(v) + "\n"
                                            for k, v in coverage.items())
        (home / "project.yml").write_text(text, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    return work


def gate(work, **opts):
    return gates.build(dict({"gate": "coverage"}, **opts), where=work)


def write(work, text, name="coverage.xml"):
    (work / name).write_text(text, encoding="utf-8")


def test_a_report_over_the_floor_passes(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 80})
    write(work, report({"a.py": [1, 1, 1, 1, 0]}))
    r = gate(work).run("anything")
    assert r
    assert r.detail == "80% of 5 lines, overall floor is 80"


def test_a_report_under_the_floor_fails_and_says_by_how_much(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 80})
    write(work, report({"a.py": [1, 1, 1, 0, 0]}))
    r = gate(work).run("anything")
    assert not r
    assert r.detail == "60% of 5 lines, overall floor is 80"


def test_the_number_is_the_project_file_and_not_the_flow(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 50})
    write(work, report({"a.py": [1, 1, 1, 0, 0]}))
    assert gate(work).run("x")
    (tmp_path / "orchestrate" / "project.yml").write_text(
        "project:\n  name: here\ncoverage:\n  overall: 70\n", encoding="utf-8")
    assert not gate(work).run("x")


def test_a_floor_written_in_the_flow_is_refused(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 80})
    write(work, report({"a.py": [1]}))
    r = gate(work, overall=10).run("x")
    assert not r
    assert "project.yml" in r.detail


def test_no_project_file_is_a_failure_not_a_pass(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, project=False)
    write(work, report({"a.py": [1]}))
    r = gate(work).run("x")
    assert not r
    assert r.detail.startswith("no project.yml")


def test_a_project_file_silent_about_the_number_fails(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"critical": 100})
    write(work, report({"a.py": [1]}))
    r = gate(work).run("x")
    assert not r
    assert r.detail == "project.yml has no coverage: overall"


def test_a_broken_project_file_fails_with_the_loaders_words(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 120})
    write(work, report({"a.py": [1]}))
    r = gate(work).run("x")
    assert not r
    assert "coverage: overall should be 0 to 100" in r.detail


def test_the_report_is_read_where_the_run_works(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 80})
    write(work, report({"a.py": [1]}), name="cov.xml")
    assert gate(work, report="cov.xml").run("x")
    r = gate(work).run("x")
    assert not r
    assert r.detail.startswith("no coverage report at ")


def test_a_report_that_is_not_xml_fails(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 80})
    write(work, "TOTAL 100%")
    r = gate(work).run("x")
    assert not r
    assert r.detail.startswith("cannot read coverage.xml")


def test_critical_counts_only_the_files_it_is_pointed_at(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"critical": 100, "overall": 10})
    write(work, report({"pay/charge.py": [1, 1], "ui/page.py": [0, 0, 0]}))
    assert gate(work, floor="critical", paths=["pay/*"]).run("x")
    r = gate(work, floor="critical", paths=["pay/*", "ui/*"]).run("x")
    assert not r
    assert r.detail == "40% of 5 lines, critical floor is 100"


def test_critical_with_no_paths_fails_rather_than_meaning_everything(tmp_path,
                                                                     monkeypatch):
    work = place(tmp_path, monkeypatch, {"critical": 100})
    write(work, report({"a.py": [1]}))
    r = gate(work, floor="critical").run("x")
    assert not r
    assert "paths" in r.detail


def test_a_project_file_with_a_key_twice_fails(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 10})
    (tmp_path / "orchestrate" / "project.yml").write_text(
        "project:\n  name: here\ncoverage:\n  overall: 10\ncoverage:\n"
        "  overall: 90\n", encoding="utf-8")
    write(work, report({"a.py": [1]}))
    r = gate(work).run("x")
    assert not r
    assert "duplicate key" in r.detail


def test_one_path_needs_no_list(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"critical": 100})
    write(work, report({"pay/charge.py": [1], "ui/page.py": [0]}))
    assert gate(work, floor="critical", paths="pay/*").run("x")


def test_paths_that_match_nothing_fail(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"critical": 100})
    write(work, report({"a.py": [1]}))
    r = gate(work, floor="critical", paths=["pay/*"]).run("x")
    assert not r
    assert r.detail == "no lines in coverage.xml under pay/*"


def test_a_floor_that_is_not_a_coverage_number_fails(tmp_path, monkeypatch):
    work = place(tmp_path, monkeypatch, {"overall": 80})
    write(work, report({"a.py": [1]}))
    r = gate(work, floor="branches").run("x")
    assert not r
    assert r.detail == "no such coverage number branches. there is: critical, overall"


def test_the_lines_are_counted_and_not_the_rate_trusted(tmp_path, monkeypatch):
    """29 of 100 lines against a floor of 29 is a pass. the report's own

    `line-rate="0.29"` times 100 is 28.999999999999996 in a float.
    """
    assert 0.29 * 100 < 29
    work = place(tmp_path, monkeypatch, {"overall": 29})
    write(work, report({"a.py": [1] * 29 + [0] * 71}, rate=0.29))
    assert gate(work).run("x")


def test_a_line_two_classes_share_is_one_line(tmp_path, monkeypatch):
    """a tool that writes one class per type writes a file once per type."""
    work = place(tmp_path, monkeypatch, {"overall": 100})
    text = report({"a.py": [1, 0]}).replace(
        "</classes>",
        '<class name="b" filename="a.py"><lines><line number="2" hits="3"/>'
        "</lines></class></classes>")
    write(work, text)
    r = gate(work).run("x")
    assert r
    assert r.detail == "100% of 2 lines, overall floor is 100"


WRITES_REPORT = [sys.executable, "-c",
                 "open('coverage.xml', 'w').write(" + repr(
                     report({"a.py": [1, 1, 1, 0]})) + ")"]


def a_run(tmp_path, monkeypatch, overall):
    """a command gate writes the report in the workdir, coverage reads it."""
    work = place(tmp_path, monkeypatch, {"overall": overall})
    flow = tmp_path / "flows" / "covered"
    flow.mkdir(parents=True)
    (flow / "worker.md").write_text("you are the worker.\n", encoding="utf-8")
    (flow / "instructions.md").write_text("one step.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: covered\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "    gates:\n"
        "      - gate: command\n"
        "        command: " + json.dumps(WRITES_REPORT) + "\n"
        "      - gate: coverage\n"
        "journal: false\n"
        "provider:\n"
        "  provider: fake\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "covered", "--force",
                                      "--workdir", str(work)])
    engine.main()
    return "".join((p / "gates.md").read_text(encoding="utf-8")
                   for p in (tmp_path / "runs").iterdir()
                   if (p / "gates.md").exists())


def test_a_run_holds_its_own_report_to_the_project_floor(tmp_path, monkeypatch):
    assert "PASS coverage - 75% of 4 lines, overall floor is 70" in \
        a_run(tmp_path, monkeypatch, 70)


def test_a_run_under_the_project_floor_fails_the_gate(tmp_path, monkeypatch):
    assert "FAIL coverage - 75% of 4 lines, overall floor is 80" in \
        a_run(tmp_path, monkeypatch, 80)


def test_the_gate_is_registered():
    assert "coverage" in gates.registry
    with pytest.raises(ValueError):
        gates.build({"gate": "coverage-typo"})
