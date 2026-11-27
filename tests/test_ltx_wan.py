"""CPU integration and validation of the two learned stages."""

import json
import os
from importlib import import_module
from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.adapters.ltx_wan import InferenceControls, model_profile
from animalite.adapters.ltx_wan_bundle import (
    COMPONENTS,
    LoraWeights,
    ModelBundle,
    Snapshot,
    snapshot_digest,
)
from animalite.cli import main
from animalite.contracts.assets import VideoConditioning
from animalite.contracts.base import sha256_file
from animalite.errors import ValidationRejected


def test_pretrained_release_plan_and_verified_fetch(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from animalite.adapters import ltx_wan_pretrained as upstream
    from animalite.contracts.admission import ExecutionAdmission

    assert main(["runtime", "fetch-ltx-wan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    dossier = ExecutionAdmission.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/licensing/admissions/ltx-wan-research.json"
        ).read_bytes()
    )
    assert dossier.decision.value == "pending"
    assert set(dossier.artifact_hashes) == {v["digest"] for v in plan["checkpoints"].values()}
    assert plan["snapshot_bytes"] == sum(v["size_bytes"] for v in plan["checkpoints"].values())

    for name in ("ltx", "wan"):
        root = tmp_path / name
        root.mkdir()
        (root / "model_index.json").write_text("{}")
        for component in COMPONENTS:
            folder = root / component
            folder.mkdir()
            (folder / "config.json").write_text(name)
        monkeypatch.setitem(
            upstream.CHECKPOINTS,
            name,
            upstream.Checkpoint(name, name + "-rev", snapshot_digest(root), 1),
        )

    def download(name, *, revision, cache_dir, allow_patterns, max_workers):
        assert cache_dir == tmp_path and revision == name + "-rev"
        assert "model_index.json" in allow_patterns and "transformer/*" in allow_patterns
        return tmp_path / name

    monkeypatch.setattr(
        upstream, "import_module", lambda _: SimpleNamespace(snapshot_download=download)
    )
    result = upstream.fetch_pretrained(tmp_path)
    assert result.ltx.digest == snapshot_digest(tmp_path / "ltx")
    (tmp_path / "wan/model_index.json").write_text("changed")
    with pytest.raises(ValidationRejected, match="wan snapshot differs"):
        upstream.fetch_pretrained(tmp_path)


def test_snapshot_covers_every_loaded_component(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "model_index.json").write_text("{}")
    for name in COMPONENTS:
        (root / name).mkdir()
        (root / name / "config.json").write_text("{}")
    initial = snapshot_digest(root, tmp_path / "stage")
    assert snapshot_digest(tmp_path / "stage") == initial
    (root / "transformer/config.json").write_text('{"layers":3}')
    assert snapshot_digest(root) != initial
    (root / "vae/weights.bin").write_bytes(b"unexpected")
    with pytest.raises(ValidationRejected, match="unexpected file"):
        snapshot_digest(root)


def test_weighted_refinement_rejects_unrelated_colors():
    import numpy as np

    from animalite.adapters.ltx_wan_guidance import weighted_refinement

    base = np.full((24, 24, 3), 65, np.uint8)
    assert np.all(weighted_refinement(base, base + 12, 0.5, 24) == 70)
    assert np.all(weighted_refinement(base, base - 12, 0.5, 24) == 60)
    assert np.array_equal(weighted_refinement(base, base + 180, 0.25, 24), base)
    assert np.array_equal(weighted_refinement(base, base, 1.0, 255), base)


def test_dense_guide_moves_an_object_and_keeps_interior_poses():
    import numpy as np

    from animalite.adapters.ltx_wan_guidance import anchor_guide

    pytest.importorskip("cv2")
    generator = np.random.default_rng(71)
    left = np.zeros((80, 96, 3), np.uint8)
    left[20:52, 24:56] = generator.integers(70, 255, size=(32, 32, 3), dtype=np.uint8)
    right = np.roll(left, 8, axis=1)
    guide = list(anchor_guide({0: left, 2: right, 3: left}))
    assert all(np.array_equal(guide[i], img) for i, img in ((0, left), (2, right), (3, left)))
    expected = np.roll(left, 4, axis=1)
    assert (
        np.abs(guide[1].astype(int) - expected).mean()
        < np.abs(left.astype(int) - expected).mean() / 2
    )


def test_neural_controls_and_mask_validation():
    ref = {"path": "mask.png", "content_hash": "sha256:" + "a" * 64}
    with pytest.raises(ValidationError, match="static mask"):
        VideoConditioning(mask_image=ref, mask_video=ref)
    with pytest.raises(ValidationError):
        InferenceControls.model_validate({"ltx_steps": True})
    profile = model_profile(None)
    assert profile.learned_temporal_participation and not profile.qualification_eligible
    assert all(w.content_hash is None for w in profile.weights)
    assert profile.supports_resolution(144, 256)


def test_story_retains_replayable_conditioning(tmp_path):
    from animalite.story import Storyboard, retain_conditioning
    from animalite.story_archive import index_story

    guide = tmp_path / "run.mp4"
    guide.write_bytes(b"guide bytes")
    digest = sha256_file(str(guide))
    conditioning = VideoConditioning.model_validate(
        {
            "control_video": {"path": guide.name, "content_hash": digest},
            "anchor_strengths": {"0": 0.25},
        }
    )
    run = tmp_path / "archive"
    run.mkdir()
    stored, resolved = retain_conditioning(conditioning, tmp_path, run)
    assert stored is not None and resolved is not None
    assert stored.control_video and resolved.control_video
    relative = Path(stored.control_video.path)
    assert not relative.is_absolute()
    assert Path(resolved.control_video.path) == run / relative
    assert stored.anchor_strengths == resolved.anchor_strengths == {0: 0.25}
    guide.unlink()
    board = Storyboard.model_validate(
        {
            "story": "gallop",
            "shots": [
                {
                    "action": "extend",
                    "seconds": 1,
                    "poses": [{"image": "pose.png", "frame": i} for i in (0, 11)],
                    "conditioning": stored,
                }
            ],
        }
    )
    (run / "pose.png").write_bytes(b"pose")
    (run / "shot.mp4").write_bytes(b"shot")
    (run / "storyboard.json").write_text(board.model_dump_json())
    assert index_story(run, board, [Path("shot.mp4")]).digests[str(relative)] == digest
    with pytest.raises(ValidationError, match="named frame indices"):
        Storyboard.model_validate(
            {
                **board.model_dump(),
                "shots": [
                    {**board.shots[0].model_dump(), "conditioning": {"anchor_strengths": {"7": 1}}}
                ],
            }
        )


def tiny_snapshots(root):
    """Freshly initialized test tensors and a tokenizer made from local test text."""
    torch = import_module("torch")
    df = import_module("diffusers")
    tr = import_module("transformers")
    sp = import_module("sentencepiece")
    torch.manual_seed(17)
    corpus = root / "words.txt"
    corpus.write_text("a dog runs over the grass\na red dog lifts a paw\na painted dog lands\n")
    sp.SentencePieceTrainer.train(
        input=str(corpus),
        model_prefix=str(root / "tokens"),
        vocab_size=32,
        hard_vocab_limit=False,
        minloglevel=2,
    )
    tokenizer = tr.T5Tokenizer(
        vocab_file=str(root / "tokens.model"), extra_ids=0, model_max_length=128
    )
    encoder = tr.T5EncoderModel(
        tr.T5Config(
            vocab_size=len(tokenizer), d_model=32, d_ff=48, d_kv=8, num_heads=4, num_layers=1
        )
    )
    common = {
        "tokenizer": tokenizer,
        "text_encoder": encoder,
        "scheduler": df.FlowMatchEulerDiscreteScheduler(),
    }
    ltx = df.LTXConditionPipeline(
        **common,
        transformer=df.LTXVideoTransformer3DModel(
            in_channels=8,
            out_channels=8,
            patch_size=1,
            patch_size_t=1,
            num_attention_heads=2,
            attention_head_dim=16,
            cross_attention_dim=32,
            num_layers=1,
            caption_channels=32,
        ),
        vae=df.AutoencoderKLLTXVideo(
            in_channels=3,
            out_channels=3,
            latent_channels=8,
            block_out_channels=(8, 8, 8, 8),
            decoder_block_out_channels=(8, 8, 8, 8),
            layers_per_block=(1, 1, 1, 1, 1),
            decoder_layers_per_block=(1, 1, 1, 1, 1),
            spatio_temporal_scaling=(True, True, True, False),
            decoder_spatio_temporal_scaling=(True, True, True, False),
            decoder_inject_noise=(False,) * 5,
            upsample_residual=(False,) * 4,
            upsample_factor=(1,) * 4,
            timestep_conditioning=False,
            patch_size=4,
            patch_size_t=1,
            encoder_causal=True,
            decoder_causal=False,
        ),
    )
    wan = df.WanVACEPipeline(
        **common,
        transformer=df.WanVACETransformer3DModel(
            patch_size=(1, 2, 2),
            num_attention_heads=2,
            attention_head_dim=12,
            in_channels=16,
            out_channels=16,
            text_dim=32,
            freq_dim=64,
            ffn_dim=32,
            num_layers=2,
            vace_layers=[0],
            vace_in_channels=96,
            rope_max_seq_len=256,
        ),
        vae=df.AutoencoderKLWan(
            base_dim=4,
            z_dim=16,
            dim_mult=[1, 1, 1, 1],
            num_res_blocks=1,
            temperal_downsample=[False, True, True],
        ),
    )
    for name, pipe in (("ltx", ltx), ("wan", wan)):
        pipe.save_pretrained(root / name)
    return ModelBundle(
        **{
            key: Snapshot(directory=root / key, digest=snapshot_digest(root / key))
            for key in ("ltx", "wan")
        }
    )


@pytest.mark.media
@pytest.mark.skipif(
    os.getenv("ANIMALITE_RUN_NEURAL_SMOKE") != "1", reason="opt-in local neural runtime integration"
)
def test_real_two_stage_cpu_render(tmp_path, monkeypatch, capsys, tools):
    import subprocess

    import numpy as np
    from PIL import Image

    bundle = tiny_snapshots(tmp_path)
    pin = tmp_path / "bundle.json"
    assert (
        main(
            [
                "runtime",
                "pin-ltx-wan",
                "--ltx",
                str(bundle.ltx.directory),
                "--wan",
                str(bundle.wan.directory),
            ]
        )
        == 0
    )
    pin.write_text(capsys.readouterr().out)
    assert ModelBundle.model_validate_json(pin.read_bytes()) == bundle
    monkeypatch.setenv("ANIMALITE_LTX_WAN_BUNDLE", str(pin))
    decisions = tmp_path / "admissions"
    decisions.mkdir()
    monkeypatch.setenv("ANIMALITE_ADMISSION_DIR", str(decisions))

    def asset(path):
        return {"path": str(path), "content_hash": sha256_file(str(path))}

    anchors = []
    for k, color in [(0, (153, 29, 109)), (2, (52, 79, 215))]:
        img = tmp_path / f"pose{k}.png"
        Image.new("RGB", (320, 180), color).save(img)
        anchors.append(
            {
                "anchor_id": str(k),
                "animation_index": k,
                "asset": asset(img),
                "width": 320,
                "height": 180,
            }
        )
    anchor_file = tmp_path / "anchors.json"
    anchor_file.write_text(json.dumps({"anchors": anchors}))
    mask = tmp_path / "mask.png"
    matte = Image.new("L", (320, 180), 0)
    matte.paste(255, (80, 0, 240, 180))
    matte.save(mask)
    driver = tmp_path / "motion.mp4"
    subprocess.run(
        [
            tools.ffmpeg_path,
            "-nostdin",
            "-v",
            "error",
            "-loop",
            "1",
            "-framerate",
            "24",
            "-i",
            str(tmp_path / "pose0.png"),
            "-frames:v",
            "6",
            "-threads",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(driver),
        ],
        check=True,
    )
    cond = tmp_path / "conditions.json"
    cond.write_text(
        json.dumps(
            {
                "mask_image": asset(mask),
                "control_video": asset(driver),
                "reference_image": anchors[0]["asset"],
                "anchor_strengths": {"2": 0.75},
            }
        )
    )
    args = [
        "--profile",
        "ltx-wan-cpu",
        "--width",
        "320",
        "--height",
        "180",
        "--anchors",
        str(anchor_file),
        "--animation-frames",
        "3",
        "--control",
        "ltx_steps=1",
        "--control",
        "wan_steps=1",
        "--conditioning",
        str(cond),
        "--workspace",
        str(tmp_path / "runs"),
        "--motion",
        "a dog runs",
    ]
    assert main(["validate", *args]) != 0
    capsys.readouterr()
    # Test-only disposition for bytes created above, in a temporary store.
    (decisions / "test.json").write_text(
        json.dumps(
            {
                "record_id": "local-test",
                "profile_id": "ltx-wan-cpu",
                "subject": "random local test networks",
                "decision": "approved",
                "artifact_hashes": [bundle.ltx.digest, bundle.wan.digest],
                "permitted_purposes": ["research"],
                "reviewer": "synthetic integration fixture",
                "reference": "test_real_two_stage_cpu_render",
                "recorded_at": "2026-11-27",
            }
        )
    )

    def render(run_args):
        result = main(["render", *run_args])
        streams = capsys.readouterr()
        assert result == 0, (streams.out, streams.err)
        root = max((tmp_path / "runs/attempts").iterdir(), key=lambda p: p.stat().st_mtime_ns)
        stage = root / "work/ltx-wan"
        rgb = subprocess.check_output(
            [
                tools.ffmpeg_path,
                "-v",
                "error",
                "-i",
                str(root / "output/output.mp4"),
                "-threads",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        delivered = np.frombuffer(rgb, np.uint8).reshape(6, 180, 320, 3)
        for index, color in ((0, [153, 29, 109]), (-1, [52, 79, 215])):
            assert np.max(np.abs(delivered[index, 90, 160].astype(int) - color)) < 8
        frames = np.load(stage / "frames.npy")
        driving = np.fromfile(stage / "control_video.rgb", np.uint8).reshape(frames.shape)
        assert np.array_equal(frames[1, :, :78], driving[1, :, :78])
        assert np.array_equal(frames[1, :, 242:], driving[1, :, 242:])
        assert not np.array_equal(frames[1, :, 85:235], driving[1, :, 85:235])
        return frames[1].copy()

    initial = render(args)
    for setting in ("ltx_steps=2", "wan_steps=2"):
        changed = render([*args, "--control", setting])
        assert not np.array_equal(initial[:, 85:235], changed[:, 85:235]), setting

    # Isolate transformer-weight effects from pixel mixing, seed, and step counts.
    torch = import_module("torch")
    safetensors = import_module("safetensors.torch")
    generator = torch.Generator().manual_seed(71)

    def with_lora(snapshot, name, key, width):
        path = tmp_path / (name + ".safetensors")
        prefix = "transformer." + key + ".attn1.to_v"
        safetensors.save_file(
            {
                prefix + ".lora_A.weight": torch.randn((2, width), generator=generator),
                prefix + ".lora_B.weight": torch.randn((width, 2), generator=generator),
            },
            str(path),
        )
        return snapshot.model_copy(update={"lora": LoraWeights.pin(str(path))})

    weighted = ModelBundle(
        ltx=with_lora(bundle.ltx, "ltx-motion", "transformer_blocks.0", 32),
        wan=with_lora(bundle.wan, "wan-detail", "blocks.0", 24),
    )
    assert weighted.ltx.lora and weighted.wan.lora
    assert (
        main(
            [
                "runtime",
                "pin-ltx-wan",
                "--ltx",
                str(weighted.ltx.directory),
                "--wan",
                str(weighted.wan.directory),
                "--ltx-lora",
                str(weighted.ltx.lora.path),
                "--wan-lora",
                str(weighted.wan.lora.path),
            ]
        )
        == 0
    )
    pin.write_text(capsys.readouterr().out)
    assert ModelBundle.model_validate_json(pin.read_bytes()) == weighted
    assert main(["validate", *args]) != 0
    capsys.readouterr()
    record = json.loads((decisions / "test.json").read_text())
    record["artifact_hashes"] = [item.content_hash for item in model_profile(weighted).weights]
    (decisions / "test.json").write_text(json.dumps(record))
    raw_args = [
        *args,
        "--control",
        "render_mode=diffusion",
        "--control",
        "ltx_steps=3",
        "--control",
        "wan_steps=2",
        "--control",
        "motion_strength=0",
        "--control",
        "retain_stages=true",
    ]

    def scales(ltx, wan):
        final = render(
            [*raw_args, "--control", f"ltx_lora_scale={ltx}", "--control", f"wan_lora_scale={wan}"]
        )
        attempt = max((tmp_path / "runs/attempts").iterdir(), key=lambda p: p.stat().st_mtime_ns)
        stage = attempt / "work/ltx-wan"
        return (
            final,
            sha256_file(str(stage / "ltx_raw.npy")),
            sha256_file(str(stage / "wan_raw.npy")),
        )

    baseline, ltx0, wan0 = scales(0, 0)
    _, ltx1, _ = scales(1, 0)
    wan_final, unchanged_ltx, wan1 = scales(0, 1)
    assert ltx0 != ltx1
    assert ltx0 == unchanged_ltx and wan0 != wan1
    assert not np.array_equal(baseline, wan_final)
    assert weighted.wan.lora
    weighted.wan.lora.path.write_bytes(b"changed")
    assert main(["render", *args]) != 0
    out = capsys.readouterr()
    assert "LoRA weights differ" in out.out + out.err
    pin.write_text(bundle.model_dump_json())
    (bundle.wan.directory / "scheduler/scheduler_config.json").write_text("{}")
    assert main(["render", *args]) != 0
    out = capsys.readouterr()
    assert "digest" in (out.out + out.err)
