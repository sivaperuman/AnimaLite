#!/usr/bin/env python3
"""Print the licence metadata of the pinned distributions, as installed.

Used to fill the Python-distribution table in THIRD_PARTY_NOTICES.md from the
packages' own metadata rather than from memory. Run inside the pinned
environment::

    python tools/collect_licenses.py

Output is a Markdown table. The result is a *starting point for review*: a
metadata string is what the publisher declared, not a completed legal
evaluation.
"""

from __future__ import annotations

from importlib.metadata import distributions

# Distributions imported by the installed animalite package at run time.
RUNTIME = {
    "annotated-types",
    "numpy",
    "pydantic",
    "pydantic-core",
    "typing-extensions",
    "typing-inspection",
}
# Environment tooling that is neither a project dependency nor redistributed.
EXCLUDE = {"animalite", "pip", "setuptools", "wheel"}

ROLES = {
    "pydantic": "linked (imported at run time)",
    "pydantic-core": "linked (transitive of pydantic)",
    "annotated-types": "linked (transitive of pydantic)",
    "typing-extensions": "linked (transitive of pydantic)",
    "typing-inspection": "linked (transitive of pydantic)",
    "numpy": "linked (imported at run time)",
    "pytest": "development only (external test runner)",
    "ruff": "development only (external tool)",
    "mypy": "development only (external tool)",
    "mypy-extensions": "development only (transitive of mypy)",
    "pathspec": "development only (transitive of mypy)",
    "librt": "development only (transitive of mypy)",
    "pluggy": "development only (transitive of pytest)",
    "iniconfig": "development only (transitive of pytest)",
    "packaging": "development only (transitive of pytest)",
    "pygments": "development only (transitive of pytest)",
}


def declared_license(metadata: object) -> str:
    """Best available declaration: License-Expression, then classifier, then License."""
    expression = metadata.get("License-Expression")  # type: ignore[attr-defined]
    if expression:
        return str(expression)
    classifiers = [
        c.split("::")[-1].strip()
        for c in (metadata.get_all("Classifier") or [])  # type: ignore[attr-defined]
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    raw = (metadata.get("License") or "").strip()  # type: ignore[attr-defined]
    if raw and len(raw) < 80 and "\n" not in raw:
        return raw
    if raw:
        return "(full text embedded in metadata - review directly)"
    return "UNDECLARED - verify before distribution"


def main() -> int:
    rows = []
    for dist in distributions():
        name = dist.metadata["Name"]
        key = name.lower().replace("_", "-")
        if key in EXCLUDE:
            continue
        group = "runtime" if key in RUNTIME else "dev"
        role = ROLES.get(key, "UNRECORDED - classify before distribution")
        rows.append(
            f"| `{name}` | {dist.metadata['Version']} | {declared_license(dist.metadata)} "
            f"| {group} | {role} | https://pypi.org/project/{name}/ |"
        )
    header = (
        "| Distribution | Version | License (as declared by the publisher) "
        "| Group | Role | Reference |"
    )
    print(header)
    print("| --- | --- | --- | --- | --- | --- |")
    for row in sorted(rows, key=str.lower):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
