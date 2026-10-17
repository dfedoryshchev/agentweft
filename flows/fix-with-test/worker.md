# worker

here is a bug. do not fix it.

{TASK}

write a test that fails because of it, and write it into the file it goes
in. the test must fail on the code as it stands right now - if you cannot
make it fail, say so and stop, because then i have described the bug wrong.
write the minimum that fails for the reason the report gives, and nothing
more: the other cases the fix will reach are written after it is green, by
the step that makes it green, once nothing has stopped the run. take what the
test expects from the report or the spec, never from what the code gives back.

before you write it, find every place the report's symptom can come from:
follow the input from where the product reads it to where the symptom shows
(for a command, from its entry point through each module that handles the
input), and try the report's words on each. a probe run may show you where it
breaks; it never sets what a test expects. DID names every cause you found;
the test drives one, and the others stay in DID for the step that makes it
green. a place you checked and ruled out is a TRIED line, with why.

the spec is TASK.md, with any SPEC*.md and docs/spec* beside it. if a line of
it says the code does what it should, the report is wrong, not the code, and
so is a test handed over with the report that asks for what that line rules
out. write no test. answer these two lines, each on its own:

    CONFLICT: <file>:<line> "<the spec line, word for word>"
    request: <the report's words>

the run stops there and the question goes to a person. the quote is checked
against that line as the run found it, and a quote that is not there fails
your answer.

the order of two errors the spec does not fix is yours; follow the code's
convention and say so under ASSUMED.

say how it fails and where the tests are, each on its own line, before them:

    FAILS: <the error the unpatched code gives>
    TEST: <the test file, relative to where you are>

then the tests, and nothing else before the handoff block. the test file is
run after you answer, and a file that is not there or does not fail stops
the run. in the block, DID names each cause as you understand it, and
VERIFIED carries the run that showed the first test failing.
