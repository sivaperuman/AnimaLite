"""Classical block-matching motion estimation and motion-compensated warping.

This is the *comparator baseline*: a non-learned reference the learned candidate
must beat. It exists so that a test which the baseline also passes is visibly
not evidence of learned temporal capability (MR-018 excludes cross-fades and
repeated source frames; a classical warp is excluded for the same reason).

Implemented here in NumPy rather than delegated to an encoder filter on purpose.
A baseline used as evidence has to be deterministic and auditable: FFmpeg's
``minterpolate`` varies with build options and filter defaults, and on a
two-frame anchor pair it emits nothing at all, so its behaviour would be neither
fixed by this repository nor readable from it.

The method is standard: full-search block matching for a piecewise-constant flow
field, bilinear upsampling to per-pixel flow, bilinear backward warping of both
anchors toward the requested time, and a time-weighted blend.

Flow convention, used consistently below: ``flow[y, x] = (dx, dy)`` is the
displacement ``d`` for which ``source[p] ≈ destination[p + d]``. Landing content
at time ``t`` therefore samples the source at ``-t·d``; sampling at ``+t·d``
moves it the wrong way and silently degrades to roughly cross-fade quality.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "DEFAULT_BLOCK_SIZE",
    "DEFAULT_SEARCH_RADIUS",
    "estimate_block_flow",
    "interpolate_motion_compensated",
    "upsample_flow",
    "warp_bilinear",
]

#: Macroblock edge in pixels; 16 is the classical choice. It does NOT divide the
#: supported heights (360 / 16 = 22.5, 180 / 16 = 11.25), so the estimator covers
#: whole blocks only and the remaining strip at the bottom or right edge inherits
#: the nearest block's flow through the upsampler's clamp. That is a real
#: limitation of a block method on non-multiple geometry, disclosed rather than
#: designed around: requiring exact division would reject the P-L output spec.
DEFAULT_BLOCK_SIZE = 16

#: Full-search radius in pixels. Motion beyond this is not found; the estimator
#: reports the zero displacement rather than a confident wrong one.
DEFAULT_SEARCH_RADIUS = 16

#: A displacement must beat standing still by this mean absolute difference per
#: pixel before it is accepted. Without it, block matching locks onto noise in
#: low-texture regions: measured on the two-anchor fixture, whose true motion is
#: about 2 px, an unguarded search returned a mean displacement of 15.3 px that
#: saturated the search radius. With the zero displacement as the incumbent the
#: same estimate falls to 0.8 px.
DEFAULT_ACCEPT_MARGIN = 1.0

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _luma(image: NDArray[np.uint8]) -> NDArray[np.float32]:
    return np.asarray(image, dtype=np.float32) @ _LUMA


def estimate_block_flow(
    source: NDArray[np.uint8],
    destination: NDArray[np.uint8],
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
    search_radius: int = DEFAULT_SEARCH_RADIUS,
    accept_margin: float = DEFAULT_ACCEPT_MARGIN,
) -> NDArray[np.float32]:
    """Estimate a piecewise-constant flow field by full-search block matching.

    Returns ``(blocks_y, blocks_x, 2)`` displacements in pixels.

    The zero displacement is the incumbent, not a candidate: the search starts
    from "nothing moved" and only accepts a displacement that improves the match
    by ``accept_margin``. That ordering is what keeps flat regions still, and it
    is also why an unmatchable region reports no motion instead of a confident
    wrong one.
    """
    if source.shape != destination.shape:
        raise ValueError(
            f"anchors differ in shape: {source.shape} vs {destination.shape}; "
            "flow is only defined between frames of equal geometry"
        )
    if block_size < 1:
        raise ValueError(f"block_size must be positive, got {block_size}")
    if search_radius < 0:
        raise ValueError(f"search_radius must not be negative, got {search_radius}")

    src = _luma(source)
    dst = _luma(destination)
    # Whole blocks only. A frame whose size is not a multiple of the block edge
    # leaves a remainder strip that no block covers; `upsample_flow` clamps into
    # the last block, so the strip moves with its neighbour rather than standing
    # still. See the note on DEFAULT_BLOCK_SIZE.
    height, width = src.shape
    blocks_y, blocks_x = height // block_size, width // block_size
    if blocks_y == 0 or blocks_x == 0:
        raise ValueError(f"frame {width}x{height} is smaller than one {block_size}px block")

    padded = np.pad(dst, search_radius, mode="edge")
    trimmed_h, trimmed_w = blocks_y * block_size, blocks_x * block_size

    def block_cost(dx: int, dy: int) -> NDArray[np.float32]:
        shifted = padded[
            search_radius + dy : search_radius + dy + height,
            search_radius + dx : search_radius + dx + width,
        ]
        absolute = np.abs(src - shifted)[:trimmed_h, :trimmed_w]
        summed = absolute.reshape(blocks_y, block_size, blocks_x, block_size).sum(axis=(1, 3))
        cost: NDArray[np.float32] = summed / float(block_size * block_size)
        return cost

    best = block_cost(0, 0)
    flow = np.zeros((blocks_y, blocks_x, 2), dtype=np.float32)
    for dy in range(-search_radius, search_radius + 1):
        for dx in range(-search_radius, search_radius + 1):
            if dx == 0 and dy == 0:
                continue
            cost = block_cost(dx, dy)
            better = cost + accept_margin < best
            best = np.where(better, cost, best)
            flow[..., 0] = np.where(better, dx, flow[..., 0])
            flow[..., 1] = np.where(better, dy, flow[..., 1])
    return flow


def upsample_flow(
    flow: NDArray[np.float32], height: int, width: int, *, block_size: int = DEFAULT_BLOCK_SIZE
) -> NDArray[np.float32]:
    """Bilinearly expand a per-block flow field to per-pixel, ``(h, w, 2)``.

    Block centres sit at ``(i + 0.5) * block_size``, so a pixel's position in
    block coordinates is ``p / block_size - 0.5``. Without that half-block shift
    the field is offset by half a macroblock and the warp smears along block
    boundaries.
    """
    blocks_y, blocks_x, _ = flow.shape
    ys = np.clip(np.arange(height, dtype=np.float32) / block_size - 0.5, 0, blocks_y - 1)
    xs = np.clip(np.arange(width, dtype=np.float32) / block_size - 0.5, 0, blocks_x - 1)
    y0 = np.floor(ys).astype(np.intp)
    x0 = np.floor(xs).astype(np.intp)
    y1 = np.minimum(y0 + 1, blocks_y - 1)
    x1 = np.minimum(x0 + 1, blocks_x - 1)
    wy = (ys - y0)[:, None, None]
    wx = (xs - x0)[None, :, None]
    top = flow[y0][:, x0] * (1.0 - wx) + flow[y0][:, x1] * wx
    bottom = flow[y1][:, x0] * (1.0 - wx) + flow[y1][:, x1] * wx
    expanded: NDArray[np.float32] = (top * (1.0 - wy) + bottom * wy).astype(np.float32)
    return expanded


def warp_bilinear(image: NDArray[np.uint8], flow: NDArray[np.float32]) -> NDArray[np.float32]:
    """Sample ``image`` at ``p + flow[p]`` with bilinear interpolation.

    Coordinates are clamped to the frame, so motion that points outside repeats
    the edge pixel rather than wrapping or producing a hole.
    """
    height, width, _ = image.shape
    rows, cols = np.meshgrid(
        np.arange(height, dtype=np.float32),
        np.arange(width, dtype=np.float32),
        indexing="ij",
    )
    sx = np.clip(cols + flow[..., 0], 0.0, width - 1.0)
    sy = np.clip(rows + flow[..., 1], 0.0, height - 1.0)
    x0 = np.floor(sx).astype(np.intp)
    y0 = np.floor(sy).astype(np.intp)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = (sx - x0)[..., None]
    fy = (sy - y0)[..., None]
    source = np.asarray(image, dtype=np.float32)
    top = source[y0, x0] * (1.0 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1.0 - fx) + source[y1, x1] * fx
    sampled: NDArray[np.float32] = top * (1.0 - fy) + bottom * fy
    return sampled


def interpolate_motion_compensated(
    first: NDArray[np.uint8],
    second: NDArray[np.uint8],
    timestep: float,
    forward_flow: NDArray[np.float32],
    backward_flow: NDArray[np.float32],
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> NDArray[np.uint8]:
    """Reconstruct the frame at ``timestep`` between two anchors.

    ``forward_flow`` is ``estimate_block_flow(first, second)`` and
    ``backward_flow`` is the reverse. Both are estimated once per anchor pair and
    reused for every frame in the segment, which is what keeps the per-frame cost
    to two warps and a blend.

    At ``timestep`` 0 or 1 the corresponding anchor is returned untouched: an
    approved frame is delivered exactly, never re-sampled through a warp.
    """
    if not 0.0 <= timestep <= 1.0:
        raise ValueError(f"timestep must lie in [0, 1], got {timestep}")
    if timestep == 0.0:
        return np.asarray(first, dtype=np.uint8)
    if timestep == 1.0:
        return np.asarray(second, dtype=np.uint8)

    height, width, _ = first.shape
    fwd = upsample_flow(forward_flow, height, width, block_size=block_size)
    bwd = upsample_flow(backward_flow, height, width, block_size=block_size)
    # Negated: flow[p] says where p *went*, so landing content here samples back
    # along it. Sampling forward instead reconstructs about as well as a plain
    # cross-fade -- measured 74.3 vs 75.2 mean absolute error on a known 24 px
    # translation, against 4.8 with the sign right.
    warped_first = warp_bilinear(first, -fwd * timestep)
    warped_second = warp_bilinear(second, -bwd * (1.0 - timestep))
    blended = warped_first * (1.0 - timestep) + warped_second * timestep
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)
