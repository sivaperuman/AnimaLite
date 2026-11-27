"""Offline, supervised LTX-Video → Wan VACE inference, one resident backbone at a time."""

from __future__ import annotations

import gc
import json
import sys
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
from numpy.typing import NDArray

from animalite.adapters.ltx_wan_bundle import Snapshot, snapshot_digest


def _stage(pipe_type: Any, snapshot: Snapshot, args: dict[str, Any], folder: Path) -> list[Any]:
    torch = import_module("torch")
    # Load only the verified private copy. Mutable source files cannot change
    # between verification and inference, and no repository Python is copied.
    with TemporaryDirectory(dir=folder) as scratch:
        safe = Path(scratch)
        if snapshot_digest(snapshot.directory, safe) != snapshot.digest:
            raise ValueError("model snapshot content differs from the admitted digest")
        pipe = pipe_type.from_pretrained(
            str(safe), local_files_only=True, use_safetensors=True, torch_dtype=torch.float32
        )
        pipe.to("cpu")
        for model in (pipe.text_encoder, pipe.transformer, pipe.vae):
            if any(parameter.device.type != "cpu" for parameter in model.parameters()):
                raise ValueError("a neural pipeline component is off CPU")
        pipe.set_progress_bar_config(disable=True)
        with torch.inference_mode():
            frames = list(pipe(**args).frames[0])
    if len(frames) != args["num_frames"] or any(
        f.size != (args["width"], args["height"]) for f in frames
    ):
        raise ValueError("unexpected output dimensions from " + pipe_type.__name__)
    return frames


def run(folder: Path) -> None:
    from animalite.adapters.ltx_wan import model_profile
    from animalite.adapters.ltx_wan_bundle import ModelBundle, configured_bundle
    from animalite.admission import evaluate_admission
    from animalite.contracts.admission import AdmissionPurpose

    cfg = json.loads((folder / "plan.json").read_text())
    bundle = ModelBundle.model_validate(cfg["bundle"])
    if bundle != configured_bundle():
        raise ValueError("worker received a different bundle from the configured snapshots")
    approval = evaluate_admission(model_profile(bundle), AdmissionPurpose(cfg["purpose"]))
    if not approval.admitted:
        raise ValueError("; ".join(approval.reasons))

    if version("diffusers") != "0.35.1":
        raise ValueError("this adapter requires diffusers==0.35.1")
    torch = import_module("torch")
    ltx = import_module("diffusers.pipelines.ltx.pipeline_ltx_condition")
    wan = import_module("diffusers.pipelines.wan.pipeline_wan_vace")
    image = import_module("PIL.Image")
    w, h, n = cfg["width"], cfg["height"], cfg["frames"]
    padded_w, padded_h = (w + 31) // 32 * 32, (h + 31) // 32 * 32
    count = ((n - 1 + 7) // 8) * 8 + 1
    snapshots = Path(cfg["snapshot_scratch"])
    knobs = cfg["controls"]
    torch.set_num_threads(cfg["threads"])
    torch.set_num_interop_threads(1)
    media = cfg["media"]

    def padded(rgb: NDArray[np.uint8]) -> Any:
        return image.fromarray(
            np.pad(rgb, ((0, padded_h - h), (0, padded_w - w), (0, 0)), mode="edge")
        )

    def clip(key: str) -> list[Any]:
        items = n if key.endswith("video") else 1
        raw = np.memmap(media[key], dtype=np.uint8, mode="r", shape=(items, h, w, 3))
        frames = [padded(frame) for frame in raw]
        return frames + [frames[-1]] * (count - len(frames))

    anchors = {
        i: padded(np.load(folder / f"anchor-{i}.npy", allow_pickle=False)) for i in cfg["indices"]
    }
    driving = clip("control_video") if "control_video" in media else []
    masks = (
        clip("mask_video")
        if "mask_video" in media
        else (clip("mask_image") if "mask_image" in media else [])
    )
    conditions = []
    if driving and knobs["motion_strength"] > 0:
        conditions.append(
            ltx.LTXVideoCondition(video=driving, frame_index=0, strength=knobs["motion_strength"])
        )
    for i, img in anchors.items():
        weight = cfg["strengths"].get(str(i), 1.0)
        if weight > 0:
            conditions.append(ltx.LTXVideoCondition(image=img, frame_index=i, strength=weight))
    args = {
        "prompt": cfg["prompt"],
        "negative_prompt": cfg["negative_prompt"],
        "width": padded_w,
        "height": padded_h,
        "num_frames": count,
        "output_type": "pil",
    }
    draft = _stage(
        ltx.LTXConditionPipeline,
        bundle.ltx,
        {
            **args,
            "conditions": conditions or None,
            "frame_rate": cfg["fps"],
            "num_inference_steps": knobs["ltx_steps"],
            "generator": torch.Generator(device="cpu").manual_seed(knobs["seed"]),
        },
        snapshots,
    )
    gc.collect()
    ref = clip("reference_image")[0] if "reference_image" in media else anchors[0]
    masks = [m.convert("L") for m in masks]
    refined = _stage(
        wan.WanVACEPipeline,
        bundle.wan,
        {
            **args,
            "video": draft,
            "mask": [m.convert("RGB") for m in masks] if masks else None,
            "reference_images": [ref],
            "conditioning_scale": knobs["wan_conditioning_scale"],
            "num_inference_steps": knobs["wan_steps"],
            "generator": torch.Generator(device="cpu").manual_seed(knobs["seed"] + 1),
        },
        snapshots,
    )
    output = np.lib.format.open_memmap(
        folder / "frames.npy", mode="w+", dtype=np.uint8, shape=(n, h, w, 3)
    )
    for i in range(n):
        frame = refined[i]
        if masks:
            frame = image.composite(frame, (driving or draft)[i], masks[i])
        output[i] = np.asarray(frame.convert("RGB"))[:h, :w]
    output.flush()


if __name__ == "__main__":
    run(Path(sys.argv[1]))
