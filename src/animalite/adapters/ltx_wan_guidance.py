"""Build a two-sided motion guide and limit appearance drift during diffusion."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module
from itertools import pairwise
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray

PixelType = TypeVar("PixelType", np.uint8, np.float32)


def anchor_guide(anchors: dict[int, NDArray[np.uint8]]) -> Iterator[NDArray[np.uint8]]:
    """Warp both poses to each requested time, downweighting inconsistent flow."""
    try:
        cv = import_module("cv2")
    except ImportError as exc:
        raise RuntimeError("install the neural extra for optical flow between poses") from exc
    cv.setNumThreads(1)
    cv.ocl.setUseOpenCL(False)
    flow = cv.DISOpticalFlow_create(cv.DISOPTICAL_FLOW_PRESET_MEDIUM)
    indices = sorted(anchors)
    first = anchors[indices[0]]
    height, width = first.shape[:2]
    grid = np.stack(np.meshgrid(np.arange(width), np.arange(height)), axis=-1).astype(np.float32)

    def sample(field: NDArray[PixelType], coords: NDArray[np.float32]) -> NDArray[PixelType]:
        return np.asarray(
            cv.remap(field, coords, None, cv.INTER_LINEAR, borderMode=cv.BORDER_REPLICATE)
        )

    def consistency(
        forward: NDArray[np.float32], backward: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        dest = grid + forward
        in_bounds = (
            (dest[..., 0] >= 0)
            & (dest[..., 0] <= width - 1)
            & (dest[..., 1] >= 0)
            & (dest[..., 1] <= height - 1)
        )
        cycle = forward + sample(backward, dest)
        return np.asarray(in_bounds / (1 + np.sum(cycle * cycle, axis=-1)), dtype=np.float32)

    def inverse(field: NDArray[np.float32], fraction: float) -> NDArray[np.float32]:
        # Fixed-point inversion samples displacement at the original pixel.
        coords = grid - fraction * field
        for _ in range(2):
            coords = grid - fraction * sample(field, coords)
        return coords

    join_edges = np.ones((5, 5), np.uint8)
    yield first
    for start, end in pairwise(indices):
        left, right = anchors[start], anchors[end]
        if end > start + 1:
            a = cv.cvtColor(left, cv.COLOR_RGB2GRAY)
            b = cv.cvtColor(right, cv.COLOR_RGB2GRAY)
            forward = flow.calc(a, b, None)
            backward = flow.calc(b, a, None)
            conf_a = consistency(forward, backward)
            conf_b = consistency(backward, forward)
            for index in range(start + 1, end):
                t = (index - start) / (end - start)
                pos_a = inverse(forward, t)
                pos_b = inverse(backward, 1 - t)
                # A small floor preserves the timing prior in disoccluded areas.
                wa = (1 - t) * (0.05 + sample(conf_a, pos_a))
                wb = t * (0.05 + sample(conf_b, pos_b))
                alpha = (wb / (wa + wb))[..., None]
                warped_a = sample(left, pos_a).astype(np.float32)
                warped_b = sample(right, pos_b).astype(np.float32)
                # Blending two different ink silhouettes can draw an extra paw.
                # Choose one source for a connected disagreement region, then
                # soften the transition back to the ordinary two-sided warp.
                error = np.max(np.abs(warped_b - warped_a), axis=-1)
                soft = np.clip((cv.GaussianBlur(error, (0, 0), 1.2) - 12) / 32, 0, 1)
                support = cv.dilate((soft > 0).astype(np.uint8), join_edges)
                count, regions = cv.connectedComponents(support)
                advantage = np.bincount(regions.ravel(), weights=(wb - wa).ravel(), minlength=count)
                choice = (advantage[regions] > 0).astype(np.float32)[..., None]
                alpha = alpha + soft[..., None] * (choice - alpha)
                yield np.asarray(np.rint((1 - alpha) * warped_a + alpha * warped_b), dtype=np.uint8)
        yield right


def weighted_refinement(
    base: NDArray[np.uint8], proposal: NDArray[np.uint8], weight: float, limit: int
) -> NDArray[np.uint8]:
    """Reduce the influence of neural pixels whose color disagrees with the motion guide."""
    delta = proposal.astype(np.float32) - base
    distance = np.mean(np.square(delta), axis=-1, keepdims=True)
    confidence = 1.0 / (1.0 + distance / (limit * limit))
    change = weight * confidence * np.clip(delta, -limit, limit)
    return np.asarray(np.rint(base + change), dtype=np.uint8)
