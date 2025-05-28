#!/bin/bash

# format
pipenv run black .
pipenv run isort .

pipenv run mypy . \
    --exclude 'migrations' \
    --exclude 'build' \
    --exclude 'scripts' \
    --exclude 'src/tests' \
    --exclude 'src/tests/test_routes.py' \
    --exclude 'src/app/routes.py'

pipenv run pylint .

pipenv run pytest --disable-warnings
