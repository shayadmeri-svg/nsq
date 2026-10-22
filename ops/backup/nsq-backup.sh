#!/bin/bash
# nsq-backup.sh — the two data stores on this box, off the box, 4 times a day (nsq-backup.timer).
#
#   Postgres  pg_dump (custom format) of the nsq database, checked with pg_restore --list before upload
#   Redis     a fresh RDB snapshot (BGSAVE) of the stack's Redis, gzipped and checked before upload
#
# Each file is kept in /opt/nsq-backups for 14 days and uploaded to s3://$S3_BUCKET/db/ (the instance role may only
# upload there; the bucket is versioned and expires dumps after 30 days — terraform/backups.tf). A failed step fails
# the whole run, visible in `systemctl status nsq-backup` and `journalctl -u nsq-backup`.
# Installed by deploy.sh from ops/backup/; settings in /etc/nsq-backup.conf (S3_BUCKET, AWS_REGION).
set -euo pipefail
umask 077
. /etc/nsq-backup.conf
DIR=/opt/nsq-backups
mkdir -p "$DIR"
stamp=$(date -u +%F_%H%M)

upload() { aws s3 cp "$1" "s3://$S3_BUCKET/db/$(basename "$1")" --region "$AWS_REGION" --only-show-errors; }

# --- Postgres -----------------------------------------------------------------------------------------------------------
pg="$DIR/nsq_${stamp}.dump"
docker exec nsq-postgres pg_dump -U nsq -Fc nsq > "$pg.tmp"
docker exec -i nsq-postgres pg_restore --list < "$pg.tmp" > /dev/null  # a dump pg_restore cannot read is no backup
mv "$pg.tmp" "$pg"
upload "$pg"
echo "postgres: $(basename "$pg") $(stat -c %s "$pg") bytes uploaded"

# --- Redis --------------------------------------------------------------------------------------------------------------
before=$(docker exec nsq-redis redis-cli LASTSAVE)
docker exec nsq-redis redis-cli BGSAVE > /dev/null
for _ in $(seq 1 120); do  # wait (up to 2 min) for the snapshot to finish
  sleep 1
  [ "$(docker exec nsq-redis redis-cli LASTSAVE)" != "$before" ] && break
done
[ "$(docker exec nsq-redis redis-cli LASTSAVE)" != "$before" ] || { echo "redis: BGSAVE did not finish" >&2; exit 1; }
docker exec nsq-redis redis-cli INFO persistence | grep -q "rdb_last_bgsave_status:ok" || { echo "redis: BGSAVE failed" >&2; exit 1; }
rd="$DIR/redis_${stamp}.rdb.gz"
docker cp nsq-redis:/data/dump.rdb - | tar -xO dump.rdb | gzip -6 > "$rd.tmp"
gzip -t "$rd.tmp" && [ "$(stat -c %s "$rd.tmp")" -gt 100 ]
mv "$rd.tmp" "$rd"
upload "$rd"
echo "redis: $(basename "$rd") $(stat -c %s "$rd") bytes uploaded"

find "$DIR" \( -name 'nsq_*.dump' -o -name 'redis_*.rdb.gz' \) -mtime +14 -delete
