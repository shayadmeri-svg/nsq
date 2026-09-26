"""Backend tests. Need a Postgres (DATABASE_URL, default nsq_test on
localhost) and a Redis with the NSQ snapshot + CDMO seeds loaded
(REDIS_URL, default localhost). Skipped when either is unreachable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://nsq@localhost:5432/nsq_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["SUPERADMIN_EMAIL"] = "root@example.com"
os.environ["SUPERADMIN_PASSWORD"] = "root-password-1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

H = {"x-nsq-client": "test"}


def _infra_ok() -> bool:
    try:
        import redis
        from sqlalchemy import create_engine, text

        with create_engine(os.environ["DATABASE_URL"]).connect() as c:
            c.execute(text("select 1"))
        r = redis.from_url(os.environ["REDIS_URL"])
        return r.scard("nsq:records") > 0 and any(r.scan_iter("cdmo:plant:*", count=100))
    except Exception:
        return False


if not _infra_ok():
    pytest.skip("Postgres/Redis with data not available", allow_module_level=True)


@pytest.fixture(scope="session")
def app():
    from app.db import Base, engine
    from app.main import app as fastapi_app

    Base.metadata.drop_all(engine)
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def login(c, email, password):
    r = c.post("/api/auth/login", json={"email": email, "password": password}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest.fixture()
def root(client):
    login(client, "root@example.com", "root-password-1")
    return client
