"""Google Health — integração completa (sobrescreve a do core, mesmo domínio).

Adota a config entry, as credenciais OAuth e as entidades da integração do core.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    aiohttp_client,
    config_validation as cv,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.config_entry_oauth2_flow import (
    OAuth2Session,
    async_get_config_entry_implementation,
)
from homeassistant.helpers.typing import ConfigType

from .api import GoogleHealthClient
from .const import DEV_ACCOUNT, DEVICE_NAMES, DOMAIN, EXTRA_SCOPES
from .coordinator import GoogleHealthCoordinator, build_coordinators
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class GoogleHealthData:
    client: GoogleHealthClient
    scopes: set[str]
    coordinators: dict[str, GoogleHealthCoordinator]


type GoogleHealthConfigEntry = ConfigEntry[GoogleHealthData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GoogleHealthConfigEntry) -> bool:
    implementation = await async_get_config_entry_implementation(hass, entry)
    session = OAuth2Session(hass, entry, implementation)

    async def token() -> str:
        await session.async_ensure_token_valid()
        return session.token["access_token"]

    client = GoogleHealthClient(aiohttp_client.async_get_clientsession(hass), token)
    scopes = set(session.token.get("scope", "").split())
    coordinators = build_coordinators(hass, entry, client, scopes)
    await asyncio.gather(
        *(c.async_config_entry_first_refresh() for c in coordinators.values())
    )
    entry.runtime_data = GoogleHealthData(client, scopes, coordinators)

    # O dispositivo da conta mantém o identificador do core (entry_id) para
    # herdar área e histórico; só ganha nome em português.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Google",
        model="Conta",
        name=DEVICE_NAMES[DEV_ACCOUNT],
        entry_type=dr.DeviceEntryType.SERVICE,
    )

    missing = [s.rsplit(".", 2)[-2] for s in EXTRA_SCOPES if s not in scopes]
    if missing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"extra_scopes_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="extra_scopes",
            translation_placeholders={"scopes": ", ".join(sorted(set(missing)))},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, f"extra_scopes_{entry.entry_id}")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoogleHealthConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def loaded_entries(hass: HomeAssistant) -> list[GoogleHealthConfigEntry]:
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if getattr(e, "runtime_data", None) is not None
    ]


def debug_dump(entry: GoogleHealthConfigEntry) -> dict[str, Any]:
    return {k: c.data for k, c in entry.runtime_data.coordinators.items()}
