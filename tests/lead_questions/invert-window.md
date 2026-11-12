- behaviour: with `--invert`, `--since 2026-10-12T08:16:40Z` prints only line 1, the well-formed request that does not meet the condition
  file: logsift/filters.py
  spec: allows TASK.md:134
- behaviour: OPEN. With `--invert` and an `--until` at or before `--since`, the spec and the request don't say whether every well-formed line prints (the window "matches nothing", so the inverse is everything) or nothing prints. Unsure; see QUESTION
  file: logsift/filters.py
  spec: nothing in the spec
- behaviour: OPEN. The request doesn't limit the hour and minute range of a T offset (`+24:00`, `+05:60`). TASK.md:48 limits only log-line offsets to 00-23 / 00-59. Unsure; see QUESTION
  file: logsift/filters.py
  spec: nothing in the spec
- behaviour: OPEN. A T whose UTC value falls outside the years 0001-9999 (`0001-01-01T00:00:00+01:00`, `9999-12-31T23:59:59-01:00`) is valid in form, but the spec doesn't say whether it is an error or a usable bound
  file: logsift/filters.py
  spec: nothing in the spec
- behaviour: TASK.md gets a new section describing `top` (synopsis, field default, N default, order, tie rule, tab-separated line, `--n` as a count) inserted between line 135 and line 137. It must not renumber `## 6. Module layout (fixed)` and must not come after it, because TASK.md:5 says "The last section fixes the module layout". The heading form is OPEN; see QUESTION
  file: TASK.md
  spec: adds to TASK.md:31

HANDOFF
DID:
- Planned both feature requests, `filter --since/--until` and the `top` command, as testable behaviours. None of them contradicts or breaks a TASK.md line, so there is no CONFLICT.
ASSUMED:
- Fewer requests than N prints all of them, with no error
  why: no line says otherwise, and an error would go against "Inputs, warnings and errors work as for the other commands"
  if wrong: one test changes
QUESTION: With `--invert` and an `--until` at or before `--since`, should filter print every well-formed line (the inverse of a window that matches nothing) or nothing at all? TASK.md:134 "print the well-formed requests that do NOT meet the conditions" points to every line
RECOMMEND: print every well-formed line. `--invert` stays a plain negation and the window simply matches no request
SIZE: one test and one line in filters.py
QUESTION: Should a T offset beyond `+23:59` (for example `+24:00` or `+05:60`), or a T whose UTC instant falls outside years 0001-9999, be `error: invalid time: <T>`? TASK.md:48 limits only log offsets
RECOMMEND: reject offsets outside 00-23 / 00-59 to match TASK.md:48, and reject a T whose UTC value falls outside 0001-9999, like a malformed log time (TASK.md:49)
SIZE: a few lines in the T parser plus tests
QUESTION: What heading should the new `top` section in TASK.md get, given it can't renumber `## 6. Module layout (fixed)` (TASK.md:137) and TASK.md:5 requires that section to stay last?
RECOMMEND: insert `## 5a. top` between line 135 and line 137, so no existing line changes
SIZE: a TASK.md edit only
MUST NOT MISS:
- TASK.md:5 - "The last section fixes the module layout": the new top section can't go after section 6
- TASK.md:137 - the section heading can't be renumbered or rewritten; additions are new lines only
END HANDOFF
