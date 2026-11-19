# OpenCode VPS prompt: pull and set up the one-frame reader

Copy this into OpenCode on the VPS (repository: tonimaen92-sudo/redditfleet-frame-reader):

---

You are on a Linux VPS. Set up the isolated one-frame media reader for sorting
Reddit content into subreddits.

1. Clone the repository:
   git clone https://github.com/tonimaen92-sudo/redditfleet-frame-reader.git
   cd redditfleet-frame-reader

2. Create the environment and install dependencies:
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt

3. Configure the models:
   cp .env.example .env
   # Edit .env and set OPENROUTER_API_KEY, FRAME_MODEL, SORT_MODEL.

4. Read INSTRUCTIONS_FOR_DEEPSEEK.md before changing anything.

5. Verify the one-frame reader works:
   python frame_reader.py --media /path/to/test.jpg --no-rank

6. Verify sorting:
   python frame_reader.py --media /path/to/clip.mp4 --subreddits subreddits.json

Rules:
- Keep exactly one frame per media item. Do not restore the 3-frame 20/50/80 sample.
- Do not add the RedditFleet comment/drafting prompt to this project.
- Do not commit .env or any API key.
- Report the JSON output and any errors.

---
