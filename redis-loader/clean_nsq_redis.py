"""Delete all nsq:* keys from Redis. Called by `just clean` after confirmation."""
import os

import redis

r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
keys = list(r.scan_iter("nsq:*"))
for k in keys:
    r.delete(k)
print(f"Deleted {len(keys)} keys.")
