"""MET Norway (yr.no): segunda opinión de viento, infraestructura distinta.

Gratis y sin clave, pero exige una cabecera User-Agent identificativa; si no,
responde 403. Se configura con la variable CONTACTO.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..config import Config
from ..modelo import Lectura, RespuestaFuente
from .base import ErrorFuente, hora_local, ms_a_nudos, pedir_json

ENDPOINT = "https://api.met.no/weatherapi/locationforecast/2.0/compact"


def viento_met_norway(cfg: Config) -> RespuestaFuente:
    nombre = "MET Norway (viento)"
    parametros = {
        "lat": round(cfg.latitud, 4),
        "lon": round(cfg.longitud, 4),
    }
    try:
        datos = pedir_json(
            f"{ENDPOINT}?{urlencode(parametros)}",
            cabeceras={"User-Agent": cfg.contacto},
            tiempo_espera=cfg.tiempo_espera,
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    series = (datos.get("properties") or {}).get("timeseries") or []
    if not series:
        return RespuestaFuente(nombre=nombre, error="sin serie temporal")

    lecturas: list[Lectura] = []
    for punto in series:
        detalles = (
            (punto.get("data") or {}).get("instant", {}).get("details") or {}
        )
        velocidad = detalles.get("wind_speed")
        if velocidad is None:
            continue
        racha = detalles.get("wind_speed_of_gust")
        lecturas.append(
            Lectura(
                instante=hora_local(punto["time"], cfg.zona_horaria),
                viento_nudos=ms_a_nudos(velocidad),
                racha_nudos=ms_a_nudos(racha) if racha is not None else None,
                direccion_viento_grados=detalles.get("wind_from_direction"),
            )
        )

    if not lecturas:
        return RespuestaFuente(nombre=nombre, error="serie sin datos de viento")
    return RespuestaFuente(nombre=nombre, lecturas=lecturas)
