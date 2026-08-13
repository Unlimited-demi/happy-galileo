#!/usr/bin/env bash
# ==============================================================================
# Lightweight devctl & AI-Ops Installer / Updater
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing devctl CLI..."

# Ensure dev-net exists
docker network inspect dev-net &>/dev/null || docker network create dev-net

# Set up Python venv
VENV_DIR="${HOME}/.devctl/venv"
mkdir -p "${HOME}/.devctl"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip

if [ -f "${PROJECT_DIR}/requirements.txt" ]; then
  "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
fi

# Create user bin wrapper
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"

cat << EOF > "${BIN_DIR}/devctl"
#!/usr/bin/env bash
export PYTHONPATH="${PROJECT_DIR}:\${PYTHONPATH}"
export BASE_DOMAIN="\${BASE_DOMAIN:-dev-server.datakrib.com}"
exec "${VENV_DIR}/bin/python3" "${PROJECT_DIR}/devctl/cli.py" "\$@"
EOF

chmod +x "${BIN_DIR}/devctl"
chmod +x "${PROJECT_DIR}/devctl/cli.py"

echo "✓ devctl installed to ${BIN_DIR}/devctl"
echo "  Ensure '${BIN_DIR}' is in your PATH in ~/.bashrc or ~/.zshrc."
