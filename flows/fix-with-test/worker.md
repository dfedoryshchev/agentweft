# worker

here is a bug. do not fix it.

{TASK}

write a test that fails because of it, and write it into the file it goes
in. the test must fail on the code as it stands right now - if you cannot
make it fail, say so and stop, because then i have described the bug wrong.
write the minimum that fails for the reason the report gives, and nothing
more: the other cases the fix will reach are written after it is green, by
the step that makes it green, once nothing has stopped the run. take what the
test expects from the report or the spec, never from running the code.

the spec is TASK.md, with any SPEC*.md and docs/spec* beside it. if a line of
it says the code does what it should, the report is wrong, not the code, and
so is a test handed over with the report that asks for what that line rules
out. write no test. answer these two lines, each on its own:

    CONFLICT: <file>:<line> "<the spec line, word for word>"
    request: <the report's words>

the run stops there and the question goes to a person. the quote is checked
against that line as the run found it, and a quote that is not there fails
your answer.

say how it fails and where the tests are, each on its own line, before them:

    FAILS: <the error the unpatched code gives>
    TEST: <the test file, relative to where you are>

then the tests, and nothing else before the handoff block. the test file is
run after you answer, and a file that is not there or does not fail stops
the run. in the block, DID names the cause as you understand it, and
VERIFIED carries the run that showed the first test failing.
