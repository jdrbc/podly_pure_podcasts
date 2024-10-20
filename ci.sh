#!/bin/bash

# format
pipenv run black .
pipenv run isort .

pipenv run mypy .
pipenv run pylint .

pipenv run pytest
