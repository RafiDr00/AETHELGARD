FROM nginx:alpine
LABEL version="1.0.0-stable"

# Copy the static HTML, CSS, and JavaScript files
COPY ops_console.html /usr/share/nginx/html/
COPY ops_console.css /usr/share/nginx/html/
COPY ops_console.js /usr/share/nginx/html/
COPY modules/ /usr/share/nginx/html/modules/

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Set environment variable for API URL (can be overridden at runtime)
ENV API_URL=https://aethelgard-api.onrender.com

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
