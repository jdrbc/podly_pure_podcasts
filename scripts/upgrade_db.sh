#!/usr/bin/env bash

export PODLY_INSTANCE_DIR="$(pwd)/src/instance"
pipenv run flask --app ./src/main.py db downgrade $1