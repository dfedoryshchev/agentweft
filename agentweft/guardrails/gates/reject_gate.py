import re

import yaml

from agentweft.orchestrate import project

from .base import Gate, register


@register
class RejectGate(Gate):
    """the immediate_reject rules in project.yml, checked against the output.

    a rule that is only a sentence goes to the role, which can agree with it
    and then not do it. a rule that carries a `pattern` is checked here, and
    the output matching it fails the step. the rules only come from
    project.yml, the same way coverage takes its floor from there.

    it reads what the step produced, so it holds a step whose output is the
    change itself - a patch, a diff, a file body. it does not go and read the
    working tree.
    """

    name = "reject"

    def run(self, text):
        if self.opts:
            return self.fail("unknown option " + ", ".join(self.opts)
                             + ". the rules come from project.yml")
        if not project.path().exists():
            return self.fail("no project.yml at " + str(project.path())
                             + ", so there are no rules")
        try:
            proj = project.read()
        except ValueError as e:
            return self.fail(str(e))
        except yaml.YAMLError as e:
            return self.fail("project.yml: " + str(e))
        rules = proj.rejects()
        if not rules:
            return self.fail("no immediate_reject rule in project.yml has a "
                             "pattern, so nothing can be checked")

        hit = [rule for rule, pattern in rules
               if re.search(pattern, text, re.M) is not None]
        if hit:
            return self.fail("rejected: " + "; ".join(hit))
        prose = len(proj.standards("immediate_reject")) - len(rules)
        return self.ok(str(len(rules)) + " rules checked, " + str(prose)
                       + " only asked for")
