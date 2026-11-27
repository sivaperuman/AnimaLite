#!/usr/bin/env python3
"""Turn a ``pip install --report`` JSON document into the pinned constraints file.

Usage::

    pip install --dry-run --ignore-installed --report report.json \
        'pydantic>=2.9,<3' 'numpy>=1.26,<3' \
        'pytest>=8.3,<9' 'ruff>=0.6,<1' 'mypy>=1.11,<2'
    python tools/write_constraints.py report.json > constraints/dev-linux-cpython311.txt

The version ranges stay authoritative in pyproject.toml; this file only records
the exact resolution that the reported checks were run against.
"""

from __future__ import annotations

import json
import sys

RUNTIME_DISTRIBUTIONS = {
    "annotated-types",
    "numpy",
    "pydantic",
    "pydantic-core",
    "typing-extensions",
    "typing-inspection",
}

HEADER = """\
# AnimaLite pinned development environment
#
# Resolved on CPython 3.11 / Linux x86_64 (manylinux wheels) and used for every
# check reported in docs/verified-commands.md. Regenerate with:
#
#   pip install --dry-run --ignore-installed --report report.json \\
#       'pydantic>=2.9,<3' 'numpy>=1.26,<3' 'pytest>=8.3,<9' 'ruff>=0.6,<1' 'mypy>=1.11,<2'
#   python tools/write_constraints.py report.json > constraints/dev-linux-cpython311.txt
#
# Use as a constraints file so the pyproject ranges stay authoritative:
#   pip install -e '.[dev]' -c constraints/dev-linux-cpython311.txt
#
# Hashes are the sha256 of the exact artifact pip selected. They are recorded as
# comments rather than --hash lines so this file stays usable as a -c constraints
# file; pass --require-hashes with a requirements file when hash pinning is
# enforced. Licenses for these distributions are recorded in THIRD_PARTY_NOTICES.md.
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        report = json.load(handle)

    rows = []
    for item in report["install"]:
        metadata = item["metadata"]
        download = item.get("download_info", {})
        digest = download.get("archive_info", {}).get("hashes", {}).get("sha256")
        rows.append((metadata["name"], metadata["version"], digest))
    rows.sort(key=lambda row: row[0].lower().replace("_", "-"))

    print(HEADER)
    for name, version, digest in rows:
        group = "runtime" if name.lower().replace("_", "-") in RUNTIME_DISTRIBUTIONS else "dev"
        print(f"# {group}  sha256:{digest}")
        print(f"{name}=={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
