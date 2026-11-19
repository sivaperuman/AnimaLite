"""``python -m animalite`` fallback entry point (handoff section 13, item 1)."""

from __future__ import annotations

from animalite.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
