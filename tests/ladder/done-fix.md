# fix-with-test fix-with-test-2026-01-05-213305: done - The letter now comes from the printed (rounded) percentage, as TASK.md:120 says, not the exact one. Cause: `grade()` passed `exact` to `letter()`. Fix: it now passes `Fraction(hundredths, 100)`.

fix-with-test ran worker.md -> patcher.md in 150.9s on: # instructions.
suite: 7 of 7 gates passed; red first: shown on patcher.md, 3 of 3 new tests red without the fix and green with it: tests/test_letter.py::test_letter_at_min, tests/test_letter.py::test_letter_decimal_min, tests/test_report.py::test_letter_uses_printed_percentage; added after green: 2 coverage, 0 pins.
changed: 3 files, 0 commits (from git, below).

## the one decision
- none: nothing waits on you.

## why
patcher did:
- The letter now comes from the printed (rounded) percentage, as TASK.md:120 says, not the exact one. Cause: `grade()` passed `exact` to `letter()`. Fix: it now passes `Fraction(hundredths, 100)`.
- tally/grading.py: changed line 32 only. `letter(grades, shown)` keeps its name and signature.
- The worker named one cause (grading.py:32), and this patch fixes it. All letter output goes through `commands._row` and then `grade()`.
assumed - tell me if wrong:
- worker: The test goes in tests/test_report.py, using the existing `make` fixture? why: the existing report tests use this style. if wrong: only where the test lives changes.
- patcher: A min with more than two decimals is compared against the printed value? why: TASK.md:120 says the comparison uses the PRINTED percentage. if wrong: the patch would need a different design.

## not done
not verified:
- patcher: `report --format json` near a boundary - not tested on its own: it prints the same `Row.letter` as text output
- patcher: The `exact is None` branch of `grade()` - the patch does not reach it
doubts, left as they are:
- `rank` already uses `hundredths`, the printed value. I did not touch it (patcher)

## product gaps
- none

## full record
every line the run left, section by section; each step's own answer is in runs/fix-with-test-2026-01-05-213305/steps/ and its record in runs/fix-with-test-2026-01-05-213305/steps.jsonl.

## assumed - tell me if wrong
- worker: The test goes in tests/test_report.py, using the existing `make` fixture? why: the existing report tests use this style. if wrong: only where the test lives changes.
- patcher: A min with more than two decimals is compared against the printed value? why: TASK.md:120 says the comparison uses the PRINTED percentage. if wrong: the patch would need a different design.

## doubts
- patcher: `rank` already uses `hundredths`, the printed value. I did not touch it

## changed
- tally/grading.py +1 -1 (uncommitted), lines 32
- tests/test_report.py +7 -0 (uncommitted), lines 69-75
- tests/test_letter.py +30 -0 (untracked), lines 1-30
- git status --short:
     M tally/grading.py
     M tests/test_report.py
    ?? tests/test_letter.py
- git log --oneline 5d8ffbb..HEAD: prints nothing

## read
- worker.md read: TASK.md (whole file); tally/grading.py (whole file); tally/commands.py (whole file)
  said: tally/grading.py:24-32 - `letter` is given `exact`, not the rounded value
  said: tally/commands.py:52-57 - `_row` is the only place that calls `grade`
- patcher.md read: tally/grading.py (whole file); TASK.md:109-128; tests/test_report.py:1-60
  said: tally/grading.py:1-45 - `grade()` passed `exact` to `letter`
  said: TASK.md:109-128 - rules for rounding and the letter

## tests and checks
- worker.md: PASS red-test - red, exit 1 (python -m pytest -q tests/test_report.py)
- worker.md: PASS test-edits - tests/test_report.py: 1 test added, none the run started with changed
- patcher.md: PASS red-test - green, exit 0 (python -m pytest -q tests/test_report.py)
- patcher.md: PASS red-first - 3 of 3 new tests red without the fix and green with it (python -m pytest -q -p no:cacheprovider --junitxml={results} {test})
- patcher.md: PASS command - exit 0 (python -m pytest -q)
- patcher.md: PASS test-edits - tests/test_report.py: 1 test added, none the run started with changed
- patcher.md: PASS start-tests - 35 tests the run started with pass against the product as it is now
- red first: shown on patcher.md, 3 of 3 new tests red without the fix and green with it; added after green: 2 coverage, 0 pins
- test order: red before any product code: red-test on worker.md (tests/test_report.py, written)
- tests/test_letter.py::test_letter_at_min: red without the fix (assertion), green with it; added after green, coverage
- tests/test_letter.py::test_letter_decimal_min: red without the fix (assertion), green with it; added after green, coverage - encodes TASK.md:120 (patcher)
- tests/test_report.py::test_letter_uses_printed_percentage: red without the fix (assertion), green with it
- test files touched: tests/test_report.py +7 -0; tests/test_letter.py +30 -0
- worker verified: The new test fails on the unpatched code for the reason the report gives | cmd: python -m pytest -q tests/test_report.py::test_letter_uses_printed_percentage | saw: 1 failed in 0.20s -> backed
- patcher verified: The whole suite passes with the patch | cmd: python -m pytest -q | saw: 38 passed in 5.26s -> backed

## see the fix by hand
- red without the fix and green with it, as the red-first gate on patcher.md ran them:
    python -m pytest -q -p no:cacheprovider tests/test_letter.py::test_letter_at_min
    python -m pytest -q -p no:cacheprovider tests/test_letter.py::test_letter_decimal_min
    python -m pytest -q -p no:cacheprovider tests/test_report.py::test_letter_uses_printed_percentage
- without the fix: the run started at 5d8ffbb; the same command there, with tests/test_report.py as it is now, fails

## rulings
- pre-existing test tests/test_report.py +7 -0, add-only, no ruling needed
- none on record in decisions.md

## not verified
- patcher: `report --format json` near a boundary - not tested on its own: it prints the same `Row.letter` as text output
- patcher: The `exact is None` branch of `grade()` - the patch does not reach it

## carry forward
- task: # instructions (all of it in runs/fix-with-test-2026-01-05-213305/task.md)
- keep: TASK.md:120 - the letter is the first grade whose min is at or below the PRINTED (rounded) percentage (worker, patcher)
- tried and dropped: worker: `commands.report --failing` as a second cause - ruled out: it compares `r.hundredths`, the printed value
- tried and dropped: worker: `rank` - ruled out: it prints no letter

## retro
- worker.md 57.3s ($0.2569), won proved: no events
- patcher.md 93.6s ($0.3815), won delivered: no events
- total: 2 passes, 150.9s, $0.6384
- wall 194.9s: steps 150.9s, gates 39.8s, runner 4.2s

## run
- steps: worker.md 57.3s -> patcher.md 93.6s
- spend: 2 calls, 425440 tokens counted, $0.6384 priced
- done
- record: runs/fix-with-test-2026-01-05-213305/steps.jsonl, gates.jsonl, gates.md, steps/
- chain: 2 lines, head fc4078f1c00d65d8 (python run.py verify fix-with-test-2026-01-05-213305)
