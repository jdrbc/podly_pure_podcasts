#!/bin/sh
set -e

# Default API URL if not provided
VITE_API_URL=${VITE_API_URL:-http://localhost:5002}

echo "Configuring frontend with API URL: $VITE_API_URL"

# Find and replace the API URL placeholder in built JavaScript files
# We'll replace any occurrence of the placeholder with the runtime environment variable
find /usr/share/nginx/html -name "*.js" -type f -exec sed -i "s|__VITE_API_URL_PLACEHOLDER__|$VITE_API_URL|g" {} \;

echo "Frontend configuration complete"

# Start nginx
exec nginx -g "daemon off;"
