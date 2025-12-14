#!/usr/bin/env bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

export PODLY_INSTANCE_DIR="$REPO_ROOT/src/instance"
export PYTHONPATH="$REPO_ROOT/src"

# Default to downgrading one revision if not specified
REVISION=${1:-"-1"}

pipenv run flask --app app db downgrade "$REVISION"
