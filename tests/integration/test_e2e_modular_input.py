"""
End-to-end integration:
- Full flow: KV miss → geocode (Mockoon) → upsert KV → weather (Mockoon).
- Asserts the orchestrated outputs.
"""
import sys
import pathlib
import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2] / "ta_tdd_demo" / "package" / "bin"))
import city_weather_input_helper as mod

class DummyLogger:
    def info(self,*a,**k): ...
    def warning(self,*a,**k): ...
    def error(self,*a,**k): ...

@pytest.mark.integration
def test_end_to_end(env, ensure_kv_collection):
    city_rec, weather = mod.process_city_weather(
        city=env["TEST_CITY"], country_code=env["TEST_COUNTRY"],
        collection=ensure_kv_collection, api_key=env["API_KEY"], base_url=env["BASE_URL"],
        session_key=env["SPLUNK_SESSION_KEY"], app_name=env["SPLUNK_APP"], owner=env["OWNER"], logger=DummyLogger()
    )
    assert city_rec and "lat" in city_rec and "lon" in city_rec
    assert isinstance(weather, dict)
