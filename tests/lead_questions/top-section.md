- behaviour: TASK.md gets new bullets describing `--since` and `--until`, added under TASK.md:133 in section 5. No existing line is changed.
  file: TASK.md
  spec: adds to TASK.md:133
- behaviour: TASK.md gets a new section describing `top` that names `--n` as a count. No existing line is renamed or renumbered.
  file: TASK.md
  spec: adds to TASK.md:5
- open: where the new TASK.md section goes. TASK.md:5 says "The last section fixes the module layout", and TASK.md:137 is `## 6. Module layout (fixed)`. Inserting `## 6. top` would renumber line 137, which is a rewrite. Appending a section after it would make line 5 false. A number such as `## 5a. top` before line 137 avoids both. unsure; this choice belongs to the next step.

HANDOFF
DID:
- The two requests are planned as testable behaviours: `filter --since/--until` and a new `top` command. Neither contradicts any TASK.md line, so there is no CONFLICT.
BECAUSE:
- A new top section cannot renumber section 6 or follow it without changing line 137 or making line 5 false.
  from: TASK.md:5
  led to: QUESTION
QUESTION: Where should the `top` section go in TASK.md, given that TASK.md:5 says the last section is the module layout and TASK.md:137 numbers it `## 6`?
RECOMMEND: Insert it before line 137 as `## 5a. top`. Then no existing line changes and line 5 stays true.
SIZE: one new section in one file
MUST NOT MISS:
- TASK.md:137 - renumbering this heading changes an existing line, which stops the run
- TASK.md:5 - "The last section fixes the module layout"; appending top after section 6 makes this false
END HANDOFF
