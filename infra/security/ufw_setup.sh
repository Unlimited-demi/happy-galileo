#!/usr/bin/env bash
# ==============================================================================
# UFW Firewall Hardening Script for AI Remote Workstation
# Ensures ONLY SSH (22), HTTP (80), and HTTPS (443) are exposed to the internet.
# All application containers remain internal on dev-net with ZERO public ports.
# ==============================================================================

set -e

echo "🔒 Configuring UFW Firewall for dev-server.datakrib.com..."

# Check root privileges
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root (sudo ./ufw_setup.sh)"
  exit 1
fi

# Detect active SSH port
SSH_PORT=$(grep "^Port " /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}' || echo "22")

# Set default policies
ufw default deny incoming
ufw default allow outgoing

# Allow SSH
echo "✓ Allowing SSH on port ${SSH_PORT}..."
ufw allow ${SSH_PORT}/tcp comment "SSH Remote Workstation Access"

# Allow Web Ingress (Caddy only)
echo "✓ Allowing HTTP (80) and HTTPS (443)..."
ufw allow 80/tcp comment "Caddy HTTP Ingress & ACME Challenge"
ufw allow 443/tcp comment "Caddy HTTPS Ingress"

# Enable UFW non-interactively
echo "✓ Enabling UFW..."
ufw --force enable

echo "========================================================"
echo "🛡️  UFW Firewall Active & Locked Down!"
ufw status verbose
echo "========================================================"
