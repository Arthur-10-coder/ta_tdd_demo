# tests/integration/test_api.py
import os, requests, pytest
pytestmark = pytest.mark.integration
BASE = os.getenv("APP_BASE","http://app:8000")
def test_greeting():
    r = requests.get(f"{BASE}/greeting", timeout=5)
    assert r.json()["msg"] == "hello from mock"
