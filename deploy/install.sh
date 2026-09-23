#!/usr/bin/env bash
# Run on the intended Linux server as root from an uploaded source checkout.
# Usage: bash deploy/install.sh course.example.edu
# This starts a loopback-only service. TLS/reverse proxy are configured separately.
set -euo pipefail
umask 077

if [[ "$(id -u)" != 0 ]]; then
  echo 'Run this installation as root on the intended server.' >&2
  exit 1
fi
COURSE_HOST="${1:?Supply the intended course hostname or IP}"
if [[ ! "$COURSE_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
  echo 'Invalid host; use a hostname or IPv4 address without scheme or path.' >&2
  exit 1
fi
command -v systemctl >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="/opt/course-square/releases/$(date -u +%Y%m%dT%H%M%S)-$$"
if ! id course-square >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/course-square --shell /usr/sbin/nologin course-square
fi
install -d -m 0755 /opt/course-square /opt/course-square/releases
install -d -m 0755 "$RELEASE_DIR"
install -d -m 0700 -o course-square -g course-square /var/lib/course-square /var/lib/course-square/media /var/lib/course-square/staticfiles
install -d -m 0700 /var/backups/course-square
tar -C "$SOURCE_DIR" --exclude='.venv' --exclude='data' --exclude='private' --exclude='.env*' --exclude='__pycache__' --exclude='staticfiles' --exclude='test-results' --exclude='output' --exclude='.git' -cf - . | tar -C "$RELEASE_DIR" -xf -
chmod -R go+rX "$RELEASE_DIR"
python3 -m venv "$RELEASE_DIR/.venv"
"$RELEASE_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r "$RELEASE_DIR/requirements.txt"
chmod -R go+rX "$RELEASE_DIR/.venv"

if [[ ! -e /etc/course-square.env ]]; then
  python3 - "$COURSE_HOST" <<'PY'
import os, secrets, sys
host = sys.argv[1]
lines = [
    'DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64),
    'DJANGO_DEBUG=false',
    'DJANGO_ALLOWED_HOSTS=' + host + ',localhost,127.0.0.1',
    'DJANGO_CSRF_TRUSTED_ORIGINS=https://' + host,
    'DJANGO_SECURE_COOKIES=true',
    'DJANGO_SECURE_SSL_REDIRECT=true',
    'DATABASE_PATH=/var/lib/course-square/db.sqlite3',
    'MEDIA_ROOT=/var/lib/course-square/media',
    'STATIC_ROOT=/var/lib/course-square/staticfiles',
]
fd = os.open('/etc/course-square.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write('\n'.join(lines) + '\n')
PY
fi
set -a
source /etc/course-square.env
set +a
if [[ -f /var/lib/course-square/db.sqlite3 ]]; then
  "$RELEASE_DIR/.venv/bin/python" "$RELEASE_DIR/deploy/backup.py"
fi
cd "$RELEASE_DIR"
"$RELEASE_DIR/.venv/bin/python" manage.py check --deploy
"$RELEASE_DIR/.venv/bin/python" manage.py migrate --noinput
"$RELEASE_DIR/.venv/bin/python" manage.py generate_thumbnails
"$RELEASE_DIR/.venv/bin/python" manage.py collectstatic --noinput
chown -R course-square:course-square /var/lib/course-square
if [[ -L /opt/course-square/current ]]; then
  readlink /opt/course-square/current > /opt/course-square/previous-release.txt
fi
ln -s "$RELEASE_DIR" /opt/course-square/current.next
mv -Tf /opt/course-square/current.next /opt/course-square/current
install -m 0644 "$RELEASE_DIR/deploy/course-square.service" /etc/systemd/system/course-square.service
systemctl daemon-reload
systemctl enable course-square.service
systemctl restart course-square.service
systemctl is-active course-square.service
install -m 0644 "$RELEASE_DIR/deploy/course-square-notify.service" /etc/systemd/system/course-square-notify.service
install -m 0644 "$RELEASE_DIR/deploy/course-square-notify.timer" /etc/systemd/system/course-square-notify.timer
systemctl daemon-reload
systemctl enable --now course-square-notify.timer
if ! grep -q '^TEACHER_NOTIFY_WEBHOOK=.' /etc/course-square.env; then
  echo 'Teacher push is off: add TEACHER_NOTIFY_WEBHOOK (and COURSE_SITE_URL) to /etc/course-square.env to enable it.'
fi
echo 'Loopback service installed. Configure HTTPS routing and create the administrator before sharing the site.'
