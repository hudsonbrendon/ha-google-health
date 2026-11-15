"""Diagnóstico: JSON cru de cada coordenador (sem token)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GoogleHealthConfigEntry, debug_dump

REDACT = {"token", "macAddress", "healthUserId", "legacyUserId", "name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry
) -> dict[str, Any]:
    return {
        "scopes": sorted(entry.runtime_data.scopes),
        "data": async_redact_data(debug_dump(entry), REDACT),
    }
