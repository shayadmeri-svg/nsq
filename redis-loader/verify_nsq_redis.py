"""Sanity-check what's been loaded into Redis by load_nsq_redis.py."""
import json
import os

import redis

r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
ids = r.smembers("nsq:records")
print("records:", len(ids))
print("meta:", r.hgetall("nsq:meta"))

sample = next(iter(ids), None)
if sample:
    print("sample:", json.dumps(r.hgetall(f"nsq:record:{sample}"), indent=2))
else:
    print("no records")
