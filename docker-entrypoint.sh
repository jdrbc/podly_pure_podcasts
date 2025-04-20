#!/bin/bash
set -e

# Get the current user info
CURRENT_UID=$(id -u appuser)
CURRENT_GID=$(id -g appuser)

# Check if PUID/PGID env variables are set
if [ ! -z ${PUID} ] && [ ! -z ${PGID} ]; then
    echo "Using custom UID:GID = ${PUID}:${PGID}"
    
    # Only modify if they're different from current
    if [ "$PUID" != "$CURRENT_UID" ] || [ "$PGID" != "$CURRENT_GID" ]; then
        # We need to switch to root to modify user
        if [ "$(id -u)" = "0" ]; then
            # This script is being run as root, can modify UID directly
            usermod -o -u "$PUID" appuser
            groupmod -o -g "$PGID" appuser
        else
            # This script is being run as appuser, we can't modify UID
            echo "Warning: Cannot change UID/GID as non-root user."
            echo "Container is running with UID:GID = ${CURRENT_UID}:${CURRENT_GID}"
            echo "Consider rebuilding the image or running in privileged mode."
        fi
    fi
    
    # Ensure ownership of directories
    chown -R appuser:appuser /app/config /app/in /app/processing /app/srv /app/src/instance || true
    chmod 666 /app/config/app.log || true
fi

# Set HOME environment variable
export HOME=/home/appuser

# Execute the passed command as appuser
if [ "$(id -u)" = "0" ]; then
    exec gosu appuser "$@"
else
    exec "$@"
fi 