- open: the exact stderr text for an empty value is not decided (`error: invalid --delimiter: ` with a trailing space, or with nothing after the colon); the same goes for CR/LF values, where printing C as-is breaks the "exactly one line" rule at TASK.md:11

HANDOFF
DID:
- Planned `--delimiter C` as an addition to TASK.md:43. It changes only how roster and scores are parsed, and leaves output and the comma default alone. No conflict found
BECAUSE:
- Every error is exactly one stderr line, so printing a CR or LF value as-is would break that rule
  from: TASK.md:11
  led to: QUESTION
QUESTION: What should `error: invalid --delimiter: <C>` print when C is CR, LF or empty, given that TASK.md:11 requires exactly one stderr line?
RECOMMEND: Print C as given for an empty value (the line ends at the colon and a space). For CR and LF, show the value with `repr`-style escaping, or note that they break the one-line rule, so the tests check only the prefix and the exit code until someone decides
SIZE: one line in cli.py plus one sentence in TASK.md
END HANDOFF
