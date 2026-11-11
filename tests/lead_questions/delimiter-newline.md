- behaviour: `--delimiter ab` (two characters) gives `error: invalid --delimiter: ab` on stderr, exit 2, nothing on stdout
  file: gradebook/cli.py (_check_options)
  spec: adds to TASK.md:23
- behaviour: `--delimiter` set to CR, and set to LF, each gives `error: invalid --delimiter: <C>` with exit 2 (the raw character is printed, so for LF stderr is no longer exactly one line)
  file: gradebook/cli.py
  spec: adds to TASK.md:23
- open: printing LF or CR raw in `error: invalid --delimiter: <C>` breaks "exactly one line to stderr" (TASK.md:11); the request gives no escaping

HANDOFF
DID:
- Planned `--delimiter C` as an addition to TASK.md:43 with no conflict: default comma unchanged, quoting/trim/field-count rules carry over, output unchanged, validated before input
BECAUSE:
- Raw LF/CR in the error message would break the one-line stderr rule
  from: TASK.md:11
  led to: ASSUMED The error prints the rejected
QUESTION: An LF or CR in `--delimiter` printed raw in `error: invalid --delimiter: <C>` breaks the one-line stderr rule at TASK.md:11; should it be printed raw or escaped?
RECOMMEND: print it raw as the request writes it, and test only exit 2, the `error: invalid --delimiter: ` prefix and empty stdout for CR/LF
SIZE: one test assertion; no code change either way
MUST NOT MISS:
- TASK.md:43 - add new lines under it; do not reword or remove any existing line
END HANDOFF
