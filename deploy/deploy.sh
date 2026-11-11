#!/usr/bin/env bash
# Run from the project root on the workstation. Tests must pass first.
set -euo pipefail

HOST=pi@192.168.1.26
REMOTE=/home/pi/mathFacts

cd "$(dirname "$0")/.."

echo "=== Running tests"
.venv/bin/python -m pytest -q

echo "=== Copying code to $HOST:$REMOTE"
rsync -av --delete \
    --filter='P .venv/' \
    --filter='P instance/' \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='instance/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    ./ "$HOST:$REMOTE/"

echo "=== Setting up on the Pi"
ssh "$HOST" 'bash -s' < deploy/remote-setup.sh

echo "=== Checking from this machine"
curl -fsS http://192.168.1.26:8016/health
echo
echo "Deployed. Open http://192.168.1.26:8016 from another device."
