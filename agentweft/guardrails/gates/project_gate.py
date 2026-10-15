import yaml

from agentweft.orchestrate import project

from .base import Gate, register
from .command_gate import CommandGate

PASSED_ON = ("expect", "timeout")


@register
class ProjectGate(Gate):
    """a gate project.yml declares, run by its name through the command gate.

    the flow says which one and where it goes, on the step whose work it
    checks. the argv only comes from project.yml, the same way coverage takes
    its number from there, so a command written on the gate is refused.
    """

    name = "project"
    options = ("name",) + PASSED_ON

    def run(self, text):
        said = self.opts.get("name")
        if not said:
            return self.fail("no name. the command comes from project.yml")
        if not project.path().exists():
            return self.fail("no project.yml at " + str(project.path())
                             + ", so there is no gate " + str(said))
        try:
            argv = project.read().gate(said)
        except ValueError as e:
            return self.fail(str(e))
        except yaml.YAMLError as e:
            return self.fail("project.yml: " + str(e))
        if not argv:
            return self.fail("project.yml has no gate " + str(said))
        inner = CommandGate(command=argv, **dict(
            (k, v) for k, v in self.opts.items() if k in PASSED_ON))
        inner.where = self.where
        r = inner.run(text)
        return (self.ok if r.ok else self.fail)(str(said) + ": " + r.detail)
