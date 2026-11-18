#!/usr/bin/env python3
"""Generate and edit AI video with Google's models.

Two backends:
  omni  Gemini Omni Flash via the Gemini API (default). Needs GEMINI_API_KEY.
  veo   Veo via Gemini Enterprise Agent Platform (formerly Vertex AI). Needs a
        Google Cloud project with billing and the Agent Platform API enabled,
        plus either an API key allowed to call that API (VEO_API_KEY, falling
        back to GEMINI_API_KEY) or GOOGLE_CLOUD_PROJECT with
        application-default credentials.

Commands:
  models                       list the video models your credentials can use
  generate PROMPT [options]    text/image/reference-to-video
  edit CLIP.mp4 PROMPT         change a clip (omni) or extend it (omni/veo)
  stitch OUT.mp4 CLIP ...      join clips into one video (ffmpeg)
"""

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from google import genai
from google.genai import types

OMNI_MODEL = os.environ.get("OMNI_MODEL", "gemini-omni-flash-preview")
VEO_MODEL = os.environ.get("VEO_MODEL", "veo-3.1-generate-001")
OUT_DIR = pathlib.Path(os.environ.get("VIDEO_OUT_DIR", "output"))


# ---------- shared helpers ----------

def read_b64(path: str) -> tuple[str, str]:
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return base64.b64encode(pathlib.Path(path).read_bytes()).decode(), mime


def out_path(name: str | None, prompt: str) -> pathlib.Path:
    if not name:
        slug = "".join(ch if ch.isalnum() else "-" for ch in prompt.lower())[:40].strip("-")
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{slug or 'clip'}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / f"{name}.mp4"


def write_sidecar(path: pathlib.Path, meta: dict):
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(path)


def read_sidecar(clip: str) -> dict:
    p = pathlib.Path(clip).with_suffix(".json")
    return json.loads(p.read_text()) if p.exists() else {}


def tick(start: float):
    print(f"  generating... {int(time.time() - start)}s", file=sys.stderr, end="\r")


# ---------- Gemini Omni Flash ----------

def omni_client() -> genai.Client:
    # In a cloud session the network proxy can inject the key; the placeholder
    # is replaced on the way out.
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "proxy-injected"))


def omni_format(a) -> dict:
    fmt = {"type": "video", "delivery": "uri"}  # URI delivery handles large outputs
    if a.aspect:
        fmt["aspect_ratio"] = a.aspect
    if a.resolution:
        fmt["resolution"] = a.resolution
    if a.duration:
        fmt["duration"] = f"{a.duration}s"
    return fmt


def omni_run(a, inputs, previous_id=None) -> tuple[str, pathlib.Path]:
    c = omni_client()
    print(f"Model: {a.model}", file=sys.stderr)
    kwargs = dict(model=a.model, input=inputs, response_format=omni_format(a))
    if previous_id:
        kwargs["previous_interaction_id"] = previous_id
    start = time.time()
    r = c.interactions.create(**kwargs)
    video = r.output_video
    if video is None:
        sys.exit(f"No video returned (interaction {r.id}).")
    path = out_path(a.name, a.prompt)
    if getattr(video, "data", None):
        path.write_bytes(base64.b64decode(video.data))
    else:
        file_name = "files/" + video.uri.rstrip("/").split("/")[-1].split(":")[0]
        while (state := c.files.get(name=file_name).state.name) != "ACTIVE":
            if state == "FAILED":
                sys.exit("Video processing failed on Google's side.")
            tick(start)
            time.sleep(5)
        c.files.download(file=video.uri, destination=str(path))
    print(f"  done in {int(time.time() - start)}s", file=sys.stderr)
    return r.id, path


def omni_inputs(prompt: str, images=(), video_uri=None) -> list | str:
    parts = []
    for img in images:
        data, mime = read_b64(img)
        parts.append({"type": "image", "data": data, "mime_type": mime})
    if video_uri:
        parts.append({"type": "video", "uri": video_uri})
    if not parts:
        return prompt
    parts.append({"type": "text", "text": prompt})
    return parts


def omni_upload(c: genai.Client, clip: str) -> str:
    f = c.files.upload(file=clip)
    while f.state.name == "PROCESSING":
        time.sleep(5)
        f = c.files.get(name=f.name)
    if f.state.name == "FAILED":
        sys.exit("Upload processing failed.")
    return f.uri


# ---------- Veo on Agent Platform ----------

def veo_client() -> genai.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    if os.environ.get("VEO_AUTH") == "adc":
        # Application-default credentials (gcloud login or service account).
        if not project:
            sys.exit("Set GOOGLE_CLOUD_PROJECT to use VEO_AUTH=adc.")
        return genai.Client(vertexai=True, project=project, location=location)
    # API key allowed to call the Agent Platform API. Video generation needs the
    # project in the request, so pass it when known.
    key = os.environ.get("VEO_API_KEY") or os.environ.get("GEMINI_API_KEY", "proxy-injected")
    if project:
        return genai.Client(vertexai=True, api_key=key, project=project, location=location)
    return genai.Client(vertexai=True, api_key=key)


def veo_image(path: str) -> types.Image:
    return types.Image(image_bytes=pathlib.Path(path).read_bytes(),
                       mime_type=mimetypes.guess_type(path)[0] or "image/png")


def veo_run(a, source: types.GenerateVideosSource, cfg: dict) -> pathlib.Path:
    c = veo_client()
    print(f"Model: {a.model}", file=sys.stderr)
    config = types.GenerateVideosConfig(**{k: v for k, v in cfg.items() if v is not None})
    op = c.models.generate_videos(model=a.model, source=source, config=config)
    start = time.time()
    while not op.done:
        tick(start)
        time.sleep(10)
        op = c.operations.get(op)
    print(f"\n  done in {int(time.time() - start)}s", file=sys.stderr)
    if op.error:
        sys.exit(f"Veo error: {op.error}")
    videos = (op.response and op.response.generated_videos) or []
    if not videos:
        sys.exit(f"No video returned: {getattr(op.response, 'rai_media_filtered_reasons', None)}")
    path = out_path(a.name, a.prompt)
    path.write_bytes(videos[0].video.video_bytes)
    return path


# ---------- commands ----------

def cmd_models(a):
    c = omni_client() if a.backend == "omni" else veo_client()
    for m in c.models.list():
        if any(k in m.name.lower() for k in ("omni", "veo")):
            print(m.name.split("/")[-1], "-", m.display_name or "")


def cmd_generate(a):
    if a.backend == "omni":
        if a.last_frame or a.negative:
            sys.exit("--last-frame and --negative are only supported by the veo backend.")
        images = ([a.image] if a.image else []) + (a.ref or [])
        iid, path = omni_run(a, omni_inputs(a.prompt, images))
        write_sidecar(path, {"backend": "omni", "model": a.model, "prompt": a.prompt,
                             "images": images, "interaction_id": iid})
    else:
        source = types.GenerateVideosSource(prompt=a.prompt,
                                            image=veo_image(a.image) if a.image else None)
        refs = [types.VideoGenerationReferenceImage(image=veo_image(p), reference_type="ASSET")
                for p in (a.ref or [])]
        cfg = dict(aspect_ratio=a.aspect, resolution=a.resolution, duration_seconds=a.duration,
                   negative_prompt=a.negative, generate_audio=True,
                   last_frame=veo_image(a.last_frame) if a.last_frame else None,
                   reference_images=refs or None)
        path = veo_run(a, source, cfg)
        write_sidecar(path, {"backend": "veo", "model": a.model, "prompt": a.prompt,
                             "image": a.image, "refs": a.ref, "last_frame": a.last_frame})


def cmd_edit(a):
    meta = read_sidecar(a.clip)
    a.name = a.name or pathlib.Path(a.clip).stem + "-edit"
    if a.backend == "omni":
        previous = None if a.upload else meta.get("interaction_id")
        if previous:
            # Continue the conversation that produced the clip: best consistency.
            iid, path = omni_run(a, omni_inputs(a.prompt, a.ref or []), previous)
        else:
            uri = omni_upload(omni_client(), a.clip)
            iid, path = omni_run(a, omni_inputs(a.prompt, a.ref or [], uri))
        write_sidecar(path, {"backend": "omni", "model": a.model, "prompt": a.prompt,
                             "edited_from": a.clip, "interaction_id": iid})
    else:
        video = types.Video(video_bytes=pathlib.Path(a.clip).read_bytes(), mime_type="video/mp4")
        path = veo_run(a, types.GenerateVideosSource(prompt=a.prompt, video=video),
                       dict(resolution="720p"))
        write_sidecar(path, {"backend": "veo", "model": a.model, "prompt": a.prompt,
                             "extends": a.clip})


def cmd_stitch(a):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for clip in a.clips:
            f.write(f"file '{pathlib.Path(clip).resolve()}'\n")
    # Re-encode to a common format so clips from either backend join cleanly.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f.name,
         "-vf", f"scale={a.size}:force_original_aspect_ratio=decrease,"
                f"pad={a.size}:(ow-iw)/2:(oh-ih)/2,fps=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", a.out],
        check=True,
    )
    os.unlink(f.name)
    print(a.out)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def backend_args(sp):
        sp.add_argument("--backend", choices=["omni", "veo"],
                        default=os.environ.get("VIDEO_BACKEND", "omni"))
        sp.add_argument("--model", help=f"default: {OMNI_MODEL} (omni) / {VEO_MODEL} (veo)")

    m = sub.add_parser("models", help="list available video models")
    backend_args(m)
    m.set_defaults(fn=cmd_models)

    g = sub.add_parser("generate", help="text/image/reference to video")
    g.add_argument("prompt")
    g.add_argument("--image", help="starting image / drawing to animate")
    g.add_argument("--ref", action="append",
                   help="reference image for a character or object (repeatable; omni up to 6, veo up to 3)")
    g.add_argument("--last-frame", help="ending frame image (veo only, needs --image)")
    g.add_argument("--aspect", choices=["16:9", "9:16"])
    g.add_argument("--resolution", choices=["360p", "720p", "1080p", "4k"])
    g.add_argument("--duration", type=int, help="seconds (omni 3-15, default 10; veo 4/6/8)")
    g.add_argument("--negative", help="what to avoid (veo only)")
    g.add_argument("--name", help="output file name, no extension")
    backend_args(g)
    g.set_defaults(fn=cmd_generate)

    e = sub.add_parser("edit", help="change or extend a clip")
    e.add_argument("clip")
    e.add_argument("prompt", help='e.g. "make it night" or "continue: the boat reaches a drain"')
    e.add_argument("--ref", action="append", help="extra reference image (omni)")
    e.add_argument("--upload", action="store_true",
                   help="omni: upload the file instead of continuing its original conversation")
    e.add_argument("--aspect", choices=["16:9", "9:16"])
    e.add_argument("--resolution", choices=["360p", "720p", "1080p", "4k"])
    e.add_argument("--duration", type=int, help="seconds to add/produce (omni 3-10)")
    e.add_argument("--name")
    backend_args(e)
    e.set_defaults(fn=cmd_edit)

    s = sub.add_parser("stitch", help="join clips into one video")
    s.add_argument("out")
    s.add_argument("clips", nargs="+")
    s.add_argument("--size", default="1280:720", help="output WxH, e.g. 1080:1920 for vertical")
    s.set_defaults(fn=cmd_stitch)

    a = p.parse_args()
    if hasattr(a, "model") and not a.model:
        a.model = OMNI_MODEL if a.backend == "omni" else VEO_MODEL
    if not hasattr(a, "prompt"):
        a.prompt = ""
    a.fn(a)


if __name__ == "__main__":
    main()
