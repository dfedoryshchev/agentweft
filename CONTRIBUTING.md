# contributing

early days. the shape is settled, the edges are not.

## running the tests

    pip install -r requirements-dev.txt
    pytest

they run on the fake provider, so nothing is called and nothing costs anything.

a change that moves what a shipped flow does fails its golden in
`tests/golden/`. read the changed lines it prints, then rewrite that golden
by name: `pytest tests/test_golden.py --update-golden build-feature/pass`.
a bare `--update-golden` only writes goldens that do not exist yet.

## the two extension points

if you want a check i have not thought of, write a **gate** - it takes the text
a step produced and returns pass or fail. or use the `command` gate and write a
program instead.

if you want a different model or service, write a **provider** - one method,
`ask(prompt, timeout)`.

both register themselves by subclassing and decorating. no plugin machinery.

## what i would rather not have

- a dependency that replaces something short. i have tried that twice this year
  and taken it back out twice.
- anything that makes a role prompt stop being markdown a person can read.
- a check that lives in a prompt when it could live in a gate.
