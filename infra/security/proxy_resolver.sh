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

if [ -n "$MAILCOW_CONTAINER" ]; then
    echo "⚡ Detected active Mailcow Nginx container: ${MAILCOW_CONTAINER}"
    echo "   Configuring Mailcow to forward *.${BASE_DOMAIN} to devctl Caddy..."

    # Find Mailcow directory from docker inspect mounts
    MAILCOW_NGINX_CONF_DIR=""
    POSSIBLE_DIRS=(
        "/opt/mailcow-dockerized/data/conf/nginx"
        "/opt/mailcow/data/conf/nginx"
        "/root/mailcow-dockerized/data/conf/nginx"
    )
    for d in "${POSSIBLE_DIRS[@]}"; do
        if [ -d "$d" ]; then
            MAILCOW_NGINX_CONF_DIR="$d"
            break
        fi
    done

    if [ -z "$MAILCOW_NGINX_CONF_DIR" ]; then
        # Inspect container mount for /etc/nginx/conf.d
        DETECTED_DIR=$(docker inspect "$MAILCOW_CONTAINER" 2>/dev/null | grep -B 2 -A 5 '"Destination": "/etc/nginx/conf.d"' | grep '"Source"' | head -n 1 | awk -F'"' '{print $4}' || true)
        if [ -n "$DETECTED_DIR" ] && [ -d "$DETECTED_DIR" ]; then
            MAILCOW_NGINX_CONF_DIR="$DETECTED_DIR"
        fi
    fi

    if [ -n "$MAILCOW_NGINX_CONF_DIR" ]; then
        CONF_FILE="${MAILCOW_NGINX_CONF_DIR}/devctl_wildcard.conf"

        # Skip if this exact config already exists (idempotent)
        if [ -f "$CONF_FILE" ] && grep -q "${BASE_DOMAIN}" "$CONF_FILE"; then
            echo "[✓] Mailcow wildcard route for ${BASE_DOMAIN} already exists."
        else
            # Detect Docker bridge IP (don't hardcode 172.17.0.1)
            DOCKER_BRIDGE_IP=$(ip -4 addr show docker0 2>/dev/null | grep -oP 'inet \K[\d.]+' || echo "172.17.0.1")

            cat << EOF > "$CONF_FILE"
# Auto-configured by devctl for wildcard development routing
# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) — Domain: ${BASE_DOMAIN}
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
            echo "[*] Wrote Mailcow Nginx route to: ${CONF_FILE}"
            # Test config before reloading (don't restart blindly)
            if docker exec "$MAILCOW_CONTAINER" nginx -t 2>/dev/null; then
                docker exec "$MAILCOW_CONTAINER" nginx -s reload 2>/dev/null
                echo "[✓] Mailcow Nginx reloaded successfully."
            else
                echo "[!] WARNING: Nginx config test failed. Removing devctl config to avoid breaking Mailcow."
                rm -f "$CONF_FILE"
                echo "    Please check ${CONF_FILE} manually."
            fi
        fi
    fi
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
        if ! grep -q "${BASE_DOMAIN}" "$HOST_CADDYFILE"; then
            echo "" >> "$HOST_CADDYFILE"
            cat << EOF >> "$HOST_CADDYFILE"

# Auto-configured by devctl for wildcard development routing
*.${BASE_DOMAIN}, ${BASE_DOMAIN} {
    reverse_proxy 172.17.0.1:${INTERNAL_PORT}
}
EOF
            echo "[*] Appended wildcard route to ${HOST_CADDYFILE}"
            docker exec "$OTHER_CADDY_CONTAINER" caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || docker restart "$OTHER_CADDY_CONTAINER" 2>/dev/null || true
            echo "[✓] ${OTHER_CADDY_CONTAINER} reloaded successfully."
        else
            echo "[✓] Wildcard route already present in ${HOST_CADDYFILE}"
        fi
    else
        echo "[!] Notice: Please add '*.${BASE_DOMAIN} { reverse_proxy 172.17.0.1:${INTERNAL_PORT} }' to your ${OTHER_CADDY_CONTAINER} Caddyfile."
    fi

elif [ "$HAS_NGINX" = true ]; then
    echo "⚡ Detected active Nginx on host."
    echo "   Configuring Nginx reverse-proxy pass to Caddy on port ${INTERNAL_PORT}..."

    NGINX_CONF_DIR="/etc/nginx/conf.d"
    mkdir -p "$NGINX_CONF_DIR"
    NGINX_CONF_FILE="${NGINX_CONF_DIR}/devctl_${BASE_DOMAIN//./_}.conf"

    # Skip if this exact domain config already exists
    if [ -f "$NGINX_CONF_FILE" ] && grep -q "${BASE_DOMAIN}" "$NGINX_CONF_FILE"; then
        echo "[✓] Nginx wildcard route for ${BASE_DOMAIN} already exists."
    else
        # Back up any existing file before overwriting
        if [ -f "$NGINX_CONF_FILE" ]; then
            cp "$NGINX_CONF_FILE" "${NGINX_CONF_FILE}.bak.$(date +%s)"
            echo "[*] Backed up existing config to ${NGINX_CONF_FILE}.bak.*"
        fi

        cat << EOF > "$NGINX_CONF_FILE"
# Auto-generated by devctl for wildcard routing
# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) — Domain: ${BASE_DOMAIN}
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
        if nginx -t &>/dev/null; then
            nginx -s reload
            echo "[✓] Nginx reloaded. Routing *.${BASE_DOMAIN} -> 127.0.0.1:${INTERNAL_PORT}"
        else
            echo "[!] WARNING: Nginx config test failed. Removing devctl config to avoid breaking existing setup."
            rm -f "$NGINX_CONF_FILE"
            echo "    Please add the route manually to /etc/nginx/conf.d/."
        fi
    fi

elif [ "$HAS_HOST_CADDY" = true ]; then
    echo "⚡ Detected active Caddy on host."
    echo "   Configuring host Caddy to route *.${BASE_DOMAIN} to internal port ${INTERNAL_PORT}..."
    if [ -d "/etc/caddy/conf.d" ]; then
        cat << EOF > "/etc/caddy/conf.d/devctl_${BASE_DOMAIN//./_}.caddy"
*.${BASE_DOMAIN}, ${BASE_DOMAIN} {
    reverse_proxy 127.0.0.1:${INTERNAL_PORT}
}
EOF
        systemctl reload caddy 2>/dev/null || true
        echo "[✓] Host Caddy reloaded successfully."
    elif [ -f "/etc/caddy/Caddyfile" ]; then
        if ! grep -q "${BASE_DOMAIN}" "/etc/caddy/Caddyfile"; then
            cat << EOF >> "/etc/caddy/Caddyfile"

# Auto-configured by devctl for wildcard routing
*.${BASE_DOMAIN}, ${BASE_DOMAIN} {
    reverse_proxy 127.0.0.1:${INTERNAL_PORT}
}
EOF
            systemctl reload caddy 2>/dev/null || true
            echo "[✓] Added wildcard route to /etc/caddy/Caddyfile and reloaded."
        fi
    fi

fi
