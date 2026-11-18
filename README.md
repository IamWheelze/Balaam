# Balaam

Command-line tool for AI video generation and editing with Google's video models, the models behind Google Flow.

| Backend | Model | Access |
|---|---|---|
| `omni` (default) | Gemini Omni Flash (`gemini-omni-flash-preview`) | Gemini API key |
| `veo` | Veo 3.1 (`veo-3.1-generate-001`) | Google Cloud project on Gemini Enterprise Agent Platform |

Google shut down Veo on the Gemini API on 22 Oct 2026. Veo now runs only on Agent Platform, the new name for Vertex AI.

## Setup

```bash
pip install -r requirements.txt
```

**omni:** create a key at https://aistudio.google.com/apikey, then `export GEMINI_API_KEY=...`. In the "Balaam" cloud environment, you can save the key as a network secret instead (host `generativelanguage.googleapis.com`, header `x-goog-api-key`), and then you don't need to set the variable.

**veo:** you need a Google Cloud project with billing and the Vertex AI / Agent Platform API enabled. Then use either of these:
- **API key (express mode):** in Cloud Console, go to APIs & Services → Credentials. Edit the key's API restrictions so it also allows the Vertex AI API, then set `VEO_API_KEY`. If that variable isn't set, the tool uses `GEMINI_API_KEY`.
- **Cloud credentials:** run `gcloud auth application-default login`, or point `GOOGLE_APPLICATION_CREDENTIALS` at a service-account key file. Then run `export GOOGLE_CLOUD_PROJECT=your-project-id`. `GOOGLE_CLOUD_LOCATION` defaults to `us-central1`.

## Usage

```bash
python3 video.py models                                   # list available video models

python3 video.py generate "Slow dolly shot of a lighthouse at dusk, waves crashing"

python3 video.py generate "She turns and smiles at the camera" \
  --image start.png --aspect 9:16 --resolution 1080p --duration 8

python3 video.py generate "The knight walks through the market" \
  --ref knight_front.png --ref knight_side.png --ref sword.png   # consistent characters

python3 video.py edit output/lighthouse.mp4 "Make it a stormy night"            # change a clip
python3 video.py edit output/lighthouse.mp4 "Continue: a ship appears on the horizon"

python3 video.py stitch output/film.mp4 output/a.mp4 output/b.mp4   # join into one scene

python3 video.py generate "..." --backend veo --last-frame end.png --negative "text, watermark"
```

Each clip is saved to `output/` with a `.json` file next to it that records the prompt and settings. For omni clips, the `.json` also stores the conversation ID, so `edit` continues the same conversation and keeps the look consistent. Use `edit --upload` to edit any MP4 instead, such as footage you filmed yourself.

### Options and limits

| | omni | veo |
|---|---|---|
| Duration | 3–15 s (default 10), 3–10 s per edit/extension | 4, 6 or 8 s |
| Resolution | 360p, 720p (default), 1080p, 4k | 720p, 1080p |
| Aspect | 16:9, 9:16 | 16:9, 9:16 |
| Reference images | up to 6 (max 3 per character, 2 characters) | up to 3 |
| Extra | conversational edits, editing uploaded video | last frame, negative prompt |

You can change the defaults with the `VIDEO_BACKEND`, `OMNI_MODEL`, `VEO_MODEL` and `VIDEO_OUT_DIR` environment variables.

Tip: test prompts at `--resolution 360p --duration 3`, which is fast and cheap, then render the final version at 1080p.
