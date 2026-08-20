"""Shared pytest fixtures: isolated SQLite DB, TestClient and auth helpers."""
from __future__ import annotations

import os
import random
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Configure the app for testing before it is imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="geneforge-test-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "SECRET_KEY": "test-secret-key-not-for-production",
        "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "STORAGE_DIR": str(_TMP / "storage"),
        "FIRST_SUPERUSER_EMAIL": "admin@test.local",
        "FIRST_SUPERUSER_PASSWORD": "TestAdmin123",
        "ALLOW_REGISTRATION": "true",
        "SERVE_FRONTEND": "false",
        "EXTERNAL_PROXY_ENABLED": "false",
        "PBKDF2_ITERATIONS": "1000",  # keep the suite fast
    }
)


@pytest.fixture(scope="session")
def app_module():
    from app.main import app

    return app


@pytest.fixture(scope="session")
def client(app_module) -> Iterator[object]:
    from fastapi.testclient import TestClient

    with TestClient(app_module) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "admin@test.local", "password": "TestAdmin123"},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def project(client, admin_headers) -> dict:
    res = client.post(
        "/api/v1/projects",
        json={"name": f"Test project {random.randint(1000, 9999)}", "tags": ["pytest"]},
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def rng_template() -> str:
    """A deterministic, non-repetitive template for primer/alignment tests."""
    rng = random.Random(20260820)
    return "".join(rng.choice("ACGT") for _ in range(1200))


@pytest.fixture
def demo_plasmid_gb() -> str:
    """The demo plasmid GenBank text, generated on the fly (no fixture files)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.bio.seqio import write_genbank
    from scripts.make_samples import build_demo_plasmid

    return write_genbank(build_demo_plasmid())
