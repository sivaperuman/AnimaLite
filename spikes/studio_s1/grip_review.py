"""Inspect projected contacts on the final RGB composite going to the encoder."""

import numpy as np
from artwork import HAND_COLORS, INSPECTOR_HAND_COLORS, PAPER_EDGE, PAPER_FILL
from performance import camera, supported_grips
from PIL import Image, ImageColor, ImageFilter


def visible_grips(rgb, width, frame, actors, character):
    zoom, cx, cy = camera(frame)
    scale = zoom * width / 640
    radius = int(np.ceil(10 * scale))
    # Allow the hand and paper outlines between visible skin and paper pigment.
    reach = int(np.ceil(3 * scale))
    image = np.frombuffer(rgb, dtype=np.uint8).reshape(width * 9 // 16, width, 3)
    colors = INSPECTOR_HAND_COLORS if character == "inspector" else HAND_COLORS
    observations = {}
    for (actor, hand), grip in supported_grips(frame, actors[2]).items():
        label = f"{actor}.{'near' if hand else 'far'}"
        x = round(width / 2 + (grip.real - cx) * scale)
        y = round(image.shape[0] / 2 + (grip.imag - cy) * scale)
        patch = image[max(0, y - radius) : y + radius + 1, max(0, x - radius) : x + radius + 1]
        if patch.size:
            palm = np.all(patch == ImageColor.getrgb(colors[actor, hand]), axis=2)
            paper = np.all(patch == ImageColor.getrgb(PAPER_FILL), axis=2)
            paper |= np.all(patch == ImageColor.getrgb(PAPER_EDGE), axis=2)
            nearby = Image.fromarray(paper.astype(np.uint8) * 255).filter(
                ImageFilter.MaxFilter(2 * reach + 1)
            )
            count = int(np.count_nonzero(palm & (np.asarray(nearby) > 0)))
        else:
            count = 0
        if count < max(1, round(scale**2)):
            raise ValueError(
                f"Frame {frame}: {label} has no readable grip at ({x}, {y}); "
                f"{count} adjacent hand pixels"
            )
        observations[label] = count
    return observations
