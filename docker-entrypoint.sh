#!/bin/bash
set -e

# Check if PUID/PGID env variables are set
if [ -n "${PUID}" ] && [ -n "${PGID}" ] && [ "$(id -u)" = "0" ]; then
    echo "Using custom UID:GID = ${PUID}:${PGID}"
    
    # Update user/group IDs if needed
    usermod -o -u "$PUID" appuser
    groupmod -o -g "$PGID" appuser
    
    # Ensure required directories exist
    mkdir -p /app/src/instance /app/src/instance/data /app/src/instance/data/in /app/src/instance/data/srv /app/src/instance/config /app/src/instance/db /app/src/instance/logs
    
    # Set permissions for all application directories
    APP_DIRS="/home/appuser /app/processing /app/src/instance /app/src/instance/data /app/src/instance/config /app/src/instance/db /app/src/instance/logs /app/scripts"
    chown -R appuser:appuser $APP_DIRS 2>/dev/null || true
    
    # Ensure log file exists and has correct permissions in new location
    touch /app/src/instance/logs/app.log
    chmod 664 /app/src/instance/logs/app.log
    chown appuser:appuser /app/src/instance/logs/app.log

    # Run as appuser
    export HOME=/home/appuser
    exec gosu appuser "$@"
else
    # Run as current user (but don't assume it's appuser)
    exec "$@"
fi 