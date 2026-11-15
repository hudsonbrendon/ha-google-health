"""Serviços: leitura livre (buscar_dados) e registro de dados (escrita)."""

from __future__ import annotations

from datetime import datetime, timedelta
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from . import parse
from .api import GoogleHealthError
from .const import (
    DOMAIN,
    SCOPE_ACTIVITY_WRITE,
    SCOPE_MEASUREMENTS_WRITE,
    SCOPE_NUTRITION_WRITE,
)

DATA_TYPES = [
    "steps", "distance", "active-energy-burned", "basal-energy-burned", "total-calories",
    "floors", "altitude", "active-minutes", "active-zone-minutes", "activity-level",
    "sedentary-period", "time-in-heart-rate-zone", "calories-in-heart-rate-zone",
    "swim-lengths-data", "exercise", "heart-rate", "daily-resting-heart-rate",
    "heart-rate-variability", "daily-heart-rate-variability", "daily-heart-rate-zones",
    "oxygen-saturation", "daily-oxygen-saturation", "daily-respiratory-rate",
    "respiratory-rate-sleep-summary", "vo2-max", "daily-vo2-max", "run-vo2-max",
    "weight", "height", "body-fat", "core-body-temperature", "blood-glucose",
    "daily-sleep-temperature-derivations", "sleep", "hydration-log", "nutrition-log",
    "food", "electrocardiogram", "irregular-rhythm-notification",
]
MEALS = [
    "BEFORE_BREAKFAST", "BREAKFAST", "BEFORE_LUNCH", "LUNCH", "BEFORE_DINNER",
    "DINNER", "AFTER_DINNER", "SNACK", "ANYTIME",
]

_ENTRY = vol.Optional("config_entry_id")


def _entry(hass: HomeAssistant, call: ServiceCall, scope: str | None = None):
    from . import loaded_entries  # evita import circular

    entries = loaded_entries(hass)
    if wanted := call.data.get("config_entry_id"):
        entries = [e for e in entries if e.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("Nenhuma conta Google Health carregada.")
    entry = entries[0]
    if scope and scope not in entry.runtime_data.scopes:
        raise ServiceValidationError(
            "A conta não deu permissão de escrita. Reconfigure a integração "
            "(Configurações › Dispositivos › Google Health › Reconfigurar) e "
            "aceite as permissões de escrita."
        )
    return entry


def _when(call: ServiceCall, key: str = "quando") -> datetime:
    value = call.data.get(key)
    return dt_util.as_local(value) if value else dt_util.now()


async def _create(entry, data_type: str, field: str, value: dict) -> dict:
    try:
        res = await entry.runtime_data.client.create(data_type, field, value)
    except GoogleHealthError as err:
        raise HomeAssistantError(f"Google Health recusou: {err}") from err
    for coord in entry.runtime_data.coordinators.values():
        await coord.async_request_refresh()
    return res


def async_setup_services(hass: HomeAssistant) -> None:
    async def buscar_dados(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass, call)
        client = entry.runtime_data.client
        tipo = call.data["tipo"]
        inicio, fim = call.data.get("inicio"), call.data.get("fim")
        try:
            if call.data.get("agregado_diario"):
                fim_d = (fim or dt_util.now()).date() + timedelta(days=1)
                ini_d = (inicio.date() if inicio else fim_d - timedelta(days=7))
                pontos = await client.daily_rollup(tipo, ini_d, fim_d)
            else:
                flt = parse.time_filter(
                    tipo, inicio and dt_util.as_local(inicio), fim and dt_util.as_local(fim)
                )
                limite = call.data["limite"]
                pontos = await client.list_points(
                    tipo, page_size=min(limite, 25 if tipo in ("sleep", "exercise") else limite),
                    flt=flt, max_pages=10,
                )
                pontos = pontos[:limite]
        except GoogleHealthError as err:
            raise HomeAssistantError(str(err)) from err
        return {"tipo": tipo, "quantidade": len(pontos), "pontos": pontos}

    async def registrar_peso(call: ServiceCall) -> None:
        entry = _entry(hass, call, SCOPE_MEASUREMENTS_WRITE)
        when = _when(call)
        await _create(entry, "weight", "weight", parse.weight_point(call.data["peso"], when))
        if (fat := call.data.get("gordura_corporal")) is not None:
            await _create(entry, "body-fat", "bodyFat", parse.body_fat_point(fat, when))

    async def registrar_agua(call: ServiceCall) -> None:
        entry = _entry(hass, call, SCOPE_NUTRITION_WRITE)
        await _create(
            entry, "hydration-log", "hydrationLog",
            parse.hydration_point(call.data["quantidade"], _when(call)),
        )

    async def registrar_refeicao(call: ServiceCall) -> None:
        entry = _entry(hass, call, SCOPE_NUTRITION_WRITE)
        d = call.data
        await _create(
            entry, "nutrition-log", "nutritionLog",
            parse.nutrition_point(
                d["nome"], _when(call), d.get("calorias"), d.get("refeicao"),
                d.get("carboidratos"), d.get("gorduras"), d.get("proteinas"),
            ),
        )

    async def registrar_exercicio(call: ServiceCall) -> None:
        entry = _entry(hass, call, SCOPE_ACTIVITY_WRITE)
        d = call.data
        await _create(
            entry, "exercise", "exercise",
            parse.exercise_point(
                d["tipo"],
                # sem início: o exercício terminou agora
                _when(call, "inicio") if d.get("inicio") else dt_util.now() - timedelta(minutes=d["duracao"]),
                d["duracao"], d.get("nome"),
                d.get("calorias"), d.get("distancia"), d.get("notas"),
            ),
        )

    pos = vol.All(vol.Coerce(float), vol.Range(min=0))
    hass.services.async_register(
        DOMAIN, "buscar_dados", buscar_dados,
        vol.Schema({
            _ENTRY: cv.string,
            vol.Required("tipo"): vol.In(DATA_TYPES),
            vol.Optional("inicio"): cv.datetime,
            vol.Optional("fim"): cv.datetime,
            vol.Optional("limite", default=25): vol.All(vol.Coerce(int), vol.Range(1, 10000)),
            vol.Optional("agregado_diario", default=False): cv.boolean,
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "registrar_peso", registrar_peso,
        vol.Schema({
            _ENTRY: cv.string,
            vol.Required("peso"): pos,
            vol.Optional("gordura_corporal"): vol.All(vol.Coerce(float), vol.Range(0, 100)),
            vol.Optional("quando"): cv.datetime,
        }),
    )
    hass.services.async_register(
        DOMAIN, "registrar_agua", registrar_agua,
        vol.Schema({_ENTRY: cv.string, vol.Required("quantidade"): pos,
                    vol.Optional("quando"): cv.datetime}),
    )
    hass.services.async_register(
        DOMAIN, "registrar_refeicao", registrar_refeicao,
        vol.Schema({
            _ENTRY: cv.string,
            vol.Required("nome"): cv.string,
            vol.Optional("refeicao"): vol.In(MEALS),
            vol.Optional("calorias"): pos,
            vol.Optional("carboidratos"): pos,
            vol.Optional("gorduras"): pos,
            vol.Optional("proteinas"): pos,
            vol.Optional("quando"): cv.datetime,
        }),
    )
    hass.services.async_register(
        DOMAIN, "registrar_exercicio", registrar_exercicio,
        vol.Schema({
            _ENTRY: cv.string,
            vol.Required("tipo"): cv.string,
            vol.Required("duracao"): pos,
            vol.Optional("inicio"): cv.datetime,
            vol.Optional("nome"): cv.string,
            vol.Optional("calorias"): pos,
            vol.Optional("distancia"): pos,
            vol.Optional("notas"): cv.string,
        }),
    )
