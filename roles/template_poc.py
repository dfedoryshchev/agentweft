"""poc. nothing imports this.

every role prompt is a file plus a pile of fragments concatenated on the end,
and the only substitution is {INBOX} style env replacement done with str
.replace. it works. but the fragments are all-or-nothing - the reviewer wants
one extra block and i had to add a per-role EXTRA map to get it.

jinja would give me includes and conditionals for free:

    {% include "fragments/role-header.md" %}
    {% if role == "reviewer" %}{% include "fragments/reviewer-only.md" %}{% endif %}
"""
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("."), keep_trailing_newline=True)


def render(path, **ctx):
    return env.get_template(path).render(**ctx)


# the flow files are markdown that people read. putting {% %} in them means
# every prompt is now a template first and a prompt second, and a stray brace
# in an example breaks a run.


if __name__ == "__main__":
    import sys

    print(render(sys.argv[1], role=sys.argv[2] if len(sys.argv) > 2 else "worker"))
