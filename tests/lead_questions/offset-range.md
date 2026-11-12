- behaviour: `--invert` with `--until` at or before `--since` prints every well-formed line. The empty window is the condition and invert negates it
  file: logsift/filters.py
  spec: allows TASK.md:134
- behaviour: the spec leaves open what range of offsets T may carry (for example `+24:00` or `+05:60`). TASK.md:48 limits only log-line offsets (hours 00-23, minutes 00-59)
  file: logsift/filters.py
  spec: nothing in the spec

HANDOFF
DID:
- Planned both features as testable behaviours: `filter --since/--until` (an inclusive/exclusive window compared as instants, with `error: invalid time: <T>`) and a new `top` command (top N by bytes or duration, ties in input order, lines `<value>\t<method>\t<path>`). No code or tests were written.
QUESTION: What offset range is valid in a `--since`/`--until` T (for example `+24:00` or `+05:60`), and is a T whose UTC value falls outside the years 0001-9999 an `invalid time`? TASK.md:48 limits only log-line offsets, and the request says nothing
RECOMMEND: apply the TASK.md:48 limits (hours 00-23, minutes 00-59) and treat a T outside UTC 0001-9999 as `error: invalid time: <T>`. That mirrors the log-time rule and avoids an OverflowError crash
SIZE: a few lines in filters.py plus three tests
MUST NOT MISS:
- decisions.md:15 - the ruling delegated to the planner: --invert with an empty window prints every well-formed line
END HANDOFF
