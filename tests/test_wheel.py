import pathlib
import shutil
import subprocess
import sys
import zipfile

import pytest

pytest.importorskip("setuptools", minversion="77")

ROOT = pathlib.Path(".").resolve()


def data_files():
    """every file under the package that is not python: the prompts the
    resolver reads at run time."""
    pkg = ROOT / "agentweft"
    # state/ holds what local runs wrote; it is ignored by git and never shipped
    return sorted(p.relative_to(ROOT).as_posix() for p in pkg.rglob("*")
                  if p.is_file() and p.suffix not in (".py", ".pyc")
                  and "__pycache__" not in p.parts
                  and p.relative_to(pkg).parts[0] != "state")


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    # built from a copy so build/ and the egg-info land in the temp dir and
    # not in the checkout
    src = tmp_path_factory.mktemp("src")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy(ROOT / name, src / name)
    shutil.copytree(ROOT / "agentweft", src / "agentweft",
                    ignore=shutil.ignore_patterns("__pycache__"))
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [sys.executable, "-c",
         "import sys, setuptools.build_meta as b; b.build_wheel(sys.argv[1])",
         str(out)],
        cwd=src, check=True, capture_output=True)
    built = list(out.glob("*.whl"))
    assert len(built) == 1, built
    with zipfile.ZipFile(built[0]) as z:
        return set(z.namelist())


def test_the_package_has_prompts_to_ship():
    files = data_files()
    assert "agentweft/roles/library/reviewer.md" in files
    assert "agentweft/fragments/header.md" in files
    assert "agentweft/skills/output-rules/SKILL.md" in files


def test_the_wheel_carries_every_prompt_the_package_reads(wheel):
    missing = [f for f in data_files() if f not in wheel]
    assert not missing, missing
