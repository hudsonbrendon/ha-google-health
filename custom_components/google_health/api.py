"""Cliente mínimo da Google Health API v4 (health.googleapis.com).

Mapeado a partir do discovery document (revisão 20261114) e testado com a
conta real. Formatos em REVERSE_ENGINEERING.md.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_URL, USERINFO_URL

_LOGGER = logging.getLogger(__name__)


class GoogleHealthError(Exception):
    """Erro genérico da API."""


class GoogleHealthAuthError(GoogleHealthError):
    """Token inválido/expirado (401)."""


class GoogleHealthUnavailable(GoogleHealthError):
    """Endpoint sem permissão (escopo) ou sem suporte para o tipo de dado.

    Não derruba a atualização: o sensor fica sem valor.
    """


def rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def civil_date(day: date) -> dict[str, Any]:
    """`date` -> CivilDateTime da API."""
    return {"date": {"year": day.year, "month": day.month, "day": day.day}}


class GoogleHealthClient:
    """Chamadas REST autenticadas por um provedor de token OAuth."""

    def __init__(
        self, session: ClientSession, token_fn: Callable[[], Awaitable[str]]
    ) -> None:
        self._session = session
        self._token_fn = token_fn
        # ponytail: limite fixo de concorrência; a API não documenta cota por minuto.
        self._sem = asyncio.Semaphore(6)

    async def _request(
        self, method: str, url: str, *, params: dict | None = None, json: Any = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {await self._token_fn()}"}
        try:
            async with self._sem, self._session.request(
                method, url, params=params, json=json, headers=headers, timeout=30
            ) as resp:
                body = await resp.json(content_type=None) if resp.content_length != 0 else {}
                status = resp.status
        except (ClientError, TimeoutError) as err:
            raise GoogleHealthError(f"{method} {url}: {err}") from err
        if status < 400:
            return body or {}
        err = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        msg = f"{status} {err.get('status', '')} {err.get('message', '')}".strip()
        if status == 401:
            raise GoogleHealthAuthError(msg)
        # 403 por escopo faltando, 400 "List is not supported for data type",
        # 404 de recurso inexistente: tratados como "sem dado".
        if status in (400, 403, 404) and "SERVICE_DISABLED" not in str(body):
            raise GoogleHealthUnavailable(msg)
        raise GoogleHealthError(msg)

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        return await self._request("GET", f"{API_URL}/{path}", params=params or None)

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"{API_URL}/{path}", json=body)

    async def user_info(self) -> dict[str, Any]:
        return await self._request("GET", USERINFO_URL)

    async def list_points(
        self, data_type: str, page_size: int = 1, flt: str | None = None, max_pages: int = 1
    ) -> list[dict[str, Any]]:
        """Data points, mais novo primeiro (a API ordena por início desc)."""
        params: dict[str, Any] = {"pageSize": page_size}
        if flt:
            params["filter"] = flt
        out: list[dict[str, Any]] = []
        for _ in range(max_pages):
            page = await self.get(f"dataTypes/{data_type}/dataPoints", **params)
            out.extend(page.get("dataPoints", []))
            if not (token := page.get("nextPageToken")):
                break
            params["pageToken"] = token
        return out

    async def daily_rollup(self, data_type: str, start: date, end: date) -> list[dict]:
        """Agregados por dia civil em [start, end). Dias sem dado são omitidos."""
        body = {
            "range": {"start": civil_date(start), "end": civil_date(end)},
            "windowSizeDays": 1,
        }
        res = await self.post(f"dataTypes/{data_type}/dataPoints:dailyRollUp", body)
        return res.get("rollupDataPoints", [])

    async def rollup(
        self, data_type: str, start: datetime, end: datetime, window: str = "3600s"
    ) -> list[dict]:
        """Agregados por janela física (ex.: por hora) em [start, end), paginado."""
        body: dict[str, Any] = {
            "range": {"startTime": rfc3339(start), "endTime": rfc3339(end)},
            "windowSize": window,
            "pageSize": 1000,
        }
        out: list[dict] = []
        while True:
            res = await self.post(f"dataTypes/{data_type}/dataPoints:rollUp", body)
            out.extend(res.get("rollupDataPoints", []))
            if not (token := res.get("nextPageToken")):
                return out
            body["pageToken"] = token

    async def export_tcx(self, point_name: str) -> bytes:
        """TCX de um exercício (exige escopo de localização)."""
        url = f"{API_URL.rsplit('/users/', 1)[0]}/{point_name}:exportExerciseTcx"
        headers = {"Authorization": f"Bearer {await self._token_fn()}"}
        try:
            async with self._sem, self._session.get(
                url, params={"alt": "media"}, headers=headers, timeout=60
            ) as resp:
                data = await resp.read()
                status = resp.status
        except (ClientError, TimeoutError) as err:
            raise GoogleHealthError(f"TCX: {err}") from err
        if status == 401:
            raise GoogleHealthAuthError("401")
        if status >= 400:
            raise GoogleHealthUnavailable(f"{status} {data[:200]!r}")
        return data

    async def create(self, data_type: str, field: str, value: dict[str, Any]) -> dict:
        """Cria um data point (exige escopo de escrita)."""
        return await self.post(f"dataTypes/{data_type}/dataPoints", {field: value})


async def safe(coro: Awaitable[Any], default: Any = None) -> Any:
    """Aguarda e devolve `default` se o endpoint não estiver disponível."""
    try:
        return await coro
    except GoogleHealthUnavailable as err:
        _LOGGER.debug("Sem dado: %s", err)
        return default
