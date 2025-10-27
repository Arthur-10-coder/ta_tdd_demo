import json
import logging
import time
import urllib.parse

import requests
import import_declare_test
from solnlib import conf_manager, log
from splunklib import modularinput as smi
from splunklib import client as splunk_client

ADDON_NAME = "ta_tdd_demo"


def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def get_account_credentials(session_key: str, account_name: str):
    """
    Retrieves both the base_url and api_key from the configured account.
    """
    cfm = conf_manager.ConfManager(
        session_key,
        ADDON_NAME,
        realm=f"__REST_CREDENTIAL__#{ADDON_NAME}#configs/conf-ta_tdd_demo_account",
    )
    account_conf_file = cfm.get_conf("ta_tdd_demo_account")
    account_info = account_conf_file.get(account_name)
    return account_info.get("base_url"), account_info.get("api_key")


def check_kvstore_city(collection, city, country_code, *, session_key, app_name=ADDON_NAME, owner="nobody", logger=None):
    """
    Checks if the city record exists in the KV Store.
    Returns (True, document) if found, otherwise (False, None).
    """
    svc = splunk_client.connect(token=session_key, owner=owner, app=app_name, scheme="https", host="localhost", port=8089)
    coll = svc.kvstore[collection]
    query = {"city": city, "country_code": country_code}
    try:
        rs = coll.data.query(query=json.dumps(query))
        if rs:
            return True, rs[0]
        return False, None
    except Exception as e:
        if logger:
            logger.warning("KVStore query failed: %s", e)
        return False, None


def fetch_city_geo_data(city, country_code, api_key, base_url):
    """
    Calls:
      {base_url}/geo/1.0/direct?q={city},{country_code}&limit=1&appid={api_key}
    Returns a dict with lat/lon.
    """
    url = (
        f"{base_url.rstrip('/')}/geo/1.0/direct"
        f"?q={urllib.parse.quote(city)},{urllib.parse.quote(country_code)}"
        f"&limit=1&appid={urllib.parse.quote(api_key)}"
    )
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"geocoding {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not data:
        raise ValueError("no geocoding results")
    d0 = data[0]
    return {"city": city, "country_code": country_code, "lat": d0.get("lat"), "lon": d0.get("lon"), "raw": d0}


def create_city_record_in_kvstore(collection, geo_payload, *, session_key, app_name=ADDON_NAME, owner="nobody", logger=None):
    """
    Inserts or updates the KV Store record using city and country_code as keys.
    """
    svc = splunk_client.connect(token=session_key, owner=owner, app=app_name, scheme="https", host="localhost", port=8089)
    coll = svc.kvstore[collection]
    try:
        exists, doc = check_kvstore_city(
            collection, geo_payload["city"], geo_payload["country_code"],
            session_key=session_key, app_name=app_name, owner=owner, logger=logger
        )
        if exists and doc.get("_key"):
            coll.data.update(doc["_key"], json.dumps(geo_payload))
        else:
            coll.data.insert(json.dumps(geo_payload))
    except Exception as e:
        if logger:
            logger.warning("KV upsert failed: %s", e)
    return geo_payload


def fetch_weather_by_coordinates(lat, lon, api_key, base_url):
    """
    Calls:
      {base_url}/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}
    """
    url = (
        f"{base_url.rstrip('/')}/data/2.5/weather"
        f"?lat={lat}&lon={lon}&appid={urllib.parse.quote(api_key)}"
    )
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"weather {r.status_code}: {r.text[:200]}")
    return r.json()


def process_city_weather(city, country_code="CR", max_attempts=3, *,
                         collection, api_key, base_url, session_key, app_name=ADDON_NAME, logger=None, owner="nobody"):
    """
    Main control loop with retry limit and error logging.
    Returns (city_record, weather_data) or (None, None).
    """
    attempt = 0
    last_err = None
    while attempt < max_attempts:
        attempt += 1
        try:
            exists, city_rec = check_kvstore_city(collection, city, country_code,
                                                  session_key=session_key, app_name=app_name, owner=owner, logger=logger)
            if not exists:
                geo = fetch_city_geo_data(city, country_code, api_key, base_url)
                city_rec = create_city_record_in_kvstore(collection, geo,
                                                         session_key=session_key, app_name=app_name, owner=owner, logger=logger)
            if not city_rec or city_rec.get("lat") is None or city_rec.get("lon") is None:
                raise ValueError("missing lat/lon in city record")
            weather = fetch_weather_by_coordinates(city_rec["lat"], city_rec["lon"], api_key, base_url)
            return city_rec, weather
        except Exception as e:
            last_err = e
            if logger:
                logger.warning("Attempt %s/%s failed: %s", attempt, max_attempts, e)
            time.sleep(1)
    if logger:
        logger.error("All attempts failed: %s", last_err)
    return None, None


def index_weather_events_in_splunk(index, weather_event: dict, *, event_writer: smi.EventWriter, sourcetype="weather:current"):
    """
    Writes weather data as events into Splunk.
    """
    event_writer.write_event(
        smi.Event(
            data=json.dumps(weather_event, ensure_ascii=False, default=str),
            index=index,
            sourcetype=sourcetype,
        )
    )


def get_data_from_api(logger: logging.Logger, api_key: str, session_key: str, account_name: str, collection: str, city: str, country_code: str, index: str, event_writer: smi.EventWriter):
    """
    Extended function that retrieves city weather data using KVStore and OpenWeather.
    """
    base_url, api_key = get_account_credentials(session_key, account_name)
    logger.info(f"Fetching weather for city={city}, country={country_code} via {base_url}")

    city_rec, weather = process_city_weather(
        city=city,
        country_code=country_code,
        collection=collection,
        api_key=api_key,
        base_url=base_url,
        session_key=session_key,
        logger=logger,
    )

    if not weather:
        logger.warning("No weather data retrieved for city %s", city)
        return []

    event = {
        "_time": int(time.time()),
        "city": city,
        "country_code": country_code,
        "kv_city": city_rec,
        "weather": weather,
    }
    index_weather_events_in_splunk(index, event, event_writer=event_writer)
    return [event]


def validate_input(definition: smi.ValidationDefinition):
    return


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter):
    for input_name, input_item in inputs.inputs.items():
        normalized_input_name = input_name.split("/")[-1]
        logger = logger_for_input(normalized_input_name)
        try:
            session_key = inputs.metadata["session_key"]
            log_level = conf_manager.get_log_level(
                logger=logger,
                session_key=session_key,
                app_name=ADDON_NAME,
                conf_name="ta_tdd_demo_settings",
            )
            logger.setLevel(log_level)
            log.modular_input_start(logger, normalized_input_name)

            account = input_item.get("account")
            city = input_item.get("city")
            country_code = input_item.get("country_code")
            collection = input_item.get("kv_collection", "city_geo")
            index = input_item.get("index")

            data = get_data_from_api(
                logger, "", session_key, account, collection, city, country_code, index, event_writer
            )

            sourcetype = "weather:current"
            log.events_ingested(
                logger,
                input_name,
                sourcetype,
                len(data),
                index,
                account=account,
            )
            log.modular_input_end(logger, normalized_input_name)
        except Exception as e:
            log.log_exception(
                logger,
                e,
                "city_weather_error",
                msg_before="Exception raised while ingesting data for city_weather_input: ",
            )

