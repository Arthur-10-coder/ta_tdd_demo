"""
End-to-end integration:
- KV miss → geocode (Mockoon) → upsert KV → weather (Mockoon).
- Uses real Splunk KVStore and Mockoon containers from CI.
"""
import sys
import pathlib
import pytest

# Import production helper
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2] / "ta_tdd_demo" / "package" / "bin"))
import city_weather_input_helper as mod


class DummyLogger:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


@pytest.mark.integration
def test_end_to_end(env, ensure_kv_collection):
    """
    1) KV check (expect miss) → 2) /geo → 3) KV upsert → 4) /weather → 5) asserts
    """
    city_rec, weather = mod.process_city_weather(
        city=env["TEST_CITY"].lower(),        # Mockoon expects "guanacaste"
        country_code=env["TEST_COUNTRY"],
        collection=ensure_kv_collection,
        api_key=env["API_KEY"],
        base_url=env["BASE_URL"],
        session_key=env["SPLUNK_SESSION_KEY"],
        app_name=env["SPLUNK_APP"],
        owner=env["OWNER"],
        logger=DummyLogger(),
    )

    # KV record has coordinates
    assert isinstance(city_rec, dict)
    assert "lat" in city_rec and "lon" in city_rec
    # If your Mockoon returns fixed coords, validate them:
    assert abs(city_rec["lat"] - 10.5) < 0.01
    assert abs(city_rec["lon"] - (-85.4)) < 0.01

    # Weather payload structure
    assert isinstance(weather, dict)
    assert "weather" in weather and isinstance(weather["weather"], list)
    assert "main" in weather and "temp" in weather["main"]
