# OpenCode prompt: pull and set up the one-frame reader

Repository (public): https://github.com/tonimaen92-sudo/redditfleet-frame-reader.git

---

You are on the machine that will run the one-frame media reader. The repository is public.

1. Clone it:
   git clone https://github.com/tonimaen92-sudo/redditfleet-frame-reader.git
   cd redditfleet-frame-reader

2. Create the environment (use the block for this OS):
   Linux/macOS:
     python3 -m venv .venv
     . .venv/bin/activate
   Windows PowerShell:
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1

3. Install:
   pip install -r requirements.txt

4. Configure:
   copy .env.example .env      (Windows)
   cp .env.example .env        (Linux/macOS)
   Set OPENROUTER_API_KEY, FRAME_MODEL and SORT_MODEL in .env.

5. Read INSTRUCTIONS_FOR_DEEPSEEK.md before changing anything.

6. Verify one-frame reading:
   python frame_reader.py --media /path/to/test.jpg --no-rank

7. Verify sorting:
   python frame_reader.py --media /path/to/clip.mp4 --subreddits subreddits.json

Rules:
- Keep exactly one frame per media item. Do not restore the 3-frame 20/50/80 sample.
- Do not add the RedditFleet comment/drafting prompt to this project.
- Do not commit .env or any API key.
- Report the raw JSON output and any errors.
