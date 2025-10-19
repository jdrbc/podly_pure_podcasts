### Security review for public deployment (Railway)

This app was originally designed for a trusted LAN. We are moving to a public deployment on Railway with the following explicit goals:

- Ensure API keys cannot be exposed via the public API or the configuration page.
- Ensure application logs are not exposed over HTTP.
- We are not, for now, locking down the configuration UI or download endpoints.

#### Scope and non‑goals

- In scope: HTTP/API surface, static file serving, config serialization, log exposure, CORS posture.
- Out of scope: DB compromise, infra/host hardening, authentication/authorization for the UI, transport security termination (assumed handled by Railway).

### Attack surface summary

- Public HTTP endpoints served by Flask blueprints `api`, `main`, and `feed`.
- Static files from `src/app/static/` served by Flask for the SPA.
- Config endpoints: `GET /api/config`, `PUT /api/config`.
- Audio/content endpoints under `/api/posts/*` and legacy `/post/*`.
- No intended routes for reading files under `src/instance/**` (which contains logs, data, db, etc.).

### Findings and mitigations

1) Configuration secrets exposure (CRITICAL)

- Before: `GET /api/config` returned combined configuration including `llm.llm_api_key` and, depending on whisper mode, `whisper.api_key`.
- Risk: Any unauthenticated client could fetch API keys. The Config page also displayed these values when loaded.
- Mitigation implemented:
  - Added server-side sanitizer that removes secrets from responses for both `GET /api/config` and the response body of `PUT /api/config`.
  - The database still stores the keys; omission in GET does not clear them because updates only mutate fields present in the payload.
  - Frontend now receives blank fields for secrets; the page does not render stored keys.

2) Static file traversal via feed route (HIGH)

- Before: `feed_routes.get_feed_by_alt_or_url` attempted to serve files using `send_file(Path(static)/<path>)`, which could be error-prone for traversal.
- Mitigation implemented: switched to `send_from_directory(current_app.static_folder, path)` which enforces directory bounds.

3) Logs exposure over HTTP (HIGH)

- Observed: Logs are written to `src/instance/logs/app.log`. Flask `static_folder` is `src/app/static`, and routes only serve from there.
- No endpoints serve `src/instance/**`. With the traversal fix above, logs cannot be accessed via HTTP.
- Additional controls:
  - The app does not log secrets. Grep audits show no logging of `llm_api_key` or `api_key` values.
  - Third-party client verbose logging is restricted (e.g., Groq client level set to INFO).

4) CORS posture (INFO)

- Default `CORS_ORIGINS` is `*` to enable the frontend hosted elsewhere. This does not expose secrets since config responses omit them and no cookies/session are used.
- Recommendation: Set `CORS_ORIGINS` to your deployed frontend origin(s) in Railway for defense-in-depth when convenient.

5) Minor informational disclosures (INFO)

- Endpoint `GET /post/<guid>/json` includes server file paths for processed/unprocessed audio. This is acceptable per current non-goals but note as a potential future hardening target.

### Verification checklist

- Config secrets are not returned:
  - `curl -s https://<host>/api/config | jq .llm` → must NOT contain `llm_api_key`.
  - `curl -s https://<host>/api/config | jq .whisper` → must NOT contain `api_key`.
  - After `PUT /api/config` with a new key, the response should still omit keys, and a subsequent `GET /api/config` should omit them as well.

- Logs are not retrievable over HTTP:
  - `curl -i https://<host>/src/instance/logs/app.log` → 404.
  - `curl -i https://<host>/feed/../../src/instance/logs/app.log` → 404.

- Traversal attempts into static are blocked:
  - `curl -i https://<host>/%2e%2e/%2e%2e/src/instance/db/sqlite3.db` → 404.

- No secrets in logs:
  - Search your Railway log stream for `llm_api_key` or `api_key` and confirm none appear.

### Operational guidance for Railway

- Secrets handling
  - Keys are stored in the application database and never returned over the API.
  - On the Config page, enter keys when needed; they won’t be displayed afterwards.

- Environment configuration
  - Optionally set `CORS_ORIGINS` in Railway to your frontend origin to narrow CORS.
  - Ensure no reverse proxy layer serves `src/instance/**` paths.

### Future hardening (post-MVP)

- Add auth to the Config page and debug endpoints.
- Consider encrypting API keys at rest in the DB with an app-level KMS secret.
- Remove server file paths from debug JSON or gate them behind auth.
- Tighten CORS to specific origins by default.

### Change log

- API: Config responses now sanitize secrets (omit `llm.llm_api_key` and `whisper.api_key`).
- Routes: Static serving in `feed_routes` restricted to `send_from_directory` to prevent traversal.


