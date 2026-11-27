"""Import-order and layering regression tests.

`animalite.media` once could not be imported first: `media.encode` imported
`animalite.core.process`, which executed `animalite/core/__init__.py`, which
imported the service, which imported back into the half-initialised
`media.encode`. The CLI and the test suite happened to import `animalite.core`
first, so nothing caught it.

These tests import each public subpackage **first, in a fresh interpreter**, and
assert the documented dependency direction holds.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

PUBLIC_MODULES = [
    "animalite",
    "animalite.contracts",
    "animalite.errors",
    "animalite.proc",
    "animalite.resources",
    "animalite.admission",
    "animalite.media",
    "animalite.media.encode",
    "animalite.media.ffmpeg",
    "animalite.adapters",
    "animalite.core",
    "animalite.bench",
    "animalite.hostinfo",
    "animalite.fixtures",
    "animalite.cli",
]


@pytest.mark.parametrize("module", PUBLIC_MODULES)
def test_module_imports_first_in_a_fresh_interpreter(module):
    """Each module must import with no other animalite module already loaded."""
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, (
        f"`import {module}` failed as the first animalite import:\n{completed.stderr}"
    )


@pytest.mark.parametrize(
    ("lower", "forbidden"),
    [
        ("animalite.contracts", ("animalite.core", "animalite.media", "animalite.adapters")),
        ("animalite.errors", ("animalite.core", "animalite.media", "animalite.adapters")),
        ("animalite.proc", ("animalite.core", "animalite.media", "animalite.adapters")),
        ("animalite.resources", ("animalite.core", "animalite.media", "animalite.adapters")),
        ("animalite.admission", ("animalite.core", "animalite.media", "animalite.adapters")),
        ("animalite.media", ("animalite.core", "animalite.adapters")),
        ("animalite.adapters", ("animalite.core",)),
    ],
)
def test_lower_layers_do_not_import_higher_ones(lower, forbidden):
    """Enforce the documented direction: contracts/leaves < media < adapters < core.

    Checked by importing the lower layer in a fresh interpreter and inspecting
    ``sys.modules``, so it catches a transitive import as well as a direct one.
    """
    script = (
        f"import {lower}, sys, json;"
        f"print(json.dumps([m for m in sys.modules if m.startswith('animalite.')]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120, check=False
    )
    assert completed.returncode == 0, completed.stderr
    import json

    loaded = json.loads(completed.stdout)
    for name in forbidden:
        offenders = [m for m in loaded if m == name or m.startswith(name + ".")]
        assert not offenders, (
            f"importing {lower} pulled in {sorted(offenders)}; the dependency "
            f"direction requires {lower} to stay below {name}"
        )


def test_core_may_import_media_and_adapters():
    """The permitted direction is exercised, so the rule above is not vacuous."""
    import animalite.core  # noqa: F401

    assert "animalite.media.encode" in sys.modules
    assert "animalite.adapters.registry" in sys.modules
