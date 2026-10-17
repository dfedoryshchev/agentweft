"""a gate project.yml declares is run by name, through the command gate, in
the run's place."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.orchestrate import workflow
from agentweft.runner import stops

from test_red_order import NL, a_flow, a_repo, folders, read, running

PASS = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "import sys; print('lint said no'); sys.exit(1)"]
# leaves a file in the place it ran in, so a test can see it ran there
TOUCH = [sys.executable, "-c", "open('ran', 'w').close()"]


def project_yml(tmp_path, monkeypatch, gates):
    home = tmp_path / "orchestrate"
    home.mkdir()
    monkeypatch.setattr(workflow, "ROOT", [str(home)])
    (home / "project.yml").write_text(
        "project:" + NL + "  name: here" + NL + "gates:" + NL
        + "".join("  " + k + ": " + json.dumps(v) + NL
                  for k, v in gates.items()), encoding="utf-8")


def gated(name):
    return ("  - role: worker" + NL + "    prompt: worker.md" + NL
            + "    gates:" + NL + "      - gate: project" + NL
            + "        name: " + name + NL)


def gate_lines(folder):
    out = []
    for line in read(folder / "steps.jsonl").splitlines():
        out.extend(json.loads(line).get("gates") or [])
    return [g for g in out if g["gate"] == "project"]


def test_a_failing_project_gate_stops_the_run_and_is_recorded(tmp_path,
                                                             monkeypatch):
    place = a_repo(tmp_path / "repo")
    project_yml(tmp_path, monkeypatch, {"lint": FAIL})
    a_flow(tmp_path, "build", gated("lint"))
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")})
    assert set(called) == {"worker.md"}
    assert code == stops.exit_code(stops.GATE)
    said = gate_lines(folders()[-1])
    assert said and not said[-1]["ok"]
    assert said[-1]["detail"].startswith("lint: exit 1")
    assert "lint said no" in said[-1]["detail"]


def test_a_passing_project_gate_runs_in_the_place_and_is_recorded(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    project_yml(tmp_path, monkeypatch, {"lint": PASS, "touch": TOUCH})
    a_flow(tmp_path, "build", gated("touch"))
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({}, "done")})
    assert code == stops.EXIT_OK
    assert (place / "ran").exists()
    said = gate_lines(folders()[-1])
    assert said and said[-1]["ok"]
    assert said[-1]["detail"] == "touch: exit 0"


def test_an_unknown_project_gate_is_a_load_error_naming_it(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    place = a_repo(tmp_path / "repo")
    project_yml(tmp_path, monkeypatch, {"lint": PASS})
    a_flow(tmp_path, "build", gated("lnt"))
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")})
    assert code == 1
    assert called == []
    out = capsys.readouterr().out
    assert "lnt" in out and "lint" in out


def test_a_named_skip_is_recorded_and_the_command_is_not_run(tmp_path,
                                                            monkeypatch):
    place = a_repo(tmp_path / "repo")
    project_yml(tmp_path, monkeypatch, {"touch": TOUCH})
    a_flow(tmp_path, "build", gated("touch"))
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({}, "done")},
                      "--skip", "project", "the linter is down")
    assert code == stops.EXIT_OK
    assert not (place / "ran").exists()
    said = gate_lines(folders()[-1])
    assert said and said[-1]["ok"]
    assert said[-1]["detail"] == "not run - skipped: the linter is down"


def check(tmp_path, monkeypatch, gate, gates=None):
    if gates is not None:
        project_yml(tmp_path, monkeypatch, gates)
    else:
        monkeypatch.setattr(workflow, "ROOT", [str(tmp_path / "nowhere")])
    return (spec.check_gates("step 0: ", [gate])
            + spec.check_project_gates([{"gates": [gate]}]))


def test_the_checker_wants_a_name(tmp_path, monkeypatch):
    bad = check(tmp_path, monkeypatch, {"gate": "project"}, {"lint": PASS})
    assert bad == ["step 0: gate project needs a name, one of: lint"]


def test_the_checker_names_what_project_yml_has(tmp_path, monkeypatch):
    bad = check(tmp_path, monkeypatch, {"gate": "project", "name": "lnt"},
                {"lint": PASS, "tests": PASS})
    assert bad == ["step 0: project.yml has no gate lnt, did you mean lint?."
                   " there is: lint, tests"]


def test_the_checker_says_when_project_yml_declares_no_gates(tmp_path,
                                                             monkeypatch):
    bad = check(tmp_path, monkeypatch, {"gate": "project", "name": "lint"},
                {})
    assert bad == ["step 0: project.yml has no gate lint. there is: none"]


def test_the_checker_refuses_a_project_gate_with_no_project_yml(
        tmp_path, monkeypatch):
    bad = check(tmp_path, monkeypatch, {"gate": "project", "name": "lint"})
    assert len(bad) == 1
    assert bad[0].startswith("step 0: gate project lint needs a project.yml")


def test_a_command_written_on_the_gate_is_refused(tmp_path, monkeypatch):
    bad = check(tmp_path, monkeypatch,
                {"gate": "project", "name": "lint", "command": PASS},
                {"lint": PASS})
    assert len(bad) == 1 and "has no option command" in bad[0]


def test_a_project_yml_gone_by_the_time_it_runs_is_a_failure(tmp_path,
                                                            monkeypatch):
    from agentweft.guardrails import gates
    project_yml(tmp_path, monkeypatch, {"lint": PASS})
    g = gates.build({"gate": "project", "name": "lint"}, where=tmp_path)
    assert g.run("x")
    (tmp_path / "orchestrate" / "project.yml").unlink()
    r = g.run("x")
    assert not r and "no project.yml" in r.detail


def the_place_says(place, name, argv):
    home = place / "orchestrate"
    home.mkdir()
    (home / "project.yml").write_text(
        "project:" + NL + "  name: there" + NL + "gates:" + NL + "  " + name
        + ": " + json.dumps(argv) + NL, encoding="utf-8")


def test_the_project_yml_read_is_the_one_in_the_run_s_place(tmp_path,
                                                            monkeypatch):
    place = a_repo(tmp_path / "repo")
    monkeypatch.setattr(workflow, "ROOT", ["orchestrate"])
    the_place_says(place, "touch", TOUCH)
    (tmp_path / "orchestrate").mkdir()
    (tmp_path / "orchestrate" / "project.yml").write_text(
        "project:" + NL + "  name: here" + NL + "gates:" + NL + "  touch: "
        + json.dumps(FAIL) + NL, encoding="utf-8")
    a_flow(tmp_path, "build", gated("touch"))
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({}, "done")})
    assert code == stops.EXIT_OK
    assert (place / "ran").exists()


def test_a_place_with_a_project_yml_runs_where_the_start_has_none(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    monkeypatch.setattr(workflow, "ROOT", ["orchestrate"])
    the_place_says(place, "touch", TOUCH)
    a_flow(tmp_path, "build", gated("touch"))
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")})
    assert code == stops.EXIT_OK and called == ["worker.md"]


def test_the_reject_and_fence_read_the_place_s_project_yml(tmp_path,
                                                         monkeypatch):
    from agentweft.guardrails import fence, gates
    place = a_repo(tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workflow, "ROOT", ["orchestrate"])
    (place / "orchestrate").mkdir()
    (place / "orchestrate" / "project.yml").write_text(
        "project:" + NL + "  name: there" + NL + "standards:" + NL
        + "  immediate_reject:" + NL + "    - rule: no prints" + NL
        + "      pattern: print" + NL + "fence:" + NL + "  skip: []" + NL,
        encoding="utf-8")
    r = gates.build({"gate": "reject"}, where=place).run("print(1)")
    assert not r and "no prints" in r.detail
    assert fence.at(place) is not None


def rewrites_to(argv):
    return ("project:" + NL + "  name: here" + NL + "gates:" + NL
            + "  lint: " + json.dumps(argv) + NL)


def test_a_step_that_rewrites_project_yml_is_held_to_the_gate_it_started_with(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    monkeypatch.setattr(workflow, "ROOT", ["orchestrate"])
    the_place_says(place, "lint", FAIL)
    a_flow(tmp_path, "build", gated("lint"))
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({"orchestrate/project.yml":
                                      rewrites_to(PASS)}, "done")})
    assert code == stops.exit_code(stops.GATE)
    said = gate_lines(folders()[-1])
    assert said and not said[-1]["ok"] and "lint said no" in said[-1]["detail"]


def test_a_resume_holds_the_project_yml_the_run_started_with(tmp_path,
                                                            monkeypatch):
    place = a_repo(tmp_path / "repo")
    monkeypatch.setattr(workflow, "ROOT", ["orchestrate"])
    the_place_says(place, "lint", FAIL)
    a_flow(tmp_path, "build", gated("lint"))
    running(tmp_path, monkeypatch, place, "build",
            {"worker.md": ({"orchestrate/project.yml": rewrites_to(PASS)},
                           "done")})
    first = folders()[-1]
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({}, "done")}, "--resume", first.name)
    assert code == stops.exit_code(stops.GATE)
    said = gate_lines(folders()[-1])
    assert said and not said[-1]["ok"]


def test_a_step_that_writes_a_fence_skip_into_project_yml_does_not_widen_it(
        tmp_path, monkeypatch):
    from agentweft.guardrails import fence
    from agentweft.orchestrate import project
    place = a_repo(tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workflow, "ROOT", ["orchestrate"])
    (place / "orchestrate").mkdir()
    (place / "orchestrate" / "project.yml").write_text(
        "project:" + NL + "  name: there" + NL + "fence:" + NL + "  skip: []"
        + NL, encoding="utf-8")
    held = project.hold(place)
    (place / "orchestrate" / "project.yml").write_text(
        "project:" + NL + "  name: there" + NL + "fence:" + NL
        + "  skip: [\"**\"]" + NL, encoding="utf-8")
    assert fence.at(place, held=held).skip == []
