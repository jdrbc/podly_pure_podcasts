# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Podly is an ad-blocking system for podcasts. It creates ad-free RSS feeds by downloading episodes, transcribing them with Whisper, using LLMs to identify ad segments, and removing those segments from the audio.

## Development Commands

```bash
# Install dependencies
pipenv install --dev

# Run all CI checks (format, lint, type check, tests)
scripts/ci.sh

# Run individual checks
pipenv run black .                                    # Format code
pipenv run isort .                                    # Sort imports
pipenv run mypy . --explicit-package-bases --exclude 'migrations' --exclude 'build' --exclude 'scripts' --exclude 'src/tests'
pipenv run pylint src/ --ignore=migrations,tests     # Lint
pipenv run pytest --disable-warnings                 # Run tests

# Run a single test
pipenv run pytest src/tests/test_file.py::test_name --disable-warnings

# Database migrations (do NOT create migrations manually - request user to run after model changes)
pipenv run flask --app ./src/main.py db migrate -m "[description]"

# Docker development
./run_podly_docker.sh --dev    # Rebuild containers after code changes
./run_podly_docker.sh          # Run with existing container
```

## Architecture

### Backend (Flask + SQLite)

The backend uses a **writer service pattern** to serialize all database writes through a single process, preventing SQLite lock contention.

**Key constraint**: All database writes must go through `writer_client.action()` or `writer_client.update()`. Never use `db.session.commit()` directly in application code.

```
src/
├── main.py                    # Entry point, creates web app with Waitress server
├── app/
│   ├── __init__.py            # Flask app factory (create_web_app, create_writer_app)
│   ├── models.py              # SQLAlchemy models (Feed, Post, User, ProcessingJob, etc.)
│   ├── routes/                # Flask route blueprints
│   ├── writer/                # Writer service for serialized DB writes
│   │   ├── client.py          # writer_client singleton - use this for all writes
│   │   ├── service.py         # Writer service process
│   │   └── actions/           # Write actions (jobs, processor, system)
│   ├── jobs_manager.py        # Background job scheduling and management
│   └── processor.py           # ProcessorSingleton for podcast processing
├── podcast_processor/         # Core podcast processing logic
│   ├── podcast_processor.py   # Main PodcastProcessor class
│   ├── transcription_manager.py  # Whisper transcription (local/remote/groq)
│   ├── ad_classifier.py       # LLM-based ad segment classification
│   ├── audio_processor.py     # Audio manipulation (ffmpeg)
│   └── chapter_filter.py      # Chapter-based ad detection alternative
└── shared/                    # Shared utilities and config
```

### Frontend (React + Vite + TypeScript)

```
frontend/
├── src/
│   ├── components/           # React components
│   ├── pages/                # Page components (HomePage, ConfigPage, etc.)
│   ├── contexts/             # React contexts (Auth, AudioPlayer, Diagnostics)
│   └── services/api.ts       # API client
```

Frontend runs on port 5173 during development (proxies to backend on 5001) and is built as static assets for production.

### Processing Pipeline

1. **Download**: `PodcastDownloader` fetches episode audio
2. **Transcribe**: `TranscriptionManager` uses Whisper (local/OpenAI/Groq)
3. **Classify**: `AdClassifier` uses LLM to identify ad segments in transcript
4. **Process**: `AudioProcessor` removes ad segments with fade transitions

Two ad detection strategies:
- `llm`: Full transcription + LLM classification (default)
- `chapter`: Uses embedded chapter markers to identify ads (faster, no LLM cost)

### Database Models

Core models in `src/app/models.py`:
- `Feed`: Podcast feed with RSS URL and settings
- `Post`: Individual episode with audio paths and processing state
- `TranscriptSegment`: Transcript chunks with timing
- `Identification`: Ad segment classifications from LLM
- `ProcessingJob`: Background job tracking
- `User`: Authentication and subscription state

Settings tables (singleton pattern):
- `LLMSettings`, `WhisperSettings`, `ProcessingSettings`, `OutputSettings`, `AppSettings`

## Testing

Tests use pytest with fixtures defined in `src/tests/conftest.py`. Key patterns:
- Use custom mock classes instead of `MagicMock(spec=Model)` to avoid Flask context issues
- Prefer constructor injection over patching
- Use `tmp_path` fixture for file operations
- Use `monkeypatch` to replace external resource access

## Code Style

- Black for formatting (line length 88)
- isort for import sorting (black profile)
- mypy with strict mode for type checking
- Type hints required for all new code
