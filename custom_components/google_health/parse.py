"""Leitura dos JSONs da API (funções puras, sem Home Assistant — testáveis)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

META_KEYS = ("name", "dataSource")


def num(value: Any) -> float | None:
    """'111' / 111 / 1.5 -> float; lixo -> None (a API manda int64 como string)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def secs(value: Any) -> float | None:
    """Duração protobuf '1828.36s' -> segundos."""
    if isinstance(value, str) and value.endswith("s"):
        return num(value[:-1])
    return num(value)


def ts(value: Any) -> datetime | None:
    """RFC 3339 -> datetime UTC."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def gdate(value: Any) -> date | None:
    """{'year','month','day'} (Date ou CivilDateTime) -> date."""
    if isinstance(value, dict) and "date" in value:
        value = value["date"]
    try:
        return date(value["year"], value["month"], value["day"])
    except (KeyError, TypeError, ValueError):
        return None


def body(dp: dict[str, Any] | None) -> dict[str, Any]:
    """Conteúdo do data point (o campo cujo nome é o tipo: 'steps', 'sleep'...)."""
    if not dp:
        return {}
    for key, value in dp.items():
        if key not in META_KEYS and isinstance(value, dict):
            return value
    return {}


def when(dp: dict[str, Any] | None) -> datetime | None:
    """Momento de referência do data point (fim da sessão, amostra ou dia)."""
    b = body(dp)
    interval = b.get("interval") or {}
    sample = b.get("sampleTime") or {}
    if moment := ts(interval.get("endTime")) or ts(sample.get("physicalTime")):
        return moment
    if d := gdate(b.get("date")):
        return datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
    return None


def source(dp: dict[str, Any] | None) -> str | None:
    """Origem legível: 'Apple Watch (HEALTH_KIT)'."""
    src = (dp or {}).get("dataSource") or {}
    dev = (src.get("device") or {}).get("displayName")
    app = (src.get("application") or {}).get("packageName")
    plat = src.get("platform")
    label = dev or app
    return f"{label} ({plat})" if label and plat else (label or plat)


# -- rollups diários ----------------------------------------------------------


def rollup_days(points: list[dict[str, Any]] | None) -> dict[date, dict[str, Any]]:
    """dailyRollUp -> {dia: valor}. O valor é o único campo além das datas."""
    out: dict[date, dict[str, Any]] = {}
    for p in points or []:
        d = gdate(p.get("civilStartTime"))
        val = next(
            (v for k, v in p.items() if k not in ("civilStartTime", "civilEndTime")),
            None,
        )
        if d and isinstance(val, dict):
            out[d] = val
    return out


def by_zone(items: list[dict] | None, zone_key: str, value_key: str) -> dict[str, float]:
    """[{heartRateZone: 'PEAK', duration: '60s'}] -> {'PEAK': 60.0}."""
    out: dict[str, float] = {}
    for item in items or []:
        raw = item.get(value_key)
        val = secs(raw) if isinstance(raw, str) and raw.endswith("s") else num(raw)
        if (zone := item.get(zone_key)) and val is not None:
            out[zone] = out.get(zone, 0.0) + val
    return out


def nutrient(rollup: dict[str, Any] | None, name: str) -> float | None:
    """Gramas de um nutriente (PROTEIN, DIETARY_FIBER...) no rollup do dia."""
    for item in (rollup or {}).get("nutrients", []):
        if item.get("nutrient") == name:
            return num((item.get("quantity") or {}).get("gramsSum"))
    return None


# -- sono ---------------------------------------------------------------------


def stage_minutes(sleep: dict[str, Any], stage: str) -> float | None:
    """Minutos num estágio (DEEP/LIGHT/REM/AWAKE) pelo resumo do sono."""
    for item in (sleep.get("summary") or {}).get("stagesSummary", []):
        if item.get("type") == stage:
            return num(item.get("minutes"))
    return None


def stage_count(sleep: dict[str, Any], stage: str) -> float | None:
    for item in (sleep.get("summary") or {}).get("stagesSummary", []):
        if item.get("type") == stage:
            return num(item.get("count"))
    return None


def main_sleep(points: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Sessão de sono principal mais recente que já tem resumo (ignora cochilos)."""
    with_summary = [p for p in points or [] if body(p).get("summary")]
    for p in with_summary:
        meta = body(p).get("metadata") or {}
        if meta.get("mainSleep") or not meta.get("nap"):
            return p
    return with_summary[0] if with_summary else None


def sleep_efficiency(sleep: dict[str, Any]) -> float | None:
    """Minutos dormindo / minutos no período de sono × 100."""
    s = sleep.get("summary") or {}
    asleep, period = num(s.get("minutesAsleep")), num(s.get("minutesInSleepPeriod"))
    if asleep is None or not period:
        return None
    return round(asleep / period * 100, 1)


def sleep_avg(points: list[dict[str, Any]] | None, days: int = 7) -> float | None:
    """Média de minutos dormindo nas noites (principais) dos últimos `days` dias
    contados a partir da noite mais recente."""
    nights = [
        p
        for p in points or []
        if body(p).get("summary") and not (body(p).get("metadata") or {}).get("nap")
    ]
    if not nights:
        return None
    last = when(nights[0])
    vals = [
        num(body(p)["summary"].get("minutesAsleep"))
        for p in nights
        if last and when(p) and last - when(p) < timedelta(days=days)
    ]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


# -- exercício ----------------------------------------------------------------


def exercise_minutes(ex: dict[str, Any]) -> float | None:
    if (s := secs(ex.get("activeDuration"))) is not None:
        return round(s / 60, 1)
    i = ex.get("interval") or {}
    start, end = ts(i.get("startTime")), ts(i.get("endTime"))
    return round((end - start).total_seconds() / 60, 1) if start and end else None


def exercises_since(points: list[dict] | None, since: datetime) -> list[dict]:
    return [
        body(p)
        for p in points or []
        if (s := ts((body(p).get("interval") or {}).get("startTime"))) and s >= since
    ]


def overlap(ex: dict[str, Any], start: datetime, end: datetime) -> float:
    """Fração de [start, end) coberta pela sessão `ex`."""
    i = ex.get("interval") or {}
    a, b = ts(i.get("startTime")), ts(i.get("endTime"))
    if not a or not b or end <= start:
        return 0.0
    inter = (min(b, end) - max(a, start)).total_seconds()
    return max(inter, 0.0) / (end - start).total_seconds()


def bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    if not weight_kg or not height_cm:
        return None
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def newest(*moments: datetime | None) -> datetime | None:
    vals = [m for m in moments if m]
    return max(vals) if vals else None


# -- escrita (corpo dos data points criados pelos serviços) -------------------


def _rfc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _offset(moment: datetime) -> str:
    off = moment.utcoffset() or timedelta(0)
    return f"{int(off.total_seconds())}s"


def sample_time(moment: datetime) -> dict[str, str]:
    """`moment` precisa ter fuso (aware)."""
    return {"physicalTime": _rfc(moment), "utcOffset": _offset(moment)}


def session_interval(start: datetime, end: datetime) -> dict[str, str]:
    return {
        "startTime": _rfc(start),
        "startUtcOffset": _offset(start),
        "endTime": _rfc(end),
        "endUtcOffset": _offset(end),
    }


def weight_point(kg: float, moment: datetime) -> dict[str, Any]:
    return {"sampleTime": sample_time(moment), "weightGrams": round(kg * 1000)}


def body_fat_point(percent: float, moment: datetime) -> dict[str, Any]:
    return {"sampleTime": sample_time(moment), "percentage": percent}


def hydration_point(ml: float, moment: datetime) -> dict[str, Any]:
    return {
        "interval": session_interval(moment, moment + timedelta(minutes=1)),
        "amountConsumed": {"milliliters": ml, "userProvidedUnit": "MILLILITER"},
    }


def nutrition_point(
    name: str,
    moment: datetime,
    kcal: float | None = None,
    meal: str | None = None,
    carbs_g: float | None = None,
    fat_g: float | None = None,
    protein_g: float | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "interval": session_interval(moment, moment + timedelta(minutes=1)),
        "foodDisplayName": name,
        "mealType": meal or "ANYTIME",
    }
    if kcal is not None:
        out["energy"] = {"kcal": kcal, "userProvidedUnit": "KILOCALORIE"}
    if carbs_g is not None:
        out["totalCarbohydrate"] = {"grams": carbs_g, "userProvidedUnit": "GRAM"}
    if fat_g is not None:
        out["totalFat"] = {"grams": fat_g, "userProvidedUnit": "GRAM"}
    if protein_g is not None:
        out["nutrients"] = [
            {"nutrient": "PROTEIN", "quantity": {"grams": protein_g, "userProvidedUnit": "GRAM"}}
        ]
    return out


def exercise_point(
    exercise_type: str,
    start: datetime,
    minutes: float,
    name: str | None = None,
    kcal: float | None = None,
    km: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    end = start + timedelta(minutes=minutes)
    summary: dict[str, Any] = {}
    if kcal is not None:
        summary["caloriesKcal"] = kcal
    if km is not None:
        summary["distanceMillimeters"] = km * 1_000_000
    out: dict[str, Any] = {
        "interval": session_interval(start, end),
        "exerciseType": exercise_type,
        "displayName": name or exercise_type.replace("_", " ").title(),
        "activeDuration": f"{int(minutes * 60)}s",
        "metricsSummary": summary,
    }
    if notes:
        out["notes"] = notes
    return out


# Campo de filtro (AIP-160) por tipo, para o serviço buscar_dados.
_INTERVAL = {
    "steps", "distance", "active-energy-burned", "basal-energy-burned", "floors",
    "altitude", "active-minutes", "active-zone-minutes", "sedentary-period",
    "swim-lengths-data", "activity-level", "time-in-heart-rate-zone", "electrocardiogram",
}
_CIVIL = {"exercise", "irregular-rhythm-notification", "hydration-log", "nutrition-log", "food"}
_DAILY = {
    "daily-vo2-max", "daily-heart-rate-zones", "daily-resting-heart-rate",
    "daily-heart-rate-variability", "daily-oxygen-saturation",
    "daily-respiratory-rate", "daily-sleep-temperature-derivations",
}


def time_filter(data_type: str, start: datetime | None, end: datetime | None) -> str | None:
    """Filtro de intervalo de tempo com o campo certo para cada tipo."""
    snake = data_type.replace("-", "_")
    if data_type == "sleep":
        field, fmt = "sleep.interval.end_time", "rfc"
    elif data_type in _CIVIL:
        field, fmt = f"{snake}.interval.civil_start_time", "civil"
    elif data_type in _DAILY:
        field, fmt = f"{snake}.date", "date"
    elif data_type in _INTERVAL:
        field, fmt = f"{snake}.interval.start_time", "rfc"
    else:
        field, fmt = f"{snake}.sample_time.physical_time", "rfc"

    def lit(moment: datetime) -> str:
        if fmt == "rfc":
            return _rfc(moment)
        if fmt == "date":
            return moment.strftime("%Y-%m-%d")
        return moment.strftime("%Y-%m-%dT%H:%M:%S")

    parts = []
    if start:
        parts.append(f'{field} >= "{lit(start)}"')
    if end and data_type != "electrocardiogram":  # ECG só aceita início
        parts.append(f'{field} < "{lit(end)}"')
    return " AND ".join(parts) or None


# -- estatísticas de longo prazo (histórico no HA) ----------------------------


def hour_floor(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def sum_rows(points: list[dict], value_fn, base: float = 0.0) -> list[dict[str, Any]]:
    """rollUp por hora → linhas {start, state, sum} com soma acumulada a partir de `base`."""
    hours: dict[datetime, float] = {}
    for p in points or []:
        start = ts(p.get("startTime"))
        val = next((v for k, v in p.items() if k not in ("startTime", "endTime")), None)
        if start and isinstance(val, dict) and (v := value_fn(val)) is not None:
            hours[hour_floor(start)] = hours.get(hour_floor(start), 0.0) + v
    rows, total = [], base
    for start in sorted(hours):
        total += hours[start]
        rows.append({"start": start, "state": hours[start], "sum": round(total, 3)})
    return rows


def mean_rows(samples: list[tuple[datetime, float, float, float]]) -> list[dict[str, Any]]:
    """[(momento, média, mín, máx)] → uma linha por hora (média das médias)."""
    hours: dict[datetime, list[tuple[float, float, float]]] = {}
    for moment, avg, lo, hi in samples:
        hours.setdefault(hour_floor(moment), []).append((avg, lo, hi))
    return [
        {
            "start": h,
            "mean": round(sum(v[0] for v in vals) / len(vals), 2),
            "min": min(v[1] for v in vals),
            "max": max(v[2] for v in vals),
        }
        for h, vals in sorted(hours.items())
    ]


def point_moment(dp: dict[str, Any], tz) -> datetime | None:
    """Momento de um data point para o histórico: amostra, fim da sessão ou dia (00:00 local)."""
    b = body(dp)
    if d := gdate(b.get("date")):
        return datetime(d.year, d.month, d.day, tzinfo=tz)
    return when(dp)
