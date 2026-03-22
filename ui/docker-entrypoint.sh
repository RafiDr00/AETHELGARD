#!/bin/sh
set -e

# Default API URL
API_URL="${API_URL:-https://aethelgard-api.fly.dev}"

# Inject API URL into ops_console.html by adding a script before the main app script
# This sets window.AETHELGARD_API_URL for the JavaScript modules to use
if [ -f /usr/share/nginx/html/ops_console.html ]; then
  sed -i "s|</head>|<script>window.AETHELGARD_API_URL='${API_URL}';</script>\n</head>|g" /usr/share/nginx/html/ops_console.html
fi

# Start nginx
exec nginx -g 'daemon off;'
