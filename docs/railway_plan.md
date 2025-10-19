## Podly on Railway: Deployment Plan

This plan deploys the Flask backend (serving the built React frontend) as a single Railway Service using the existing multi-stage Dockerfile. It uses persistent volumes for SQLite DB and audio storage and optional scheduled jobs via the app’s built-in APScheduler.

### 1) Prereqs
- **Repo**: Push this repo to GitHub (or fork) so Railway can build it.
- **Docker**: We’ll use the existing `Dockerfile` (CPU-only by default). No custom buildpacks needed.
- **Ports**: App listens on port `5001` via Waitress.

### 2) Create a Railway Project and Service
1. In Railway, create a new project.
2. Add a service:
   - Option A (build from source): Deploy from GitHub → select this repo.
   - Option B (use prebuilt image from GHCR): Deploy from Image → set image to `ghcr.io/<owner>/podly-pure-podcasts:<tag>` (see tags below). This avoids long Docker builds on Railway.
3. Build / image settings:
   - Root: `.`
   - If Option A: Dockerfile: `Dockerfile`
     - Build args (optional): `LITE_BUILD=true` to skip local Whisper and reduce image size (recommended for Railway).
   - If Option B: Image reference examples (public):
     - `ghcr.io/<owner>/podly-pure-podcasts:lite` (recommended)
     - `ghcr.io/<owner>/podly-pure-podcasts:latest` (larger; includes local Whisper)
     - `ghcr.io/<owner>/podly-pure-podcasts:main-lite` (branch-suffixed)
     - For private images, add a registry auth and scope to `ghcr.io`.
   - No GPU settings (Railway containers are CPU).
4. Start command:
   - If Option A: leave default from Dockerfile (`ENTRYPOINT / CMD` run `python3 -u src/main.py`).
   - If Option B: also leave the container default CMD; images are built with the same entrypoint.

### 3) Environment Variables
Set these in the Service → Variables:
- Optional CORS:
  - `CORS_ORIGINS=*` (or a comma list of origins).
- LLM config (used for ad detection summarization, not for Whisper unless using remote):
  - `LLM_API_KEY` (or `OPENAI_API_KEY` or `GROQ_API_KEY` – any one will be picked up)
  - `LLM_MODEL` (default `gpt-4o`)
  - `OPENAI_BASE_URL` (optional if using an OpenAI-compatible provider)
- Whisper provider selection:
  - `WHISPER_TYPE` = `remote` | `groq` | `local` | `test`
    - For Railway, set `remote` or `groq`. `local` requires Whisper/pytorch which is heavy.
  - If `remote`:
    - `OPENAI_API_KEY` (or `WHISPER_REMOTE_API_KEY`)
    - `WHISPER_REMOTE_BASE_URL` (optional, default `https://api.openai.com/v1`)
    - `WHISPER_REMOTE_MODEL` (default `whisper-1`)
  - If `groq`:
    - `GROQ_API_KEY`
    - `GROQ_WHISPER_MODEL` (default `whisper-large-v3-turbo`)
- Background scheduler (optional):
  - To enable automatic refreshes, configure in-app at `/config` → App → Background interval. You can also seed via DB after first run; there’s no separate env for interval.

Notes:
- The app applies env var overrides at boot and stores persistent settings in SQLite. You can also configure everything from the web UI at `/config` after first deployment.

GHCR tags published by CI (from `.github/workflows/docker-publish.yml`):
- `latest`, `lite` (multi-arch) on default branch
- Branch/semver-suffixed variants like `main-latest`, `main-lite`, and `vX.Y.Z-latest`/`vX.Y.Z-lite`
- For Railway, prefer `:lite` or `:main-lite` to keep images small and CPU-friendly.

### 4) Persistent Storage (Volumes)
Create a persistent volume and mount it at `/app/src/instance` so DB and data survive restarts:
- In Railway → Service → Settings → Volumes → Add Volume
  - Mount path: `/app/src/instance`

What’s stored there:
- SQLite DB files: `sqlite3.db`, `db/`, `migrations` state
- APScheduler job store: `jobs.sqlite`
- Logs: `logs/app.log`
- Audio:
  - Unprocessed input: `data/in/`
  - Processed output: `data/srv/` (exposed by app in feeds)

### 5) Networking
- Railway assigns an external URL. The app serves the React UI and API from the same service on port `5001`.
- No additional proxy config is required. Ensure the service’s internal port is set to `5001`.

### 6) Healthcheck
Configure a basic HTTP healthcheck:
- Path: `/`
- Expected HTTP: 200
- Interval/timeout: defaults are fine.

### 7) Build/Run Profile
- Container size: use a plan with enough RAM for ffmpeg and CPU processing. For remote Whisper, CPU is sufficient.
- If image build time is long, ensure `LITE_BUILD=true` so Whisper and torch are not installed.

### 8) Post-Deploy Steps
1. Open the public URL → `/config` and input keys and preferences.
2. Choose Whisper provider:
   - Remote OpenAI-compatible: set API key and model.
   - Groq: set `GROQ_API_KEY` and model.
3. Optionally enable background updates by setting a minutes interval.
4. Add a podcast feed from the homepage.

### 9) Optional: Custom Domain
Point a custom domain to the Railway service; configure CORS if you’ll access the API from another origin.

### 10) Backups
- Periodically export `/app/src/instance/sqlite3.db` and `/app/src/instance/data/`.
- You can also snapshot the entire mounted volume from Railway.

### 11) Troubleshooting
- 404 at `/`: Make sure frontend assets are bundled into the image (the Dockerfile copies `frontend/dist` to `src/app/static`) and the container started successfully.
- DB locked errors: Railway’s shared CPU can be slow; retries are configured with a `timeout=90` for SQLite. If persistent, scale up CPU/RAM.
- Whisper model errors: If using `remote`, ensure `OPENAI_API_KEY`/`base_url` are correct; test via `/api/config/test-whisper`.
- Large audio files timing out: Use remote Whisper to offload transcription. Ensure background jobs are enabled for periodic refreshes if desired.

### 12) Example Railway Variables (remote OpenAI Whisper)
- `CORS_ORIGINS=*`
- `WHISPER_TYPE=remote`
- `OPENAI_API_KEY=...`
- `WHISPER_REMOTE_MODEL=whisper-1`
- `LLM_API_KEY=...` (can be same as OpenAI if using OpenAI for LLM)
- `LLM_MODEL=gpt-4o`

That’s it. The single service will host both API and UI, with persistent storage for DB and audio.

