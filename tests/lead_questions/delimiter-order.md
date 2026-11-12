- behaviour: `--delimiter` given LF gives `error: invalid --delimiter: \n` (backslash and `n`), and CR gives `error: invalid --delimiter: \r`. Either way it is exactly one line on stderr, exit 2. Test through `main([...])` directly, because argv on Windows may not carry CR or LF.
  file: gradebook/cli.py
  spec: breaks TASK.md:11
- note: the escaping is the call made under the ruling at decisions.md:16 ("Make the call yourself"). Every other character is echoed exactly as given.
  file: gradebook/cli.py
- open: when `--delimiter` and another option value (`--curve`, `--drop-lowest`) are both invalid, TASK.md:23 only says "option values" come first and does not order them. Nothing should be tested for this.
  file: gradebook/cli.py

HANDOFF
DID:
- Planned `--delimiter C` for every command as 21 testable behaviours plus 3 open points. Nothing in the spec contradicts it, so there is no CONFLICT.
QUESTION: When `--delimiter` and `--curve`/`--drop-lowest` are both invalid, which error is reported? TASK.md:23 only says "option values" come first
RECOMMEND: Leave it unspecified and untested for now; the code may check the delimiter last among option values
SIZE: one TASK.md line and one test if fixed
MUST NOT MISS:
- TASK.md:11 - every error is exactly one stderr line, so CR and LF must not be echoed raw
- TASK.md:23 - option-value errors come before stdin-twice and before any input is read
END HANDOFF
