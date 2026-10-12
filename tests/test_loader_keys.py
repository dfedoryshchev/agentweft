"""the loader takes the keys something reads, and refuses the rest at load.

a key the loader accepts and nothing reads looks like a setting and sets
nothing. a misspelt gate used to load fine and fail only once its step had
run and been paid for.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import reader, spec
from agentweft.roles import resolver
from agentweft.runner import prompts

# an en-dash: three bytes in UTF-8, and three different characters to cp1252
DASH = chr(0x2013)


def flow(**extra):
    raw = {"name": "x", "steps": [{"role": "worker"}]}
    raw.update(extra)
    return raw


def step(**keys):
    s = {"role": "reviewer"}
    s.update(keys)
    return {"name": "x", "steps": [s]}


def refused(raw):
    with pytest.raises(ValueError) as e:
        spec.load(raw)
    return str(e.value)


@pytest.mark.parametrize("key, value", [("temperature", 0.1),
                                        ("note", "a comment with a key on it")])
def test_a_flow_key_nothing_reads_is_refused(key, value):
    assert "unknown key " + key in refused(flow(**{key: value}))


def test_a_misspelt_flow_key_names_the_one_it_meant():
    assert "unknown key timout, did you mean timeout?" in \
        refused(flow(timout=10))


def test_a_misspelt_step_key_names_the_one_it_meant():
    assert "step 0: unknown key fanot, did you mean fanout?" in \
        refused(step(fanot=True))


def test_an_unregistered_gate_is_refused_at_load_with_the_known_ones():
    text = refused(step(gates=[{"gate": "regx", "pattern": "x"}]))
    assert "step 0: no such gate regx, did you mean regex?" in text
    for name in ("command", "coverage", "length", "red-test", "regex",
                 "reject", "verdict"):
        assert name in text


def test_a_gate_without_a_name_is_refused():
    assert "step 0: gate 0 has no gate name" in \
        refused(step(gates=[{"pattern": "x"}]))


def test_gates_are_a_list_of_mappings():
    assert "step 0: gates should be a list" in \
        refused(step(gates={"gate": "regex"}))
    assert "step 0: gate 0 should be a mapping" in \
        refused(step(gates=["regex"]))


def test_a_misspelt_gate_option_names_the_one_it_meant():
    text = refused(step(gates=[{"gate": "regex", "pattern": "x",
                                "presnt": False}]))
    assert "step 0: gate regex has no option presnt, did you mean present?" \
        in text


def test_every_gate_option_the_gates_read_is_taken():
    raw = step(gates=[
        {"gate": "regex", "pattern": "x", "present": False},
        {"gate": "length", "max_lines": 4, "min_lines": 1},
        {"gate": "verdict", "passes": 3},
        {"gate": "command", "command": ["x"], "expect": 0, "timeout": 5,
         "cold": {"command": ["y"], "threshold": 0.5}},
        {"gate": "red-test", "marker": "FAILS:", "red": True,
         "command": ["x"], "expect": 1, "timeout": 5},
        {"gate": "coverage", "report": "c.xml", "floor": "critical",
         "paths": ["a/*"]},
        {"gate": "reject"}])
    assert spec.check(raw) == []


def test_a_preflight_key_nothing_reads_is_refused():
    assert "step 0: preflight: unknown key treshold, did you mean " \
        "threshold?" in refused(step(preflight={"treshold": 0.5}))


def test_a_preflight_mode_is_flag_refuse_or_park():
    # anything but refuse used to read as flag, so a misspelt refuse let the
    # step through
    text = refused(step(preflight={"mode": "refues"}))
    assert "step 0: preflight mode should be one of flag, refuse, park" in text
    assert text.count("mode should be one of") == 1


def test_preflight_is_a_mapping():
    assert "step 0: preflight should be a mapping" in \
        refused(step(preflight="refuse"))


def test_a_context_key_nothing_reads_is_refused():
    assert "context: unknown key argument, did you mean arguments?" in \
        refused(flow(context={"command": ["x"], "argument": {}}))


def test_context_is_a_mapping():
    assert "context should be a mapping" in refused(flow(context=["x"]))


def test_a_promises_key_nothing_reads_is_refused():
    assert "promises: unknown key invariant, did you mean invariants?" in \
        refused(flow(promises={"invariant": ["x"]}))


def test_promises_is_a_mapping_and_invariants_a_list():
    assert "promises should be a mapping" in refused(flow(promises="x"))
    assert "promises: invariants should be a list" in \
        refused(flow(promises={"invariants": "one line"}))


SHIPPED = sorted(p.parent for p in Path("flows").glob("*/flow.yaml")) \
    + sorted(p.parent for p in Path("examples").glob("*/flow.yaml"))


@pytest.mark.parametrize("where", SHIPPED, ids=lambda p: str(p.as_posix()))
def test_every_shipped_flow_and_example_still_loads(where):
    text = (where / "flow.yaml").read_text(encoding="utf-8")
    assert spec.check(reader.read(text)) == []


def test_a_flow_file_with_an_en_dash_loads_intact(cp1252, tmp_path,
                                                  monkeypatch):
    (tmp_path / "dash").mkdir()
    (tmp_path / "dash" / "flow.yaml").write_text(
        "name: one " + DASH + " two\nsteps:\n  - role: worker\n",
        encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path)])
    assert runner.config("dash").name == "one " + DASH + " two"


def test_role_files_with_an_en_dash_are_read_intact(cp1252, tmp_path,
                                                    monkeypatch):
    (tmp_path / "fragments").mkdir()
    for name in resolver.FRAGMENTS + ["reviewer-only"]:
        (tmp_path / "fragments" / (name + ".md")).write_text(
            name + " " + DASH + "\n", encoding="utf-8")
    (tmp_path / "skills" / "one").mkdir(parents=True)
    (tmp_path / "skills" / "one" / "SKILL.md").write_text(
        "---\nname: one\n---\nskill " + DASH + "\n", encoding="utf-8")
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    (flow_dir / "instructions.md").write_text("flow " + DASH + "\n",
                                              encoding="utf-8")
    monkeypatch.setattr(resolver, "HERE", tmp_path)

    got = resolver.resolve({"steps": [{"role": "reviewer"}]}, flow_dir)

    for word in ("role-header", "skill", "flow", "reviewer-only"):
        assert word + " " + DASH in got["reviewer"]
