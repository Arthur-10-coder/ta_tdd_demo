"""
Unit tests: exercise function behavior with local fakes and HTTP stubs.
- No external Splunk or Mockoon containers required.
- requests-mock simulates OpenWeather/Mockoon responses.
- In-memory fakes simulate Splunk KV Store and EventWriter behavior.
"""
import sys
import pathlib
import json
import requests_mock

# Import production helper
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2] / "ta_tdd_demo" / "package" / "bin"))
import city_weather_input_helper as mod


# ---------------------- In-memory fakes ----------------------
class FakeKVData:
    """Replicates KVStore data API: query/insert/update/delete in memory."""
    def __init__(self):
        self.docs = {}
    def query(self, query=None):
        q = json.loads(query) if query else {}
        for d in self.docs.values():
            if d.get("city") == q.get("city") and d.get("country_code") == q.get("country_code"):
                return [d]
        return []
    def insert(self, payload):
        d = json.loads(payload) if isinstance(payload, str) else payload
        d["_key"] = f"{d['city']}-{d['country_code']}"
        self.docs[d["_key"]] = d
        return d
    def update(self, key, payload):
        d = json.loads(payload) if isinstance(payload, str) else payload
        d["_key"] = key
        self.docs[key] = d
        return d
    def delete(self, key=None):
        if key:
            self.docs.pop(key, None)
        else:
            self.docs.clear()

class FakeKVStore:
    """Holds named collections that expose a .data with FakeKVData."""
    def __init__(self):
        self._colls = {}
    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = type("C", (), {"data": FakeKVData()})()
        return self._colls[name]
    def create(self, name):
        self.__getitem__(name)

class FakeSplunkService:
    """Minimal Splunk service exposing kvstore and receivers.simple.submit."""
    def __init__(self):
        self.kvstore = FakeKVStore()
    @property
    def receivers(self):
        class Simple:
            def submit(self, *_args, **_kwargs):  # no-op for unit scope
                pass
        return {"simple": Simple()}

class DummyWriter:
    """Captures written events to assert serialization and content."""
    def __init__(self):
        self.events = []
    def write_event(self, evt):
        self.events.append(evt)

class DummyLogger:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


# Route Splunk client connection to the in-memory fake service
mod.splunk_client.connect = lambda **_: FakeSplunkService()


# ----------------------------- Tests -----------------------------
def test_check_kvstore_city_and_create_upsert_unit():
    """KV: verify miss → insert → hit → update with the in-memory fake."""
    coll = "city_geo"
    city, country = "guanacaste", "CR"

    ok, doc = mod.check_kvstore_city(coll, city, country, session_key="S", logger=DummyLogger())
    assert ok is False and doc is None

    created = mod.create_city_record_in_kvstore(
        coll, {"city": city, "country_code": country, "lat": 10.5, "lon": -85.4},
        session_key="S", logger=DummyLogger()
    )
    assert created["lat"] == 10.5 and created["lon"] == -85.4

    ok, doc = mod.check_kvstore_city(coll, city, country, session_key="S", logger=DummyLogger())
    assert ok is True and doc["lon"] == -85.4

    mod.create_city_record_in_kvstore(
        coll, {"city": city, "country_code": country, "lat": 10.6, "lon": -85.5},
        session_key="S", logger=DummyLogger()
    )
    ok, doc = mod.check_kvstore_city(coll, city, country, session_key="S", logger=DummyLogger())
    assert doc["lat"] == 10.6 and doc["lon"] == -85.5


def test_fetch_city_geo_and_weather_with_requests_mock():
    """HTTP: stub geocoding and weather endpoints and validate parsing."""
    base_url = "http://mockoon:3000"
    api_key = "K"
    with requests_mock.Mocker() as m:
        # Match endpoint regardless of query to keep test simple
        m.get(f"{base_url}/geo/1.0/direct", json=[{"lat": 10.5, "lon": -85.4}], status_code=200)
        m.get(f"{base_url}/data/2.5/weather", json={"main": {"temp": 302.15}}, status_code=200)

        geo = mod.fetch_city_geo_data("guanacaste", "CR", api_key, base_url)
        assert geo["lat"] == 10.5 and geo["lon"] == -85.4

        weather = mod.fetch_weather_by_coordinates(10.5, -85.4, api_key, base_url)
        assert weather["main"]["temp"] == 302.15


def test_process_city_weather_flow_with_fakes_and_requests_mock():
    """Orchestration: miss → geocode → upsert → weather, all locally faked."""
    base_url, api_key, coll = "http://mockoon:3000", "K", "city_geo"
    city, country = "guanacaste", "CR"

    # reset in-memory KV
    svc = mod.splunk_client.connect(token="S")
    svc.kvstore[coll].data.delete()

    with requests_mock.Mocker() as m:
        m.get(f"{base_url}/geo/1.0/direct", json=[{"lat": 10.5, "lon": -85.4}], status_code=200)
        m.get(f"{base_url}/data/2.5/weather", json={"ok": True}, status_code=200)

        city_rec, weather = mod.process_city_weather(
            city=city, country_code=country,
            collection=coll, api_key=api_key, base_url=base_url,
            session_key="S", logger=DummyLogger()
        )
        assert city_rec["lat"] == 10.5 and city_rec["lon"] == -85.4
        assert weather["ok"] is True


def test_index_weather_events_in_splunk_serialization_only():
    """Event writer: ensure JSON payload contains expected fields."""
    writer = DummyWriter()
    evt = {"city": "guanacaste", "weather": {"temp": 302.15}}
    mod.index_weather_events_in_splunk("weather_test", evt, event_writer=writer, sourcetype="weather:current")
    assert len(writer.events) == 1
    payload = json.loads(writer.events[0].data)
    assert payload["city"] == "guanacaste" and payload["weather"]["temp"] == 302.15
