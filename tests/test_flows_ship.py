import pathlib
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner import prompts


def flows_in(root):
    return sorted(p.name for p in pathlib.Path(root).iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def test_every_shipped_flow_parses():
    for name in flows_in("flows"):
        spec = runner.config(name)
        assert spec.name
        assert spec.steps


def test_every_step_has_a_prompt_file_that_exists():
    for name in flows_in("flows"):
        for step in runner.steps(name):
            assert prompts.flow_path(name, step).exists(), (name, step)


def test_every_flow_declares_what_it_promises():
    for name in flows_in("flows"):
        spec = runner.config(name)
        assert spec.promises.invariants, name


def test_the_examples_parse_too():
    prompts.FLOW_ROOT[0] = "examples"
    try:
        for name in flows_in("examples"):
            spec = runner.config(name)
            assert spec.steps
            for step in runner.steps(name):
                assert prompts.flow_path(name, step).exists(), (name, step)
    finally:
        prompts.FLOW_ROOT[0] = "flows"


def test_the_examples_need_no_key():
    prompts.FLOW_ROOT[0] = "examples"
    try:
        for name in flows_in("examples"):
            spec = runner.config(name)
            assert (spec.get("provider") or {}).get("provider") == "fake", name
    finally:
        prompts.FLOW_ROOT[0] = "flows"
