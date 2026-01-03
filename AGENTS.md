Project-specific rules:
- Do not create Alembic migrations yourself; request the user to generate migrations after model changes.
- Only use ./scripts/ci.sh to run tests & lints - do not attempt to run directly
- use pipenv
- All database writes must go through the `writer` service. Do not use `db.session.commit()` directly in application code. Use `writer_client.action()` instead.
