# instructions - build feature

builds one feature, tests first.

the request:

{TASK}

the spec is TASK.md in the place you are working in, with any SPEC*.md and
docs/spec* beside it. the request is what someone asks for now; the spec is
what the project has already decided. read the spec before anything else,
and any file the request names.

- tests before code. this is the flow, not a preference.
- build what the request asks for and the spec allows. a thing neither asks
  for is not a bonus, it is a change nobody asked to review.
- when the request asks for something a line of the spec rules out, which one
  wins is not yours to decide. answer these two lines, each on its own:

      CONFLICT: <file>:<line> "<the spec line, word for word>"
      request: <the request's words>

  the run stops there and the question goes to a person. the quote is
  checked against that line as the run found it, and a quote that is not
  there fails your answer.
