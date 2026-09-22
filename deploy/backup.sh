#!/usr/bin/env bash
# Nightly consistent copy of the SQLite database; keeps the last 14.
# Installed to /usr/local/bin/schedule-builder-backup by deploy/setup.sh and run from cron.
#
# To copy backups off the VM as well, create an Object Storage bucket (Always Free
# includes 20 GB) and append:  oci os object put --bucket-name schedule-backups --file "$target"

set -euo pipefail

DB="${DATABASE_PATH:-/var/lib/schedule-builder/schedule.db}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/schedule-builder/backups}"
KEEP="${KEEP:-14}"

[[ -f "$DB" ]] || exit 0
mkdir -p "$BACKUP_DIR"
target="$BACKUP_DIR/schedule-$(date +%Y%m%d-%H%M%S).db"

# .backup takes a consistent snapshot even while the app is writing.
sqlite3 "$DB" ".backup '$target'"
gzip -f "$target"

ls -1t "$BACKUP_DIR"/schedule-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
