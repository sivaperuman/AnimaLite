# Opening-frame dog walk

This CPU development experiment renders the ten-second dog-walk shot at 144 × 256 and 24 fps. The cutout was traced for the specific uploaded opening drawing. The renderer takes all its subject textures from the first displayed picture. The fall-and-recover choreography, camera measurements and illustrated street layout were calibrated against the reference clip. Later video frames are used for evaluation and were not sampled for textures. The output is silent.

From the repository root, in a Python 3.12 environment with FFmpeg and libx264 available, run the following commands.

```sh
python -m pip install -e .
python -m pip install -r spikes/dog_walk_frame0/requirements.txt
python spikes/dog_walk_frame0/render.py 'He Tried to Walk the Dog.mp4' dog-walk-take.mp4
```

The Studio storyboard uses the same sparse blocking and can also be rendered with `animalite story-render examples/dog-walk.json --workspace work/studio`. The default `DogWalk` contract retains the walk-and-sit performance for existing callers. Select `"performance": "fall-and-recover"` to stage the fall. The two paths use different character artwork.
