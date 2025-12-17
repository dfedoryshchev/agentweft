# verify

here is a test and a patch. check the order was kept:

    PASS the test is written before the patch
    FAIL the test is written before the patch - <what happened>

then the same for: the test fails on the unpatched code, and the patch is the
smallest thing that turns it green.

do not improve the patch. do not restate it.
