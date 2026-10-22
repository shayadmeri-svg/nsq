# Backups

Both data stores on the EC2 box go off the box 4 times a day (02:15, 08:15, 14:15, 20:15 UTC):

| Store | File | Contents |
|---|---|---|
| Postgres | `db/nsq_<date>_<time>.dump` | `pg_dump -Fc` of the `nsq` database: users, organisations, plant data, Connect |
| Redis | `db/redis_<date>_<time>.rdb.gz` | an RDB snapshot: the NSQ dataset and what the app keeps in Redis |

- **Where**: `s3://<backup bucket>/db/` (`terraform output backup_bucket`), versioned, encrypted, expired after 30 days;
  and `/opt/nsq-backups` on the box for 14 days. The instance can upload but not read or delete them.
- **What runs it**: `nsq-backup.timer` → `/usr/local/bin/nsq-backup.sh`, installed by `deploy.sh` from this folder.
  Settings: `/etc/nsq-backup.conf` (`S3_BUCKET`, `AWS_REGION`), written at first boot by Terraform.
- **Each dump is checked before upload** (`pg_restore --list`; `gzip -t` and a fresh `BGSAVE`). A failed check fails
  the run.

## Is it running?

```bash
systemctl list-timers nsq-backup.timer
journalctl -u nsq-backup --since -2d
aws s3 ls s3://<backup bucket>/db/ | tail      # from a machine with read access (the box itself has none)
sudo systemctl start nsq-backup                 # run one now
```

## Restore Postgres

Download the dump (from a machine with read access to the bucket), copy it to the box, then:

```bash
sudo docker compose stop api connect                   # nothing writes while restoring
sudo docker cp nsq_2026-10-22_1415.dump nsq-postgres:/tmp/r.dump
sudo docker exec nsq-postgres pg_restore -U nsq -d nsq --clean --if-exists --no-owner /tmp/r.dump
sudo docker compose up -d api connect
```

## Restore Redis

```bash
gunzip redis_2026-10-22_1415.rdb.gz
sudo docker compose stop redis api
# put the snapshot in the volume, removing the append-only files (they would be loaded instead of it)
sudo docker run --rm -v nsq-platform_redis-data:/data -v "$PWD":/in alpine \
  sh -c 'rm -rf /data/appendonlydir /data/appendonly.aof; cp /in/redis_2026-10-22_1415.rdb /data/dump.rdb'
# start once with append-only off, so the snapshot is what loads
sudo docker run -d --name nsq-redis-restore -v nsq-platform_redis-data:/data redis:7-alpine redis-server --appendonly no
sudo docker exec nsq-redis-restore redis-cli DBSIZE                      # the restored key count
sudo docker exec nsq-redis-restore redis-cli CONFIG SET appendonly yes  # writes fresh append-only files from memory
sleep 5 && sudo docker exec nsq-redis-restore redis-cli INFO persistence | grep aof_rewrite_in_progress   # wait for :0
sudo docker rm -f nsq-redis-restore
sudo docker compose up -d redis api
```

The NSQ dataset can also be re-pulled from Upstash at any time (`./pull-upstash.sh`).
