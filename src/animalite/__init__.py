"""AnimaLite: CPU-first frame-conditioned 2D quick-clip execution foundation.

Package A scope: contracts, local execution lifecycle, CPU media pipeline, host
inventory, benchmark harness and a deterministic, explicitly non-learned fixture
adapter. No learned temporal model is integrated yet, so no result produced by
this package can satisfy MR-018 or AT-055/AT-056.
"""

from __future__ import annotations

__all__ = ["SCHEMA_VERSION", "__version__"]

__version__ = "0.1.0"

#: Version stamped into every serialized top-level contract document.
SCHEMA_VERSION = "animalite.contracts/v1"
