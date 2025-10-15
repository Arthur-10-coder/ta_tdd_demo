"""
KVStore integration:
- Upsert a city record.
- Query the record and validate fields/values.
"""
import sys
import pathlib
import pytest

# Import production helper
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1] / "package" / "bin"))
import city_weather_input_helper as mod


class DummyLogger:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


@pytest.mark.integration
def test_kv_create_and_get(env, ensure_kv_collection):
    """
    Insert (or update) a KV document for the test city and verify it can be retrieved.
    Uses lowercase city to match the Mockoon geocode expectation.
    """
    city = env["TEST_CITY"].lower()   # "guanacaste"
    country = env["TEST_COUNTRY"]

    geo = {"city": city, "country_code": country, "lat": 10.5, "lon": -85.4}
    mod.create_city_record_in_kvstore(
        ensure_kv_collection,
        geo,
        session_key=env["SPLUNK_SESSION_KEY"],
        app_name=env["SPLUNK_APP"],
        owner=env["OWNER"],
        logger=DummyLogger(),
    )

    # Query and validate
    exists, doc = mod.check_kvstore_city(
        ensure_kv_collection,
        city,
        country,
        session_key=env["SPLUNK_SESSION_KEY"],
        app_name=env["SPLUNK_APP"],
        owner=env["OWNER"],
        logger=DummyLogger(),
    )
    assert exists is True
    assert "lat" in doc and "lon" in doc
    assert abs(doc["lat"] - 10.5) < 0.01
    assert abs(doc["lon"] - (-85.4)) < 0.01
