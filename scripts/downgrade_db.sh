#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/create_migration.sh "message"
# Creates migrations using the project's local instance directory so the app
# doesn't attempt to mkdir /app on macOS dev machines.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

MIGRATION_MSG=${1:-"migration"}

# Prefer using repo-local src/instance to avoid writing to /app
export PODLY_INSTANCE_DIR="$REPO_ROOT/src/instance"

echo "Using PODLY_INSTANCE_DIR=$PODLY_INSTANCE_DIR"

# Ensure instance and data directories exist
mkdir -p "$PODLY_INSTANCE_DIR"
mkdir -p "$PODLY_INSTANCE_DIR/data/in"
mkdir -p "$PODLY_INSTANCE_DIR/data/srv"

echo "Applying migration (upgrade)"

read -r -p "Apply migration now? [y/N]: " response
case "$response" in
    [yY][eE][sS]|[yY])
        echo "Applying migration..."
        pipenv run flask --app ./src/main.py db upgrade
        echo "Migration applied."
        ;;
    *)
        echo "Upgrade cancelled. Migration files created but not applied."
        ;;
esac
