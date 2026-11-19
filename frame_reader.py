"""One-frame media reader for sorting Reddit posts into subreddits.

This is the isolated, 1-frame version of RedditFleet's NSFW comment frame
reader. It keeps the same sampling and vision-model approach, but reads a
single frame (midpoint of a video, or the still image) instead of the
original 20% / 50% / 80% three-frame sample.

CLI:
    python frame_reader.py --media clip.mp4 --subreddits subreddits.json
    python frame_reader.py --media photo.jpg --subreddits subreddits.json --no-rank
"""

import argparse
import base64
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import cv2
import requests
from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_TYPES = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
VIDEO_TYPES = {".mp4", ".mov", ".webm", ".avi"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_VIDEO_SECONDS = 300
MAX_IMAGE_PIXELS = 24_000_000
MAX_VIDEO_PIXELS = 4096 * 2160
MAX_FRAME_EDGE = 1280
VIDEO_FRACTION = 0.5          # the one frame: video midpoint
VIDEO_TIMEOUT_MS = 5000


class MediaError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Frame:
    timestamp_seconds: float | None
    jpeg: bytes


def _is_local_path(path):
    value = str(path).replace("\\", "/")
    return not (value.startswith("//") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]+:", value)
                or ":" in value[2:])


def _read_local(path, limit):
    try:
        resolved = path.resolve(strict=True)
        if not _is_local_path(resolved):
            raise MediaError("invalid_media_path")
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode):
            raise MediaError("file_unavailable")
        if info.st_size > limit:
            raise MediaError("media_too_large")
        with resolved.open("rb") as stream:
            content = stream.read(limit + 1)
    except (OSError, RuntimeError, ValueError):
        raise MediaError("file_unavailable") from None
    if len(content) > limit:
        raise MediaError("media_too_large")
    return content


def _image_frame(content, expected_format):
    try:
        with Image.open(BytesIO(content), formats=[expected_format]) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise MediaError("frame_too_large")
            if getattr(image, "is_animated", False):
                raise MediaError("animated_image")
            corrected = ImageOps.exif_transpose(image)
            corrected.thumbnail((MAX_FRAME_EDGE, MAX_FRAME_EDGE), Image.Resampling.LANCZOS)
            if "A" in corrected.getbands() or "transparency" in corrected.info:
                rgba = corrected.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = corrected.convert("RGB")
    except Image.DecompressionBombError:
        raise MediaError("frame_too_large") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, OverflowError):
        raise MediaError("invalid_image") from None
    output = BytesIO()
    rgb.save(output, format="JPEG", quality=82)
    return Frame(None, output.getvalue())


def _is_video_container(content, suffix):
    if suffix in {".mp4", ".mov"}:
        return content[4:8] in {b"ftyp", b"wide", b"free", b"moov", b"mdat"}
    if suffix == ".webm":
        return content.startswith(b"\x1a\x45\xdf\xa3")
    return content.startswith(b"RIFF") and content[8:12] == b"AVI "


def _encode_video_frame(frame, timestamp):
    height, width = frame.shape[:2]
    if not height or not width or height * width > MAX_VIDEO_PIXELS:
        raise MediaError("frame_too_large")
    try:
        if max(height, width) > MAX_FRAME_EDGE:
            ratio = MAX_FRAME_EDGE / max(height, width)
            frame = cv2.resize(frame, (max(1, round(width * ratio)), max(1, round(height * ratio))),
                               interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    except cv2.error:
        raise MediaError("encode_failed") from None
    if not ok:
        raise MediaError("encode_failed")
    return Frame(timestamp, encoded.tobytes())


def _video_frame(content, suffix):
    if not _is_video_container(content, suffix):
        raise MediaError("invalid_video")
    capture = cv2.VideoCapture()
    stream = BytesIO(content)
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, VIDEO_TIMEOUT_MS,
              cv2.CAP_PROP_READ_TIMEOUT_MSEC, VIDEO_TIMEOUT_MS]
    try:
        try:
            opened = capture.open(stream, cv2.CAP_FFMPEG, params)
        except (TypeError, cv2.error):
            raise MediaError("invalid_video") from None
        if not opened:
            raise MediaError("invalid_video")

        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not (math.isfinite(frame_count) and frame_count > 0
                and math.isfinite(fps) and fps > 0):
            raise MediaError("invalid_video_metadata")
        if frame_count / fps > MAX_VIDEO_SECONDS:
            raise MediaError("video_too_long")

        width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
            raise MediaError("invalid_video_metadata")
        if width * height > MAX_VIDEO_PIXELS:
            raise MediaError("frame_too_large")

        index = int(frame_count * VIDEO_FRACTION)
        if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
            raise MediaError("video_seek_failed")
        ok, frame = capture.read()
        if not ok or frame is None:
            raise MediaError("frame_decode_failed")
        return _encode_video_frame(frame, index / fps)
    except cv2.error:
        raise MediaError("frame_decode_failed") from None
    finally:
        capture.release()
        stream.close()


def sample_one_frame(path):
    """Return exactly one Frame: the still image, or a video midpoint frame."""
    path = Path(path)
    if not _is_local_path(path):
        raise MediaError("invalid_media_path")
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        return _image_frame(_read_local(path, MAX_IMAGE_BYTES), IMAGE_TYPES[suffix])
    if suffix in VIDEO_TYPES:
        return _video_frame(_read_local(path, MAX_VIDEO_BYTES), suffix)
    raise MediaError("unsupported_media")


def _post_chat(model, messages, max_tokens=500):
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY first.")
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "max_tokens": max_tokens,
              "reasoning": {"enabled": False}, "stream": False},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"].get("content") or ""


def _parse_json(text):
    text = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except ValueError:
        return {}


OBSERVATION_PROMPT = """You are reading ONE frame from a Reddit post's media to sort it
into the right subreddit. Return ONLY a JSON object with these keys:
- observations: one short, neutral sentence describing only what is clearly visible.
- tags: 5-15 lowercase content tags (body focus, clothing, setting, activity, style).
- body_focus: comma-separated visible focus areas, or "" when unclear.
- setting: indoor/outdoor/studio/unknown and a short detail.
- clothing: visible clothing or "nude" when clearly nude; "" when unclear.
- acts: visible activity or pose; "" when unclear.
- people: "solo", "couple", "group", or "unknown".
- text_on_image: visible text only, otherwise "".
- promotional_cta: true only if the visible text asks viewers to message, follow,
  subscribe, visit a bio/link, or open a paid profile.
Describe only this single frame. Never infer audio, identity, age, race, ethnicity,
intent, or what happened before/after. Do not be graphic."""


def describe_frame(frame, model=None):
    """Read one frame and return the structured observation JSON."""
    model = model or os.environ.get("FRAME_MODEL", "deepseek/deepseek-v4.1-flash-1017")
    image = base64.b64encode(frame.jpeg).decode("ascii")
    content = [
        {"type": "text", "text": OBSERVATION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
    ]
    raw = _post_chat(model, [{"role": "user", "content": content}], max_tokens=420)
    result = _parse_json(raw)
    if not isinstance(result, dict):
        return {}
    return result


def rank_subreddits(observation, candidates, model=None):
    """Rank candidate subreddits against one frame's observations."""
    model = model or os.environ.get("SORT_MODEL", "deepseek/deepseek-v4-pro-0813")
    prompt = f"""Sort one Reddit post into the best-fitting subreddits.

Frame observations (JSON):
{json.dumps(observation, ensure_ascii=False)}

Candidate subreddits (JSON):
{json.dumps(candidates, ensure_ascii=False)}

Return ONLY a JSON object:
{{"ordered": [{{"name": "<exact candidate name>", "score": 0-100, "reason": "<one short sentence>"}}]}}
Rank the best 5 fits. Use only candidate names. Score 90+ only when the frame
clearly matches the subreddit's stated theme; 50-89 for plausible; below 50 for weak.
Never invent a subreddit."""
    raw = _post_chat(model, [{"role": "user", "content": prompt}], max_tokens=600)
    result = _parse_json(raw)
    ordered = result.get("ordered") if isinstance(result, dict) else None
    if not isinstance(ordered, list):
        return []
    cleaned = []
    names = {c["name"] for c in candidates}
    for row in ordered:
        if isinstance(row, dict) and row.get("name") in names:
            cleaned.append({"name": row["name"], "score": row.get("score"),
                            "reason": row.get("reason", "")})
    return cleaned


def main():
    parser = argparse.ArgumentParser(description="Read one media frame and sort it into subreddits.")
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--subreddits", type=Path, help="JSON list of {name, description, keywords}")
    parser.add_argument("--no-rank", action="store_true", help="Only return observations/tags")
    args = parser.parse_args()

    frame = sample_one_frame(args.media)
    observation = describe_frame(frame)
    result = {
        "file": str(args.media),
        "frame": "still" if frame.timestamp_seconds is None else f"{frame.timestamp_seconds:.2f}s",
        "observation": observation,
    }
    if args.subreddits and not args.no_rank:
        candidates = json.loads(args.subreddits.read_text(encoding="utf-8"))
        result["ranked_subreddits"] = rank_subreddits(observation, candidates)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
