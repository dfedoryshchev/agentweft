import pathlib
import re

import pytest

tomllib = pytest.importorskip("tomllib")

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_build_floor_can_read_the_license_as_written():
    """setuptools reads a license given as plain text only from 77 on."""
    got = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert isinstance(got["project"]["license"], str)
    floor = [r for r in got["build-system"]["requires"]
             if r.startswith("setuptools")]
    assert len(floor) == 1
    least = re.search(r">=\s*(\d+)", floor[0])
    assert least and int(least.group(1)) >= 77
