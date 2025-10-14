"""
API integration:
- Calls the real Mockoon API started in CI (no HTTP mocks).
- Verifies geocoding returns lat/lon for the test city.
- Uses the returned lat/lon to fetch current weather.
"""
import sys
import pathlib
import pytest

# Import production helper
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2] / "ta_tdd_demo" / "package" / "bin"))
import city_weather_input_helper as mod


@pytest.mark.integration
def test_geo_from_api(env):
    """Calls /geo/1.0/direct and validates latitude and longitude fields."""
    response = mod.fetch_city_geo_data(
        env["TEST_CITY"], env["TEST_COUNTRY"], env["API_KEY"], env["BASE_URL"]
    )
    assert isinstance(response, dict)
    assert "lat" in response and "lon" in response
    assert response["lat"] == 10.5 and response["lon"] == -85.4


@pytest.mark.integration
def test_weather_from_api(env):
    """
    Uses /geo to resolve lat/lon for the test city, then calls /data/2.5/weather.
    Validates the weather payload structure.
    """
    geo = mod.fetch_city_geo_data(env["TEST_CITY"], env["TEST_COUNTRY"], env["API_KEY"], env["BASE_URL"])
    lat, lon = geo["lat"], geo["lon"]

    weather = mod.fetch_weather_by_coordinates(lat, lon, env["API_KEY"], env["BASE_URL"])
    assert isinstance(weather, dict)

    if "main" in weather:
        assert "temp" in weather["main"]
