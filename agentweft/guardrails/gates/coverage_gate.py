import fnmatch
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from agentweft.orchestrate import project

from .base import Gate, register

KNOWN = ("report", "floor", "paths")


@register
class CoverageGate(Gate):
    """a coverage report held to the floor project.yml gives.

    the flow says which report and which floor. the number itself only comes
    from project.yml, which is where test-qa's old number went.

    it reads cobertura xml, which most coverage tools can write, and counts
    lines, not branches. it runs nothing: the command that writes the report
    goes in a command gate before it. `critical` is a floor for some files,
    so it needs `paths` to say which.
    """

    name = "coverage"

    def run(self, text):
        odd = [k for k in self.opts if k not in KNOWN]
        if odd:
            return self.fail("unknown option " + ", ".join(odd)
                             + ". the number comes from project.yml")
        floor = self.opts.get("floor", "overall")
        if floor not in project.COVERAGE_KNOWN:
            return self.fail("no such coverage number " + str(floor)
                             + ". there is: " + ", ".join(project.COVERAGE_KNOWN))
        paths = self.opts.get("paths") or []
        paths = [paths] if isinstance(paths, str) else list(paths)
        if floor == "critical" and not paths:
            return self.fail("critical needs paths, the report does not know "
                             "which files are critical")

        if not project.path().exists():
            return self.fail("no project.yml at " + str(project.path())
                             + ", so there is no floor")
        try:
            want = project.read().coverage(floor)
        except ValueError as e:
            return self.fail(str(e))
        except yaml.YAMLError as e:
            return self.fail("project.yml: " + str(e))
        if want is None:
            return self.fail("project.yml has no coverage: " + floor)

        name = self.opts.get("report", "coverage.xml")
        where = Path(self.where) if self.where else Path(".")
        try:
            tree = ET.parse(str(where / name))
        except FileNotFoundError:
            return self.fail("no coverage report at " + str(where / name))
        except ET.ParseError as e:
            return self.fail("cannot read " + name + ": " + str(e))

        # one file can be written once per class in it, so a line is keyed on
        # the file and covered if any of its copies was hit.
        hit = {}
        for cls in tree.iter("class"):
            fname = cls.get("filename", "")
            if paths and not any(fnmatch.fnmatchcase(fname, p) for p in paths):
                continue
            for line in cls.iter("line"):
                key = (fname, line.get("number"))
                hit[key] = hit.get(key, False) or int(line.get("hits", 0)) > 0

        if not hit:
            return self.fail("no lines in " + name
                             + (" under " + ", ".join(paths) if paths else ""))
        covered = sum(1 for v in hit.values() if v)
        said = (str(covered * 100 // len(hit)) + "% of " + str(len(hit))
                + " lines, " + floor + " floor is " + str(want))
        if covered * 100 >= want * len(hit):
            return self.ok(said)
        return self.fail(said)
