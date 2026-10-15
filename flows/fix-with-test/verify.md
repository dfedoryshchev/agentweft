# verify

here is a test and a patch. check the order was kept:

    PASS the test is written before the patch
    FAIL the test is written before the patch - <what happened>

then the same for: the test fails on the unpatched code, and the patch is the
smallest thing that turns it green.

a check the runner already ran is listed under "what the runner ran and saw
itself". that is a run, not a claim: a check it settles is a PASS that names
the line, not a question about an order you cannot see.
