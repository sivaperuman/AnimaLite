# Weighted LTX and Wan evaluation

The uploaded dog and handler clip runs for 10 seconds at 144×256 and 24 fps. Six short renders cover the entire source. Each render received 2–4 timed reference poses. The other animation frames were withheld. No motion video was supplied. The guide uses dense optical flow between the poses, and the neural stages use the same locally initialized small checkpoints as the integration test. The comparison MP4 shows the original, the guide alone, and the encoded guided result. The gallop repeats once at half speed.

## Held-out frames

Values are mean absolute errors in 8-bit RGB before delivery encoding. Lower is closer to the corresponding original frame. The hold baseline repeats the first image of each shot. All comparisons use the same seed, prompt, poses and two inference steps per stage. The test measures one reference clip. It does not establish pretrained performance or anatomically correct leg extension.

| Shot | Source interval (s) | Input pose indices at 12 fps | Withheld | Hold | Raw diffusion | Guide alone | Guided LTX + Wan |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Opening | 0–1 | 0, 11 | 10 | 10.58 | 80.30 | 11.60 | 12.09 |
| Launch | 1–2.5 | 0, 6, 12, 17 | 14 | 15.25 | 77.52 | 13.79 | 14.16 |
| Gallop | 2.5–4.5 | 0, 8, 15, 23 | 20 | 41.65 | 67.72 | 23.87 | 23.90 |
| Pull | 4.5–5.5 | 0, 6, 11 | 9 | 38.90 | 71.57 | 20.54 | 20.57 |
| Landing | 5.5–7.5 | 0, 8, 15, 23 | 20 | 51.63 | 69.96 | 15.52 | 15.95 |
| Recovery | 7.5–10 | 0, 10, 20, 29 | 26 | 12.33 | 69.41 | 4.73 | 5.39 |
| All frames | 0–10 | 21 supplied poses | 99 | 28.84 | 71.63 | 14.19 | 14.56 |

The guide preserves the artwork through the run and fall. Selecting one warped pose in a region with conflicting outlines reduces the double image of the paws. Foot placement and the timing of full extension still differ from the original. The untrained neural corrections slightly increase average error over the guide alone.

## Repeat with pretrained weights

1. Run `animalite runtime fetch-ltx-wan` to inspect the pinned revisions. The verified component lists total 44.43 GB. The worker currently needs up to 25.39 GB more scratch. From the official component configurations, the current float32 worker needs about 29.6 GiB per stage for parameters alone. Activations, buffers and runtime overhead add to this estimate. Actual peak memory with the pretrained weights remains unmeasured.
2. Install the checkpoints on a host with sufficient resources and record the execution decision for those exact digests. For a trained motion or artwork LoRA, pin its safetensors file and include its digest in the decision.
3. Repeat the shot timings above. Hold settings fixed while comparing raw diffusion, the guide alone, guided inference, and each trained LoRA at zero and its intended scale. Use `retain_stages=true` to retain raw LTX, raw Wan and the guide for independent inspection. Check the front and rear paws at takeoff, full extension and contact alongside the pixel metrics.

The small-network integration test separately applies a nonzero LoRA to each transformer and checks that changing its scale changes that stage’s actual output. The dog footage uses the base test networks without an external LoRA.
