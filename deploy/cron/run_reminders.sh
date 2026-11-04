#!/bin/sh
# Daily reminder job: sends the vaccination / vet follow-up / expected-birth pushes that are due
# (7 days before, 1 day before, on the day, and when overdue). Each reminder is pushed once per step.
# Install (as the user that runs the API), once:
#   chmod +x /home/ubuntu/farmivo/farmivo_backend/deploy/cron/run_reminders.sh
#   crontab -e   and add the line:
#   0 7 * * * /home/ubuntu/farmivo/farmivo_backend/deploy/cron/run_reminders.sh >> /var/log/farmivo-reminders.log 2>&1
# Test now: run the script by hand; it prints {"farms": ..., "notified": ...}.
set -eu
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SECRET="$(grep -E '^FARMIVO_CRON_SECRET=' "$DIR/.env" | tail -1 | cut -d= -f2-)"
if [ -z "$SECRET" ]; then echo "FARMIVO_CRON_SECRET is not set in $DIR/.env" >&2; exit 1; fi
date
curl -fsS -X POST -H "X-Cron-Secret: $SECRET" http://127.0.0.1:8000/v1/internal/reminders/run
echo
