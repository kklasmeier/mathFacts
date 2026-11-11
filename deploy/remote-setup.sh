#!/usr/bin/env bash
# Runs on the Pi from /home/pi/mathFacts. Safe to run again after each deploy.
set -euo pipefail

APP_DIR=/home/pi/mathFacts
cd "$APP_DIR"

mkdir -p instance

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# Secret key is created once on the Pi and never copied off it.
if [ ! -f instance/mathfacts.env ]; then
    secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
    printf 'SECRET_KEY=%s\n' "$secret" > instance/mathfacts.env
    chmod 600 instance/mathfacts.env
    echo "Created instance/mathfacts.env"
fi

sudo install -m 644 deploy/mathfacts.service /etc/systemd/system/mathfacts.service
sudo install -m 644 deploy/nginx-mathfacts.conf /etc/nginx/sites-available/mathfacts
sudo ln -sfn /etc/nginx/sites-available/mathfacts /etc/nginx/sites-enabled/mathfacts

if ! sudo nginx -t; then
    echo "nginx config test failed; removing the mathfacts site link." >&2
    sudo rm -f /etc/nginx/sites-enabled/mathfacts
    exit 1
fi

sudo systemctl daemon-reload
sudo systemctl enable mathfacts
sudo systemctl restart mathfacts
sudo systemctl reload nginx

echo "Waiting for gunicorn..."
for _ in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:8017/health >/dev/null 2>&1; then
        echo "mathfacts is up on 127.0.0.1:8017"
        exit 0
    fi
    sleep 0.5
done
echo "mathfacts did not answer on 127.0.0.1:8017" >&2
sudo systemctl status mathfacts --no-pager >&2 || true
exit 1
