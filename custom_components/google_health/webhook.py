"""Notificações em tempo real (assinante da Google Health API).

Doc: https://developers.google.com/health/webhooks

O Google faz duas verificações ao criar o assinante: POST com o segredo no
`Authorization` → espera 201; sem o segredo → espera 401/403. Depois, cada
notificação de dado novo dispara uma atualização imediata dos coordenadores.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import TYPE_CHECKING

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from . import GoogleHealthConfigEntry

_LOGGER = logging.getLogger(__name__)
EVENT = f"{DOMAIN}_notificacao"


def ensure_credentials(hass: HomeAssistant, entry: GoogleHealthConfigEntry) -> tuple[str, str]:
    """Gera (uma vez) o id do webhook e o segredo, guardados na config entry."""
    data = dict(entry.data)
    if "webhook_id" not in data:
        data["webhook_id"] = webhook.async_generate_id()
        data["webhook_secret"] = secrets.token_urlsafe(32)
        hass.config_entries.async_update_entry(entry, data=data)
    return data["webhook_id"], data["webhook_secret"]


def webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """URL pública do webhook; sem URL externa configurada, só o caminho
    (prefixe com o domínio pelo qual o HA é acessado de fora)."""
    path = webhook.async_generate_path(webhook_id)
    try:
        return get_url(hass, allow_internal=False, prefer_cloud=False) + path
    except NoURLAvailableError:
        return path


def register(hass: HomeAssistant, entry: GoogleHealthConfigEntry) -> None:
    webhook_id, secret = ensure_credentials(hass, entry)

    async def handle(hass: HomeAssistant, wid: str, request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.removeprefix("Bearer "), secret):
            return web.Response(status=401)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and payload.get("type") == "verification":
            return web.Response(status=201)
        rt = entry.runtime_data
        rt.notifications += 1
        rt.last_notification = dt_util.utcnow()
        rt.last_payload = payload
        # Corpo: {"data": {...}} ou lista (lote de até 99). Só avisa o que mudou;
        # os valores vêm na atualização dos coordenadores.
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            data = item.get("data", item) if isinstance(item, dict) else {"dados": item}
            hass.bus.async_fire(EVENT, data)
        _LOGGER.debug("Notificação Google Health: %s", payload)
        for coord in rt.coordinators.values():
            hass.async_create_task(coord.async_request_refresh())  # debounced, não segura a resposta
        return web.Response(status=204)  # o Google reenvia se não for 204

    webhook.async_register(
        hass, DOMAIN, f"Google Health ({entry.title})", webhook_id, handle,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
