# Balaam

Video generation with Google's Veo models (the models behind Google Flow), using the Gemini API.

## Setup

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...   # from https://aistudio.google.com/apikey
```

In the "Balaam" cloud environment, the key is stored as a network secret and added to requests automatically, so you don't need to set `GEMINI_API_KEY`.

## Usage

```bash
python3 veo.py models                                   # list the Veo models your key can use

python3 veo.py generate "Slow dolly shot of a lighthouse at dusk, waves crashing, warm light"

python3 veo.py generate "She turns and smiles at the camera" \
  --image start.png --aspect 9:16 --resolution 1080p      # image-to-video

python3 veo.py generate "Camera pans from the door to the window" \
  --image first.png --last-frame last.png                 # set the first and last frames

python3 veo.py generate "The knight walks through the market" \
  --ref knight.png --ref sword.png                        # keep a character or object consistent

python3 veo.py extend output/lighthouse.mp4 "A storm rolls in"   # continue a clip

python3 veo.py stitch output/film.mp4 output/a.mp4 output/b.mp4  # join clips into one scene
```

Clips are saved to `output/`, each with a `.json` file that records its prompt and the server-side video URI that `extend` uses. Generated videos stay on Google's servers for only about 2 days, so extend a clip soon after generating it.

Set `VEO_MODEL` to use a different model, for example `veo-3.1-fast-generate-preview`, which is cheaper and faster. Some options (1080p, reference images, last frame, duration) depend on the model.
