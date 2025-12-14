Project-specific rules:
- Do not create Alembic migrations yourself; request the user to generate migrations after model changes.
- Only use ./scripts/ci.sh to run tests & lints - do not attempt to run directly
- use pipenv