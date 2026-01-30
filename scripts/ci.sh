#!/bin/bash

# Parse command line arguments
RUN_INTEGRATION=false
for arg in "$@"; do
    if [ "$arg" = "--int" ]; then
        RUN_INTEGRATION=true
    fi
done

# format
echo '============================================================='
echo "Running 'pipenv run black .'"
echo '============================================================='
pipenv run black .
echo '============================================================='
echo "Running 'pipenv run isort .'"
echo '============================================================='
pipenv run isort .

# lint and type check
echo '============================================================='
echo "Running 'pipenv run mypy .'"
echo '============================================================='
pipenv run mypy . \
    --explicit-package-bases \
    --exclude 'migrations' \
    --exclude 'build' \
    --exclude 'scripts' \
    --exclude 'src/tests' \
    --exclude 'src/tests/test_routes.py' \
    --exclude 'src/app/routes.py'

echo '============================================================='
echo "Running 'pipenv run pylint src/ --ignore=migrations,tests'"
echo '============================================================='
pipenv run pylint src/ --ignore=migrations,tests

# run tests
echo '============================================================='
echo "Running 'pipenv run pytest --disable-warnings'"
echo '============================================================='
pipenv run pytest --disable-warnings

# Run integration tests only if --int flag is provided
if [ "$RUN_INTEGRATION" = true ]; then
    echo '============================================================='
    echo "Running integration workflow checks..."
    echo '============================================================='
    pipenv run python scripts/check_integration_workflow.py
fi