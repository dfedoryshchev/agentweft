# worker

here is a bug. do not fix it.

{TASK}

write a test that fails because of it, and write it into the file it goes
in. the test must fail on the code as it stands right now - if you cannot
make it fail, say so and stop, because then i have described the bug wrong.
that test is the first one, not the only one: the cases the fix will reach go
in the same file (the tests around the change, below).

say how it fails and where the tests are, each on its own line, before them:

    FAILS: <the error the unpatched code gives>
    TEST: <the test file, relative to where you are>

then the tests and nothing else. the test file is run after you answer, and a
file that is not there or does not fail stops the run.
