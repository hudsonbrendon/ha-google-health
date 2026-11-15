"""Testes dos parsers (formatos copiados de respostas reais da API, valores trocados)."""

import importlib.util
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "parse", Path(__file__).parents[1] / "custom_components/google_health/parse.py"
)
p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p)

SLEEP = {
    "name": "users/1/dataTypes/sleep/dataPoints/9",
    "dataSource": {"platform": "HEALTH_KIT", "application": {"packageName": "com.apple.health"}},
    "sleep": {
        "interval": {"startTime": "2026-07-30T03:43:33.317046Z", "endTime": "2026-07-30T10:00:03Z"},
        "type": "STAGES",
        "summary": {
            "minutesInSleepPeriod": "376", "minutesAsleep": "375", "minutesAwake": "1",
            "stagesSummary": [
                {"type": "DEEP", "minutes": "80", "count": "3"},
                {"type": "AWAKE", "minutes": "1", "count": "2"},
            ],
        },
    },
}
NAP = {"sleep": {"interval": {"endTime": "2026-07-30T15:00:00Z"}, "metadata": {"nap": True},
                 "summary": {"minutesAsleep": "20", "minutesInSleepPeriod": "25"}}}
EXERCISE = {
    "dataSource": {"platform": "HEALTH_KIT", "device": {"displayName": "Apple Watch"}},
    "exercise": {
        "interval": {"startTime": "2026-07-29T22:20:49Z", "endTime": "2026-07-29T22:51:18Z"},
        "exerciseType": "BIKING", "activeDuration": "1828.368554s",
        "metricsSummary": {"caloriesKcal": 245, "averageHeartRateBeatsPerMinute": "118"},
    },
}


def test_basics():
    assert p.num("111") == 111.0 and p.num(None) is None and p.num("x") is None
    assert p.secs("1828.5s") == 1828.5
    assert p.ts("2026-07-30T10:00:03Z") == datetime(2026, 7, 30, 10, 0, 3, tzinfo=UTC)
    assert p.gdate({"date": {"year": 2026, "month": 11, "day": 15}, "time": {}}) == date(2026, 11, 15)
    assert p.source(EXERCISE) == "Apple Watch (HEALTH_KIT)"
    assert p.source(SLEEP) == "com.apple.health (HEALTH_KIT)"
    assert p.bmi(85, 178) == 26.8


def test_rollup_days_and_zones():
    pts = [
        {"civilStartTime": {"date": {"year": 2026, "month": 7, "day": 30}, "time": {}},
         "civilEndTime": {"date": {"year": 2026, "month": 7, "day": 31}, "time": {}},
         "steps": {"countSum": "111"}},
    ]
    assert p.rollup_days(pts) == {date(2026, 7, 30): {"countSum": "111"}}
    zones = [{"heartRateZone": "PEAK", "duration": "60s"}, {"heartRateZone": "PEAK", "duration": "30s"}]
    assert p.by_zone(zones, "heartRateZone", "duration") == {"PEAK": 90.0}
    kcal = [{"heartRateZone": "LIGHT", "kcal": 12.5}]
    assert p.by_zone(kcal, "heartRateZone", "kcal") == {"LIGHT": 12.5}
    roll = {"nutrients": [{"nutrient": "PROTEIN", "quantity": {"gramsSum": 42}}]}
    assert p.nutrient(roll, "PROTEIN") == 42 and p.nutrient(roll, "SUGAR") is None


def test_sleep():
    assert p.main_sleep([NAP, SLEEP]) is SLEEP
    s = p.body(SLEEP)
    assert p.stage_minutes(s, "DEEP") == 80 and p.stage_count(s, "AWAKE") == 2
    assert p.sleep_efficiency(s) == 99.7
    assert p.sleep_avg([SLEEP, NAP]) == 375
    assert p.when(SLEEP) == datetime(2026, 7, 30, 10, 0, 3, tzinfo=UTC)


def test_exercise():
    ex = p.body(EXERCISE)
    assert p.exercise_minutes(ex) == 30.5
    since = datetime(2026, 7, 29, tzinfo=UTC)
    assert p.exercises_since([EXERCISE], since) == [ex]
    assert p.exercises_since([EXERCISE], since + timedelta(days=1)) == []


def test_write_payloads():
    br = timezone(timedelta(hours=-3))
    t = datetime(2026, 11, 15, 8, 0, tzinfo=br)
    assert p.weight_point(85.25, t) == {
        "sampleTime": {"physicalTime": "2026-11-15T11:00:00Z", "utcOffset": "-10800s"},
        "weightGrams": 85250,
    }
    hyd = p.hydration_point(250, t)
    assert hyd["amountConsumed"]["milliliters"] == 250
    assert hyd["interval"]["endTime"] == "2026-11-15T11:01:00Z"
    meal = p.nutrition_point("Ovos", t, kcal=150, meal="BREAKFAST", protein_g=12)
    assert meal["energy"]["kcal"] == 150 and meal["nutrients"][0]["nutrient"] == "PROTEIN"
    ex = p.exercise_point("STRENGTH_TRAINING", t, 60, kcal=300, km=1.5)
    assert ex["activeDuration"] == "3600s"
    assert ex["interval"]["endTime"] == "2026-11-15T12:00:00Z"
    assert ex["metricsSummary"] == {"caloriesKcal": 300, "distanceMillimeters": 1_500_000}


def test_time_filter():
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    t1 = datetime(2026, 11, 2, tzinfo=UTC)
    assert p.time_filter("sleep", t0, None) == 'sleep.interval.end_time >= "2026-11-01T00:00:00Z"'
    assert p.time_filter("exercise", t0, t1) == (
        'exercise.interval.civil_start_time >= "2026-11-01T00:00:00" AND '
        'exercise.interval.civil_start_time < "2026-11-02T00:00:00"'
    )
    assert p.time_filter("daily-resting-heart-rate", t0, None) == 'daily_resting_heart_rate.date >= "2026-11-01"'
    assert p.time_filter("heart-rate", t0, None).startswith("heart_rate.sample_time.physical_time")
    assert p.time_filter("electrocardiogram", t0, t1) == 'electrocardiogram.interval.start_time >= "2026-11-01T00:00:00Z"'
    assert p.time_filter("steps", None, None) is None
