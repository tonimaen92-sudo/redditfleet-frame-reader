# Instructions for DeepSeek on the VPS: one-frame reader for subreddit sorting

## What this is

This folder is the isolated 1-frame version of RedditFleet's media frame reader.
The original reader samples **three** video frames at 20% / 50% / 80% and asks
the vision model for one observation per frame. This version samples **one**
frame (video midpoint, or the still image) and asks the vision model for a
single structured observation that can be used to sort the post into subreddits.

Original code in the separate content engine (for reference only, do not edit these on the VPS):

| Concern | Original file | Key lines |
|---|---|---|
| 3-frame sampling | `content_engine/media.py` | `_VIDEO_FRACTIONS = (0.2, 0.5, 0.8)`; `_video_frames`; `sample_media` |
| Bounded video decode | `content_engine/media.py` | `_is_video_container`, `_encode_video_frame`, `_video_frames` |
| Vision request | `content_engine/client.py` | `describe_frames` (accepts 1 or 3 frames) |
| Observation validation | `content_engine/drafting.py` | `_vision_review` (expects one note per frame) |
| Media download | `backend/nsfw_autopilot_media.py` | `download_media` (browser/CDP fetch, size caps) |

The standalone `frame_reader.py` here already contains the 1-frame adaptation;
you do not need the rest of RedditFleet to run it.

## The exact 3-frame -> 1-frame change

If you adapt the original `media.py` directly instead of using the standalone
file, make these changes:

1. Replace:
   ```python
   _VIDEO_FRACTIONS = (0.2, 0.5, 0.8)
   ```
   with:
   ```python
   _VIDEO_FRACTION = 0.5
   ```
2. In `_video_frames`, replace the `for fraction in _VIDEO_FRACTIONS:` loop with a
   single sample:
   ```python
   index = int(frame_count * _VIDEO_FRACTION)
   if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
       raise MediaError("video_seek_failed")
   ok, frame = capture.read()
   if not ok or frame is None:
       raise MediaError("frame_decode_failed")
   return (_encode_video_frame(frame, index / fps),)
   ```
3. Change the minimum-frame check from `frame_count < 3` to `frame_count < 1`
   (or remove it, since `frame_count > 0` is already checked).
4. In `client.py::describe_frames`, change:
   ```python
   if len(frames) not in (1, 3):
       raise ValueError("Expected one still or three ordered video frames.")
   ```
   to:
   ```python
   if len(frames) != 1:
       raise ValueError("Expected exactly one frame.")
   ```
   and make the prompt singular: "Describe only this one frame. Never infer
   things that are not visible in it."
5. `drafting.py::_vision_review` already compares `len(observations)` to
   `len(frames)`, so it needs no change once `frames` has length 1.

## Files in this folder

- `frame_reader.py` - self-contained sampler + vision call + subreddit ranking.
- `subreddits.example.json` - candidate format: `name`, `description`, `keywords`.
- `requirements.txt` - runtime dependencies.
- `.env.example` - model and API settings.

## VPS setup

```bash
cd /path/to/frame_reader
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with the real OPENROUTER_API_KEY
```

`FRAME_MODEL` must be a vision-capable model that accepts image input.
`SORT_MODEL` can be a text-only model.

## Run: read one frame only

```bash
python frame_reader.py --media /path/to/clip.mp4 --no-rank
```

Output:

```json
{
  "file": "/path/to/clip.mp4",
  "frame": "3.42s",
  "observation": {
    "observations": "A person is visible from behind in a bedroom, wearing a thong.",
    "tags": ["from behind", "thong", "bedroom", "ass focus"],
    "body_focus": "ass",
    "setting": "indoor, bedroom",
    "clothing": "thong",
    "acts": "standing",
    "people": "solo",
    "text_on_image": "",
    "promotional_cta": false
  }
}
```

## Run: read and sort into subreddits

```bash
python frame_reader.py --media /path/to/clip.mp4 --subreddits subreddits.json
```

Output adds:

```json
"ranked_subreddits": [
  {"name": "ass_cheeks", "score": 94, "reason": "Rear view with visible cheeks in a thong."},
  {"name": "ass", "score": 82, "reason": "General ass-focused content."}
]
```

## Sorting pipeline to implement on the VPS

1. Build `subreddits.json` from the live subreddit list. For each subreddit
   include:
   - `name`: exact subreddit name, no `r/`.
   - `description`: the subreddit's short description or rules summary.
   - `keywords`: 5-20 lowercase terms that distinguish that subreddit.
2. For each media file:
   - call `sample_one_frame(path)`.
   - call `describe_frame(frame)`.
   - call `rank_subreddits(observation, candidates)`.
3. Accept the top result only when `score >= 70`; otherwise send it to manual
   review instead of forcing a subreddit.
4. Persist `file`, `frame`, `observation`, `ranked_subreddits`, and the chosen
   subreddit.
5. Keep one file per media item; never write the JPEG frames to disk.

## Hard requirements

- **Exactly one frame per item.** Do not silently fall back to 3 frames.
- Do not infer audio, identity, race, ethnicity, age, intent, or events outside
  the frame.
- Reject files over 100 MiB, videos over 300 seconds, images over 24 MP, and
  videos over 4096x2160.
- Use `cv2.CAP_FFMPEG` with the 5-second open/read timeouts from
  `frame_reader.py`; do not pass untrusted URLs directly to OpenCV.
- Keep the JPEG encode at quality 82 and the longest edge at 1280 px.
- Never call the vision model with more than one image in this version.

## Integration note

The original project's `create_draft` path also expects frame notes. For sorting
you only need `sample_one_frame` + `describe_frame`; you do not need
`create_draft`, `style_examples.json`, the persona, or the comment prompt.
