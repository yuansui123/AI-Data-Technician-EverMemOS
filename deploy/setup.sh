#!/usr/bin/env bash
# EC2 one-time setup for AI Data Technician demo.
# Supports Ubuntu and Amazon Linux 2023.
# Usage: bash deploy/setup.sh
set -euo pipefail

echo "=== AI Data Technician — EC2 Setup ==="

# Detect package manager
if command -v apt-get &>/dev/null; then
    PKG="apt"
elif command -v dnf &>/dev/null; then
    PKG="dnf"
else
    echo "ERROR: Unsupported OS (no apt or dnf found)." && exit 1
fi

# ── 1. Install Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[1/5] Installing Docker..."
    if [ "$PKG" = "apt" ]; then
        sudo apt-get update -y
        sudo apt-get install -y docker.io
    else
        sudo dnf install -y docker
    fi
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER"
    echo "  Docker installed. You may need to log out/in for group changes."
else
    echo "[1/5] Docker already installed."
fi

# ── 2. Install Caddy ─────────────────────────────────────────────────────────
if ! command -v caddy &>/dev/null; then
    echo "[2/5] Installing Caddy..."
    if [ "$PKG" = "apt" ]; then
        sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
        sudo apt-get update -y
        sudo apt-get install -y caddy
    else
        sudo dnf install -y 'dnf-command(copr)'
        sudo dnf copr enable -y @caddy/caddy
        sudo dnf install -y caddy
    fi
    echo "  Caddy installed."
else
    echo "[2/5] Caddy already installed."
fi

# ── 3. Install pixi ──────────────────────────────────────────────────────────
if ! command -v pixi &>/dev/null; then
    echo "[3/5] Installing pixi..."
    curl -fsSL https://pixi.sh/install.sh | bash
    export PATH="$HOME/.pixi/bin:$PATH"
    echo "  pixi installed."
else
    echo "[3/5] pixi already installed."
fi

# ── 4. Mount EBS data volume ─────────────────────────────────────────────────
DATA_DIR="/data"
if ! mountpoint -q "$DATA_DIR" 2>/dev/null; then
    echo "[4/5] Setting up EBS data volume..."
    EBS_DEVICE=""
    for dev in /dev/xvdf /dev/xvdh /dev/nvme1n1; do
        if [ -b "$dev" ]; then
            EBS_DEVICE="$dev"
            break
        fi
    done

    if [ -z "$EBS_DEVICE" ]; then
        echo "  WARNING: No additional EBS volume found. Using /data on root volume."
        sudo mkdir -p "$DATA_DIR"
    else
        if ! sudo blkid "$EBS_DEVICE" &>/dev/null; then
            sudo mkfs.xfs "$EBS_DEVICE"
        fi
        sudo mkdir -p "$DATA_DIR"
        sudo mount "$EBS_DEVICE" "$DATA_DIR"
        if ! grep -q "$DATA_DIR" /etc/fstab; then
            echo "$EBS_DEVICE $DATA_DIR xfs defaults,nofail 0 2" | sudo tee -a /etc/fstab
        fi
        echo "  Mounted $EBS_DEVICE at $DATA_DIR"
    fi
else
    echo "[4/5] $DATA_DIR already mounted."
fi

sudo mkdir -p "$DATA_DIR/datasets" "$DATA_DIR/projects"
sudo chown -R "$USER:$USER" "$DATA_DIR"

# ── 5. Install app dependencies ──────────────────────────────────────────────
APP_DIR="$HOME/app"
echo "[5/5] Installing app dependencies..."
if [ -f "$APP_DIR/pixi.toml" ]; then
    cd "$APP_DIR"
    pixi install
    echo "  Dependencies installed."
else
    echo "  WARNING: $APP_DIR/pixi.toml not found. Clone the repo first:"
    echo "    git clone -b demo <repo-url> ~/app"
fi

# ── 6. Deploy Caddy config ───────────────────────────────────────────────────
if [ -f "$APP_DIR/deploy/Caddyfile" ]; then
    sudo cp "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
    echo "  Caddyfile copied to /etc/caddy/"
fi

# ── 7. Deploy systemd service ────────────────────────────────────────────────
if [ -f "$APP_DIR/deploy/adt.service" ]; then
    sudo cp "$APP_DIR/deploy/adt.service" /etc/systemd/system/adt.service
    sudo systemctl daemon-reload
    sudo systemctl enable adt
    echo "  systemd service installed and enabled."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Create ~/.env with your API keys (NOT inside ~/app/):"
echo "     cp ~/app/.env.template ~/.env"
echo "     nano ~/.env"
echo "     chmod 600 ~/.env"
echo ""
echo "  2. Edit /etc/caddy/Caddyfile with your domain/subdomain"
echo ""
echo "  3. Upload dataset:"
echo "     scp -r MayoData1000/ ubuntu@<ip>:/data/datasets/"
echo ""
echo "  4. Start services:"
echo "     sudo systemctl start caddy"
echo "     sudo systemctl start adt"
echo ""
echo "  5. Check status:"
echo "     systemctl status adt"
echo "     systemctl status caddy"
