#!/bin/bash
set -e

# Generate lock file for the regular Pipfile
echo "Locking Pipfile..."
pipenv lock

# Temporarily move Pipfiles to lock Pipfile.lite
echo "Preparing to lock Pipfile.lite..."
mv Pipfile Pipfile.tmp
mv Pipfile.lite Pipfile

# Generate lock file for Pipfile.lite
echo "Locking Pipfile.lite..."
pipenv lock

# Rename the new lock file to Pipfile.lite.lock
echo "Renaming lockfile for lite version..."
mv Pipfile.lock Pipfile.lite.lock

# Restore original Pipfile names
echo "Restoring original Pipfile names..."
mv Pipfile Pipfile.lite
mv Pipfile.tmp Pipfile

echo "Lockfiles generated successfully!"
echo "- Pipfile.lock"
echo "- Pipfile.lite.lock"
