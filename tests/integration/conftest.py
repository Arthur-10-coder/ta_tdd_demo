"""
Integration fixtures:
- Read environment variables provided by GitHub Actions.
- Wait for Splunk service readiness.
- Ensure the KV collection exists before tests run.
"""
import os
import time
import pytest
from splunklib import client as splunk_client

REQUIRED_ENV = [
    "SPLUNK_SESSION_KEY",
    "SPLUNK_APP",
    "KV_COLLECTION",
    "OWNER",
    "SPLUNK_HOST",
    "SPLUNK_PORT",
    "SPLUNK_SCHEME",
    "BASE_URL",
    "API_KEY",
    "TEST_CITY",
    "TEST_COUNTRY",
    "TEST_INDEX",
]

def _require_env():
    missing = [v for v in REQUIRED_ENV if not os.getenv(v)]
    if missing:
        pytest.skip(f"Missing environment variables for integration tests: {missing}")

@pytest.fixture(scope="session")
def env():
    _require_env()
    return {k: os.getenv(k) for k in REQUIRED_ENV}

@pytest.fixture(scope="session")
def splunk_service(env):
    """Connect to Splunk and ensure kvstore is reachable (with retries)."""
    for _ in range(30):
        try:
            svc = splunk_client.connect(
                token=env["SPLUNK_SESSION_KEY"],
                owner=env["OWNER"],
                app=env["SPLUNK_APP"],
                scheme=env["SPLUNK_SCHEME"],
                host=env["SPLUNK_HOST"],
                port=int(env["SPLUNK_PORT"]),
            )
            _ = svc.kvstore
            return svc
        except Exception:
            time.sleep(2)
    pytest.fail("Splunk service not ready")

@pytest.fixture(scope="session")
def ensure_kv_collection(env, splunk_service):
    """Create the KV collection once; optionally clear after the suite."""
    name = env["KV_COLLECTION"]
    try:
        _ = splunk_service.kvstore[name]
    except KeyError:
        splunk_service.kvstore.create(name)
    yield name
    try:
        splunk_service.kvstore[name].data.delete()
    except Exception:
        pass

@pytest.fixture(scope="session", autouse=True)
def ensure_test_index(env, splunk_service):
    """Create the test index if it doesn't exist."""
    index_name = env.get("TEST_INDEX", "weather_test")
    try:
        _ = splunk_service.indexes[index_name]
    except KeyError:
        splunk_service.indexes.create(index_name)
    yield index_name
