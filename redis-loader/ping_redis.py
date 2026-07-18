"""Verify Redis connectivity without loading or modifying anything."""
import os

import redis

r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
print("PONG" if r.ping() else "FAILED")
