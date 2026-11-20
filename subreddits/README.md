# Per-account subreddit lists

Each file matches the subreddits assigned to that account in the Live Logs/NSFW Comments setup.
Use the account file with the reader:

```bash
python frame_reader.py --media clip.mp4 --subreddits subreddits/<account>.json
```

`subreddits.json` is the deduplicated union.
