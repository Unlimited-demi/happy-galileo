#!/usr/bin/env bash
# ==============================================================================
# Auto-Proxy Conflict Resolver for devctl
# Detects host Nginx, Apache, or Caddy and configures seamless upstream routing
# ==============================================================================

set -e

BASE_DOMAIN="${1:-dev-server.suburban.ng}"
INTERNAL_PORT="${2:-8080}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "[*] Inspecting port 80 and 443 bindings on host..."

PORT_80_PROCESS=$(ss -tulpn 2>/dev/null | grep ':80 ' || true)
PORT_443_PROCESS=$(ss -tulpn 2>/dev/null | grep ':443 ' || true)

HAS_NGINX=false
HAS_APACHE=false
HAS_HOST_CADDY=false
HAS_PORT_CONFLICT=false

if echo "$PORT_80_PROCESS" | grep -iq "nginx" || (command -v nginx &>/dev/null && systemctl is-active --quiet nginx 2>/dev/null); then
    HAS_NGINX=true
    HAS_PORT_CONFLICT=true
elif echo "$PORT_80_PROCESS" | grep -iq "apache\|httpd" || (command -v apache2 &>/dev/null && systemctl is-active --quiet apache2 2>/dev/null); then
    HAS_APACHE=true
    HAS_PORT_CONFLICT=true
elif echo "$PORT_80_PROCESS" | grep -iq "caddy" || (command -v caddy &>/dev/null && systemctl is-active --quiet caddy 2>/dev/null); then
    HAS_HOST_CADDY=true
    HAS_PORT_CONFLICT=true
elif [ -n "$PORT_80_PROCESS" ] || [ -n "$PORT_443_PROCESS" ]; then
    # Port 80/443 is occupied by some other process or container
    HAS_PORT_CONFLICT=true
fi

# Find an open internal port if 8080 is also occupied
while ss -tulpn 2>/dev/null | grep -q ":${INTERNAL_PORT} "; do
    INTERNAL_PORT=$((INTERNAL_PORT + 1))
done

if [ "$HAS_PORT_CONFLICT" = true ]; then
    echo "⚡ Port 80/443 is in use on this server. Configuring Caddy on internal port ${INTERNAL_PORT}..."
    mkdir -p "${PROJECT_DIR}/infra"
    ENV_FILE="${PROJECT_DIR}/infra/.env"
    touch "${ENV_FILE}"

    # Remove existing CADDY_HTTP_PORT / CADDY_HTTPS_PORT lines if present
    sed -i '/^CADDY_HTTP_PORT=/d' "${ENV_FILE}" 2>/dev/null || true
    sed -i '/^CADDY_HTTPS_PORT=/d' "${ENV_FILE}" 2>/dev/null || true

    # Safely append internal port configuration
    cat << EOF >> "${ENV_FILE}"
CADDY_HTTP_PORT=${INTERNAL_PORT}
CADDY_HTTPS_PORT=8443
EOF
else
    echo "[✓] No host port conflicts detected. Caddy will bind directly to 80/443."
fi

# Check for Mailcow Dockerized Nginx
MAILCOW_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i 'nginx.*mailcow\|mailcow.*nginx' | head -n 1 || true)

# Detect Docker bridge IP (don't hardcode 172.17.0.1)
DOCKER_BRIDGE_IP=$(ip -4 addr show docker0 2>/dev/null | grep -oP 'inet \K[\d.]+' || echo "172.17.0.1")
SNIPPET_FILE="${PROJECT_DIR}/infra/upstream_proxy_${BASE_DOMAIN//./_}.conf"

if [ -n "$MAILCOW_CONTAINER" ]; then
    echo "⚡ Detected active Mailcow Nginx container: ${MAILCOW_CONTAINER}"
    cat << EOF > "$SNIPPET_FILE"
# ==============================================================================
# Upstream routing snippet for Mailcow Nginx: *.${BASE_DOMAIN}
# Place in: /opt/mailcow-dockerized/data/conf/nginx/devctl_wildcard.conf
# ==============================================================================
server {
    listen 80;
    server_name *.${BASE_DOMAIN} ${BASE_DOMAIN};

    location / {
        proxy_pass http://${DOCKER_BRIDGE_IP}:${INTERNAL_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    echo ""
    echo "📋 [MANUAL INSTRUCTION] Generated Mailcow Nginx snippet: ${SNIPPET_FILE}"
    echo "   To activate routing to internal Caddy (port ${INTERNAL_PORT}), run:"
    echo "     cp ${SNIPPET_FILE} /opt/mailcow-dockerized/data/conf/nginx/devctl_wildcard.conf"
    echo "     docker exec ${MAILCOW_CONTAINER} nginx -t && docker exec ${MAILCOW_CONTAINER} nginx -s reload"
    echo ""
fi

# Check for existing third-party Caddy container (e.g. agentic-ccs-caddy)
OTHER_CADDY_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i 'caddy' | grep -v '^caddy$' | head -n 1 || true)

if [ -n "$OTHER_CADDY_CONTAINER" ]; then
    echo "⚡ Detected active Docker Caddy container: ${OTHER_CADDY_CONTAINER}"
    echo "   Configuring ${OTHER_CADDY_CONTAINER} to route *.${BASE_DOMAIN} to devctl Caddy on port ${INTERNAL_PORT}..."

    # Find host Caddyfile path via docker inspect mounts
    HOST_CADDYFILE=$(docker inspect "$OTHER_CADDY_CONTAINER" 2>/dev/null | grep -B 2 -A 5 'Caddyfile' | grep '"Source"' | head -n 1 | awk -F'"' '{print $4}' || true)
    
    if [ -z "$HOST_CADDYFILE" ] || [ ! -f "$HOST_CADDYFILE" ]; then
        # Search common paths
        for p in "/home/newroot/LegendAgenticCCS/Caddyfile" "/home/newroot/LegendAgenticCCS/caddy/Caddyfile" "/root/LegendAgenticCCS/Caddyfile" "/opt/caddy/Caddyfile"; do
            if [ -f "$p" ]; then
                HOST_CADDYFILE="$p"
                break
            fi
        done
    fi

    if [ -n "$HOST_CADDYFILE" ] && [ -f "$HOST_CADDYFILE" ]; then
    cat << EOF > "$SNIPPET_FILE"
# ==============================================================================
# Upstream routing snippet for Caddy: *.${BASE_DOMAIN}
# Add this block to your Caddyfile:
# ==============================================================================
*.${BASE_DOMAIN}, ${BASE_DOMAIN} {
    reverse_proxy 172.17.0.1:${INTERNAL_PORT}
}
EOF
    echo ""
    echo "📋 [MANUAL INSTRUCTION] Generated Caddy snippet: ${SNIPPET_FILE}"
    echo "   Add the snippet contents to your Caddyfile (${OTHER_CADDYFILE:-/etc/caddy/Caddyfile})"
    echo "   Then reload: docker exec ${OTHER_CADDY_CONTAINER} caddy reload --config /etc/caddy/Caddyfile"
    echo ""

elif [ "$HAS_NGINX" = true ]; then
    echo "⚡ Detected active Nginx on host."
    cat << EOF > "$SNIPPET_FILE"
# ==============================================================================
# Upstream routing snippet for Host Nginx: *.${BASE_DOMAIN}
# Place in: /etc/nginx/conf.d/devctl_${BASE_DOMAIN//./_}.conf
# ==============================================================================
server {
    listen 80;
    server_name *.${BASE_DOMAIN} ${BASE_DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${INTERNAL_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    echo ""
    echo "📋 [MANUAL INSTRUCTION] Generated Nginx snippet: ${SNIPPET_FILE}"
    echo "   To activate routing to internal Caddy (port ${INTERNAL_PORT}), run:"
    echo "     cp ${SNIPPET_FILE} /etc/nginx/conf.d/devctl_${BASE_DOMAIN//./_}.conf"
    echo "     nginx -t && systemctl reload nginx"
    echo ""

elif [ "$HAS_HOST_CADDY" = true ]; then
    echo "⚡ Detected active Caddy on host."
    cat << EOF > "$SNIPPET_FILE"
# ==============================================================================
# Upstream routing snippet for Host Caddy: *.${BASE_DOMAIN}
# Add this block to /etc/caddy/Caddyfile:
# ==============================================================================
*.${BASE_DOMAIN}, ${BASE_DOMAIN} {
    reverse_proxy 127.0.0.1:${INTERNAL_PORT}
}
EOF
    echo ""
    echo "📋 [MANUAL INSTRUCTION] Generated Host Caddy snippet: ${SNIPPET_FILE}"
    echo "   Add the snippet contents to /etc/caddy/Caddyfile"
    echo "   Then reload: systemctl reload caddy"
    echo ""

fi

fi
