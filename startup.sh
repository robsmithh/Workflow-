#!/usr/bin/env bash
# Azure App Service startup command.
# Configure in the portal: Settings > Configuration > General settings > Startup Command:
#   startup.sh
set -euo pipefail

# Apply database migrations before serving.
alembic upgrade head

exec gunicorn -c gunicorn_conf.py app.main:app
