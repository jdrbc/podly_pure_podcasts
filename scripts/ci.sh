#!/bin/bash

# format
pipenv run black .
pipenv run isort .

pipenv run mypy . --exclude 'migrations' --exclude 'build' --exclude 'src/app/routes.py' --exclude 'src/tests' --exclude 'src/conftest.py'
pipenv run pylint --ignore=migrations .

pipenv run pytest --disable-warnings
