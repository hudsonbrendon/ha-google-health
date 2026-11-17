"""Calendários de exercícios e de sono (histórico completo consultado sob demanda)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GoogleHealthConfigEntry
from .api import GoogleHealthError
from .const import DEV_EXERCISE, DEV_SLEEP
from .entity import GoogleHealthEntity
from .parse import body, exercise_minutes, num, sleep_efficiency, time_filter, ts
from .sensor import _ex_name

_LOGGER = logging.getLogger(__name__)


def _exercise_event(dp: dict[str, Any]) -> CalendarEvent | None:
    ex = body(dp)
    i = ex.get("interval") or {}
    start, end = ts(i.get("startTime")), ts(i.get("endTime"))
    if not start or not end:
        return None
    m = ex.get("metricsSummary") or {}
    lines = [
        f"Duração: {exercise_minutes(ex)} min",
        f"Calorias: {num(m.get('caloriesKcal'))} kcal" if m.get("caloriesKcal") else None,
        f"FC média: {m.get('averageHeartRateBeatsPerMinute')} bpm" if m.get("averageHeartRateBeatsPerMinute") else None,
        f"Distância: {num(m.get('distanceMillimeters')) / 1e6:.2f} km" if m.get("distanceMillimeters") else None,
        f"Passos: {m.get('steps')}" if m.get("steps") else None,
        ex.get("notes"),
    ]
    return CalendarEvent(
        start=start, end=end, summary=_ex_name(ex) or "Exercício",
        description="\n".join(x for x in lines if x), uid=dp.get("name"),
    )


def _sleep_event(dp: dict[str, Any]) -> CalendarEvent | None:
    s = body(dp)
    i = s.get("interval") or {}
    start, end = ts(i.get("startTime")), ts(i.get("endTime"))
    if not start or not end:
        return None
    summ = s.get("summary") or {}
    asleep = num(summ.get("minutesAsleep"))
    title = f"Sono {int(asleep // 60)}h{int(asleep % 60):02d}" if asleep else "Sono"
    if (s.get("metadata") or {}).get("nap"):
        title = title.replace("Sono", "Cochilo")
    stages = {x.get("type"): num(x.get("minutes")) for x in summ.get("stagesSummary", [])}
    lines = [
        f"Eficiência: {eff}%" if (eff := sleep_efficiency(s)) else None,
        *(f"{n}: {int(stages[k])} min" for k, n in
          (("DEEP", "Profundo"), ("LIGHT", "Leve"), ("REM", "REM"), ("AWAKE", "Acordado"))
          if stages.get(k) is not None),
    ]
    return CalendarEvent(
        start=start, end=end, summary=title,
        description="\n".join(x for x in lines if x), uid=dp.get("name"),
    )


class HealthCalendar(GoogleHealthEntity, CalendarEntity):
    def __init__(self, coordinator, device: str, key: str, name: str, dtype: str, fn) -> None:
        super().__init__(coordinator, device, key)
        self._attr_name = name
        self._dtype = dtype
        self._fn = fn

    @property
    def event(self) -> CalendarEvent | None:
        points = (self.coordinator.data or {}).get(self._dtype) or []
        return self._fn(points[0]) if points else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        client = self.coordinator.config_entry.runtime_data.client
        try:
            points = await client.list_points(
                self._dtype, page_size=25,
                flt=time_filter(self._dtype, start_date, end_date), max_pages=20,
            )
        except GoogleHealthError as err:
            _LOGGER.warning("Calendário %s: %s", self._dtype, err)
            return []
        return [e for p in points if (e := self._fn(p))]


async def async_setup_entry(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    slow = entry.runtime_data.coordinators["slow"]
    async_add_entities([
        HealthCalendar(slow, DEV_EXERCISE, "calendar_exercise", "Exercícios", "exercise", _exercise_event),
        HealthCalendar(slow, DEV_SLEEP, "calendar_sleep", "Sono", "sleep", _sleep_event),
    ])
