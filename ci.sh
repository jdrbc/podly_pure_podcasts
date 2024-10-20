#!/bin/bash

pipenv run mypy .

pipenv run pylint .

pipenv run black .

pipenv run isort .

pipenv run pytest
