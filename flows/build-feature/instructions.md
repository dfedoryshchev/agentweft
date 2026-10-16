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
- a request that adds an option, flag, field or command, and leaves what a
  line of the spec requires true whenever it is not used, adds to the spec
  and is not a conflict. a conflict is a request that asks, for the same
  inputs and options a line already covers, for something other than what
  that line requires. a line that forbids or requires something in every
  case, with `never`, `always`, `only` or `must`, already covers every
  option, so an option that switches it off is a conflict.

  with fields separated by commas in the spec, a `--delimiter` option used
  only when given adds to it. with an amount that is never 0, an
  `--allow-zero` option contradicts it.
- when the request asks for something a line of the spec rules out, which one
  wins is not yours to decide. answer these two lines, each on its own:

      CONFLICT: <file>:<line> "<the spec line, word for word>"
      request: <the request's words>

  the run stops there and the question goes to a person. the quote is
  checked against that line as the run found it, and a quote that is not
  there fails your answer.
