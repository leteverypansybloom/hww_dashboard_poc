"""Regenerate constraints.txt, the pinned runtime set for every platform.

    python scripts/update_constraints.py

Resolves the runtime dependencies in pyproject.toml (the package's own,
plus its dashboard and bigquery extras) for CPython 3.11, 3.12 and 3.13
on Linux and Windows x86_64. It uses pip's resolver without installing
anything, so it needs network access to PyPI. A package that resolves
to different versions on different Pythons gets one pin per Python,
with an environment marker. The type stubs that mypy reads are pinned
to the versions installed in the current environment. Review the diff
before committing.
"""

import json
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CONSTRAINTS = PROJECT / "constraints.txt"
PYTHONS = ("3.11", "3.12", "3.13")
PLATFORMS = {
    "linux": (
        "manylinux_2_28_x86_64",
        "manylinux_2_17_x86_64",
        "manylinux2014_x86_64",
        "linux_x86_64",
    ),
    "windows": ("win_amd64",),
}
EXTRAS = ("dashboard", "bigquery")
STUBS = ("pandas-stubs", "types-openpyxl")
HEADER = """\
# Pinned runtime dependencies of hww-dashboard[dashboard,bigquery], for
# reproducible installs: CI, the GCP image and laptops
# (pip install -r requirements.txt -c constraints.txt).
# pyproject.toml keeps compatible ranges; this file pins one version of
# everything they resolve to. Every pin has wheels for CPython 3.11, 3.12
# and 3.13 on Linux and Windows x86_64.
#
# Regenerate with: python scripts/update_constraints.py
# then review the diff. Don't edit by hand.
"""


def requirements(pyproject: Path = PROJECT / "pyproject.toml") -> list[str]:
    """Read the runtime requirements from pyproject.toml.

    Args:
        pyproject: The project file.

    Returns:
        The package's dependencies, then those of each runtime extra.
    """
    with open(pyproject, "rb") as f:
        project = tomllib.load(f)["project"]
    found = list(project["dependencies"])
    for extra in EXTRAS:
        found += project["optional-dependencies"][extra]
    return found


def resolve(python: str, platforms: Sequence[str]) -> dict[str, str]:
    """Ask pip which versions it would install for one platform.

    Args:
        python: Python version, e.g. ``"3.11"``.
        platforms: Wheel platform tags pip may use.

    Returns:
        Package name (lower case) -> version.

    Raises:
        RuntimeError: pip could not resolve the set.
    """
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "report.json"
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--quiet",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--report",
            str(report),
            "--python-version",
            python,
            "--implementation",
            "cp",
            "--target",
            str(Path(scratch) / "target"),
        ]
        for platform in platforms:
            command += ["--platform", platform]
        done = subprocess.run(
            command + requirements(), capture_output=True, text=True
        )
        if done.returncode:
            raise RuntimeError(
                f"pip failed for Python {python}:\n{done.stderr}"
            )
        data = json.loads(report.read_text(encoding="utf-8"))
    return {
        item["metadata"]["name"].lower(): item["metadata"]["version"]
        for item in data["install"]
    }


def merge_pins(
    resolved: Mapping[tuple[str, str], Mapping[str, str]],
) -> list[str]:
    """Combine per-platform versions into constraint lines.

    Args:
        resolved: (Python version, OS) -> package -> version.

    Returns:
        Sorted lines: ``name==version``, or one line per Python version
        with a marker when Pythons need different versions.

    Raises:
        ValueError: One Python resolves a package differently on Linux
            and Windows, which a constraints file can't express simply.
    """
    lines = []
    names = sorted({name for pins in resolved.values() for name in pins})
    for name in names:
        by_python: dict[str, str] = {}
        for (python, _os_name), pins in resolved.items():
            if name not in pins:
                continue
            if by_python.setdefault(python, pins[name]) != pins[name]:
                raise ValueError(
                    f"{name} differs between platforms on Python {python}."
                )
        if len(set(by_python.values())) == 1:
            lines.append(f"{name}=={next(iter(by_python.values()))}")
        else:
            lines += [
                f'{name}=={v}; python_version == "{p}"'
                for p, v in sorted(by_python.items())
            ]
    return lines


def main() -> int:
    """Resolve every platform and rewrite constraints.txt.

    Returns:
        Exit code 0.
    """
    resolved = {
        (python, os_name): resolve(python, platforms)
        for python in PYTHONS
        for os_name, platforms in PLATFORMS.items()
    }
    stubs = [f"{name}=={version(name)}" for name in STUBS]
    text = (
        HEADER
        + "\n".join(merge_pins(resolved))
        + "\n\n# Type stubs, so mypy gives the same result everywhere.\n"
        + "\n".join(stubs)
        + "\n"
    )
    CONSTRAINTS.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {CONSTRAINTS.name}. Review the diff before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
