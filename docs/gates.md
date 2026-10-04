# gates

a gate is a check that is a program, not a prompt. it takes the text a step
produced and says pass or fail and why.

the reviewer is a prompt asking a model to be careful. a gate is a thing that
either matched or did not. they are for different jobs and i kept trying to
make the first one do the second.

## using them

    steps:
      - role: reviewer
        prompt: reviewer.md
        gates:
          - gate: regex
            pattern: "^## needs me"
          - gate: length
            max_lines: 40
          - gate: regex
            pattern: "TODO"
            present: false

results print under the step and land in `runs/<run id>/gates.md`. the journal
only hears about a gate that failed, because that one stops the run.

## the five

- **regex** - `pattern`, and `present: false` to require it is absent.
- **length** - `max_lines`, `min_lines`.
- **command** - `command: [...]`, with `{file}` replaced by a temp file holding
  the output. passes when the exit code matches `expect` (default 0). it runs
  in the run's `workdir` (see `docs/flows.md`), so it can check the work
  itself and not only what the step said about it.
- **red-test** - `marker` (default `FAILS:`) has to be in the output, or with
  `red: false` has to be gone from it.
- **coverage** - a cobertura xml report, `report` (default `coverage.xml`, read
  in the run's `workdir`), held to a floor from `project.yml` (see
  `docs/orchestrate.md`). `floor` names which one, `overall` (default) or
  `critical`; `critical` needs `paths`, the file patterns it covers. it counts
  lines, not branches, and a line is covered if any copy of it in the report
  was hit. it runs nothing, so the command that writes the report goes in a
  command gate before it. no `project.yml`, or one with no number for the
  floor, is a failure and not a pass.

## the number is not in the flow

    gates:
      - gate: command
        command: ["python", "-m", "pytest", "-q", "--cov", "--cov-report=xml"]
      - gate: coverage
      - gate: coverage
        floor: critical
        paths: ["billing/*"]

the flow says which report and which floor. what the floor IS comes from
`coverage:` in `project.yml`, and a number written on the gate is refused.
test-qa used to carry it as a sentence, where it could be read, agreed with and
then not met. it is a check now.

## why command matters

anything with a cli is a check now, without me writing an adapter. a linter, a
spell checker, a test runner, something that does not exist yet. the gate does
not know or care what it is - it looks at the exit code.

that is the whole extension point of this repo. if you want a check i have not
thought of, you do not write a plugin, you write a program.

fix-with-test is where it earns it. the closing step used to be a model reading
its own patch and saying the test passes now; it is `python -m pytest -q` and
an exit code, and a non-zero one stops the run.
