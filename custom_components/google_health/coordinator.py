"""Coordenadores: três grupos com intervalos diferentes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GoogleHealthAuthError, GoogleHealthClient, GoogleHealthError, safe
from .const import DOMAIN, SCOPE_ECG, SCOPE_IRN
from .parse import rollup_days

_LOGGER = logging.getLogger(__name__)

# Tipos agregados por dia (hoje + 6 dias anteriores) — atividade e nutrição.
ROLLUP_TYPES = [
    "steps",
    "distance",
    "active-energy-burned",
    "total-calories",
    "floors",
    "altitude",
    "active-minutes",
    "active-zone-minutes",
    "sedentary-period",
    "time-in-heart-rate-zone",
    "calories-in-heart-rate-zone",
    "heart-rate",
    "hydration-log",
    "nutrition-log",
]
# Última medição de cada tipo (pageSize=1; a API devolve o mais novo primeiro).
FAST_LATEST = [
    "heart-rate",
    "daily-resting-heart-rate",
    "daily-heart-rate-variability",
    "heart-rate-variability",
    "daily-oxygen-saturation",
    "oxygen-saturation",
    "daily-respiratory-rate",
    "daily-heart-rate-zones",
    "daily-vo2-max",
    "vo2-max",
    "run-vo2-max",
    "nutrition-log",
    "hydration-log",
]
SLOW_LATEST = [
    "weight",
    "height",
    "body-fat",
    "core-body-temperature",
    "blood-glucose",
    "daily-sleep-temperature-derivations",
    "respiratory-rate-sleep-summary",
]


class GoogleHealthCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordenador genérico; `fetch` devolve um dict de JSON cru."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        interval: timedelta,
        fetch: Callable[[], Awaitable[dict[str, Any]]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{name}",
            update_interval=interval,
        )
        self._fetch = fetch

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except GoogleHealthAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GoogleHealthError as err:
            raise UpdateFailed(str(err)) from err


async def _latest(client: GoogleHealthClient, types: list[str]) -> dict[str, Any]:
    pts = await asyncio.gather(*(safe(client.list_points(t), []) for t in types))
    return {t: (p[0] if p else None) for t, p in zip(types, pts, strict=True)}


def build_coordinators(
    hass: HomeAssistant, entry: ConfigEntry, client: GoogleHealthClient, scopes: set[str]
) -> dict[str, GoogleHealthCoordinator]:
    """fast (15 min): atividade, coração, nutrição. slow (30 min): corpo, sono,
    exercícios. account (6 h): perfil, configurações, aparelhos."""
    fast_latest = list(FAST_LATEST)
    if SCOPE_ECG in scopes:
        fast_latest.append("electrocardiogram")
    if SCOPE_IRN in scopes:
        fast_latest.append("irregular-rhythm-notification")

    async def fetch_fast() -> dict[str, Any]:
        today = dt_util.now().date()
        start, end = today - timedelta(days=6), today + timedelta(days=1)
        rolls, latest = await asyncio.gather(
            asyncio.gather(
                *(safe(client.daily_rollup(t, start, end), []) for t in ROLLUP_TYPES)
            ),
            _latest(client, fast_latest),
        )
        return {
            "roll": {
                t: rollup_days(r) for t, r in zip(ROLLUP_TYPES, rolls, strict=True)
            },
            "last": latest,
        }

    async def fetch_slow() -> dict[str, Any]:
        latest, sleep, exercise = await asyncio.gather(
            _latest(client, SLOW_LATEST),
            safe(client.list_points("sleep", page_size=10), []),
            safe(client.list_points("exercise", page_size=25), []),
        )
        return {"last": latest, "sleep": sleep, "exercise": exercise}

    async def fetch_account() -> dict[str, Any]:
        profile, settings, identity, devices, irn = await asyncio.gather(
            safe(client.get("profile"), {}),
            safe(client.get("settings"), {}),
            safe(client.get("identity"), {}),
            safe(client.get("pairedDevices"), {}),
            safe(client.get("irnProfile"), {}) if SCOPE_IRN in scopes else _none(),
        )
        return {
            "profile": profile,
            "settings": settings,
            "identity": identity,
            "devices": devices.get("pairedDevices", []),
            "irn": irn,
        }

    return {
        "fast": GoogleHealthCoordinator(
            hass, entry, "fast", timedelta(minutes=15), fetch_fast
        ),
        "slow": GoogleHealthCoordinator(
            hass, entry, "slow", timedelta(minutes=30), fetch_slow
        ),
        "account": GoogleHealthCoordinator(
            hass, entry, "account", timedelta(hours=6), fetch_account
        ),
    }


async def _none() -> None:
    return None
