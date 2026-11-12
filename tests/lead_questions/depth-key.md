- behaviour: with `--depth N`, the key is `/` followed by the first N non-empty segments joined by `/`. Example: `--depth 2` on `/api/v1/users` gives `/api/v1`
  file: logsift/count.py
  spec: adds to TASK.md:75
- open: the spec does not say which error wins when `--depth` has an invalid value and `--by` is not `path` (e.g. `--by ip --depth 0`)
- open: the spec does not say how a target not starting with `/` is grouped. Example: `*`, which by the request's rule would become `/*`

HANDOFF
DID:
- Planned `count --depth N` (it works only with `--by path` and groups paths by their first N non-empty segments) as 17 testable behaviours, 4 open points and 2 coverage gaps; no code or tests written
QUESTION: When `--by` is not `path` and the `--depth` value is also invalid (e.g. `count --by ip --depth 0`), which error is printed, `--depth needs --by path` or `invalid --depth: 0`? It turns on TASK.md:10, which allows exactly one error line
RECOMMEND: print `error: --depth needs --by path` first. Whether `--depth` is allowed at all is checked before its value, which matches the request's order of sentences
SIZE: one line ordering in logsift/cli.py plus one test
QUESTION: Is a target that does not start with `/` (e.g. `*` or `http://h/x`) grouped by the same rule (giving `/*` and `/http:/h`)? It turns on TASK.md:52, which leaves the target free
RECOMMEND: yes, apply the rule as written, since the request defines the key purely from non-empty segments
SIZE: no code beyond the rule; one test
MUST NOT MISS:
- TASK.md:10 - an error is exactly one `error: ` line on stderr, nothing on stdout, exit 2
END HANDOFF
