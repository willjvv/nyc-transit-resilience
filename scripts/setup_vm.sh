#!/usr/bin/env bash
# One-shot provisioning script for an Ubuntu VM (e.g. Oracle Cloud Free
# Tier). Installs Python, sets up the venv, installs cron jobs, and
# optionally sets up a Cloudflare Tunnel so you can share the dashboard
# publicly for free without opening any inbound ports.
#
# Run this ON the VM, after cloning the repo there.
# Usage: bash scripts/setup_vm.sh

set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo "== Installing system dependencies =="
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip cron

echo "== Setting up Python virtual environment =="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "== Setting up .env =="
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from template - edit it now to add your MTA_API_KEY"
fi

mkdir -p logs

echo "== Installing cron jobs =="
echo "Review and edit orchestration/crontab.txt to match this VM's paths (PROJECT_DIR=$PROJECT_DIR),"
echo "then install with: crontab orchestration/crontab.txt"

echo ""
echo "== Optional: Cloudflare Tunnel for a public dashboard URL =="
echo "1. Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
echo "2. Authenticate: cloudflared tunnel login"
echo "3. Create a tunnel: cloudflared tunnel create subway-dashboard"
echo "4. Run the dashboard in the background:"
echo "     nohup .venv/bin/streamlit run dashboard/app.py --server.port 8501 > logs/dashboard.log 2>&1 &"
echo "5. Route the tunnel to it: cloudflared tunnel route dns subway-dashboard <your-subdomain>"
echo "6. Run the tunnel: cloudflared tunnel run subway-dashboard"
echo ""
echo "Setup complete. Next steps:"
echo "  1. Edit .env with your MTA_API_KEY"
echo "  2. python -m ingestion.gtfs_static_loader"
echo "  3. crontab orchestration/crontab.txt   (after editing paths)"
