#!/bin/sh
set -e

# Default API URL if not provided
VITE_API_URL=${VITE_API_URL:-http://localhost:5002}

echo "Configuring frontend with API URL: $VITE_API_URL"

# Replace the API URL placeholder in the runtime config file
sed -i "s|__VITE_API_URL_PLACEHOLDER__|$VITE_API_URL|g" /usr/share/nginx/html/config.js

echo "Frontend configuration complete"

# Start nginx
exec nginx -g "daemon off;"
