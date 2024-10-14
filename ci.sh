#!/bin/bash

# Run mypy
pipenv run mypy .

# Run pylint
pipenv run pylint **/*.py

# Run black
pipenv run black .

# Run isort
pipenv run isort .

# Run pytest
pipenv run pytest