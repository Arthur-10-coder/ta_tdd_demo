import sys
import pathlib
import time
import json
import hashlib
import pytest
import splunklib.client as splunk_client
import splunklib.results as results

# Import production helper
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1] / "package" / "bin"))
import city_weather_input_helper as mod


class DummyLogger:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


def _run_spl_search(splunk_svc, search_query, timeout=40, sleep_interval=5, run_counter=0):
    """Run a Splunk SPL search and return unique JSON results."""
    hashes = []
    collected = []
    elapsed = 0
    tot_timeout = timeout + (run_counter * 60)

    kwargs = {"earliest_time": "0", "latest_time": "now", "output_mode": "json"}

    while elapsed < tot_timeout:
        oneshot = splunk_svc.jobs.export(search_query, **kwargs)
        reader = results.JSONResultsReader(oneshot)
        for result in reader:
            if not isinstance(result, dict):
                continue
            raw_str = json.dumps(result.get("_raw", {}))
            h = hashlib.md5(raw_str.encode()).hexdigest()
            if h not in hashes:
                hashes.append(h)
                collected.append(result)
        time.sleep(sleep_interval)
        elapsed += sleep_interval

    return collected


@pytest.mark.integration
def test_end_to_end_and_indexing(env, ensure_kv_collection):
    """
    Full E2E test:
    1. Calls process_city_weather() which:
       - Checks KV Store
       - Calls Mockoon /geo and /weather
       - Upserts into KV
       - Indexes weather event in Splunk
    2. Verifies returned lat/lon/temp
    3. Runs SPL query to confirm event is actually indexed in Splunk
    """
    # Step 1: Trigger the weather flow
    city_rec, weather = mod.process_city_weather(
        city=env["TEST_CITY"].lower(),
        country_code=env["TEST_COUNTRY"],
        collection=ensure_kv_collection,
        api_key=env["API_KEY"],
        base_url=env["BASE_URL"],
        session_key=env["SPLUNK_SESSION_KEY"],
        app_name=env["SPLUNK_APP"],
        owner=env["OWNER"],
        logger=DummyLogger(),
    )

    # Step 2: Validate returned data
    assert "lat" in city_rec and "lon" in city_rec
    assert abs(city_rec["lat"] - 10.5) < 0.01
    assert abs(city_rec["lon"] - (-85.4)) < 0.01
    assert "weather" in weather and "temp" in weather["main"]

    # Step 3: Connect to Splunk and search for the event
    splunk_svc = splunk_client.connect(
        host=env["SPLUNK_HOST"],
        port=int(env["SPLUNK_PORT"]),
        scheme=env["SPLUNK_SCHEME"],
        token=env["SPLUNK_SESSION_KEY"],
    )

    sourcetype = "weather:current"
    index = env["TEST_INDEX"]
    search_query = f'search index={index} sourcetype="{sourcetype}" city="{env["TEST_CITY"].lower()}"'

    events = []
    for attempt in range(3):
        events = _run_spl_search(splunk_svc, search_query, timeout=40, sleep_interval=5, run_counter=attempt)
        if events or attempt == 2:
            break
        time.sleep(2)

    # Step 4: Assert real indexing in Splunk
    assert len(events) > 0, "No indexed event found in Splunk"
    raw_json = json.loads(events[0]["_raw"])
    assert raw_json["city"] == env["TEST_CITY"].lower()
    assert "weather" in raw_json and "temp" in raw_json["weather"]
