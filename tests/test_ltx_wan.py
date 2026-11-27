"""CPU integration and validation of the two learned stages."""

import json
import os
from importlib import import_module
from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.adapters.ltx_wan import InferenceControls, model_profile
from animalite.adapters.ltx_wan_bundle import COMPONENTS, ModelBundle, Snapshot, snapshot_digest
from animalite.cli import main
from animalite.contracts.assets import VideoConditioning
from animalite.contracts.base import sha256_file
from animalite.errors import ValidationRejected


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

    (bundle.wan.directory / "scheduler/scheduler_config.json").write_text("{}")
    assert main(["render", *args]) != 0
    out = capsys.readouterr()
    assert "digest" in (out.out + out.err)
