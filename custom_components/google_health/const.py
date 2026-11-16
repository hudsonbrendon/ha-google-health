"""Constantes da integração Google Health."""

from __future__ import annotations

DOMAIN = "google_health"

OAUTH2_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH2_TOKEN = "https://oauth2.googleapis.com/token"
API_URL = "https://health.googleapis.com/v4/users/me"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
API_CONSOLE_URL = (
    "https://console.developers.google.com/apis/api/health.googleapis.com/overview"
)

_P = "https://www.googleapis.com/auth/googlehealth."
SCOPE_ACTIVITY = _P + "activity_and_fitness.readonly"
SCOPE_MEASUREMENTS = _P + "health_metrics_and_measurements.readonly"
SCOPE_SLEEP = _P + "sleep.readonly"
SCOPE_NUTRITION = _P + "nutrition.readonly"
SCOPE_PROFILE = _P + "profile.readonly"
SCOPE_SETTINGS = _P + "settings.readonly"
SCOPE_ECG = _P + "ecg.readonly"
SCOPE_IRN = _P + "irn.readonly"
SCOPE_LOCATION = _P + "location.readonly"
SCOPE_ACTIVITY_WRITE = _P + "activity_and_fitness.writeonly"
SCOPE_MEASUREMENTS_WRITE = _P + "health_metrics_and_measurements.writeonly"
SCOPE_NUTRITION_WRITE = _P + "nutrition.writeonly"
SCOPE_USERINFO = "https://www.googleapis.com/auth/userinfo.profile"

# Pedidos num login novo / reautenticação. Os que já estavam no core são
# obrigatórios; ECG, IRN e escrita são extras (a integração funciona sem eles).
OAUTH_SCOPES = [
    SCOPE_ACTIVITY,
    SCOPE_MEASUREMENTS,
    SCOPE_SLEEP,
    SCOPE_NUTRITION,
    SCOPE_PROFILE,
    SCOPE_SETTINGS,
    SCOPE_USERINFO,
    SCOPE_ECG,
    SCOPE_IRN,
    SCOPE_LOCATION,
    SCOPE_ACTIVITY_WRITE,
    SCOPE_MEASUREMENTS_WRITE,
    SCOPE_NUTRITION_WRITE,
]
# Escopos extras → rótulo do aviso em Reparos.
EXTRA_SCOPES = {
    SCOPE_ECG: "ECG",
    SCOPE_IRN: "ritmo irregular",
    SCOPE_LOCATION: "GPS dos treinos (TCX)",
    SCOPE_ACTIVITY_WRITE: "gravar atividade/exercícios",
    SCOPE_MEASUREMENTS_WRITE: "gravar medições (peso)",
    SCOPE_NUTRITION_WRITE: "gravar nutrição/água",
}

# Dispositivos (grupos) — cada um vira um aparelho no HA.
DEV_ACCOUNT = "account"
DEV_ACTIVITY = "activity"
DEV_HEART = "heart"
DEV_BODY = "body"
DEV_SLEEP = "sleep"
DEV_NUTRITION = "nutrition"
DEV_EXERCISE = "exercise"
DEVICE_NAMES = {
    DEV_ACCOUNT: "Google Health Conta",
    DEV_ACTIVITY: "Google Health Atividade",
    DEV_HEART: "Google Health Coração",
    DEV_BODY: "Google Health Corpo",
    DEV_SLEEP: "Google Health Sono",
    DEV_NUTRITION: "Google Health Nutrição",
    DEV_EXERCISE: "Google Health Exercícios",
}
