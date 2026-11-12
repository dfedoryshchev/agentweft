- behaviour: TASK.md gains a `top` section that names `--n` as a count, plus (if a module is added) a row in the module table, added as new lines only: every line the run started with stays word for word
  file: TASK.md
  spec: adds to TASK.md:31 "- Options that take a count (named below) take a whole number written in digits, 1 or more; any"

HANDOFF
DID:
- Planned the `top` command as behaviours a test can check. None contradicts TASK.md, so there is no CONFLICT line. One question about where the new TASK.md section goes is left for the person.
BECAUSE:
- Line 5 says the last section fixes the module layout. Appending `## 7. top` after it would make line 5 false, and renumbering section 6 would rewrite a line, which stops the run
  from: TASK.md:5
  led to: QUESTION
QUESTION: Where should the `top` section go in TASK.md? Appending it after section 6 makes TASK.md:5 ("The last section fixes the module layout") false, and renumbering section 6 at TASK.md:141 rewrites a line. Should it go between TASK.md:139 and TASK.md:141 under a heading that changes no existing line (for example `## 5a. top`)?
RECOMMEND: Insert a new `## 5a. top` section between lines 139 and 141, and add any new module row after TASK.md:155. That keeps every existing line word for word and keeps line 5 true.
SIZE: about 10 new lines in TASK.md only
MUST NOT MISS:
- TASK.md:5 - "The last section fixes the module layout" must stay true after the TASK.md edit
TRIED:
- Marking TASK.md:5 as `breaks` - dropped, because the section can go before section 6 without making line 5 false; it went to the QUESTION instead
END HANDOFF
