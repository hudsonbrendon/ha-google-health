"""Histórico nas estatísticas de longo prazo do HA (gráficos de meses/anos).

Estatísticas externas `google_health:<id>`, importadas por hora. Cada rodada continua
da última hora gravada (que é regravada, pois pode ter chegado dado depois).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import GoogleHealthClient, GoogleHealthError, safe
from .const import DOMAIN
from .parse import body, mean_rows, num, point_moment, sum_rows, time_filter, ts

_LOGGER = logging.getLogger(__name__)
CHUNK = timedelta(days=14)


@dataclass(frozen=True)
class SumStat:
    key: str
    name: str
    data_type: str
    unit: str
    unit_class: str | None
    value: Callable[[dict], float | None]


@dataclass(frozen=True)
class PointStat:
    key: str
    name: str
    data_type: str
    unit: str
    value: Callable[[dict], float | None]


def _mm(v: dict) -> float | None:
    mm = num(v.get("millimetersSum"))
    return mm / 1000 if mm is not None else None


SUMS = [
    SumStat("passos", "Passos", "steps", "passos", None, lambda v: num(v.get("countSum"))),
    SumStat("distancia", "Distância", "distance", "m", "distance", _mm),
    SumStat("calorias_ativas", "Calorias ativas", "active-energy-burned", "kcal", "energy",
            lambda v: num(v.get("kcalSum"))),
    SumStat("andares", "Andares", "floors", "andares", None, lambda v: num(v.get("countSum"))),
]


def _w(b: dict) -> float | None:
    g = num(b.get("weightGrams"))
    return round(g / 1000, 2) if g else None


POINTS = [
    PointStat("peso", "Peso", "weight", "kg", _w),
    PointStat("fc_repouso", "FC em repouso", "daily-resting-heart-rate", "bpm",
              lambda b: num(b.get("beatsPerMinute"))),
    PointStat("vfc", "Variabilidade da FC", "daily-heart-rate-variability", "ms",
              lambda b: num(b.get("averageHeartRateVariabilityMilliseconds")) or None),
    PointStat("frequencia_respiratoria", "Frequência respiratória", "daily-respiratory-rate",
              "rpm", lambda b: num(b.get("breathsPerMinute"))),
    PointStat("sono", "Tempo dormindo", "sleep", "min",
              lambda b: num((b.get("summary") or {}).get("minutesAsleep"))),
    PointStat("gordura_corporal", "Gordura corporal", "body-fat", "%",
              lambda b: num(b.get("percentage"))),
]


def _meta(key: str, name: str, unit: str, unit_class: str | None, has_sum: bool) -> dict:
    return {
        "source": DOMAIN,
        "statistic_id": f"{DOMAIN}:{key}",
        "name": f"Google Health {name}",
        "unit_of_measurement": unit,
        "unit_class": unit_class,
        "has_sum": has_sum,
        "mean_type": StatisticMeanType.NONE if has_sum else StatisticMeanType.ARITHMETIC,
    }


async def _last(hass: HomeAssistant, statistic_id: str) -> dict[str, Any] | None:
    res = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, False, {"sum", "state"}
    )
    rows = res.get(statistic_id) or []
    return rows[0] if rows else None


async def async_import_history(
    hass: HomeAssistant, client: GoogleHealthClient, days: int = 365
) -> dict[str, int]:
    """Importa/atualiza tudo. Devolve {id: linhas gravadas}."""
    now = dt_util.utcnow()
    first = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    written: dict[str, int] = {}

    for stat in SUMS:
        sid = f"{DOMAIN}:{stat.key}"
        last = await _last(hass, sid)
        if last:
            start = dt_util.utc_from_timestamp(last["start"])
            base = (last.get("sum") or 0) - (last.get("state") or 0)
        else:
            start, base = first, 0.0
        rows: list[dict] = []
        cursor = start
        try:
            while cursor < now:
                end = min(cursor + CHUNK, now + timedelta(hours=1))
                pts = await safe(client.rollup(stat.data_type, cursor, end), [])
                new = sum_rows(pts, stat.value, rows[-1]["sum"] if rows else base)
                rows.extend(new)
                cursor = end
        except GoogleHealthError as err:
            _LOGGER.warning("Histórico %s interrompido: %s", stat.key, err)
        if rows:
            async_add_external_statistics(
                hass, _meta(stat.key, stat.name, stat.unit, stat.unit_class, True), rows
            )
        written[stat.key] = len(rows)

    # FC: média/mín/máx por hora
    sid, last = f"{DOMAIN}:frequencia_cardiaca", await _last(hass, f"{DOMAIN}:frequencia_cardiaca")
    cursor = dt_util.utc_from_timestamp(last["start"]) if last else first
    samples: list[tuple[datetime, float, float, float]] = []
    while cursor < now:
        end = min(cursor + CHUNK, now + timedelta(hours=1))
        for p in await safe(client.rollup("heart-rate", cursor, end), []):
            hr = p.get("heartRate") or {}
            if (start := ts(p.get("startTime"))) and (avg := num(hr.get("beatsPerMinuteAvg"))):
                samples.append((start, avg, num(hr.get("beatsPerMinuteMin")) or avg,
                                num(hr.get("beatsPerMinuteMax")) or avg))
        cursor = end
    if rows := mean_rows(samples):
        async_add_external_statistics(
            hass, _meta("frequencia_cardiaca", "Frequência cardíaca", "bpm", None, False), rows
        )
    written["frequencia_cardiaca"] = len(rows)

    tz = dt_util.get_default_time_zone()
    for stat in POINTS:
        sid = f"{DOMAIN}:{stat.key}"
        last = await _last(hass, sid)
        since = dt_util.utc_from_timestamp(last["start"]) if last else first
        page = 25 if stat.data_type == "sleep" else 1000
        pts = await safe(
            client.list_points(stat.data_type, page_size=page,
                               flt=time_filter(stat.data_type, dt_util.as_local(since), None),
                               max_pages=100),
            [],
        )
        samples = [
            (m, v, v, v)
            for p in pts
            if (m := point_moment(p, tz)) and (v := stat.value(body(p))) is not None
        ]
        if rows := mean_rows(samples):
            async_add_external_statistics(
                hass, _meta(stat.key, stat.name, stat.unit, None, False), rows
            )
        written[stat.key] = len(rows)

    _LOGGER.debug("Histórico Google Health: %s", written)
    return written
