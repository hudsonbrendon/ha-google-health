"""Config flow OAuth2 (credenciais em Configurações › Credenciais de aplicativo)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, ConfigFlowResult
from homeassistant.helpers import aiohttp_client, config_entry_oauth2_flow

from .api import GoogleHealthClient, GoogleHealthError
from .const import API_CONSOLE_URL, DOMAIN, OAUTH_SCOPES, SCOPE_PROFILE

_LOGGER = logging.getLogger(__name__)


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            # Sem include_granted_scopes: o client OAuth é compartilhado com outras
            # integrações (Drive, YouTube) e o Google recusa misturar esses escopos.
        }

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_user(user_input)

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        token = data["token"]
        if SCOPE_PROFILE not in token.get("scope", "").split():
            return self.async_abort(reason="missing_profile_scope")

        async def static() -> str:
            return token["access_token"]

        client = GoogleHealthClient(aiohttp_client.async_get_clientsession(self.hass), static)
        try:
            identity = await client.get("identity")
        except GoogleHealthError as err:
            _LOGGER.error("Falha ao ler identidade: %s", err)
            if "SERVICE_DISABLED" in str(err) or "has not been used" in str(err):
                return self.async_abort(
                    reason="api_not_enabled", description_placeholders={"url": API_CONSOLE_URL}
                )
            return self.async_abort(reason="cannot_connect")
        if not (uid := identity.get("healthUserId")):
            return self.async_abort(reason="missing_profile_scope")

        await self.async_set_unique_id(uid)
        if self.source in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            entry = (
                self._get_reauth_entry()
                if self.source == SOURCE_REAUTH
                else self._get_reconfigure_entry()
            )
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data=data)
        self._abort_if_unique_id_configured()

        title = "Google Health"
        try:
            info = await client.user_info()
            title = info.get("given_name") or info.get("name") or title
        except GoogleHealthError:
            pass
        return self.async_create_entry(title=title, data=data)
