"""Sensores do Google Health (nomes em português)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import GoogleHealthConfigEntry
from .const import (
    DEV_ACCOUNT,
    DEV_ACTIVITY,
    DEV_BODY,
    DEV_EXERCISE,
    DEV_HEART,
    DEV_NUTRITION,
    DEV_SLEEP,
    DOMAIN,
    SCOPE_ECG,
    SCOPE_IRN,
)
from .entity import GoogleHealthEntity
from .parse import (
    bmi,
    body,
    by_zone,
    exercise_minutes,
    exercises_since,
    gdate,
    main_sleep,
    newest,
    num,
    nutrient,
    secs,
    sleep_avg,
    sleep_efficiency,
    source,
    stage_count,
    stage_minutes,
    ts,
    when,
)

PARALLEL_UPDATES = 0
BPM = "bpm"
MS = UnitOfTime.MILLISECONDS
RPM = "rpm"
VO2 = "mL/kg/min"

ZONES = {"LIGHT": "leve", "MODERATE": "moderada", "VIGOROUS": "intensa", "PEAK": "pico"}
AZM = {
    "sumInFatBurnHeartZone": "queima_de_gordura",
    "sumInCardioHeartZone": "cardio",
    "sumInPeakHeartZone": "pico",
}
FITNESS = {
    "POOR": "Ruim", "FAIR": "Regular", "AVERAGE": "Médio", "GOOD": "Bom",
    "VERY_GOOD": "Muito bom", "EXCELLENT": "Excelente",
}
ECG = {
    "NORMAL_SINUS_RHYTHM": "Ritmo sinusal normal",
    "ATRIAL_FIBRILLATION": "Fibrilação atrial",
    "INCONCLUSIVE": "Inconclusivo",
    "INCONCLUSIVE_HIGH_HEART_RATE": "Inconclusivo (FC alta)",
    "INCONCLUSIVE_LOW_HEART_RATE": "Inconclusivo (FC baixa)",
    "UNREADABLE": "Ilegível",
    "NOT_ANALYZED": "Não analisado",
}
MEALS = {
    "BEFORE_BREAKFAST": "Antes do café", "BREAKFAST": "Café da manhã",
    "BEFORE_LUNCH": "Antes do almoço", "LUNCH": "Almoço",
    "BEFORE_DINNER": "Antes do jantar", "DINNER": "Jantar",
    "AFTER_DINNER": "Depois do jantar", "SNACK": "Lanche", "ANYTIME": "Qualquer hora",
}
EXERCISES = {
    "WALKING": "Caminhada", "RUNNING": "Corrida", "BIKING": "Ciclismo",
    "OUTDOOR_BIKE": "Ciclismo ao ar livre", "STATIONARY_BIKE": "Bicicleta ergométrica",
    "SPINNING": "Spinning", "SWIMMING": "Natação", "SWIMMING_POOL": "Natação (piscina)",
    "STRENGTH_TRAINING": "Musculação", "WEIGHTS": "Musculação",
    "WEIGHTLIFTING": "Levantamento de peso", "FUNCTIONAL_STRENGTH_TRAINING": "Funcional",
    "HIIT": "HIIT", "YOGA": "Ioga", "PILATES": "Pilates", "ELLIPTICAL": "Elíptico",
    "TREADMILL": "Esteira", "TREADMILL_WALK": "Caminhada na esteira", "HIKING": "Trilha",
    "SOCCER": "Futebol", "DANCING": "Dança", "CROSSFIT": "CrossFit",
    "STRETCHING": "Alongamento", "ROWING_MACHINE": "Remo ergométrico",
    "WORKOUT": "Treino", "CARDIO_WORKOUT": "Cardio", "CORE_TRAINING": "Core",
    "MEDITATE": "Meditação", "TENNIS": "Tênis", "BOXING": "Boxe", "OTHER": "Outro",
}


def _br(moment: datetime | date | None) -> str | None:
    if moment is None:
        return None
    if isinstance(moment, datetime):
        return dt_util.as_local(moment).strftime("%d/%m/%Y %H:%M")
    return moment.strftime("%d/%m/%Y")


def _today() -> date:
    return dt_util.now().date()


def _roll(data: dict, dtype: str, day: date | None = None) -> dict[str, Any]:
    return (data.get("roll", {}).get(dtype) or {}).get(day or _today()) or {}


def _days(data: dict, dtype: str, fn: Callable[[dict], Any]) -> dict[str, Any]:
    """Atributo 'últimos 7 dias' {dd/mm: valor}."""
    days = data.get("roll", {}).get(dtype) or {}
    return {d.strftime("%d/%m"): fn(v) for d, v in sorted(days.items())}


def _dp(data: dict, dtype: str) -> dict | None:
    return data.get("last", {}).get(dtype)


def _last(data: dict, dtype: str) -> dict[str, Any]:
    return body(_dp(data, dtype))


def _measured(dtype: str) -> Callable[[dict], dict[str, Any]]:
    def attrs(data: dict) -> dict[str, Any]:
        dp = _dp(data, dtype)
        b = body(dp)
        d = gdate(b.get("date"))
        return {"medido_em": _br(d) if d else _br(when(dp)), "fonte": source(dp)}

    return attrs


def _sum_list(items: list | None, key: str) -> float | None:
    vals = [num(i.get(key)) for i in items or []]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _round(v: float | None, nd: int = 1) -> float | int | None:
    if v is None:
        return None
    return round(v) if nd == 0 else round(v, nd)


@dataclass(frozen=True, kw_only=True)
class GHSensorDescription(SensorEntityDescription):
    device: str
    group: str
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _d(key: str, name: str, device: str, group: str, value_fn, **kw) -> GHSensorDescription:
    return GHSensorDescription(
        key=key, name=name, device=device, group=group, value_fn=value_fn, **kw
    )


KCAL = {"native_unit_of_measurement": UnitOfEnergy.KILO_CALORIE, "device_class": SensorDeviceClass.ENERGY}
DAILY_KCAL = {**KCAL, "state_class": SensorStateClass.TOTAL_INCREASING}
MIN = {"native_unit_of_measurement": UnitOfTime.MINUTES, "device_class": SensorDeviceClass.DURATION}
MEAS = {"state_class": SensorStateClass.MEASUREMENT}
GRAM = {"native_unit_of_measurement": UnitOfMass.GRAMS, "device_class": SensorDeviceClass.WEIGHT, **MEAS}


# -- Atividade (hoje) ---------------------------------------------------------

def _steps(v: dict) -> int:
    return int(num(v.get("countSum")) or 0)


def _steps_avg(data: dict) -> float | None:
    days = data.get("roll", {}).get("steps") or {}
    vals = [_steps(v) for d, v in days.items() if d != _today()]
    return round(sum(vals) / 6) if days else None


def _active_minutes(v: dict) -> dict[str, float]:
    return {
        ZONES.get(i.get("activityLevel"), i.get("activityLevel")): num(i.get("activeMinutesSum")) or 0
        for i in v.get("activeMinutesRollupByActivityLevel", [])
    }


def _zone_minutes(v: dict) -> dict[str, float]:
    z = by_zone(v.get("timeInHeartRateZones"), "heartRateZone", "duration")
    return {ZONES.get(k, k): round(s / 60) for k, s in z.items()}


ACTIVITY = [
    _d("steps", "Passos", DEV_ACTIVITY, "fast", lambda d: _steps(_roll(d, "steps")),
       native_unit_of_measurement="passos", icon="mdi:shoe-print",
       state_class=SensorStateClass.TOTAL_INCREASING,
       attrs_fn=lambda d: {"ultimos_7_dias": _days(d, "steps", _steps)}),
    _d("steps_yesterday", "Passos ontem", DEV_ACTIVITY, "fast",
       lambda d: _steps(_roll(d, "steps", _today() - timedelta(days=1))),
       native_unit_of_measurement="passos", icon="mdi:shoe-print", **MEAS),
    _d("steps_avg_7d", "Média de passos (7 dias)", DEV_ACTIVITY, "fast", _steps_avg,
       native_unit_of_measurement="passos", icon="mdi:chart-line", **MEAS),
    _d("distance", "Distância", DEV_ACTIVITY, "fast",
       lambda d: (num(_roll(d, "distance").get("millimetersSum")) or 0) / 1000,
       native_unit_of_measurement=UnitOfLength.METERS,
       suggested_unit_of_measurement=UnitOfLength.KILOMETERS,
       suggested_display_precision=2, device_class=SensorDeviceClass.DISTANCE,
       state_class=SensorStateClass.TOTAL_INCREASING),
    _d("active_calories", "Calorias ativas", DEV_ACTIVITY, "fast",
       lambda d: _round(num(_roll(d, "active-energy-burned").get("kcalSum")) or 0, 0), **DAILY_KCAL),
    _d("total_calories", "Calorias totais", DEV_ACTIVITY, "fast",
       lambda d: _round(num(_roll(d, "total-calories").get("kcalSum")) or 0, 0), **DAILY_KCAL),
    _d("basal_calories", "Calorias basais", DEV_ACTIVITY, "fast",
       lambda d: _round(
           (num(_roll(d, "total-calories").get("kcalSum")) or 0)
           - (num(_roll(d, "active-energy-burned").get("kcalSum")) or 0), 0),
       **DAILY_KCAL),
    _d("floors", "Andares", DEV_ACTIVITY, "fast",
       lambda d: int(num(_roll(d, "floors").get("countSum")) or 0),
       native_unit_of_measurement="andares", icon="mdi:stairs-up",
       state_class=SensorStateClass.TOTAL_INCREASING),
    _d("elevation", "Elevação", DEV_ACTIVITY, "fast",
       lambda d: (num(_roll(d, "altitude").get("gainMillimetersSum")) or 0) / 1000,
       native_unit_of_measurement=UnitOfLength.METERS, device_class=SensorDeviceClass.DISTANCE,
       icon="mdi:elevation-rise", state_class=SensorStateClass.TOTAL_INCREASING),
    _d("active_minutes", "Minutos ativos", DEV_ACTIVITY, "fast",
       lambda d: sum(_active_minutes(_roll(d, "active-minutes")).values()),
       **MIN, icon="mdi:run", state_class=SensorStateClass.TOTAL_INCREASING,
       attrs_fn=lambda d: _active_minutes(_roll(d, "active-minutes"))),
    _d("active_zone_minutes", "Minutos em zona ativa", DEV_ACTIVITY, "fast",
       lambda d: sum(num(_roll(d, "active-zone-minutes").get(k)) or 0 for k in AZM),
       **MIN, icon="mdi:heart-flash", state_class=SensorStateClass.TOTAL_INCREASING,
       attrs_fn=lambda d: {v: num(_roll(d, "active-zone-minutes").get(k)) or 0 for k, v in AZM.items()}),
    _d("sedentary_time", "Tempo sedentário", DEV_ACTIVITY, "fast",
       lambda d: round((secs(_roll(d, "sedentary-period").get("durationSum")) or 0) / 60),
       **MIN, icon="mdi:sofa", state_class=SensorStateClass.TOTAL_INCREASING),
    _d("heart_zone_minutes", "Tempo em zonas de FC", DEV_ACTIVITY, "fast",
       lambda d: sum(v for k, v in _zone_minutes(_roll(d, "time-in-heart-rate-zone")).items() if k != "leve"),
       **MIN, icon="mdi:heart-pulse", state_class=SensorStateClass.TOTAL_INCREASING,
       attrs_fn=lambda d: _zone_minutes(_roll(d, "time-in-heart-rate-zone"))),
    _d("heart_zone_calories", "Calorias em zonas de FC", DEV_ACTIVITY, "fast",
       lambda d: _round(sum(by_zone(_roll(d, "calories-in-heart-rate-zone").get("caloriesInHeartRateZones"), "heartRateZone", "kcal").values()), 0),
       **DAILY_KCAL,
       attrs_fn=lambda d: {ZONES.get(k, k): round(v) for k, v in by_zone(
           _roll(d, "calories-in-heart-rate-zone").get("caloriesInHeartRateZones"), "heartRateZone", "kcal").items()}),
]

# -- Coração --------------------------------------------------------------------

HEART = [
    _d("heart_rate", "Frequência cardíaca", DEV_HEART, "fast",
       lambda d: num(_last(d, "heart-rate").get("beatsPerMinute")),
       native_unit_of_measurement=BPM, icon="mdi:heart-pulse", **MEAS,
       attrs_fn=lambda d: {**_measured("heart-rate")(d),
                           "contexto": (_last(d, "heart-rate").get("metadata") or {}).get("motionContext")}),
    _d("heart_rate_avg_today", "FC média hoje", DEV_HEART, "fast",
       lambda d: _round(num(_roll(d, "heart-rate").get("beatsPerMinuteAvg")), 0),
       native_unit_of_measurement=BPM, icon="mdi:heart", **MEAS,
       attrs_fn=lambda d: {"minima": num(_roll(d, "heart-rate").get("beatsPerMinuteMin")),
                           "maxima": num(_roll(d, "heart-rate").get("beatsPerMinuteMax"))}),
    _d("resting_heart_rate", "FC em repouso", DEV_HEART, "fast",
       lambda d: num(_last(d, "daily-resting-heart-rate").get("beatsPerMinute")),
       native_unit_of_measurement=BPM, icon="mdi:heart", **MEAS,
       attrs_fn=_measured("daily-resting-heart-rate")),
    _d("hrv", "Variabilidade da FC", DEV_HEART, "fast",
       lambda d: _round(num(_last(d, "daily-heart-rate-variability").get("averageHeartRateVariabilityMilliseconds"))),
       native_unit_of_measurement=MS, icon="mdi:heart-settings", **MEAS,
       attrs_fn=lambda d: {**_measured("daily-heart-rate-variability")(d),
                           "rmssd_sono_profundo_ms": _round(num(_last(d, "daily-heart-rate-variability").get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds"))),
                           "fc_nao_rem": num(_last(d, "daily-heart-rate-variability").get("nonRemHeartRateBeatsPerMinute")),
                           "entropia": _round(num(_last(d, "daily-heart-rate-variability").get("entropy")), 2)}),
    _d("hrv_last", "Variabilidade da FC (última medição)", DEV_HEART, "fast",
       lambda d: _round(num(_last(d, "heart-rate-variability").get("rootMeanSquareOfSuccessiveDifferencesMilliseconds"))),
       native_unit_of_measurement=MS, icon="mdi:heart-settings-outline", **MEAS,
       attrs_fn=lambda d: {**_measured("heart-rate-variability")(d),
                           "sdnn_ms": _round(num(_last(d, "heart-rate-variability").get("standardDeviationMilliseconds")))}),
    _d("spo2", "Oxigenação do sangue (SpO2)", DEV_HEART, "fast",
       lambda d: _round(num(_last(d, "daily-oxygen-saturation").get("averagePercentage"))),
       native_unit_of_measurement=PERCENTAGE, icon="mdi:water-percent", **MEAS,
       attrs_fn=lambda d: {**_measured("daily-oxygen-saturation")(d),
                           "minima": num(_last(d, "daily-oxygen-saturation").get("lowerBoundPercentage")),
                           "maxima": num(_last(d, "daily-oxygen-saturation").get("upperBoundPercentage"))}),
    _d("spo2_last", "SpO2 (última medição)", DEV_HEART, "fast",
       lambda d: num(_last(d, "oxygen-saturation").get("percentage")),
       native_unit_of_measurement=PERCENTAGE, icon="mdi:water-percent", **MEAS,
       attrs_fn=_measured("oxygen-saturation")),
    _d("respiratory_rate", "Frequência respiratória", DEV_HEART, "fast",
       lambda d: _round(num(_last(d, "daily-respiratory-rate").get("breathsPerMinute"))),
       native_unit_of_measurement=RPM, icon="mdi:lungs", **MEAS,
       attrs_fn=_measured("daily-respiratory-rate")),
    _d("vo2_max", "VO2 máx (condicionamento cardio)", DEV_HEART, "fast",
       lambda d: _round(num(_last(d, "daily-vo2-max").get("vo2Max")) or num(_last(d, "vo2-max").get("vo2Max"))),
       native_unit_of_measurement=VO2, icon="mdi:run-fast", **MEAS,
       attrs_fn=lambda d: {**_measured("daily-vo2-max")(d),
                           "nivel": FITNESS.get(_last(d, "daily-vo2-max").get("cardioFitnessLevel")),
                           "estimado": _last(d, "daily-vo2-max").get("estimated")}),
    _d("run_vo2_max", "VO2 máx de corrida", DEV_HEART, "fast",
       lambda d: _round(num(_last(d, "run-vo2-max").get("runVo2Max"))),
       native_unit_of_measurement=VO2, icon="mdi:run", **MEAS, attrs_fn=_measured("run-vo2-max")),
    _d("heart_zones", "Zonas de FC", DEV_HEART, "fast",
       lambda d: next((f"{z.get('minBeatsPerMinute')}–{z.get('maxBeatsPerMinute')}"
                       for z in _last(d, "daily-heart-rate-zones").get("heartRateZones", [])
                       if z.get("heartRateZoneType") == "MODERATE"), None),
       icon="mdi:heart-cog", entity_category=EntityCategory.DIAGNOSTIC,
       attrs_fn=lambda d: {ZONES.get(z.get("heartRateZoneType"), z.get("heartRateZoneType")):
                           f"{z.get('minBeatsPerMinute')}–{z.get('maxBeatsPerMinute')} bpm"
                           for z in _last(d, "daily-heart-rate-zones").get("heartRateZones", [])}),
    _d("ecg", "Último ECG", DEV_HEART, "fast",
       lambda d: ECG.get(_last(d, "electrocardiogram").get("resultClassification")),
       icon="mdi:heart-box",
       attrs_fn=lambda d: {**_measured("electrocardiogram")(d),
                           "fc_media": num(_last(d, "electrocardiogram").get("beatsPerMinuteAvg")),
                           "derivacao": _last(d, "electrocardiogram").get("leadNumber")}),
    _d("irn", "Alerta de ritmo irregular", DEV_HEART, "fast",
       lambda d: when(_dp(d, "irregular-rhythm-notification")),
       device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:heart-broken",
       attrs_fn=lambda d: {"janelas_positivas": sum(
           1 for w in _last(d, "irregular-rhythm-notification").get("alertWindows", []) if w.get("positive"))}),
]

# -- Corpo ----------------------------------------------------------------------


def _weight(d: dict) -> float | None:
    g = num(_last(d, "weight").get("weightGrams"))
    return round(g / 1000, 2) if g else None


def _height(d: dict) -> float | None:
    mm = num(_last(d, "height").get("heightMillimeters"))
    return round(mm / 10, 1) if mm else None


BODY = [
    _d("weight", "Peso", DEV_BODY, "slow", _weight,
       native_unit_of_measurement=UnitOfMass.KILOGRAMS, device_class=SensorDeviceClass.WEIGHT, **MEAS,
       attrs_fn=lambda d: {**_measured("weight")(d), "notas": _last(d, "weight").get("notes")}),
    _d("height", "Altura", DEV_BODY, "slow", _height,
       native_unit_of_measurement=UnitOfLength.CENTIMETERS, device_class=SensorDeviceClass.DISTANCE,
       icon="mdi:human-male-height", **MEAS, attrs_fn=_measured("height")),
    _d("bmi", "IMC", DEV_BODY, "slow", lambda d: bmi(_weight(d), _height(d)),
       native_unit_of_measurement="kg/m²", icon="mdi:human", **MEAS),
    _d("body_fat", "Gordura corporal", DEV_BODY, "slow",
       lambda d: _round(num(_last(d, "body-fat").get("percentage"))),
       native_unit_of_measurement=PERCENTAGE, icon="mdi:scale-bathroom", **MEAS,
       attrs_fn=_measured("body-fat")),
    _d("body_temperature", "Temperatura corporal", DEV_BODY, "slow",
       lambda d: _round(num(_last(d, "core-body-temperature").get("temperatureCelsius"))),
       native_unit_of_measurement=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE, **MEAS,
       attrs_fn=lambda d: {**_measured("core-body-temperature")(d),
                           "local": _last(d, "core-body-temperature").get("measurementLocation")}),
    _d("skin_temperature_variation", "Variação da temperatura da pele (sono)", DEV_BODY, "slow",
       lambda d: _round(
           num(_last(d, "daily-sleep-temperature-derivations").get("nightlyTemperatureCelsius")) - b
           if (b := num(_last(d, "daily-sleep-temperature-derivations").get("baselineTemperatureCelsius"))) is not None
           and num(_last(d, "daily-sleep-temperature-derivations").get("nightlyTemperatureCelsius")) is not None
           else None, 2),
       native_unit_of_measurement=UnitOfTemperature.CELSIUS, icon="mdi:thermometer-lines", **MEAS,
       attrs_fn=lambda d: {**_measured("daily-sleep-temperature-derivations")(d),
                           "noite_c": num(_last(d, "daily-sleep-temperature-derivations").get("nightlyTemperatureCelsius")),
                           "referencia_c": num(_last(d, "daily-sleep-temperature-derivations").get("baselineTemperatureCelsius"))}),
    _d("blood_glucose", "Glicose", DEV_BODY, "slow",
       lambda d: _round(num(_last(d, "blood-glucose").get("bloodGlucoseMilligramsPerDeciliter")), 0),
       native_unit_of_measurement="mg/dL", icon="mdi:diabetes", **MEAS,
       attrs_fn=lambda d: {**_measured("blood-glucose")(d),
                           "momento": _last(d, "blood-glucose").get("measurementTiming"),
                           "amostra": _last(d, "blood-glucose").get("specimen")}),
]

# -- Sono -----------------------------------------------------------------------


def _sleep(d: dict) -> dict[str, Any]:
    return body(main_sleep(d.get("sleep")))


def _summary(key: str) -> Callable[[dict], float | None]:
    return lambda d: num((_sleep(d).get("summary") or {}).get(key))


def _sleep_attrs(d: dict) -> dict[str, Any]:
    s = _sleep(d)
    i = s.get("interval") or {}
    return {
        "inicio": _br(ts(i.get("startTime"))),
        "fim": _br(ts(i.get("endTime"))),
        "tipo": s.get("type"),
        "fonte": source(main_sleep(d.get("sleep"))),
    }


def _resp_sleep(d: dict) -> dict[str, Any]:
    return _last(d, "respiratory-rate-sleep-summary")


DUR_H = {**MIN, "suggested_unit_of_measurement": UnitOfTime.HOURS, **MEAS}
SLEEP = [
    _d("sleep_asleep", "Tempo dormindo", DEV_SLEEP, "slow", _summary("minutesAsleep"),
       icon="mdi:sleep", **DUR_H, attrs_fn=_sleep_attrs),
    _d("sleep_in_bed", "Tempo na cama", DEV_SLEEP, "slow", _summary("minutesInSleepPeriod"),
       icon="mdi:bed", **DUR_H),
    _d("sleep_awake", "Tempo acordado", DEV_SLEEP, "slow", _summary("minutesAwake"),
       icon="mdi:eye", **MIN, **MEAS),
    _d("sleep_to_fall_asleep", "Tempo para adormecer", DEV_SLEEP, "slow",
       _summary("minutesToFallAsleep"), icon="mdi:bed-clock", **MIN, **MEAS),
    _d("sleep_after_wakeup", "Tempo na cama após acordar", DEV_SLEEP, "slow",
       _summary("minutesAfterWakeUp"), icon="mdi:alarm", **MIN, **MEAS),
    _d("sleep_deep", "Sono profundo", DEV_SLEEP, "slow", lambda d: stage_minutes(_sleep(d), "DEEP"),
       icon="mdi:power-sleep", **MIN, **MEAS),
    _d("sleep_light", "Sono leve", DEV_SLEEP, "slow", lambda d: stage_minutes(_sleep(d), "LIGHT"),
       icon="mdi:weather-night", **MIN, **MEAS),
    _d("sleep_rem", "Sono REM", DEV_SLEEP, "slow", lambda d: stage_minutes(_sleep(d), "REM"),
       icon="mdi:eye-refresh", **MIN, **MEAS),
    _d("sleep_awakenings", "Despertares", DEV_SLEEP, "slow",
       lambda d: stage_count(_sleep(d), "AWAKE"), icon="mdi:alarm-light", **MEAS),
    _d("sleep_efficiency", "Eficiência do sono", DEV_SLEEP, "slow",
       lambda d: sleep_efficiency(_sleep(d)), native_unit_of_measurement=PERCENTAGE,
       icon="mdi:percent", **MEAS),
    _d("sleep_start", "Início do sono", DEV_SLEEP, "slow",
       lambda d: ts((_sleep(d).get("interval") or {}).get("startTime")),
       device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:bed-clock"),
    _d("sleep_end", "Fim do sono", DEV_SLEEP, "slow",
       lambda d: ts((_sleep(d).get("interval") or {}).get("endTime")),
       device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:weather-sunset-up"),
    _d("sleep_avg_7d", "Média de sono (7 noites)", DEV_SLEEP, "slow",
       lambda d: sleep_avg(d.get("sleep")), icon="mdi:chart-bell-curve", **DUR_H),
    _d("sleep_respiratory_rate", "Respiração durante o sono", DEV_SLEEP, "slow",
       lambda d: _round(num((_resp_sleep(d).get("fullSleepStats") or {}).get("breathsPerMinute"))),
       native_unit_of_measurement=RPM, icon="mdi:lungs", **MEAS,
       attrs_fn=lambda d: {**_measured("respiratory-rate-sleep-summary")(d), **{
           f"{n}_rpm": _round(num((_resp_sleep(d).get(k) or {}).get("breathsPerMinute")))
           for k, n in (("deepSleepStats", "profundo"), ("lightSleepStats", "leve"), ("remSleepStats", "rem"))}}),
]

# -- Nutrição (hoje) ------------------------------------------------------------


def _nut(d: dict) -> dict[str, Any]:
    return _roll(d, "nutrition-log")


def _nutrient_g(name: str) -> Callable[[dict], float]:
    return lambda d: _round(nutrient(_nut(d), name) or 0)


NUTRITION = [
    _d("hydration", "Água ingerida", DEV_NUTRITION, "fast",
       lambda d: round((num((_roll(d, "hydration-log").get("amountConsumed") or {}).get("millilitersSum")) or 0) / 1000, 3),
       native_unit_of_measurement=UnitOfVolume.LITERS, device_class=SensorDeviceClass.VOLUME,
       state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:cup-water",
       attrs_fn=lambda d: {"ultimos_7_dias_ml": _days(d, "hydration-log", lambda v: num((v.get("amountConsumed") or {}).get("millilitersSum")))}),
    _d("calories_consumed", "Calorias consumidas", DEV_NUTRITION, "fast",
       lambda d: _round(num((_nut(d).get("energy") or {}).get("kcalSum")) or 0, 0), **DAILY_KCAL,
       attrs_fn=lambda d: {"ultimos_7_dias": _days(d, "nutrition-log", lambda v: _round(num((v.get("energy") or {}).get("kcalSum")), 0))}),
    _d("carbs", "Carboidratos", DEV_NUTRITION, "fast",
       lambda d: _round(num((_nut(d).get("totalCarbohydrate") or {}).get("gramsSum")) or 0),
       icon="mdi:bread-slice", **GRAM),
    _d("fat", "Gorduras", DEV_NUTRITION, "fast",
       lambda d: _round(num((_nut(d).get("totalFat") or {}).get("gramsSum")) or 0),
       icon="mdi:oil", **GRAM),
    _d("protein", "Proteínas", DEV_NUTRITION, "fast", _nutrient_g("PROTEIN"), icon="mdi:food-steak", **GRAM),
    _d("fiber", "Fibras", DEV_NUTRITION, "fast", _nutrient_g("DIETARY_FIBER"), icon="mdi:leaf", **GRAM),
    _d("sugar", "Açúcar", DEV_NUTRITION, "fast", _nutrient_g("SUGAR"), icon="mdi:spoon-sugar", **GRAM),
    _d("sodium", "Sódio", DEV_NUTRITION, "fast",
       lambda d: _round((nutrient(_nut(d), "SODIUM") or 0) * 1000, 0),
       native_unit_of_measurement=UnitOfMass.MILLIGRAMS, device_class=SensorDeviceClass.WEIGHT,
       icon="mdi:shaker", **MEAS),
    _d("caffeine", "Cafeína", DEV_NUTRITION, "fast",
       lambda d: _round((nutrient(_nut(d), "CAFFEINE") or 0) * 1000, 0),
       native_unit_of_measurement=UnitOfMass.MILLIGRAMS, device_class=SensorDeviceClass.WEIGHT,
       icon="mdi:coffee", **MEAS),
    _d("last_meal", "Última refeição", DEV_NUTRITION, "fast",
       lambda d: _last(d, "nutrition-log").get("foodDisplayName"), icon="mdi:silverware-fork-knife",
       attrs_fn=lambda d: {
           "horario": _br(ts((_last(d, "nutrition-log").get("interval") or {}).get("startTime"))),
           "refeicao": MEALS.get(_last(d, "nutrition-log").get("mealType")),
           "calorias": num((_last(d, "nutrition-log").get("energy") or {}).get("kcal"))}),
]

# -- Exercícios -----------------------------------------------------------------


def _ex(d: dict) -> dict[str, Any]:
    return body((d.get("exercise") or [None])[0])


def _ex_name(ex: dict) -> str | None:
    if not ex:
        return None
    t = ex.get("exerciseType", "")
    return EXERCISES.get(t) or ex.get("displayName") or t.replace("_", " ").title()


def _week(d: dict) -> list[dict]:
    return exercises_since(d.get("exercise"), dt_util.now() - timedelta(days=7))


def _ex_attrs(d: dict) -> dict[str, Any]:
    ex = _ex(d)
    if not ex:
        return {}
    m = ex.get("metricsSummary") or {}
    i = ex.get("interval") or {}
    pace = num(m.get("averagePaceSecondsPerMeter"))
    return {
        "nome": ex.get("displayName"),
        "tipo": ex.get("exerciseType"),
        "inicio": _br(ts(i.get("startTime"))),
        "fim": _br(ts(i.get("endTime"))),
        "duracao_min": exercise_minutes(ex),
        "calorias": num(m.get("caloriesKcal")),
        "fc_media": num(m.get("averageHeartRateBeatsPerMinute")),
        "distancia_km": _round((num(m.get("distanceMillimeters")) or 0) / 1e6, 2) or None,
        "passos": num(m.get("steps")),
        "minutos_zona_ativa": num(m.get("activeZoneMinutes")),
        "elevacao_m": _round((num(m.get("elevationGainMillimeters")) or 0) / 1000) or None,
        "ritmo_min_km": _round(pace * 1000 / 60, 2) if pace else None,
        "vo2max_corrida": num(m.get("runVo2Max")),
        "gps": (ex.get("exerciseMetadata") or {}).get("hasGps"),
        "notas": ex.get("notes"),
        "fonte": source((d.get("exercise") or [None])[0]),
    }


EXERCISE = [
    _d("last_exercise", "Último exercício", DEV_EXERCISE, "slow", lambda d: _ex_name(_ex(d)),
       icon="mdi:dumbbell", attrs_fn=_ex_attrs),
    _d("last_exercise_start", "Início do último exercício", DEV_EXERCISE, "slow",
       lambda d: ts((_ex(d).get("interval") or {}).get("startTime")),
       device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:clock-start"),
    _d("last_exercise_duration", "Duração do último exercício", DEV_EXERCISE, "slow",
       lambda d: exercise_minutes(_ex(d)) if _ex(d) else None, icon="mdi:timer", **MIN, **MEAS),
    _d("last_exercise_calories", "Calorias do último exercício", DEV_EXERCISE, "slow",
       lambda d: num((_ex(d).get("metricsSummary") or {}).get("caloriesKcal")), **KCAL),
    _d("last_exercise_heart_rate", "FC média do último exercício", DEV_EXERCISE, "slow",
       lambda d: num((_ex(d).get("metricsSummary") or {}).get("averageHeartRateBeatsPerMinute")),
       native_unit_of_measurement=BPM, icon="mdi:heart-pulse", **MEAS),
    _d("exercises_7d", "Exercícios (7 dias)", DEV_EXERCISE, "slow", lambda d: len(_week(d)),
       native_unit_of_measurement="exercícios", icon="mdi:calendar-check", **MEAS,
       attrs_fn=lambda d: {"exercicios": [f"{_br(ts((e.get('interval') or {}).get('startTime')))} {_ex_name(e)}" for e in _week(d)]}),
    _d("exercise_minutes_7d", "Minutos de exercício (7 dias)", DEV_EXERCISE, "slow",
       lambda d: round(sum(exercise_minutes(e) or 0 for e in _week(d))), icon="mdi:timer-sand", **MIN, **MEAS),
    _d("exercise_calories_7d", "Calorias em exercício (7 dias)", DEV_EXERCISE, "slow",
       lambda d: round(sum(num((e.get("metricsSummary") or {}).get("caloriesKcal")) or 0 for e in _week(d))),
       **KCAL),
]

# -- Conta ----------------------------------------------------------------------

UNITS = ["distanceUnit", "weightUnit", "heightUnit", "waterUnit", "glucoseUnit", "temperatureUnit", "swimUnit"]


def _profile_attrs(d: dict) -> dict[str, Any]:
    p, s, i = d.get("profile") or {}, d.get("settings") or {}, d.get("identity") or {}
    attrs = {
        "membro_desde": _br(gdate(p.get("membershipStartDate"))),
        "passada_caminhada_cm": _round((p.get("userConfiguredWalkingStrideLengthMm") or p.get("autoWalkingStrideLengthMm") or 0) / 10) or None,
        "passada_corrida_cm": _round((p.get("userConfiguredRunningStrideLengthMm") or p.get("autoRunningStrideLengthMm") or 0) / 10) or None,
        "passada_automatica": s.get("autoStrideEnabled"),
        "idioma": s.get("languageLocale"),
        "fuso_horario": s.get("timeZone"),
        "id_fitbit": i.get("legacyUserId"),
        "id_google_health": i.get("healthUserId"),
        "irn_inscrito": (d.get("irn") or {}).get("enrollmentStatus"),
    }
    for k in UNITS:
        if v := s.get(k):
            attrs[f"unidade_{k.removesuffix('Unit')}"] = v.rsplit("_", 1)[-1].lower()
    return attrs


ACCOUNT = [
    _d("age", "Idade", DEV_ACCOUNT, "account", lambda d: (d.get("profile") or {}).get("age"),
       native_unit_of_measurement="anos", icon="mdi:cake-variant", attrs_fn=_profile_attrs),
    _d("member_since", "Membro desde", DEV_ACCOUNT, "account",
       lambda d: gdate((d.get("profile") or {}).get("membershipStartDate")),
       device_class=SensorDeviceClass.DATE, icon="mdi:calendar-account",
       entity_category=EntityCategory.DIAGNOSTIC),
    _d("paired_devices", "Aparelhos pareados", DEV_ACCOUNT, "account",
       lambda d: len(d.get("devices") or []), icon="mdi:watch",
       attrs_fn=lambda d: {"aparelhos": [x.get("deviceVersion") for x in d.get("devices") or []]}),
]


def _last_sync(fast: dict, slow: dict) -> datetime | None:
    moments = [when(dp) for dp in (fast.get("last") or {}).values()]
    moments += [when(dp) for dp in (slow.get("last") or {}).values()]
    moments += [when(p) for p in (slow.get("sleep") or [])[:1] + (slow.get("exercise") or [])[:1]]
    # dias com passos contam como "dado recebido" (meio-dia local)
    for d in (fast.get("roll", {}).get("steps") or {}):
        moments.append(dt_util.as_utc(datetime(d.year, d.month, d.day, 12, tzinfo=dt_util.get_default_time_zone())))
    now = dt_util.utcnow()
    return newest(*(m for m in moments if m and m <= now))


ALL = ACTIVITY + HEART + BODY + SLEEP + NUTRITION + EXERCISE + ACCOUNT


class GoogleHealthSensor(GoogleHealthEntity, SensorEntity):
    entity_description: GHSensorDescription

    def __init__(self, coordinator, description: GHSensorDescription) -> None:
        super().__init__(coordinator, description.device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if fn := self.entity_description.attrs_fn:
            attrs = {k: v for k, v in fn(self.coordinator.data or {}).items() if v not in (None, {}, [])}
            return attrs or None
        return None


class LastSyncSensor(GoogleHealthEntity, SensorEntity):
    """Momento do dado mais recente recebido (diagnóstico de sincronização)."""

    _attr_name = "Último dado recebido"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:cloud-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, fast, slow) -> None:
        super().__init__(fast, DEV_ACCOUNT, "last_data")
        self._slow = slow

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._slow.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        return _last_sync(self.coordinator.data or {}, self._slow.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self.native_value
        return {"dias_sem_dados": (dt_util.utcnow() - v).days if v else None}


class PairedDeviceSensor(CoordinatorEntity, SensorEntity):
    """Bateria / última sincronização de um rastreador ou balança Fitbit/Pixel."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = device["name"].rsplit("/", 1)[-1]
        self._key = key
        self._attr_unique_id = f"{self._device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="Google",
            model=device.get("deviceType", "").title() or None,
            name=device.get("deviceVersion") or "Aparelho",
            connections={("mac", device["macAddress"].lower())} if device.get("macAddress") else set(),
        )
        if key == "battery_level":
            self._attr_name = "Bateria"
            self._attr_device_class = SensorDeviceClass.BATTERY
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
        else:
            self._attr_name = "Última sincronização"
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _device(self) -> dict | None:
        return next(
            (x for x in (self.coordinator.data or {}).get("devices", [])
             if x["name"].rsplit("/", 1)[-1] == self._device_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._device() is not None

    @property
    def native_value(self) -> Any:
        dev = self._device() or {}
        if self._key == "battery_level":
            return dev.get("batteryLevel")
        return ts(dev.get("lastSyncTime"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        dev = self._device() or {}
        if self._key == "battery_level":
            return {"status": dev.get("batteryStatus"), "recursos": dev.get("features")}
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coords = entry.runtime_data.coordinators
    scopes = entry.runtime_data.scopes

    skip = set()
    if SCOPE_ECG not in scopes:
        skip.add("ecg")
    if SCOPE_IRN not in scopes:
        skip.add("irn")
    async_add_entities(
        [GoogleHealthSensor(coords[d.group], d) for d in ALL if d.key not in skip]
        + [LastSyncSensor(coords["fast"], coords["slow"])]
    )

    known: set[str] = set()

    @callback
    def add_devices() -> None:
        new = [
            dev for dev in (coords["account"].data or {}).get("devices", [])
            if dev["name"].rsplit("/", 1)[-1] not in known
        ]
        for dev in new:
            known.add(dev["name"].rsplit("/", 1)[-1])
        async_add_entities(
            [PairedDeviceSensor(coords["account"], dev, k) for dev in new for k in ("battery_level", "last_sync_time")]
        )

    add_devices()
    entry.async_on_unload(coords["account"].async_add_listener(add_devices))
