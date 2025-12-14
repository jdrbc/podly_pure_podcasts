#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <branch-name> [<start-point>]" >&2
  exit 1
}

if [[ ${1-} == "" ]]; then
  usage
fi

BRANCH_NAME="$1"
START_POINT="${2-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKTREES_ROOT="$REPO_ROOT/.worktrees"
WORKTREE_PATH="$WORKTREES_ROOT/$BRANCH_NAME"

if git worktree list --porcelain | grep -q "^worktree $WORKTREE_PATH$"; then
  echo "Worktree already exists at $WORKTREE_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$WORKTREE_PATH")"

if [[ -d "$WORKTREE_PATH" ]]; then
  echo "Target path $WORKTREE_PATH already exists. Remove it first." >&2
  exit 1
fi

echo "Creating worktree at $WORKTREE_PATH" >&2
if git rev-parse --verify --quiet "$BRANCH_NAME" >/dev/null; then
  git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"
else
  if [[ -n "$START_POINT" ]]; then
    git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" "$START_POINT"
  else
    git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH"
  fi
fi

pushd "$WORKTREE_PATH" >/dev/null

if command -v pipenv >/dev/null; then
  echo "Installing dependencies via pipenv" >&2
  pipenv install --dev
else
  echo "pipenv not found on PATH; skipping dependency installation" >&2
fi

ENV_SOURCE=""
if [[ -f "$REPO_ROOT/.env" ]]; then
  ENV_SOURCE="$REPO_ROOT/.env"
elif [[ -f "$REPO_ROOT/.env.local" ]]; then
  ENV_SOURCE="$REPO_ROOT/.env.local"
fi

if [[ -n "$ENV_SOURCE" ]]; then
  if [[ -f .env ]]; then
    echo "Worktree already has a .env file; leaving existing file in place" >&2
  else
    echo "Copying $(basename "$ENV_SOURCE") into worktree" >&2
    cp "$ENV_SOURCE" ./.env
  fi
else
  echo "No .env or .env.local found in repository root; nothing copied" >&2
fi

if command -v code >/dev/null; then
  echo "Opening worktree in VS Code" >&2
  code "$WORKTREE_PATH"
else
  echo "VS Code command-line tool 'code' not found; skipping auto-open" >&2
fi

popd >/dev/null
