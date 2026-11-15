"""Sobe a integração inteira num HA de teste com a API simulada."""

from datetime import timedelta
import time
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.google_health.api import GoogleHealthUnavailable
from custom_components.google_health.const import DOMAIN, OAUTH_SCOPES, SCOPE_ECG

from .test_parse import EXERCISE, SLEEP

READ_SCOPES = [s for s in OAUTH_SCOPES if "writeonly" not in s and s != SCOPE_ECG]


def _day(d):
    return {"date": {"year": d.year, "month": d.month, "day": d.day}, "time": {}}


def fake_api(calls):
    today = dt_util.now().date()
    roll = {
        "steps": {"countSum": "8421"},
        "distance": {"millimetersSum": "6100000"},
        "active-energy-burned": {"kcalSum": 412.4},
        "total-calories": {"kcalSum": 2301.9},
        "hydration-log": {"amountConsumed": {"millilitersSum": 1500}},
        "nutrition-log": {"energy": {"kcalSum": 1800}, "nutrients": [
            {"nutrient": "PROTEIN", "quantity": {"gramsSum": 120}},
            {"nutrient": "SODIUM", "quantity": {"gramsSum": 2.3}}]},
        "time-in-heart-rate-zone": {"timeInHeartRateZones": [
            {"heartRateZone": "LIGHT", "duration": "3600s"},
            {"heartRateZone": "MODERATE", "duration": "1200s"}]},
    }
    latest = {
        "heart-rate": {"heartRate": {"beatsPerMinute": "72", "sampleTime": {"physicalTime": "2026-07-30T13:05:28Z"}}},
        "daily-resting-heart-rate": {"dailyRestingHeartRate": {"beatsPerMinute": "55", "date": {"year": 2026, "month": 7, "day": 30}}},
        "weight": {"weight": {"weightGrams": 85000, "sampleTime": {"physicalTime": "2026-07-30T15:51:47Z"}}},
        "height": {"height": {"heightMillimeters": "1780", "sampleTime": {"physicalTime": "2026-07-30T15:51:47Z"}}},
        "sleep": SLEEP,
        "exercise": EXERCISE,
    }

    async def request(self, method, url, *, params=None, json=None):
        calls.append((method, url, params, json))
        path = url.split("/users/me/", 1)[-1]
        if path == "identity":
            return {"healthUserId": "123"}
        if path == "profile":
            return {"age": 34, "membershipStartDate": {"year": 2026, "month": 7, "day": 30}}
        if path == "irnProfile":
            return {"enrollmentStatus": False}
        if path in ("settings", "pairedDevices"):
            return {"pairedDevices": [{"name": "users/1/pairedDevices/abc", "deviceVersion": "Pixel Watch 3",
                                       "batteryLevel": 80, "lastSyncTime": "2026-11-15T10:00:00Z"}]} if path == "pairedDevices" else {}
        if path.endswith(":dailyRollUp"):
            t = path.split("/")[1]
            if t not in roll:
                return {}
            field = {"active-energy-burned": "activeEnergyBurned", "total-calories": "totalCalories",
                     "hydration-log": "hydrationLog", "nutrition-log": "nutritionLog",
                     "time-in-heart-rate-zone": "timeInHeartRateZone"}.get(t, t)
            return {"rollupDataPoints": [{"civilStartTime": _day(today),
                                          "civilEndTime": _day(today + timedelta(days=1)), field: roll[t]}]}
        if path.endswith("/dataPoints") and method == "GET":
            t = path.split("/")[1]
            if t == "total-calories":
                raise GoogleHealthUnavailable("400 List is not supported")
            return {"dataPoints": [latest[t]]} if t in latest else {}
        if path.endswith("/dataPoints") and method == "POST":
            return {"done": True}
        raise AssertionError(f"inesperado {method} {url}")

    return request


async def _setup(hass: HomeAssistant, scopes):
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(hass, DOMAIN, ClientCredential("id", "secret"), DOMAIN)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="123", title="Hudson",
        data={"auth_implementation": DOMAIN, "token": {
            "access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600,
            "scope": " ".join(scopes)}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_setup_and_sensors(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("America/Fortaleza")
    calls = []
    with patch("custom_components.google_health.api.GoogleHealthClient._request", fake_api(calls)):
        entry = await _setup(hass, READ_SCOPES)
        ents = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        by_key = {e.unique_id.removeprefix(f"{entry.entry_id}_"): e.entity_id for e in ents}

        def st(key):
            return hass.states.get(by_key[key])

        assert len(ents) > 70
        assert "ecg" not in by_key  # sem escopo de ECG
        assert st("steps").state == "8421"
        assert float(st("distance").state) == pytest.approx(6.1)  # km sugerido
        assert st("basal_calories").state == "1890"
        assert st("heart_zone_minutes").state == "20"
        assert st("hydration").state == "1.5"
        assert st("sodium").state == "2300"
        assert st("protein").state == "120.0"
        assert st("resting_heart_rate").state == "55.0"
        assert st("weight").state == "85.0"
        assert st("bmi").state == "26.8"
        assert st("sleep_asleep").attributes["inicio"].startswith("30/07/2026")
        assert st("sleep_efficiency").state == "99.7"
        assert st("last_exercise").state == "Ciclismo"
        assert st("last_exercise_duration").state == "30.5"
        assert st("age").state == "34"
        assert st("last_data").state == dt_util.as_utc(
            dt_util.start_of_local_day() + timedelta(hours=12)).isoformat()
        assert hass.states.get("sensor.pixel_watch_3_bateria").state == "80"
        assert hass.states.get(by_key["calendar_exercise"]).attributes["message"] == "Ciclismo"

        res = await hass.services.async_call(
            DOMAIN, "buscar_dados", {"tipo": "heart-rate", "limite": 5},
            blocking=True, return_response=True)
        assert res["quantidade"] == 1

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "registrar_peso", {"peso": 84.2}, blocking=True)

        events = await hass.services.async_call(
            "calendar", "get_events",
            {"entity_id": by_key["calendar_sleep"], "start_date_time": "2026-07-29 00:00:00",
             "end_date_time": "2026-07-31 00:00:00"},
            blocking=True, return_response=True)
        assert events[by_key["calendar_sleep"]]["events"][0]["summary"] == "Sono 6h15"


async def test_write_services(hass: HomeAssistant) -> None:
    calls = []
    with patch("custom_components.google_health.api.GoogleHealthClient._request", fake_api(calls)):
        await _setup(hass, OAUTH_SCOPES)
        await hass.services.async_call(
            DOMAIN, "registrar_peso", {"peso": 84.2, "gordura_corporal": 21.5}, blocking=True)
        await hass.services.async_call(DOMAIN, "registrar_agua", {"quantidade": 300}, blocking=True)
        await hass.services.async_call(
            DOMAIN, "registrar_exercicio", {"tipo": "STRENGTH_TRAINING", "duracao": 60, "calorias": 350},
            blocking=True)
        posts = [(u.split("dataTypes/")[1], b) for m, u, _, b in calls if m == "POST" and u.endswith("/dataPoints")]
        assert [p[0] for p in posts] == [
            "weight/dataPoints", "body-fat/dataPoints", "hydration-log/dataPoints", "exercise/dataPoints"]
        assert posts[0][1]["weight"]["weightGrams"] == 84200
        assert posts[3][1]["exercise"]["activeDuration"] == "3600s"
